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

function applyStyle(state) {
  const style = state.style || {};
  const accent = style.accent_color || "#f6c453";
  const opacity = Number(style.background_opacity ?? 0.35);
  const scale = Number(style.scale ?? 1);
  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty("--panel-bg", `rgba(12, 18, 28, ${Math.max(0, Math.min(opacity, 1))})`);
  document.documentElement.style.setProperty("--scale", Math.max(0.6, Math.min(scale, 2)));
}

function panel(title, body, wide = false) {
  return `<section class="panel ${wide ? "wide" : ""}">
    <div class="panel-title">${title}</div>
    ${body}
  </section>`;
}

function renderWidget(widget, state) {
  switch (widget.id) {
    case "run_timer":
      return panel("Run Timer", `<div class="big-value">${state.run_timer_label || "--"}</div>`);
    case "level":
      return panel("Level", `<div class="big-value">${formatNumber(state.player_level)}</div>`);
    case "kills":
      return panel("Kills", `<div class="big-value">${formatNumber(state.mob_kills)}</div>`);
    case "current_stage":
      return panel("Stage", `<div class="big-value">${state.current_stage || "--"}</div>`);
    case "tracked_items":
      return panel("Tracked Items", renderTrackedItems(state), false);
    case "stage_summary":
      return panel("Stage Summary", renderStageSummary(state), true);
    case "weapons":
      return panel("Weapons", renderWeapons(state), true);
    case "items":
      return panel("Items", renderItems(state), true);
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
    const unknown = row.unknown_starting_inventory ? `<span class="muted"> +${row.unknown_starting_inventory} unknown</span>` : "";
    return `<div class="counter-row"><span>${row.label}</span><strong>${formatNumber(row.count)}${unknown}</strong></div>`;
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
      ${rows.map((row) => `<tr><td>${row.stage}</td><td>${row.time}</td><td>${row.kills}</td><td>${row.items}</td></tr>`).join("")}
    </tbody>
  </table>`;
}

function renderWeapons(state) {
  const rows = state.weapons || [];
  if (!rows.length) {
    return `<div class="muted">${state.weapons_available ? "No weapons yet" : "Weapons unavailable"}</div>`;
  }
  return rows.map((weapon) => {
    const stats = (weapon.stats || []).map((stat) => `${stat.label} ${stat.value}`).join(" · ");
    return `<div class="weapon-row"><span>${weapon.name} <span class="muted">Lv. ${weapon.level}</span></span><span>${stats || "--"}</span></div>`;
  }).join("");
}

function renderItems(state) {
  const rows = state.items || [];
  if (!rows.length) {
    return `<div class="muted">${state.items_available ? "No items yet" : "Items unavailable"}</div>`;
  }
  return rows.map((item) => `<div class="item-row"><span>${item}</span></div>`).join("");
}

function render(state) {
  applyStyle(state);
  pollMs = Number(state.poll_ms || pollMs);
  const widgets = enabledWidgets(state);
  const status = state.status || "waiting";
  const statusPanel = status === "live" ? "" : panel("Status", `<div class="small-value">${status.replace("_", " ")}</div>`, true);
  root.innerHTML = statusPanel + widgets.map((widget) => renderWidget(widget, state)).join("");
}

async function refresh() {
  try {
    const response = await fetch("/api/overlay-state", { cache: "no-store" });
    render(await response.json());
  } catch (error) {
    root.innerHTML = panel("Status", `<div class="small-value">overlay unavailable</div>`, true);
  } finally {
    window.setTimeout(refresh, pollMs);
  }
}

refresh();