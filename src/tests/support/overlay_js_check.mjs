// Exercises the overlay.js quiet-status behaviour under a minimal DOM stub.
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";
import assert from "node:assert";

// `OVERLAY_JS` exists so this harness can be pointed at a deliberately broken
// copy of overlay.js. Do that after touching it: a DOM stub that stops
// exercising the thing it stubs still prints five green lines.
const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(
  process.env.OVERLAY_JS || path.join(HERE, "..", "..", "media", "overlay", "overlay.js"),
  "utf8"
);

function classList() {
  const set = new Set();
  return {
    set,
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
  };
}

function makeElement() {
  return {
    innerHTML: "",
    classList: classList(),
    style: { setProperty() {}, },
    querySelectorAll: () => [],
    appendChild() {},
  };
}

// overlay.js ends with a bare `refresh()` bootstrap, so a context always burns
// one poll on creation. `fetchState` lets a test decide whether that first poll
// succeeds (a warm overlay) or fails (a cold one that never rendered).
function makeContext({ pathname = "/overlay", search = "", fetchState = null } = {}) {
  const rootEl = makeElement();
  const logs = { error: [], info: [] };
  const control = { state: fetchState };
  // Recorded rather than discarded: the rarity colours reach the stylesheet as
  // :root custom properties and nowhere else, so a no-op `setProperty` would
  // make check 7 pass against an overlay that never sets them.
  const rootProps = new Map();
  const ctx = {
    console: {
      error: (...a) => logs.error.push(a.join(" ")),
      info: (...a) => logs.info.push(a.join(" ")),
      warn: () => {},
      log: () => {},
    },
    URLSearchParams,
    Set,
    Map,
    Object,
    Array,
    Number,
    Math,
    JSON,
    String,
    Boolean,
    document: {
      getElementById: () => rootEl,
      body: { classList: classList() },
      documentElement: {
        style: { setProperty: (name, value) => rootProps.set(name, String(value)) },
      },
      createElement: () => makeElement(),
    },
    window: {
      location: { pathname, search },
      setTimeout: () => {},
    },
    fetch: async () => {
      if (control.state === null) {
        throw new Error("boom");
      }
      return { ok: true, json: async () => control.state };
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(
    SOURCE
      + "\nglobalThis.__t = { render, refresh, holdLastGoodState, root,"
      + " get failures() { return consecutiveFetchFailures; } };",
    ctx
  );
  return { ctx, rootEl, logs, control, rootProps, t: ctx.__t };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

const baseWidgets = { kps: { id: "kps", enabled: true, order: 1 } };
const liveState = {
  status: "live",
  style: {},
  widgets: baseWidgets,
  kps: { current: 7, minute_avg: 5, five_minute_avg: 4, run_avg: 3 },
  stats: [{ label: "Damage", display_label: "DMG", value: "120%" }],
  tracked_items: [{ id: "a", label: "Anvil", count: 3 }],
};

// --- 1. status card is out of the payload unless opted in --------------------
{
  const { t, rootEl } = makeContext();
  t.render(liveState);
  assert.ok(!rootEl.innerHTML.includes("status-panel"), "live must not draw a status card");

  t.render({ ...liveState, status: "reconnecting" });
  assert.ok(
    !rootEl.innerHTML.includes("status-panel"),
    "reconnecting must be quiet"
  );

  t.render({ ...liveState, status: "stale" });
  assert.ok(
    !rootEl.innerHTML.includes("status-panel"),
    "stale must be quiet while show_status is off"
  );

  t.render({ ...liveState, status: "stale", style: { show_status: true } });
  assert.ok(
    rootEl.innerHTML.includes("status-panel"),
    "stale must draw the card when show_status is on"
  );
  console.log("ok: status card gating");
}

// --- Build Progression marks Min without completing the Ideal row -----------
{
  const { t, rootEl } = makeContext();
  t.render({
    status: "live",
    style: {},
    widgets: {
      build_progression: { id: "build_progression", enabled: true, order: 1 },
    },
    build_progression: {
      configured: true,
      available: true,
      complete: false,
      name: "Test Build",
      progress: "0/1",
      rows: [{
        kind: "stat",
        label: "DMG",
        label_color: "#93C5FD",
        value: "3.5x/4x",
        status: "neutral",
        complete: false,
        min_met: true,
        late: false,
        banished: false,
        symbol: "✓",
        time: "TO IDEAL",
      }],
    },
  });
  assert.ok(rootEl.innerHTML.includes("status-neutral min-met"), "Min row gets its visual class");
  assert.ok(rootEl.innerHTML.includes("TO IDEAL"), "remaining Ideal target stays visible");
  console.log("ok: build Min milestone");
}

// --- 2. first-ever frame with no data still explains itself ------------------
{
  const { t, rootEl } = makeContext();
  t.render({ status: "waiting", style: {}, widgets: baseWidgets });
  assert.ok(
    rootEl.innerHTML.includes("status-panel"),
    "a first load with no held frame must say something"
  );
  console.log("ok: cold-start card");
}

// --- 3. the last good frame is held instead of blanked -----------------------
{
  const { t, rootEl } = makeContext();
  t.render(liveState);
  const liveHtml = rootEl.innerHTML;
  assert.ok(liveHtml.includes("7/s"), "live KPS should render");

  // The tracker resets: a real payload with all data fields emptied.
  t.render({
    status: "reconnecting",
    style: {},
    widgets: baseWidgets,
    kps: {},
    stats: [],
    tracked_items: [],
  });
  assert.ok(
    rootEl.innerHTML.includes("7/s"),
    "reconnecting must replay the held KPS, not blank it"
  );

  t.render({ ...liveState, kps: { current: 9, minute_avg: 5, five_minute_avg: 4, run_avg: 3 } });
  assert.ok(rootEl.innerHTML.includes("9/s"), "a live payload must win over the held one");
  console.log("ok: hold-last-good");
}

// --- 4. failed polls never wipe a rendered overlay ---------------------------
{
  const { t, rootEl, logs, control } = makeContext({ fetchState: liveState });
  await settle();
  assert.strictEqual(t.failures, 0, "the bootstrap poll should have succeeded");
  const before = rootEl.innerHTML;
  assert.ok(before.includes("7/s"), "the warm overlay rendered");

  control.state = null; // the app goes away mid-scene
  for (let i = 0; i < 5; i += 1) {
    await t.refresh();
  }
  assert.strictEqual(rootEl.innerHTML, before, "DOM must survive failures below the threshold");
  assert.ok(!rootEl.classList.contains("overlay-degraded"), "no dimming below the threshold");
  assert.strictEqual(logs.error.length, 0, "no log below the threshold");

  await t.refresh();
  assert.strictEqual(rootEl.innerHTML, before, "DOM must survive past the threshold too");
  assert.ok(rootEl.classList.contains("overlay-degraded"), "degraded class at the threshold");
  assert.strictEqual(logs.error.length, 1, "exactly one error line");
  assert.ok(logs.error[0].includes("holding the last good frame"));

  await t.refresh();
  assert.strictEqual(logs.error.length, 1, "the error line must not repeat every poll");

  // Recovery clears the dimming and says so once.
  control.state = liveState;
  await t.refresh();
  assert.ok(!rootEl.classList.contains("overlay-degraded"), "recovery clears the dimming");
  assert.strictEqual(logs.info.length, 1, "recovery logs once");
  console.log("ok: failure grace, single log line, recovery");
}

// --- 5. a cold overlay that never rendered still shows the failure -----------
{
  const { t, rootEl } = makeContext();
  await settle();
  await t.refresh();
  assert.ok(
    rootEl.innerHTML.includes("overlay unavailable"),
    "nothing rendered yet means there is no frame to hold"
  );
  console.log("ok: cold-start failure card");
}

// --- 6. the Luck widget renders, and both toggles are honoured --------------
{
  const luckWidgets = { luck_rarity: { id: "luck_rarity", enabled: true, order: 1 } };
  const luckPayload = {
    available: true,
    show_bar: true,
    show_expected: true,
    expected_layout: "column",
    tiers: [
      { rarity: "LEGENDARY", color: "#FACC15", chance: 54.88, chance_text: "54.88%", actual: 116, expected_text: "118" },
      { rarity: "RARE", color: "#E879F9", chance: 29.28, chance_text: "29.28%", actual: 78, expected_text: "78" },
      { rarity: "UNCOMMON", color: "#60A5FA", chance: 9.76, chance_text: "9.76%", actual: 38, expected_text: "36" },
      { rarity: "COMMON", color: "#22C55E", chance: 6.08, chance_text: "6.08%", actual: 45, expected_text: "45" },
    ],
  };
  const luckState = { status: "live", style: {}, widgets: luckWidgets, luck_rarity: luckPayload };

  const { t, rootEl } = makeContext();

  // Without a renderer the widget is silently blank, which is the whole reason
  // this check exists: the Python payload can be perfect and show nothing.
  t.render(luckState);
  let html = rootEl.innerHTML;
  assert.ok(html.includes("54.88%"), "the chance row must render");
  assert.ok(html.includes("luck-bar-segment"), "the bar must render when show_bar is on");
  assert.ok(html.includes("(118)"), "column must render the expected figure in brackets");
  assert.ok(html.includes("luck-layout-column"), "column layout class");
  assert.ok(!html.includes("Legendary"), "no rarity words reach the overlay");
  assert.strictEqual((html.match(/luck-cell/g) || []).length, 4, "four cells");

  // All four toggle combinations, and the chance row survives every one.
  for (const showBar of [true, false]) {
    for (const showExpected of [true, false]) {
      t.render({ ...luckState, luck_rarity: { ...luckPayload, show_bar: showBar, show_expected: showExpected } });
      const combo = rootEl.innerHTML;
      assert.ok(combo.includes("54.88%"), `chance row must survive bar=${showBar} expected=${showExpected}`);
      assert.strictEqual(
        combo.includes("luck-bar-segment"),
        showBar,
        `bar visibility must follow show_bar (${showBar})`
      );
      assert.strictEqual(
        combo.includes("luck-expected-block"),
        showExpected,
        `block visibility must follow show_expected (${showExpected})`
      );
    }
  }

  t.render({ ...luckState, luck_rarity: { ...luckPayload, expected_layout: "row" } });
  html = rootEl.innerHTML;
  assert.ok(html.includes("luck-layout-row"), "row layout class");
  assert.ok(html.includes("/118"), "row joins the pair with a slash");
  assert.ok(!html.includes("luck-dot"), "row carries no dots");

  // Unmeasurable, toggle off: the projector clears show_expected and sends no
  // status_message (the toggle itself hides the block, nothing to say).
  t.render({ ...luckState, luck_rarity: { ...luckPayload, available: false, show_expected: false } });
  html = rootEl.innerHTML;
  assert.ok(html.includes("54.88%"), "an unmeasurable run keeps its chances");
  assert.ok(!html.includes("luck-expected-block"), "and drops the block rather than showing zeros");

  // Unmeasurable, toggle on: a resolved status_message replaces the figures
  // instead of leaving an empty area indistinguishable from the toggle being
  // off. Presence alone decides -- this side never learns what "available"
  // means.
  t.render({
    ...luckState,
    luck_rarity: {
      ...luckPayload,
      available: false,
      show_expected: false,
      status_message: "Missed run start",
    },
  });
  html = rootEl.innerHTML;
  assert.ok(html.includes("54.88%"), "a status message still keeps the chances");
  assert.ok(!html.includes("luck-expected-block"), "the figures block is not drawn alongside the message");
  assert.ok(
    html.includes("Missed run start"),
    "the resolved status text must render in place of the figures"
  );

  // A measurable run must never show a leftover status message even if one
  // arrived on the payload -- figures win once show_expected is true.
  t.render({
    ...luckState,
    luck_rarity: { ...luckPayload, status_message: "" },
  });
  html = rootEl.innerHTML;
  assert.ok(html.includes("luck-expected-block"), "figures render when show_expected is true");
  assert.ok(!html.includes("luck-expected-status"), "no status line alongside real figures");

  console.log("ok: luck widget layouts and toggles");
}

// --- 7. rarity colours come from the payload, not from the stylesheet --------
// `overlay.css` used to carry its own tier table on `.stage-item-count`, and it
// disagreed with the model on two of the four: rare was a violet and uncommon a
// cyan, while the Luck widget on the same page drew them magenta and blue from
// `projections/obs.py`. One overlay, one rarity, two colours. The stylesheet
// now only names `--rarity-*`, so the whole fix lives in these properties being
// set -- which is exactly why the stub above records them.
{
  const stageWidgets = { stage_summary: { id: "stage_summary", enabled: true, order: 1 } };
  const stageState = {
    status: "live",
    style: {},
    widgets: stageWidgets,
    rarity_colors: {
      LEGENDARY: "#FACC15",
      RARE: "#E879F9",
      UNCOMMON: "#60A5FA",
      COMMON: "#22C55E",
    },
    rarity_labels: {
      LEGENDARY: "Legendary",
      RARE: "Epic",
      UNCOMMON: "Rare",
      COMMON: "Common",
    },
    stage_summary: [
      { stage: "1", time: "05:12", kills: "420", items: [{ rarity: "RARE", label: "Epic", count: 2 }] },
    ],
  };

  const { t, rootEl, rootProps } = makeContext();
  t.render(stageState);

  assert.strictEqual(rootProps.get("--rarity-rare"), "#E879F9", "the tier hex reaches :root");
  assert.strictEqual(
    rootProps.get("--rarity-rare-rgb"),
    "232, 121, 249",
    "and its loose channels, which the capsule's fill and glow need"
  );
  for (const [name, hex] of [["legendary", "#FACC15"], ["uncommon", "#60A5FA"], ["common", "#22C55E"]]) {
    assert.strictEqual(rootProps.get(`--rarity-${name}`), hex, `${name} reaches :root too`);
  }

  // The markup must stay colourless: a hex inlined here would be a third copy.
  const html = rootEl.innerHTML;
  assert.ok(html.includes("stage-item-count rare active"), "the count wears its tier class");
  assert.ok(html.includes('title="Epic"'), "the tooltip uses the player-facing game name");
  assert.ok(!html.includes('title="RARE"'), "the internal key stays out of visible text");
  assert.ok(!/#[0-9a-fA-F]{6}/.test(html), "no rarity hex may be inlined into the markup");

  // A payload without the field must not blank the tiers -- the :root fallback
  // in overlay.css covers the frame before the first poll, and a stale value is
  // better than a colourless one.
  const { rootProps: bare } = (() => {
    const made = makeContext();
    made.t.render({ ...stageState, rarity_colors: undefined });
    return made;
  })();
  assert.ok(!bare.has("--rarity-rare"), "a missing field leaves the stylesheet's fallback alone");

  console.log("ok: rarity colours flow from the payload");
}

console.log("\nall overlay.js checks passed");
