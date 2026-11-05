// Real Chromium layout checks. No desktop input or existing browser profile is used.
// node scripts/verify_overlay_localization.mjs FIXTURES_JSON OUTPUT_DIR [BASE_URL]
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [fixturesPath,outputPath,externalBase]=process.argv.slice(2);
if (!fixturesPath || !outputPath) throw new Error('Pass fixture JSON and output directory.');
const output=path.resolve(outputPath);
await fs.mkdir(output,{recursive:true});
const fixtures=JSON.parse(await fs.readFile(fixturesPath,'utf8'));
const browser=process.env.BONKSCANNER_QA_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
let server,chrome,ws;
let counter=0;
const pending=new Map();
const exceptions=[];
const results=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,timeout=20000) {
  const end=Date.now()+timeout;
  while(Date.now()<end) {const value=await fn();if(value)return value;await delay(50);}
  throw new Error('Timed out waiting for browser.');
}
function command(method,params={}) {
  const id=++counter;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+' timed out'));},20000);
    pending.set(id,{resolve:result=>{clearTimeout(timer);resolve(result);},reject});
    ws.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const response=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(response.exceptionDetails)throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
}
try {
  let base=externalBase;
  if(!base) {
    server=http.createServer(async(req,res)=>{
      try {
        const url=new URL(req.url,'http://localhost');
        if(url.pathname==='/api/overlay-state') {
          res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixtures[0]));return;
        }
        const asset=url.pathname.startsWith('/assets/') ? path.basename(url.pathname) : 'index.html';
        if(!['overlay.js','overlay.css','index.html'].includes(asset)){res.writeHead(404).end();return;}
        let data=await fs.readFile(path.join(root,'src/media/overlay',asset),'utf8');
        // Remote font downloads are irrelevant to these HUDs and would slow an offline check.
        if(asset==='index.html')data=data.replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g,'');
        res.setHeader('Content-Type',asset.endsWith('.js')?'text/javascript':asset.endsWith('.css')?'text/css':'text/html');
        res.end(data);
      } catch(error){res.writeHead(500).end(String(error));}
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    base=`http://127.0.0.1:${server.address().port}`;
  }
  const profile=path.join(output,'chrome-profile');
  chrome=spawn(browser,['--headless=new','--disable-gpu','--disable-ipc-flooding-protection','--no-first-run','--no-default-browser-check',
    '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
  chrome.on('error',error=>exceptions.push(String(error)));
  const port=await until(async()=>{
    try{return Number((await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);}catch{return 0;}
  });
  const targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id) {
      const task=pending.get(message.id);if(!task)return;pending.delete(message.id);
      if(message.error)task.reject(new Error(JSON.stringify(message.error)));else task.resolve(message.result);
    } else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails);
  };
  await command('Page.enable');await command('Runtime.enable');
  await command('Emulation.setDeviceMetricsOverride',{width:1280,height:1080,deviceScaleFactor:1,mobile:false});
  await command('Page.navigate',{url:base+'/overlay'});
  await until(async()=>evaluate('typeof hasRenderedOnce !== "undefined" && hasRenderedOnce'));
  await evaluate(`window.__qaState=${JSON.stringify(fixtures[0])};
    window.__qaOriginalFetch=window.fetch;
    window.fetch=async(url,options)=>String(url).includes('/api/overlay-state')
      ? {ok:true,json:async()=>window.__qaState} : window.__qaOriginalFetch(url,options);`);
  await evaluate('document.fonts.ready.then(()=>true)');
  for(const fixture of fixtures) {
    for(const scale of [.75,1,1.5,2]) {
      for(const widgetId of ['stats','weapon_tracker','stage_summary']) {
        for(const layout of widgetId==='weapon_tracker'?['compact','detailed']:widgetId==='stage_summary'?['detailed','absolute']:['detailed']) {
          for(const width of widgetId==='stage_summary'?[null]:[null,360]) {
            const state=structuredClone(fixture);
            const widget=state.widgets[widgetId];
            widget.scale=scale;widget.layout=layout;
            if(width!==null)widget.width=width;else delete widget.width;
            delete widget.height;
            if(layout==='absolute') {
              for(const entry of Object.values(state.widgets))entry.enabled=entry.id===widgetId;
              widget.x=20;widget.y=20;
            }
            const label=`${fixture.localization.language}-${fixture.localization.game_language}-${widgetId}-${layout}-${scale}-${width??'auto'}`;
            await evaluate(`history.replaceState(null,'','${layout==='absolute'?'/overlay':'/overlay/'+widgetId}');
              window.__qaState=${JSON.stringify(state)};render(window.__qaState);`);
            const issues=await evaluate(`(()=>{
              const errors=[];
              const panel=document.querySelector('.panel');
              const bounds=panel.getBoundingClientRect();
              for(const element of document.querySelectorAll('.stat-row span,.stat-row strong,.stage-header')) {
                if(element.scrollWidth>element.clientWidth+2)errors.push({kind:'clipped',text:element.textContent});
                const box=element.getBoundingClientRect();
                if(box.right>bounds.right+2||box.left<bounds.left-2)errors.push({kind:'outside-panel',text:element.textContent});
              }
              const headers=[...document.querySelectorAll('.stage-header')];
              for(let i=1;i<headers.length;i++) {
                if(headers[i-1].getBoundingClientRect().right>headers[i].getBoundingClientRect().left)
                  errors.push({kind:'overlapping-headers',text:headers[i-1].textContent});
              }
              return errors;
            })()`);
            results.push({case:label,issues});
            if(widgetId==='stage_summary') {
              const before=await evaluate("document.querySelector('.stage-summary-widget').getBoundingClientRect().width");
              const small=structuredClone(state);
              for(const row of small.stage_summary){row.time='1:00';row.kills='1';for(const item of row.items)item.count=1;}
              await evaluate(`window.__qaState=${JSON.stringify(small)};render(window.__qaState);`);
              const after=await evaluate("document.querySelector('.stage-summary-widget').getBoundingClientRect().width");
              if(Math.abs(before-after)>2)issues.push({kind:'unstable-number-frame',before,after});
              await evaluate(`window.__qaState=${JSON.stringify(state)};render(window.__qaState);`);
            }
            if(scale===1 && width===null && layout==='detailed') {
              const shot=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
              await fs.writeFile(path.join(output,label+'.png'),Buffer.from(shot.data,'base64'));
            }
          }
        }
      }
    }
    console.log(fixture.localization.language,fixture.localization.game_language,'checked');
  }
  const failures=results.filter(result=>result.issues.length);
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify({base,cases:results.length,exceptions,failures},null,2));
  console.log(JSON.stringify({cases:results.length,exceptions:exceptions.length,failures:failures.length}));
  if(failures.length||exceptions.length)process.exitCode=1;
} finally {
  if(ws?.readyState===WebSocket.OPEN) {
    try{await command('Browser.close');}catch{}
    ws.close();
  }
  if(chrome && chrome.exitCode===null)chrome.kill();
  if(server)server.closeAllConnections();
  if(server)await new Promise(resolve=>server.close(resolve));
}
