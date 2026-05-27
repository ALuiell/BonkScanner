const root = document.getElementById("overlay");
let pollMs = 500;

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
  return Number(value).toLocaleString("en-US");
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

function applyStyle(state, requestedWidget) {
  const style = state.style || {};
  const accent = style.accent_color || "#f6c453";
  const opacity = clampNumber(style.background_opacity, 0, 1, 0.0);
  const stageOpacity = clampNumber(style.stage_background_opacity, 0, 1, 0.15);
  const configuredScale = Math.max(0.6, Math.min(Number(style.scale ?? 1), 4));
  const singleWidget = Boolean(requestedWidget);
  const baseWidth = requestedWidget === "stage_summary" ? 410 : 260;
  const baseHeight = requestedWidget === "stage_summary" ? 210 : 160;
  const autoScale = singleWidget
    ? Math.max(1, Math.min(window.innerWidth / baseWidth, window.innerHeight / baseHeight, 4))
    : 1;
  const scale = singleWidget ? Math.max(configuredScale, autoScale) : Math.min(configuredScale, 2);
  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty("--panel-bg-opacity", Math.max(0, Math.min(opacity, 0.45)));
  document.documentElement.style.setProperty("--stage-bg-opacity", Math.max(0, Math.min(stageOpacity, 0.45)));
  document.documentElement.style.setProperty("--scale", scale);
}

function panel(title, body, classes = "", widget = null) {
  const backgroundOpacity = clampNumber(widget?.background_opacity, 0, 1, classes.includes("stage-summary-widget") ? 0.15 : 0.0);
  const borderOpacity = widget?.show_border ? 0.15 : 0;
  const style = `--widget-bg-opacity:${backgroundOpacity};--widget-border-opacity:${borderOpacity};`;
  return `<section class="panel ${classes}" style="${style}">
    <div class="panel-title">${escapeHtml(title)}</div>
    ${body}
  </section>`;
}

function renderWidget(widget, state) {
  switch (widget.id) {
    case "tracked_items":
      return panel("Tracked Items", renderTrackedItems(state), "wide item-widget", widget);
    case "stats":
      return panel("Stats", renderStats(state, widget), "wide stats-widget", widget);
    case "stage_summary":
      return panel("Stage Summary", renderStageSummary(state), "wide stage-summary-widget", widget);
    case "weapons":
      return panel("Weapons", renderWeapons(state, widget), "wide", widget);
    case "items":
      return panel("Items", renderItems(state, widget), "wide items-widget", widget);
    case "banishes":
      return panel("Banishes", renderBanishes(state, widget), "wide banishes-widget", widget);
    default:
      return "";
  }
}

function renderTrackedItems(state) {
  const rows = state.tracked_items || [];
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  return `<div class="chip-strip">${rows.map((row) => {
    const unknown = row.unknown_starting_inventory ? `<span class="muted"> +${formatNumber(row.unknown_starting_inventory)}?</span>` : "";
    const label = String(row.label || "").replace(/\s+map\s*1$/i, "");
    return `<div class="counter-chip"><span>${escapeHtml(label)}</span><strong>${formatNumber(row.count)}${unknown}</strong></div>`;
  }).join("")}</div>`;
}

function renderStats(state, widget) {
  const maxRows = Number(widget.max_rows || 8);
  const rows = (state.stats || []).slice(0, maxRows);
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  return `<div class="stats-list">${rows.map((row) => `<div class="stat-row"><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value || "--")}</strong></div>`).join("")}</div>`;
}

function renderStageSummary(state) {
  const rows = Array.isArray(state.stage_summary) ? state.stage_summary : [];
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
      <div class="stage-cell stage-items">${renderStageItems(items)}</div>
    </div>`;
  }).join("");
  return `<div class="stage-table">${headers}${body}</div>`;
}

function renderStageItems(items) {
  const rows = Array.isArray(items) ? items : [];
  const rowsByRarity = new Map(rows.map((item) => [String(item.rarity || "").toUpperCase(), item]));
  const raritySlots = [
    ["LEGENDARY", "var(--hud-orange)"],
    ["RARE", "var(--hud-purple)"],
    ["UNCOMMON", "var(--hud-green)"],
    ["COMMON", "var(--hud-cyan)"],
  ];
  return `<span class="stage-item-counts">${raritySlots.map(([rarity, fallbackColor]) => {
    const item = rowsByRarity.get(rarity);
    const count = Number(item?.count || 0);
    const color = escapeHtml(item?.color || fallbackColor);
    const label = escapeHtml(rarity);
    const value = count > 0 ? formatNumber(count) : "--";
    return `<span class="stage-item-count ${count > 0 ? "active" : "empty"}" title="${label}" style="color:${color}">${value}</span>`;
  }).join("")}</span>`;
}

function renderWeapons(state, widget) {
  const maxRows = Number(widget.max_rows || 4);
  const rows = (state.weapons || []).slice(0, maxRows);
  if (!rows.length) {
    return `<div class="muted">${state.weapons_available ? "No weapons yet" : "Weapons unavailable"}</div>`;
  }
  return rows.map((weapon) => {
    const stats = (weapon.stats || []).map((stat) => `${escapeHtml(stat.label)} ${escapeHtml(stat.value)}`).join(" · ");
    return `<div class="weapon-row"><span>${escapeHtml(weapon.name)} <span class="muted">Lv. ${formatNumber(weapon.level)}</span></span><span>${stats || "--"}</span></div>`;
  }).join("");
}

function renderItems(state, widget) {
  const maxRows = Number(widget.max_rows || 12);
  const allRows = state.items || [];
  const rows = allRows.slice(0, maxRows);
  const remaining = Math.max(0, allRows.length - rows.length);
  if (!allRows.length) {
    return `<div class="muted">${state.items_available ? "No items yet" : "Items unavailable"}</div>`;
  }
  const more = remaining > 0 ? `<span class="item-chip more-chip">+${formatNumber(remaining)} more</span>` : "";
  return `<div class="item-strip">${rows.map((item) => `<span class="item-chip">${escapeHtml(item)}</span>`).join("")}${more}</div>`;
}

function renderBanishes(state, widget) {
  const maxRows = Number(widget.max_rows || 12);
  const allRows = state.banishes || [];
  const rows = allRows.slice(0, maxRows);
  const remaining = Math.max(0, allRows.length - rows.length);
  if (!allRows.length) {
    return `<div class="muted">No banishes yet</div>`;
  }
  const more = remaining > 0 ? `<span class="item-chip more-chip">+${formatNumber(remaining)} more</span>` : "";
  return `<div class="item-strip banish-strip">${rows.map((item) => `<span class="item-chip banish-chip">${escapeHtml(item)}</span>`).join("")}${more}</div>`;
}

function render(state) {
  pollMs = Number(state.poll_ms || pollMs);
  const requested = requestedWidgetId();
  applyStyle(state, requested);
  const widgets = enabledWidgets(state);
  const status = state.status || "waiting";
  const statusPanel = status === "live" ? "" : panel("Status", `<div class="small-value">${escapeHtml(status.replace("_", " "))}</div>`, "wide status-panel");
  const missingWidgetPanel = requested && !widgets.length ? panel("Status", `<div class="small-value">widget unavailable</div>`, "wide status-panel") : "";
  root.classList.toggle("single-widget", Boolean(requested));
  root.innerHTML = statusPanel + missingWidgetPanel + widgets.map((widget) => renderWidget(widget, state)).join("");
}

async function refresh() {
  try {
    const response = await fetch("/api/overlay-state", { cache: "no-store" });
    render(await response.json());
  } catch (error) {
    root.innerHTML = panel("Status", `<div class="small-value">overlay unavailable</div>`, "wide status-panel");
  } finally {
    window.setTimeout(refresh, pollMs);
  }
}

refresh();
