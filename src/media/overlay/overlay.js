const root = document.getElementById("overlay");
let pollMs = 500;
let canvasWidth = 1920;
let canvasHeight = 1080;

// A single failed poll used to replace the whole overlay with a status card.
// One dropped fetch -- the app restarting its server, a closed keep-alive, a
// browser-source reload -- emptied the OBS scene and rebuilt it from scratch on
// the next success. Nothing is touched until this many polls have failed in a
// row (~3 s at the 500 ms default), and even then the DOM is kept: only a
// `overlay-degraded` class goes on, so the last good frame stays visible.
const OVERLAY_FAILURE_GRACE_POLLS = 6;
let consecutiveFetchFailures = 0;
let hasRenderedOnce = false;
let loggedDegraded = false;

// Payload fields that carry run *data* rather than layout. While the tracker is
// not `live` these are replayed from the last good frame instead of being
// blanked to "--", so a game restart freezes the numbers rather than wiping
// them. Layout (widgets/canvas/style) always comes from the fresh payload --
// the overlay editor POSTs geometry to the same endpoint and must stay live.
const HELD_STATE_FIELDS = [
  "run_id",
  "current_stage",
  "run_timer_label",
  "mob_kills",
  "player_level",
  "chests_per_minute",
  "tracked_items",
  "stage_summary",
  "kps",
  "stats",
  "banishes",
  "luck_rarity",
  "build_progression",
];
// `reconnecting` is the tracker's quiet middle state: data is known frozen, but
// a restart is the expected cause and the surface must not announce it.
const QUIET_STATUSES = new Set(["live", "reconnecting"]);
let lastGoodState = null;

function requestedWidgetId() {
  const match = window.location.pathname.match(/^\/overlay\/([^/]+)\/?$/);
  if (!match || match[1] === "compact" || match[1] === "full") {
    return "";
  }
  return decodeURIComponent(match[1]);
}

function enabledWidgets(state) {
  const widgets = Object.values(state.widgets || {});
  const requested = requestedWidgetId();
  return widgets
    .filter((widget) => widget.enabled && (!requested || widget.id === requested))
    .sort((left, right) => (left.order || 0) - (right.order || 0));
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "--";
  }
  return num.toLocaleString("en-US");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return fallback;
  }
  return Math.max(min, Math.min(number, max));
}

function applyStyle(state) {
  const style = state.style || {};
  const accent = style.accent_color || "#f6c453";
  const opacity = clampNumber(style.background_opacity, 0, 1, 0.0);
  const configuredScale = Math.max(0.6, Math.min(Number(style.scale ?? 1), 4));
  // We remove autoScale so widgets can truly reflow and add columns when the OBS width increases.
  // The user can still control the overall text size via the "Scale" setting in the app.
  const scale = configuredScale;

  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty("--panel-bg-opacity", Math.max(0, Math.min(opacity, 0.45)));
  document.documentElement.style.setProperty("--scale", scale);
  applyRarityColors(state.rarity_colors);
}

// The tier colours arrive on every payload from `projections/obs.py`, which is
// the only place that knows them. The stylesheet used to carry its own copy on
// `.stage-item-count`, and it disagreed with the model on two of the four -- so
// "rare" was one colour in the Luck widget and another in the stage table, on
// the same page. The `:root` block still holds the same four values as a
// fallback for the frame before the first poll lands; nothing else may.
function applyRarityColors(colors) {
  if (!colors || typeof colors !== "object") {
    return;
  }
  const root = document.documentElement;
  Object.keys(colors).forEach((rarity) => {
    const hex = String(colors[rarity] || "");
    const rgb = hexToRgbTriplet(hex);
    if (!rgb) {
      return;
    }
    const name = rarity.toLowerCase();
    root.style.setProperty(`--rarity-${name}`, hex);
    // The capsule's fill, border and glow are the same hue at four different
    // alphas, so the stylesheet needs the channels loose, not the hex.
    root.style.setProperty(`--rarity-${name}-rgb`, rgb);
  });
}

function hexToRgbTriplet(hex) {
  const match = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!match) {
    return null;
  }
  const value = parseInt(match[1], 16);
  return `${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}`;
}

function panel(title, body, classes = "", widget = null) {
  const backgroundOpacity = clampNumber(widget?.background_opacity, 0, 1, classes.includes("stage-summary-widget") ? 0.4 : 0.0);
  const border = widget?.show_border ? "1px solid rgba(255,255,255,.14)" : "none";
  const style = `--widget-bg-opacity:${backgroundOpacity};border:${border};`;
  const showHeader = widget?.show_header !== false;
  const titleHtml = showHeader ? `<div class="panel-title">${escapeHtml(title)}</div>` : "";
  return `<section class="panel ${classes}" style="${style}">
    ${titleHtml}
    ${body}
  </section>`;
}

function renderWidget(widget, state) {
  switch (widget.id) {
    case "tracked_items":
      return panel("Tracked Items", renderTrackedItems(state), "wide item-widget", widget);
    case "stats":
      return panel("Stats", renderStats(state, widget), "wide stats-widget", widget);
    case "kps":
      return panel("KPS", renderKps(state, widget), "kps-widget", widget);
    case "stage_summary":
      return panel("Stage Summary", renderStageSummary(state), "wide stage-summary-widget", widget);
    case "banishes":
      return panel("Banishes", renderBanishes(state, widget), "wide banishes-widget", widget);
    case "luck_rarity":
      return panel("Luck", renderLuckRarity(state), "wide luck-widget", widget);
    case "build_progression":
      return panel(
        "Build Progression",
        renderBuildProgression(state),
        "wide build-progress-widget",
        widget,
      );
    default:
      return "";
  }
}

function buildLabelColor(value) {
  const color = String(value || "");
  return /^#[0-9a-f]{6}$/i.test(color) ? color : "#e5e7eb";
}

function renderBuildProgression(state) {
  const build = state.build_progression || {};
  if (!build.configured) {
    return `<div class="muted">Build not configured</div>`;
  }
  if (!build.available) {
    return `<div class="muted">Waiting for live run</div>`;
  }
  if (build.complete) {
    if (build.late_complete) {
      return `<div class="build-complete late">! BUILD COMPLETE <span>${escapeHtml(build.completion_time || "--:--")}</span></div>`;
    }
    return `<div class="build-complete">\u2713 BUILD COMPLETE <span>${escapeHtml(build.completion_time || "--:--")}</span></div>`;
  }
  const rows = Array.isArray(build.rows) ? build.rows : [];
  let lastKind = "";
  const sectionLabels = { item: "ITEMS", stat: "STATS", progress: "PROGRESS" };
  const body = rows.map((row) => {
    const heading = build.show_section_headings && row.kind !== lastKind
      ? `<div class="build-section">${sectionLabels[row.kind] || "PROGRESS"}</div>`
      : "";
    lastKind = row.kind;
    const lateClass = row.late ? " late" : "";
    const banishedClass = row.banished ? " banished" : "";
    const minMetClass = row.min_met && !row.complete ? " min-met" : "";
    return `${heading}<div class="build-row status-${escapeHtml(row.status)}${minMetClass}${lateClass}${banishedClass}">
    <span class="build-symbol">${escapeHtml(row.symbol)}</span>
    <span class="build-label" style="color:${buildLabelColor(row.label_color)}">${escapeHtml(row.label)}</span>
    <strong>${escapeHtml(row.value)}</strong>
    ${row.time ? `<span class="build-time">${escapeHtml(row.time)}</span>` : ""}
  </div>`;
  }).join("");
  return `<div class="build-head"><strong>${escapeHtml(build.name)}</strong><span>${escapeHtml(build.progress)}</span></div><div class="build-list">${body}</div>`;
}

function renderTrackedItems(state) {
  const rows = state.tracked_items || [];
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  return `<div class="chip-strip">${rows.map((row) => {
    const label = String(row.label || "").replace(/\s+map\s*1$/i, "");
    return `<div class="counter-chip"><span>${escapeHtml(label)}</span><strong>${formatNumber(row.count)}</strong></div>`;
  }).join("")}</div>`;
}

function renderStats(state, widget) {
  const maxRows = Number(widget.max_rows || 40);
  const rows = (state.stats || []).slice(0, maxRows);
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  const labels = rows.map((row) => String(row.display_label || row.label || ""));
  const maxLen = Math.max(...labels.map((label) => label.length));
  const labelWidth = Math.max(60, maxLen * 8.8);
  const style = `--stat-label-width: calc(${labelWidth}px * var(--scale));`;
  const body = rows.map((row, index) => `<div class="stat-row"><span>${escapeHtml(labels[index])}</span><strong>${escapeHtml(row.value || "--")}</strong></div>`).join("");
  return `<div class="stats-list" style="${style}">${body}</div>`;
}

function formatRate(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  return `${formatNumber(value)}/s`;
}

function renderKps(state, widget) {
  const kps = state.kps || {};
  const allMetrics = [
    { label: "KPS", value: formatRate(kps.current) },
    { label: "60s", value: formatRate(kps.minute_avg) },
    { label: "5m", value: formatRate(kps.five_minute_avg) },
    { label: "Run", value: formatRate(kps.run_avg) },
  ];
  const enabledMetricIds = Array.isArray(widget?.selected_kps_metrics) && widget.selected_kps_metrics.length
    ? new Set(widget.selected_kps_metrics)
    : new Set(["current", "minute_avg", "five_minute_avg", "run_avg"]);
  const metricIds = ["current", "minute_avg", "five_minute_avg", "run_avg"];
  const metrics = allMetrics.filter((_metric, index) => enabledMetricIds.has(metricIds[index]));
  return `<div class="kps-strip">${metrics.map((metric) => `
    <span class="kps-metric">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}</strong>
    </span>
  `).join("")}</div>`;
}

function renderStageSummary(state) {
  const rows = Array.isArray(state.stage_summary) ? state.stage_summary : [];
  const rarityLabels = state.rarity_labels || {};
  const stageRows = Array.from({ length: 4 }, (_unused, index) => {
    return rows[index] || { stage: String(index + 1), time: "--", kills: "--", items: [] };
  });
  if (!stageRows.length) {
    return `<div class="muted">--</div>`;
  }
  const headers = ["Stage", "Time", "Kills", "Items"]
    .map((label) => `<div class="stage-header">${escapeHtml(label)}</div>`)
    .join("");
  const body = stageRows.map((row, index) => {
    const items = Array.isArray(row.items) ? row.items : [];
    const inactive = !items.length && row.time === "--" && row.kills === "--";
    return `<div class="stage-row ${inactive ? "inactive" : ""}">
      <div class="stage-cell">${escapeHtml(row.stage || String(index + 1))}</div>
      <div class="stage-cell">${escapeHtml(row.time || "--")}</div>
      <div class="stage-cell">${escapeHtml(row.kills || "--")}</div>
      <div class="stage-cell stage-items">${renderStageItems(items, rarityLabels)}</div>
    </div>`;
  }).join("");
  return `<div class="stage-table">${headers}${body}</div>`;
}

function renderStageItems(items, rarityLabels = {}) {
  const rows = Array.isArray(items) ? items : [];
  const rowsByRarity = new Map(rows.map((item) => [String(item.rarity || "").toUpperCase(), item]));
  const raritySlots = ["LEGENDARY", "RARE", "UNCOMMON", "COMMON"];
  return `<span class="stage-item-counts">${raritySlots.map((rarity) => {
    const item = rowsByRarity.get(rarity);
    const count = Number(item?.count || 0);
    const label = escapeHtml(String(item?.label || rarityLabels[rarity] || rarity));
    const value = count > 0 ? formatNumber(count) : "--";
    const rarityClass = rarity.toLowerCase();
    return `<span class="stage-item-count ${rarityClass} ${count > 0 ? "active" : "empty"}" title="${label}">${value}</span>`;
  }).join("")}</span>`;
}



// The Luck widget. Every number, colour and toggle arrives resolved from
// `projections/obs.py`, which is where the rarity model and the run's summary
// live; this does layout only, so the two overlays cannot drift apart on what
// they say -- only on how they arrange it.
//
// The block anchors to the chance row, not to the bar: the bar is optional and
// an anchor that can disappear is not one. Both are children of the same
// column, which is also why nothing here reads the bar's segment widths -- a
// tier at 1% is a one-pixel segment with no room under it.
function renderLuckRarity(state) {
  const luck = state.luck_rarity || {};
  const tiers = Array.isArray(luck.tiers) ? luck.tiers : [];
  if (!tiers.length) {
    return `<div class="muted">--</div>`;
  }
  const chances = tiers.map((tier) => `
    <span class="luck-chance" style="color:${escapeHtml(String(tier.color || "#E5E7EB"))};">${escapeHtml(String(tier.chance_text || "--"))}</span>
  `).join(`<span class="luck-sep">|</span>`);

  const bar = luck.show_bar ? renderLuckBar(tiers) : "";
  // Presence alone decides: a resolved status string always means "draw this
  // instead", whatever made the run unmeasurable. This side never learns that.
  const statusMessage = luck.status_message ? String(luck.status_message) : "";
  const expected = statusMessage
    ? `<div class="luck-expected-status muted">${escapeHtml(statusMessage)}</div>`
    : luck.show_expected
      ? renderLuckExpected(tiers, luck.expected_layout)
      : "";
  return `<div class="luck-block">
    <div class="luck-chances">${chances}</div>
    ${bar}
    ${expected}
  </div>`;
}

function renderLuckBar(tiers) {
  const total = tiers.reduce((sum, tier) => sum + Math.max(0, Number(tier.chance) || 0), 0);
  if (total <= 0) {
    return `<div class="luck-bar"></div>`;
  }
  const segments = tiers
    .filter((tier) => (Number(tier.chance) || 0) > 0)
    .map((tier) => `<span class="luck-bar-segment" style="flex-grow:${(Number(tier.chance) || 0) / total};background:${escapeHtml(String(tier.color || "#E5E7EB"))};"></span>`)
    .join("");
  return `<div class="luck-bar">${segments}</div>`;
}

function renderLuckExpected(tiers, layout) {
  // `column` is a 2x2 of `● 116 (118)` with the dot carrying the tier colour;
  // `row` is one line of `116/118` with no dots, which works because the cells
  // stretch to the full width and the whitespace does what the dot does.
  const isRow = String(layout || "column") === "row";
  const cells = tiers.map((tier) => {
    const color = escapeHtml(String(tier.color || "#E5E7EB"));
    const actual = escapeHtml(formatNumber(tier.actual));
    const expected = escapeHtml(String(tier.expected_text || "--"));
    const dot = isRow ? "" : `<span class="luck-dot" style="color:${color};">&#9679;</span>`;
    const pair = isRow ? `/${expected}` : `(${expected})`;
    return `<span class="luck-cell">
      ${dot}<strong style="color:${color};">${actual}</strong><span class="luck-expected">${pair}</span>
    </span>`;
  }).join("");
  return `<div class="luck-expected-block ${isRow ? "luck-layout-row" : "luck-layout-column"}">${cells}</div>`;
}

function renderBanishes(state, widget) {
  const maxRows = Number(widget.max_rows || 40);
  const allRows = state.banishes || [];
  const rows = allRows.slice(0, maxRows);
  const remaining = Math.max(0, allRows.length - rows.length);
  if (!allRows.length) {
    return `<div class="muted">No banishes yet</div>`;
  }
  const more = remaining > 0 ? `<span class="item-chip more-chip">+${formatNumber(remaining)} more</span>` : "";
  return `<div class="banish-list">${rows.map((item) => `<span class="item-chip banish-chip">${escapeHtml(item)}</span>`).join("")}${more}</div>`;
}

const isEditMode = new URLSearchParams(window.location.search).has("edit");
let lastEditWidgetRevision = null;
let editWidgetWatcherStarted = false;
let hasRenderedEditWidgets = false;
let lastEditWidgetSettings = new Map();
if (isEditMode) {
  document.body.classList.add("edit-mode-active");
}

// Where a widget sits until someone drags it, in the coordinates of the
// reference canvas below rather than of whatever canvas is configured.
//
// Both columns did overlap at the widgets' natural heights -- `banishes` into
// `luck_rarity` by 43px, and `stage_summary` (217 tall) into `tracked_items`
// 200 below it -- so a first-time editor met them stacked on top of each other
// and had to pull them apart before it could tell what it was looking at. Both
// columns are spaced by measured height now.
const DEFAULT_COORDINATES = {
  stage_summary: { x: 20, y: 80 },
  tracked_items: { x: 20, y: 320 },
  stats: { x: 1600, y: 80 },
  kps: { x: 1600, y: 260 },
  banishes: { x: 1600, y: 360 },
  luck_rarity: { x: 1600, y: 530 },
  build_progression: { x: 20, y: 500 }
};

// The canvas the coordinates above are written against. They used to be applied
// raw to any canvas, and `x: 1600` on a 1280-wide one is not merely a poor
// placement -- the shell clips at its own edge, so those four widgets were
// invisible and unreachable at every zoom and scroll position. A streamer who
// set a 720p canvas saw only whatever they had already placed by hand, and
// toggling the rest on did nothing they could see. Reported as "Tracked Items
// is the only widget that shows up".
const REFERENCE_CANVAS_WIDTH = 1920;

// Horizontal only, and that asymmetry is the point.
//
// `x` scales because it carries an *anchor*: the right-hand cluster sits at the
// right edge of a 1920 scene, and it should read as right-anchored on a 1280 or
// a 2560 one rather than drifting into the middle. Widgets in a column share
// their `x`, so scaling it cannot push two of them together.
//
// `y` does not scale, because it carries a *gap* -- the vertical spacing above
// was measured against the widgets' natural heights, and those heights do not
// scale with the canvas. Multiplying `y` by 0.667 for a 720-tall canvas while
// `banishes` stays 141px tall closes the 170px gap under it to 113 and puts it
// back on top of `luck_rarity`, which is the overlap the spacing was chosen to
// remove. Raw `y` keeps every gap as authored; the clamp below is what handles
// a canvas too short to hold the column.
//
// Neither is enough alone, because a widget has width: 1600 scaled to a 1280
// canvas is 1067, and a 285px-wide Stats panel there still ends 72px past the
// edge. Only a measured clamp can promise the widget is *inside*, and it cannot
// run here -- nothing has a size until it is in the document. So this places,
// and `clampDefaultedWidgets` below corrects.
function defaultPosition(widgetId) {
  const reference = DEFAULT_COORDINATES[widgetId] || { x: 20, y: 80 };
  return {
    x: Math.round(reference.x * (canvasWidth / REFERENCE_CANVAS_WIDTH)),
    y: reference.y,
  };
}

// Pull every still-unplaced widget fully inside the canvas, now that it has a
// measured size. Only the defaulted ones: a coordinate the user chose is theirs
// to keep, and `data-defaulted` is dropped the moment a drag saves one.
//
// Idempotent by construction -- a second pass finds `left` already under the
// maximum and changes nothing -- which matters because the OBS path re-renders
// on every poll.
function clampDefaultedWidgets() {
  root.querySelectorAll('.widget-wrapper[data-defaulted="true"]').forEach((element) => {
    const maxLeft = Math.max(0, canvasWidth - element.offsetWidth);
    const maxTop = Math.max(0, canvasHeight - element.offsetHeight);
    const left = Math.min(parseFloat(element.style.left) || 0, maxLeft);
    const top = Math.min(parseFloat(element.style.top) || 0, maxTop);
    element.style.left = `${Math.round(left)}px`;
    element.style.top = `${Math.round(top)}px`;
  });
}

// How much the editor shrinks the canvas to fit the window. 1 outside edit
// mode, and never above 1 inside it: the canvas is scaled down to be seen
// whole, never blown up. Read by the drag handler, which works in canvas
// coordinates while pointer events arrive in screen ones.
let editorScale = 1;

// Breathing room around the scaled canvas, in screen pixels: the frame's own
// margins plus the fixed banner overhead above it.
const EDITOR_FIT_MARGIN_X = 40;
const EDITOR_FIT_MARGIN_Y = 160;
// Below this the canvas is too small to aim at, and scrolling a slightly
// clipped canvas beats squinting at all of it.
const EDITOR_MIN_SCALE = 0.25;

function ensureEditorFrame() {
  if (!isEditMode || document.getElementById("edit-canvas-frame")) {
    return;
  }
  const frame = document.createElement("div");
  frame.id = "edit-canvas-frame";
  root.parentNode.insertBefore(frame, root);
  frame.appendChild(root);
}

function applyEditorScale() {
  if (!isEditMode) {
    return;
  }
  const fitWidth = (window.innerWidth - EDITOR_FIT_MARGIN_X) / canvasWidth;
  const fitHeight = (window.innerHeight - EDITOR_FIT_MARGIN_Y) / canvasHeight;
  editorScale = Math.max(EDITOR_MIN_SCALE, Math.min(1, fitWidth, fitHeight));

  const frame = document.getElementById("edit-canvas-frame");
  if (!frame) {
    return;
  }
  // Only on the frame. Custom properties inherit, so the shell inside it picks
  // `--editor-scale` up for its transform -- one owner for the fit, rather
  // than the same number written to two elements that can then disagree.
  frame.style.setProperty("--editor-scale", editorScale);
  frame.style.setProperty("--editor-frame-width", `${Math.round(canvasWidth * editorScale)}px`);
  frame.style.setProperty("--editor-frame-height", `${Math.round(canvasHeight * editorScale)}px`);
}

if (isEditMode) {
  window.addEventListener("resize", applyEditorScale);
}

function shouldPositionAbsolutely(widgets) {
  if (requestedWidgetId()) {
    return false;
  }
  if (isEditMode) {
    return true;
  }
  return widgets.some(w => w.x !== null && w.x !== undefined && w.y !== null && w.y !== undefined);
}

function holdLastGoodState(state) {
  const status = state.status || "waiting";
  if (status === "live") {
    lastGoodState = state;
    return state;
  }
  if (!lastGoodState) {
    return state;
  }
  const held = Object.assign({}, state);
  HELD_STATE_FIELDS.forEach((field) => {
    if (field in lastGoodState) {
      held[field] = lastGoodState[field];
    }
  });
  return held;
}

function getOverlayStateForRendering(state) {
  if (!isEditMode) {
    return state;
  }
  const renderedState = JSON.parse(JSON.stringify(state));
  if (!renderedState.tracked_items || !renderedState.tracked_items.length) {
    renderedState.tracked_items = [
      { label: "Anvil", count: 3 },
      { label: "Coin", count: 1450 },
      { label: "Golden Egg", count: 12 }
    ];
  }
  if (!renderedState.stats || !renderedState.stats.length) {
    // The live payload resolves display_label server-side from the widget's
    // "Short stat names" setting; the demo rows have to honour the same setting
    // or the editor would preview a layout the real source never renders.
    const statsWidget = (renderedState.widgets || {}).stats || {};
    const short = statsWidget.short_stat_labels !== false;
    renderedState.stats = [
      { label: "Damage", display_label: short ? "DMG" : "Damage", value: "+150%" },
      { label: "Attack Speed", display_label: short ? "AS" : "Attack Speed", value: "+45%" },
      { label: "Luck", display_label: "Luck", value: "82" },
      { label: "XP Gain", display_label: short ? "XP" : "XP Gain", value: "+25%" }
    ];
  }
  if (
    !renderedState.kps
    || Object.keys(renderedState.kps).length === 0
    || Object.values(renderedState.kps).every((value) => value === null || value === undefined)
  ) {
    renderedState.kps = {
      current: 150,
      minute_avg: 243,
      five_minute_avg: 221,
      run_avg: 138,
    };
  }
  if (!renderedState.banishes || !renderedState.banishes.length) {
    renderedState.banishes = ["Garlic", "Bible", "Cross"];
  }
  if (Array.isArray(renderedState.stage_summary) && renderedState.stage_summary.length > 0) {
    renderedState.stage_summary.forEach((row) => {
      row.time = (row.time === "--" || !row.time) ? "04:30" : row.time;
      row.kills = (row.kills === "--" || !row.kills) ? "380" : row.kills;
      if (!row.items || !row.items.length) {
        row.items = [
          { rarity: "LEGENDARY", count: 1 },
          { rarity: "RARE", count: 2 },
          { rarity: "UNCOMMON", count: 4 }
        ];
      }
    });
  } else {
    renderedState.stage_summary = [
      { stage: "1", time: "05:12", kills: "420", items: [{ rarity: "LEGENDARY", count: 1 }, { rarity: "RARE", count: 2 }, { rarity: "UNCOMMON", count: 4 }] },
      { stage: "2", time: "04:30", kills: "380", items: [{ rarity: "RARE", count: 1 }, { rarity: "UNCOMMON", count: 3 }, { rarity: "COMMON", count: 5 }] },
      { stage: "3", time: "06:15", kills: "510", items: [{ rarity: "LEGENDARY", count: 2 }, { rarity: "COMMON", count: 8 }] },
      { stage: "4", time: "--", kills: "--", items: [] }
    ];
  }
  return renderedState;
}

function showEditBanner() {
  if (document.getElementById("edit-mode-banner")) {
    return;
  }
  const banner = document.createElement("div");
  banner.id = "edit-mode-banner";
  banner.className = "edit-banner";
  banner.innerHTML = `
    <div class="edit-banner-title">Overlay Layout Editor</div>
    <div class="edit-banner-text">Drag widgets to place them anywhere. Close this browser tab when done.</div>
    <div class="edit-resolution-controls">
      <label>Canvas Resolution:</label>
      <input type="number" id="canvas-width-input" value="${canvasWidth}" min="400" max="7680" />
      <span>x</span>
      <input type="number" id="canvas-height-input" value="${canvasHeight}" min="300" max="4320" />
      <button id="apply-resolution-btn">Apply</button>
    </div>
  `;
  document.body.appendChild(banner);

  document.getElementById("apply-resolution-btn").addEventListener("click", async () => {
    const widthInput = document.getElementById("canvas-width-input");
    const heightInput = document.getElementById("canvas-height-input");
    const newWidth = Math.max(400, Math.min(parseInt(widthInput.value) || 1920, 7680));
    const newHeight = Math.max(300, Math.min(parseInt(heightInput.value) || 1080, 4320));

    // Update frontend globals & CSS variables immediately for instant visual feedback!
    canvasWidth = newWidth;
    canvasHeight = newHeight;
    root.style.setProperty("--canvas-width", `${canvasWidth}px`);
    root.style.setProperty("--canvas-height", `${canvasHeight}px`);
    // A taller or wider canvas needs a different fit, and the next render is a
    // widget-revision away -- the resolution POST does not bump one.
    applyEditorScale();

    widthInput.value = canvasWidth;
    heightInput.value = canvasHeight;

    // Persist to backend
    try {
      await fetch("/api/save-canvas-resolution", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ width: canvasWidth, height: canvasHeight })
      });
    } catch (err) {
      console.error("Failed to save canvas resolution:", err);
    }
  });
}

function setupDragAndDrop() {
  const draggables = Array.from(document.querySelectorAll(
    ".widget-wrapper.draggable:not([data-edit-initialized])"
  ));
  draggables.forEach((el) => {
    el.setAttribute("data-edit-initialized", "true");
  });
  draggables.forEach((el) => {
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialLeft = 0;
    let initialTop = 0;

    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button, select, input, a")) {
        return;
      }
      // Avoid drag triggers when resizing widgets via bottom-right handle.
      // `rect` is in screen pixels and so is `clientX`, so the handle's own
      // size has to be scaled to match: the canvas transform shrinks the
      // native handle along with everything else, and an 18px dead zone over a
      // 12px handle steals grab area the user can see is not a handle.
      const rect = el.getBoundingClientRect();
      const borderSize = 18 * editorScale;
      if (e.clientX > rect.right - borderSize && e.clientY > rect.bottom - borderSize) {
        return;
      }
      isDragging = true;
      el.classList.add("dragging");
      el.setPointerCapture(e.pointerId);

      startX = e.clientX;
      startY = e.clientY;

      initialLeft = parseFloat(el.style.left) || 0;
      initialTop = parseFloat(el.style.top) || 0;

      e.preventDefault();
    });

    el.addEventListener("pointermove", (e) => {
      if (!isDragging) return;
      
      // Pointer deltas arrive in screen pixels; `left`/`top` are canvas
      // pixels. They are the same thing at scale 1 and only at scale 1 --
      // without the division the widget drifts behind the cursor by exactly
      // the amount the editor shrank the canvas.
      const dx = (e.clientX - startX) / editorScale;
      const dy = (e.clientY - startY) / editorScale;

      let newLeft = Math.round(initialLeft + dx);
      let newTop = Math.round(initialTop + dy);

      const viewportWidth = canvasWidth;
      const viewportHeight = canvasHeight;
      
      newLeft = Math.max(0, Math.min(newLeft, viewportWidth - 50));
      newTop = Math.max(0, Math.min(newTop, viewportHeight - 50));

      el.style.left = `${newLeft}px`;
      el.style.top = `${newTop}px`;
    });

    const stopDragging = async (e) => {
      if (!isDragging) return;
      isDragging = false;
      el.classList.remove("dragging");
      try {
        el.releasePointerCapture(e.pointerId);
      } catch (err) {}

      const finalLeft = parseFloat(el.style.left) || 0;
      const finalTop = parseFloat(el.style.top) || 0;

      // This position is now the user's, so it stops being the clamp's business
      // -- the drag may legally end at `canvasWidth - 50`, which is further
      // right than the clamp would ever place a widget, and re-clamping it here
      // would slide it back the moment they let go. The next payload carries
      // the saved coordinates and rebuilds the element without the attribute
      // anyway; this closes the window before that arrives.
      el.removeAttribute("data-defaulted");

      const widgetId = el.getAttribute("data-id");
      if (widgetId) {
        try {
          await fetch("/api/save-widget-positions", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({
              id: widgetId,
              x: finalLeft,
              y: finalTop
            })
          });
        } catch (error) {
          console.error("Failed to save widget position:", error);
        }
      }
    };

    el.addEventListener("pointerup", stopDragging);
    el.addEventListener("pointercancel", stopDragging);
  });

  const controlsInNewWidgets = (selector) => draggables.flatMap(
    (el) => Array.from(el.querySelectorAll(selector))
  );
  const decButtons = controlsInNewWidgets(".widget-scale-btn.dec-scale");
  const incButtons = controlsInNewWidgets(".widget-scale-btn.inc-scale");

  decButtons.forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const widgetId = btn.getAttribute("data-id");
      const wrapper = btn.closest(".widget-wrapper");
      if (wrapper && widgetId) {
        let currentScale = parseFloat(wrapper.getAttribute("data-scale")) || 1.0;
        let newScale = Math.round((currentScale - 0.05) * 100) / 100;
        newScale = Math.max(0.4, Math.min(newScale, 4.0));
        
        wrapper.setAttribute("data-scale", newScale);
        wrapper.style.setProperty("--scale", newScale);
        const input = wrapper.querySelector(".widget-scale-input");
        if (input) {
          input.value = `${Math.round(newScale * 100)}%`;
        }

        try {
          await fetch("/api/save-widget-positions", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ id: widgetId, scale: newScale })
          });
        } catch (err) {
          console.error("Failed to save widget scale:", err);
        }
      }
    });
  });

  incButtons.forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const widgetId = btn.getAttribute("data-id");
      const wrapper = btn.closest(".widget-wrapper");
      if (wrapper && widgetId) {
        let currentScale = parseFloat(wrapper.getAttribute("data-scale")) || 1.0;
        let newScale = Math.round((currentScale + 0.05) * 100) / 100;
        newScale = Math.max(0.4, Math.min(newScale, 4.0));
        
        wrapper.setAttribute("data-scale", newScale);
        wrapper.style.setProperty("--scale", newScale);
        const input = wrapper.querySelector(".widget-scale-input");
        if (input) {
          input.value = `${Math.round(newScale * 100)}%`;
        }

        try {
          await fetch("/api/save-widget-positions", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ id: widgetId, scale: newScale })
          });
        } catch (err) {
          console.error("Failed to save widget scale:", err);
        }
      }
    });
  });

  // Set up scale text inputs
  const scaleInputs = controlsInNewWidgets(".widget-scale-input");
  scaleInputs.forEach((input) => {
    input.addEventListener("focus", () => {
      let val = input.value.replace("%", "");
      input.value = val;
      input.select();
    });

    const applyInputVal = async () => {
      const widgetId = input.getAttribute("data-id");
      const wrapper = input.closest(".widget-wrapper");
      if (wrapper && widgetId) {
        let val = parseInt(input.value) || 100;
        val = Math.max(40, Math.min(val, 400));
        let newScale = val / 100;

        wrapper.setAttribute("data-scale", newScale);
        wrapper.style.setProperty("--scale", newScale);
        input.value = `${val}%`;

        try {
          await fetch("/api/save-widget-positions", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ id: widgetId, scale: newScale })
          });
        } catch (err) {
          console.error("Failed to save widget scale:", err);
        }
      }
    };

    input.addEventListener("blur", applyInputVal);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        input.blur();
      }
    });
  });

  // Setup ResizeObserver to detect and persist manual widget resizing in Edit Mode
  if (window.ResizeObserver) {
    const resizeOb = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const el = entry.target;
        // Replacing a widget after an option change disconnects it from the
        // document. ResizeObserver reports that removal as a 0×0 resize; if
        // we save it, the server clamps it to its 60×40 safety floor and the
        // next editor frame becomes an unrecoverable postage stamp.
        if (!el.isConnected) {
          continue;
        }
        const widgetId = el.getAttribute("data-id");
        if (widgetId) {
          // `offsetWidth`/`offsetHeight`, not `getBoundingClientRect()`: the
          // rect is measured after the editor's canvas transform, so under a
          // fitted canvas a 285px widget reports ~190px -- and that is what
          // would be POSTed and persisted. Every open of the editor would have
          // shrunk every widget a little further. These two are border-box
          // like the rect, and in layout pixels the transform cannot reach.
          const w = el.offsetWidth;
          const h = el.offsetHeight;

          const savedW = parseInt(el.getAttribute("data-width")) || 0;
          const savedH = parseInt(el.getAttribute("data-height")) || 0;
          
          if (Math.abs(w - savedW) > 2 || Math.abs(h - savedH) > 2) {
            el.setAttribute("data-width", w);
            el.setAttribute("data-height", h);

            if (el.resizeTimeout) {
              clearTimeout(el.resizeTimeout);
            }
            el.resizeTimeout = setTimeout(async () => {
              try {
                await fetch("/api/save-widget-positions", {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json"
                  },
                  body: JSON.stringify({ id: widgetId, width: w, height: h })
                });
              } catch (err) {
                console.error("Failed to save widget size:", err);
              }
            }, 500);
          }
        }
      }
    });

    draggables.forEach((el) => {
      // Same units as the observer above, or the first callback would read a
      // 95px difference that nobody caused and save it.
      el.setAttribute("data-width", el.offsetWidth);
      el.setAttribute("data-height", el.offsetHeight);
      resizeOb.observe(el);
    });
  }
}

const EDIT_LAYOUT_FIELDS = new Set(["x", "y", "width", "height", "scale"]);

function editWidgetSettingsSignature(widget) {
  return JSON.stringify(
    Object.keys(widget || {})
      .filter((key) => !EDIT_LAYOUT_FIELDS.has(key))
      .sort()
      .map((key) => [key, widget[key]])
  );
}

function preserveEditWidgetLayout(currentElement, desiredElement) {
  // Layout pixels, for the same reason the resize observer uses them: this
  // writes an explicit `width`/`height` that the observer then reads back, and
  // a size measured through the canvas transform would be pinned smaller than
  // what is on screen -- once per settings change, compounding.
  const width = Math.max(1, currentElement.offsetWidth);
  const height = Math.max(1, currentElement.offsetHeight);

  desiredElement.style.left = currentElement.style.left;
  desiredElement.style.top = currentElement.style.top;
  desiredElement.style.width = `${width}px`;
  desiredElement.style.height = `${height}px`;
  desiredElement.setAttribute("data-width", String(width));
  desiredElement.setAttribute("data-height", String(height));
  desiredElement.classList.add("custom-size-active");

  const scale = currentElement.getAttribute("data-scale");
  if (scale) {
    desiredElement.setAttribute("data-scale", scale);
    desiredElement.style.setProperty("--scale", scale);
  }
}

function syncEditModeWidgets(html, widgets) {
  const nextSettings = new Map(
    widgets.map((widget) => [widget.id, editWidgetSettingsSignature(widget)])
  );

  if (!hasRenderedEditWidgets) {
    root.innerHTML = html;
    hasRenderedEditWidgets = true;
    lastEditWidgetSettings = nextSettings;
    return;
  }

  const staging = document.createElement("div");
  staging.innerHTML = html;
  const desiredWidgets = new Map(
    Array.from(staging.querySelectorAll(".widget-wrapper[data-id]"))
      .map((element) => [element.getAttribute("data-id"), element])
  );
  const currentWidgets = new Map(
    Array.from(root.querySelectorAll(".widget-wrapper[data-id]"))
      .map((element) => [element.getAttribute("data-id"), element])
  );

  currentWidgets.forEach((element, widgetId) => {
    if (!desiredWidgets.has(widgetId)) {
      element.remove();
    }
  });

  desiredWidgets.forEach((desiredElement, widgetId) => {
    const currentElement = currentWidgets.get(widgetId);
    if (!currentElement) {
      root.appendChild(desiredElement);
      return;
    }
    if (lastEditWidgetSettings.get(widgetId) !== nextSettings.get(widgetId)) {
      preserveEditWidgetLayout(currentElement, desiredElement);
      currentElement.replaceWith(desiredElement);
    }
  });

  lastEditWidgetSettings = nextSettings;
}

function render(state) {
  pollMs = Number(state.poll_ms || pollMs);
  canvasWidth = Number(state.canvas_width || 1920);
  canvasHeight = Number(state.canvas_height || 1080);
  root.style.setProperty("--canvas-width", `${canvasWidth}px`);
  root.style.setProperty("--canvas-height", `${canvasHeight}px`);
  // Before anything is measured: both survivors of the transform below --
  // the drag handler and the resize observer -- read `editorScale`.
  ensureEditorFrame();
  applyEditorScale();

  const requested = requestedWidgetId();
  applyStyle(state);

  const heldState = isEditMode ? state : holdLastGoodState(state);
  const renderedState = getOverlayStateForRendering(heldState);
  const widgets = enabledWidgets(renderedState);

  const status = isEditMode ? "live" : (renderedState.status || "waiting");

  const useAbsolute = shouldPositionAbsolutely(widgets);
  root.classList.toggle("single-widget", Boolean(requested));
  root.classList.toggle("absolute-layout", useAbsolute);

  // Three gates, and all three have to open. Quiet statuses never show a card;
  // `show_status` is opt-in for streamers who want it; and a frame we have no
  // data for at all still says something, otherwise the very first load of a
  // freshly configured overlay is an unexplained blank page.
  const showStatusCard = (state.style || {}).show_status === true || !lastGoodState;
  const statusPanel = QUIET_STATUSES.has(status) || !showStatusCard
    ? ""
    : panel("Status", `<div class="small-value">${escapeHtml(status.replaceAll("_", " "))}</div>`, "wide status-panel");
  const missingWidgetPanel = requested && !widgets.length ? panel("Status", `<div class="small-value">widget unavailable</div>`, "wide status-panel") : "";

  let html = statusPanel + missingWidgetPanel;

  if (useAbsolute) {
    html += widgets.map((widget) => {
      const placed = widget.x !== null && widget.x !== undefined
        && widget.y !== null && widget.y !== undefined;
      const fallback = placed ? null : defaultPosition(widget.id);
      const x = placed ? widget.x : fallback.x;
      const y = placed ? widget.y : fallback.y;
      // Read back by `clampDefaultedWidgets`, which can only correct a position
      // nobody chose. Dropped as soon as a drag saves one.
      const defaultedAttr = placed ? "" : ` data-defaulted="true"`;
      const wScale = widget.scale !== null && widget.scale !== undefined ? widget.scale : 1.0;
      const wWidth = widget.width !== null && widget.width !== undefined ? `${widget.width}px` : "auto";
      const wHeight = widget.height !== null && widget.height !== undefined ? `${widget.height}px` : "auto";
      const hasCustomSize = (widget.width !== null && widget.width !== undefined) || (widget.height !== null && widget.height !== undefined);
      const sizeClass = hasCustomSize ? " custom-size-active" : "";
      const dragClass = isEditMode ? " draggable" : "";
      
      const style = `position: absolute; left: ${x}px; top: ${y}px; width: ${wWidth}; height: ${wHeight}; --scale: ${wScale};`;
      const widgetContent = renderWidget(widget, renderedState);
      
      const toolbarHtml = isEditMode ? `
        <div class="widget-toolbar">
          <button class="widget-scale-btn dec-scale" title="Decrease Scale" data-id="${escapeHtml(widget.id)}">-</button>
          <input type="text" class="widget-scale-input" value="${Math.round(wScale * 100)}%" data-id="${escapeHtml(widget.id)}" />
          <button class="widget-scale-btn inc-scale" title="Increase Scale" data-id="${escapeHtml(widget.id)}">+</button>
        </div>
      ` : "";

      const widthAttr = widget.width !== null && widget.width !== undefined ? `data-width="${widget.width}"` : "";
      const heightAttr = widget.height !== null && widget.height !== undefined ? `data-height="${widget.height}"` : "";

      return `<div class="widget-wrapper${dragClass}${sizeClass}" data-id="${escapeHtml(widget.id)}" data-scale="${wScale}"${defaultedAttr} ${widthAttr} ${heightAttr} style="${style}">
        ${toolbarHtml}
        ${widgetContent}
      </div>`;
    }).join("");
  } else {
    html += widgets.map((widget) => {
      const wScale = widget.scale !== null && widget.scale !== undefined ? widget.scale : 1.0;
      const wWidth = widget.width !== null && widget.width !== undefined ? `${widget.width}px` : "auto";
      const wHeight = widget.height !== null && widget.height !== undefined ? `${widget.height}px` : "auto";
      const hasCustomSize = (widget.width !== null && widget.width !== undefined) || (widget.height !== null && widget.height !== undefined);
      const sizeClass = hasCustomSize ? " custom-size-active" : "";
      return `<div class="widget-wrapper${sizeClass}" data-id="${escapeHtml(widget.id)}" style="width: ${wWidth}; height: ${wHeight}; --scale: ${wScale};">
        ${renderWidget(widget, renderedState)}
      </div>`;
    }).join("");
  }

  if (isEditMode) {
    syncEditModeWidgets(html, widgets);
  } else {
    root.innerHTML = html;
  }

  if (useAbsolute) {
    // After the DOM exists and before anything measures it: `setupDragAndDrop`
    // seeds `data-width`/`data-height` and the drag reads `style.left`, and
    // both must see the corrected position rather than the one it replaced.
    clampDefaultedWidgets();
  }

  if (useAbsolute && isEditMode) {
    setupDragAndDrop();
    showEditBanner();
  }

  hasRenderedOnce = true;
}

async function refresh() {
  try {
    const response = await fetch("/api/overlay-state", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const state = await response.json();
    if (isEditMode) {
      lastEditWidgetRevision = Number(state.widget_revision || 0);
    }
    consecutiveFetchFailures = 0;
    if (loggedDegraded) {
      console.info("[overlay] overlay state poll recovered");
      loggedDegraded = false;
    }
    root.classList.remove("overlay-degraded");
    render(state);
  } catch (error) {
    consecutiveFetchFailures += 1;
    if (!hasRenderedOnce) {
      // Nothing has ever been drawn, so there is no frame to hold; this is the
      // only case that may still put a card in an empty root.
      root.innerHTML = panel("Status", `<div class="small-value">overlay unavailable</div>`, "wide status-panel");
    } else if (consecutiveFetchFailures >= OVERLAY_FAILURE_GRACE_POLLS) {
      root.classList.add("overlay-degraded");
      if (!loggedDegraded) {
        loggedDegraded = true;
        console.error(
          `[overlay] overlay state poll failed ${consecutiveFetchFailures} times in a row `
          + `(${error && error.message ? error.message : error}); holding the last good frame`
        );
      }
    }
  } finally {
    if (!isEditMode) {
      window.setTimeout(refresh, pollMs);
    } else if (!editWidgetWatcherStarted) {
      editWidgetWatcherStarted = true;
      watchEditWidgetChanges();
    }
  }
}

async function watchEditWidgetChanges() {
  while (isEditMode) {
    try {
      const after = Number(lastEditWidgetRevision || 0);
      const response = await fetch(`/api/overlay-widget-revision?after=${after}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const revision = Number(payload.revision || 0);
      if (revision !== lastEditWidgetRevision) {
        await refresh();
      }
    } catch (error) {
      await new Promise((resolve) => window.setTimeout(resolve, pollMs));
    }
  }
}

refresh();
