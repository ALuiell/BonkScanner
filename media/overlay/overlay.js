const root = document.getElementById("overlay");
let pollMs = 500;

function enabledWidgets(state) {
  const widgets = Object.values(state.widgets || {});
  return widgets
    .filter((widget) => widget.enabled)
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

function applyStyle(state) {
  const style = state.style || {};
  const accent = style.accent_color || "#f6c453";
  const opacity = Number(style.background_opacity ?? 0.35);
  const scale = Number(style.scale ?? 1);
  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty("--panel-bg", `rgba(8, 12, 18, ${Math.max(0, Math.min(opacity, 0.45))})`);
  document.documentElement.style.setProperty("--scale", Math.max(0.6, Math.min(scale, 2)));
}

function panel(title, body, classes = "") {
  return `<section class="panel ${classes}">
    <div class="panel-title">${escapeHtml(title)}</div>
    ${body}
  </section>`;
}

function renderWidget(widget, state) {
  switch (widget.id) {
    case "run_timer":
      return panel("Run Timer", `<div class="metric-value">${escapeHtml(state.run_timer_label || "--")}</div>`, "metric");
    case "level":
      return panel("Level", `<div class="metric-value">${formatNumber(state.player_level)}</div>`, "metric");
    case "kills":
      return panel("Kills", `<div class="metric-value">${formatNumber(state.mob_kills)}</div>`, "metric");
    case "current_stage":
      return panel("Stage", `<div class="metric-value">${escapeHtml(state.current_stage || "--")}</div>`, "metric");
    case "tracked_items":
      return panel("Tracked Items", renderTrackedItems(state));
    case "stage_summary":
      return panel("Stage Summary", renderStageSummary(state), "wide");
    case "weapons":
      return panel("Weapons", renderWeapons(state, widget), "wide");
    case "items":
      return panel("Items", renderItems(state, widget), "wide");
    default:
      return "";
  }
}

function renderTrackedItems(state) {
  const rows = state.tracked_items || [];
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  return rows.map((row) => {
    const unknown = row.unknown_starting_inventory ? `<span class="muted"> +${formatNumber(row.unknown_starting_inventory)}?</span>` : "";
    return `<div class="counter-row"><span>${escapeHtml(row.label)}</span><strong>${formatNumber(row.count)}${unknown}</strong></div>`;
  }).join("");
}

function renderStageSummary(state) {
  const rows = state.stage_summary || [];
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  return `<table class="summary-table">
    <thead><tr><th>Stage</th><th>Time</th><th>Kills</th><th>Items</th></tr></thead>
    <tbody>
      ${rows.map((row) => `<tr><td>${escapeHtml(row.stage)}</td><td>${escapeHtml(row.time)}</td><td>${escapeHtml(row.kills)}</td><td>${renderRarityCounts(row.items)}</td></tr>`).join("")}
    </tbody>
  </table>`;
}

function renderRarityCounts(items) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    return `<span class="muted">--</span>`;
  }
  return `<span class="rarity-counts">${rows.map((item) => {
    const color = escapeHtml(item.color || "#e5e7eb");
    const label = escapeHtml(item.rarity || "rarity");
    return `<span class="rarity-count" title="${label}"><span class="rarity-dot" style="background:${color}"></span>${formatNumber(item.count)}</span>`;
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
  const rows = (state.items || []).slice(0, maxRows);
  if (!rows.length) {
    return `<div class="muted">${state.items_available ? "No items yet" : "Items unavailable"}</div>`;
  }
  return rows.map((item) => `<div class="item-row"><span>${escapeHtml(item)}</span></div>`).join("");
}

function render(state) {
  applyStyle(state);
  pollMs = Number(state.poll_ms || pollMs);
  const widgets = enabledWidgets(state);
  const status = state.status || "waiting";
  const statusPanel = status === "live" ? "" : panel("Status", `<div class="small-value">${escapeHtml(status.replace("_", " "))}</div>`, "wide status-panel");
  root.innerHTML = statusPanel + widgets.map((widget) => renderWidget(widget, state)).join("");
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