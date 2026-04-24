if bonkLogger and bonkLogger.stop then
  pcall(bonkLogger.stop)
end

bonkLogger = {
  logPath = os.getenv('TEMP') .. '\\bonk_interactable_log_v7.csv',
  file = nil,
  seq = 0,
  run = 1,
  active = false,
  maxEvents = 45000,
  rows = 0,

  spawnerAddr = getAddress('GameAssembly.dll+49C2A0'),

  instRandom = getAddress('GameAssembly.dll+49CA28'),
  randomTrans1 = getAddress('GameAssembly.dll+49CA47'),
  randomTrans2 = getAddress('GameAssembly.dll+49CB70'),

  instChest = getAddress('GameAssembly.dll+49D3DA'),
  chestTrans = getAddress('GameAssembly.dll+49D3F0'),

  instOtherA = getAddress('GameAssembly.dll+49D7F6'),
  instOtherB = getAddress('GameAssembly.dll+49DBE5'),

  instShrine = getAddress('GameAssembly.dll+49E70C'),
  shrineTrans1 = getAddress('GameAssembly.dll+49E722'),
  shrineTrans2 = getAddress('GameAssembly.dll+49E770'),
  shrineTrans3 = getAddress('GameAssembly.dll+49E77D'),

  startAddr = getAddress('GameAssembly.dll+4BFE00'),
  startTrans1 = getAddress('GameAssembly.dll+4BFE72'),
  startTrans2 = getAddress('GameAssembly.dll+4BFEB2'),
  startTrans3 = getAddress('GameAssembly.dll+4BFF00'),
  lateAddr = getAddress('GameAssembly.dll+4C0032'),

  activeSeq = 0,
  activeObj = 0,
  activeIndex = 0,
  activeAmount = 0,
  activeLen = 0,
  activePrefabs = '',

  lastInstSource = '',
  lastInstGo = 0,
}

local function hex(v)
  v = tonumber(v) or 0
  return string.format('0x%X', v)
end

local function csv(v)
  v = tostring(v or '')
  if v:find('[,"\r\n]') then
    v = '"' .. v:gsub('"', '""') .. '"'
  end
  return v
end

local function safeReadPointer(addr)
  local ok, v = pcall(readPointer, addr)
  return ok and (v or 0) or 0
end

local function safeReadInteger(addr)
  local ok, v = pcall(readInteger, addr)
  return ok and (v or 0) or 0
end

local function safeReadQword(addr)
  local ok, v = pcall(readQword, addr)
  return ok and (v or 0) or 0
end

local function safeReadFloat(addr)
  local ok, v = pcall(readFloat, addr)
  return ok and (v or 0) or 0
end

local function readIl2CppString(strPtr)
  if strPtr == 0 then
    return ''
  end

  local len = safeReadInteger(strPtr + 0x10)
  if len <= 0 or len > 256 then
    return ''
  end

  local ok, s = pcall(readString, strPtr + 0x14, len * 2, true)
  return ok and (s or '') or ''
end

local function readPrefabList(prefabsArray)
  if prefabsArray == 0 then
    return 0, ''
  end

  local len = tonumber(safeReadQword(prefabsArray + 0x18)) or 0
  if len < 0 then len = 0 end
  if len > 32 then len = 32 end

  local items = {}
  for i = 0, len - 1 do
    items[#items + 1] = hex(safeReadPointer(prefabsArray + 0x20 + (i * 8)))
  end

  return len, table.concat(items, ';')
end

local function appendRow(cols)
  local f = bonkLogger.file
  if not f then
    return
  end

  local out = {}
  for i = 1, #cols do
    out[i] = csv(cols[i])
  end

  f:write(table.concat(out, ',') .. '\r\n')
  bonkLogger.rows = bonkLogger.rows + 1
  if bonkLogger.rows >= 64 then
    f:flush()
    bonkLogger.rows = 0
  end
end

local function loggerBreakpoints()
  return {
    bonkLogger.spawnerAddr,
    bonkLogger.instRandom,
    bonkLogger.randomTrans1,
    bonkLogger.randomTrans2,
    bonkLogger.instChest,
    bonkLogger.chestTrans,
    bonkLogger.instOtherA,
    bonkLogger.instOtherB,
    bonkLogger.instShrine,
    bonkLogger.shrineTrans1,
    bonkLogger.shrineTrans2,
    bonkLogger.shrineTrans3,
    bonkLogger.startAddr,
    bonkLogger.startTrans1,
    bonkLogger.startTrans2,
    bonkLogger.startTrans3,
    bonkLogger.lateAddr,
  }
end

local function removeLoggerBreakpoints()
  for _, addr in ipairs(loggerBreakpoints()) do
    pcall(debug_removeBreakpoint, addr)
  end
end

local function appendGeneric(eventName, source, label, notes)
  appendRow({
    os.date('%Y-%m-%d %H:%M:%S'),
    bonkLogger.run,
    bonkLogger.seq,
    eventName,
    source or '',
    hex(RIP),
    hex(safeReadPointer(RSP)),
    hex(RAX),
    hex(RBX),
    hex(RCX),
    hex(RDX),
    hex(RSI),
    hex(RDI),
    hex(R8),
    hex(R9),
    bonkLogger.activeSeq,
    hex(bonkLogger.activeObj),
    bonkLogger.activeIndex,
    bonkLogger.activeAmount,
    bonkLogger.activeLen,
    bonkLogger.activePrefabs,
    bonkLogger.lastInstSource,
    hex(bonkLogger.lastInstGo),
    label or '',
    notes or ''
  })
end

local function contextNotes()
  return table.concat({
    'active_spawner_seq=' .. tostring(bonkLogger.activeSeq),
    'active_randomObject=' .. hex(bonkLogger.activeObj),
    'active_caller_index=' .. tostring(bonkLogger.activeIndex),
    'active_amount=' .. tostring(bonkLogger.activeAmount),
    'active_prefabs_len=' .. tostring(bonkLogger.activeLen),
    'active_prefabs=' .. tostring(bonkLogger.activePrefabs),
    'last_inst_source=' .. tostring(bonkLogger.lastInstSource),
    'last_inst_go=' .. hex(bonkLogger.lastInstGo)
  }, ';')
end

local function logSpawnerHit()
  local randomObject = tonumber(RDX) or 0
  local callerIndex = tonumber(RBX) or 0

  local amount = 0
  local maxAmount = 0
  local checkRadius = 0
  local scaleMin = 0
  local scaleMax = 0
  local maxSlopeAngle = 0
  local upOffset = 0
  local prefabsArray = 0
  local prefabsLen = 0
  local prefabsJoined = ''
  local alignWithNormal = 0

  if randomObject ~= 0 then
    amount = safeReadInteger(randomObject + 0x10)
    maxAmount = safeReadInteger(randomObject + 0x14)
    checkRadius = safeReadFloat(randomObject + 0x18)
    scaleMin = safeReadFloat(randomObject + 0x1C)
    scaleMax = safeReadFloat(randomObject + 0x20)
    maxSlopeAngle = safeReadFloat(randomObject + 0x24)
    upOffset = safeReadFloat(randomObject + 0x28)
    prefabsArray = safeReadPointer(randomObject + 0x30)
    prefabsLen, prefabsJoined = readPrefabList(prefabsArray)
    alignWithNormal = safeReadInteger(randomObject + 0x44)
  end

  bonkLogger.activeSeq = bonkLogger.seq
  bonkLogger.activeObj = randomObject
  bonkLogger.activeIndex = callerIndex
  bonkLogger.activeAmount = amount
  bonkLogger.activeLen = prefabsLen
  bonkLogger.activePrefabs = prefabsJoined

  local notes = table.concat({
    'caller_index=' .. tostring(callerIndex),
    'amount=' .. tostring(amount),
    'maxAmount=' .. tostring(maxAmount),
    string.format('checkRadius=%.3f', checkRadius),
    string.format('scaleMin=%.3f', scaleMin),
    string.format('scaleMax=%.3f', scaleMax),
    string.format('maxSlopeAngle=%.3f', maxSlopeAngle),
    string.format('upOffset=%.3f', upOffset),
    'prefabs_ptr=' .. hex(prefabsArray),
    'prefabs_len=' .. tostring(prefabsLen),
    'align=' .. tostring(alignWithNormal)
  }, ';')

  appendGeneric('spawner', 'RandomObjectSpawner', prefabsJoined, notes)
end

local function logInstantiateReturn(source)
  local instance = tonumber(RAX) or 0
  bonkLogger.lastInstSource = source
  bonkLogger.lastInstGo = instance

  local notes = table.concat({
    'instance=' .. hex(instance),
    'instance_deref=' .. hex(safeReadPointer(instance)),
    'possible_prefab_rcx=' .. hex(RCX),
    'possible_prefab_rbx=' .. hex(RBX),
    'possible_prefab_rsi=' .. hex(RSI),
    'possible_prefab_rdi=' .. hex(RDI),
    contextNotes()
  }, ';')

  appendGeneric('instret', source, hex(instance), notes)
end

local function logInstantiateTransform(source)
  local transform = tonumber(RAX) or 0
  local gameObject = tonumber(RCX) or 0

  local notes = table.concat({
    'gameObject_rcx=' .. hex(gameObject),
    'transform=' .. hex(transform),
    'transform_deref=' .. hex(safeReadPointer(transform)),
    contextNotes()
  }, ';')

  appendGeneric('inst_transform', source, hex(transform), notes)
end

local function logStart()
  local component = tonumber(RCX) or 0

  local notes = table.concat({
    'start_component=' .. hex(component),
    'component_deref=' .. hex(safeReadPointer(component)),
    'rbx=' .. hex(RBX),
    'rdi=' .. hex(RDI)
  }, ';')

  appendGeneric('start', 'BaseInteractable.Start', hex(component), notes)
end

local function logStartTransform(slot)
  local component = tonumber(RBX) or 0
  local transform = tonumber(RAX) or 0

  local notes = table.concat({
    'start_component=' .. hex(component),
    'component_deref=' .. hex(safeReadPointer(component)),
    'transform=' .. hex(transform),
    'transform_deref=' .. hex(safeReadPointer(transform)),
    'slot=' .. tostring(slot)
  }, ';')

  appendGeneric('start_transform', 'BaseInteractable.Start', hex(transform), notes)
end

local function logLateCall()
  local categoryPtr = tonumber(RAX) or 0
  local label = readIl2CppString(categoryPtr)
  local lateObj = tonumber(RBX) or 0

  local notes = table.concat({
    'category_ptr=' .. hex(categoryPtr),
    'late_obj=' .. hex(lateObj),
    'late_obj_deref=' .. hex(safeReadPointer(lateObj)),
    'rcx_before_call=' .. hex(RCX),
    'rdi=' .. hex(RDI)
  }, ';')

  appendGeneric('latecall', 'latecall', label, notes)
end

function debugger_onBreakpoint()
  if not bonkLogger or not bonkLogger.active then
    return 0
  end

  local rip = tonumber(RIP) or 0
  local handled = false

  local ok, err = pcall(function()
    if bonkLogger.seq >= bonkLogger.maxEvents then
      appendGeneric('limit', 'logger', '', 'maxEvents=' .. tostring(bonkLogger.maxEvents))
      bonkLogger.active = false
      removeLoggerBreakpoints()
      handled = true
      return
    end

    if rip == bonkLogger.spawnerAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logSpawnerHit()
    elseif rip == bonkLogger.instRandom then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn('RandomObjectSpawner')
    elseif rip == bonkLogger.randomTrans1 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('RandomObjectSpawner.trans1')
    elseif rip == bonkLogger.randomTrans2 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('RandomObjectSpawner.trans2')
    elseif rip == bonkLogger.instChest then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn('SpawnChests')
    elseif rip == bonkLogger.chestTrans then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('SpawnChests.trans')
    elseif rip == bonkLogger.instOtherA then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn('SpawnOther.A')
    elseif rip == bonkLogger.instOtherB then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn('SpawnOther.B')
    elseif rip == bonkLogger.instShrine then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn('SpawnShrines')
    elseif rip == bonkLogger.shrineTrans1 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('SpawnShrines.trans1')
    elseif rip == bonkLogger.shrineTrans2 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('SpawnShrines.trans2')
    elseif rip == bonkLogger.shrineTrans3 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform('SpawnShrines.trans3')
    elseif rip == bonkLogger.startAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStart()
    elseif rip == bonkLogger.startTrans1 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(1)
    elseif rip == bonkLogger.startTrans2 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(2)
    elseif rip == bonkLogger.startTrans3 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(3)
    elseif rip == bonkLogger.lateAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logLateCall()
    end
  end)

  if not ok then
    appendGeneric('error', 'logger', '', tostring(err))
  end

  if handled then
    debug_continueFromBreakpoint('co_run')
    return 1
  end

  return 0
end

function bonkLogger.flush()
  if bonkLogger.file then
    bonkLogger.file:flush()
    bonkLogger.rows = 0
  end
end

function bonkLogger.stop()
  bonkLogger.active = false
  removeLoggerBreakpoints()
  if bonkLogger.file then
    pcall(function()
      bonkLogger.file:flush()
      bonkLogger.file:close()
    end)
    bonkLogger.file = nil
  end
  print('Bonk logger stopped: ' .. bonkLogger.logPath)
end

function bonkLogger.start(customPath)
  if customPath and customPath ~= '' then
    bonkLogger.logPath = customPath
  end

  removeLoggerBreakpoints()
  if bonkLogger.file then
    pcall(function()
      bonkLogger.file:close()
    end)
  end

  bonkLogger.file = assert(io.open(bonkLogger.logPath, 'w'))
  bonkLogger.file:write('ts,run,seq,event,source,rip,return_addr,rax,rbx,rcx,rdx,rsi,rdi,r8,r9,active_spawner_seq,active_randomObject,active_caller_index,active_amount,active_prefabs_len,active_prefabs,last_inst_source,last_inst_go,label,notes\r\n')

  bonkLogger.seq = 0
  bonkLogger.run = 1
  bonkLogger.rows = 0
  bonkLogger.activeSeq = 0
  bonkLogger.activeObj = 0
  bonkLogger.activeIndex = 0
  bonkLogger.activeAmount = 0
  bonkLogger.activeLen = 0
  bonkLogger.activePrefabs = ''
  bonkLogger.lastInstSource = ''
  bonkLogger.lastInstGo = 0
  bonkLogger.active = true

  appendRow({
    os.date('%Y-%m-%d %H:%M:%S'),
    bonkLogger.run,
    bonkLogger.seq,
    'marker',
    'logger',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    0,
    '0x0',
    0,
    0,
    0,
    '',
    '',
    '0x0',
    'RUN_1_START',
    ''
  })

  for _, addr in ipairs(loggerBreakpoints()) do
    debug_setBreakpoint(addr)
  end

  print('Bonk logger v7 started: ' .. bonkLogger.logPath)
end

bonkLogger.start()
