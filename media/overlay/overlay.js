const root = document.getElementById("overlay");
let pollMs = 500;
let canvasWidth = 1920;
let canvasHeight = 1080;

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
}

function panel(title, body, classes = "", widget = null) {
  const backgroundOpacity = clampNumber(widget?.background_opacity, 0, 1, classes.includes("stage-summary-widget") ? 0.4 : 0.0);
  const style = `--widget-bg-opacity:${backgroundOpacity};`;
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
    case "stage_summary":
      return panel("Stage Summary", renderStageSummary(state), "wide stage-summary-widget", widget);
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
  const maxRows = Number(widget.max_rows || 40);
  const rows = (state.stats || []).slice(0, maxRows);
  if (!rows.length) {
    return `<div class="muted">--</div>`;
  }
  const maxLen = Math.max(...rows.map((row) => String(row.label || "").length));
  const labelWidth = Math.max(60, maxLen * 8.8);
  const style = `--stat-label-width: calc(${labelWidth}px * var(--scale));`;
  const body = rows.map((row) => `<div class="stat-row"><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value || "--")}</strong></div>`).join("");
  return `<div class="stats-list" style="${style}">${body}</div>`;
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
  const raritySlots = ["LEGENDARY", "RARE", "UNCOMMON", "COMMON"];
  return `<span class="stage-item-counts">${raritySlots.map((rarity) => {
    const item = rowsByRarity.get(rarity);
    const count = Number(item?.count || 0);
    const label = escapeHtml(rarity);
    const value = count > 0 ? formatNumber(count) : "--";
    const rarityClass = rarity.toLowerCase();
    return `<span class="stage-item-count ${rarityClass} ${count > 0 ? "active" : "empty"}" title="${label}">${value}</span>`;
  }).join("")}</span>`;
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
if (isEditMode) {
  document.body.classList.add("edit-mode-active");
}

const DEFAULT_COORDINATES = {
  stage_summary: { x: 20, y: 80 },
  tracked_items: { x: 20, y: 280 },
  stats: { x: 1600, y: 80 },
  banishes: { x: 1600, y: 400 }
};

function shouldPositionAbsolutely(widgets) {
  if (requestedWidgetId()) {
    return false;
  }
  if (isEditMode) {
    return true;
  }
  return widgets.some(w => w.x !== null && w.x !== undefined && w.y !== null && w.y !== undefined);
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
    renderedState.stats = [
      { label: "Damage", value: "+150%" },
      { label: "Attack Speed", value: "+45%" },
      { label: "Luck", value: "82" },
      { label: "XP Gain", value: "+25%" }
    ];
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
  const draggables = document.querySelectorAll(".widget-wrapper.draggable");
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
      // Avoid drag triggers when resizing widgets via bottom-right handle
      const rect = el.getBoundingClientRect();
      const borderSize = 18;
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
      
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

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

  const decButtons = document.querySelectorAll(".widget-scale-btn.dec-scale");
  const incButtons = document.querySelectorAll(".widget-scale-btn.inc-scale");

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
  const scaleInputs = document.querySelectorAll(".widget-scale-input");
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
        const widgetId = el.getAttribute("data-id");
        if (widgetId) {
          const rect = el.getBoundingClientRect();
          const w = Math.round(rect.width);
          const h = Math.round(rect.height);

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
      const rect = el.getBoundingClientRect();
      el.setAttribute("data-width", Math.round(rect.width));
      el.setAttribute("data-height", Math.round(rect.height));
      resizeOb.observe(el);
    });
  }
}

function render(state) {
  pollMs = Number(state.poll_ms || pollMs);
  canvasWidth = Number(state.canvas_width || 1920);
  canvasHeight = Number(state.canvas_height || 1080);
  root.style.setProperty("--canvas-width", `${canvasWidth}px`);
  root.style.setProperty("--canvas-height", `${canvasHeight}px`);

  const requested = requestedWidgetId();
  applyStyle(state);

  const renderedState = getOverlayStateForRendering(state);
  const widgets = enabledWidgets(renderedState);

  const status = isEditMode ? "live" : (renderedState.status || "waiting");
  
  const useAbsolute = shouldPositionAbsolutely(widgets);
  root.classList.toggle("single-widget", Boolean(requested));
  root.classList.toggle("absolute-layout", useAbsolute);

  const statusPanel = status === "live" ? "" : panel("Status", `<div class="small-value">${escapeHtml(status.replaceAll("_", " "))}</div>`, "wide status-panel");
  const missingWidgetPanel = requested && !widgets.length ? panel("Status", `<div class="small-value">widget unavailable</div>`, "wide status-panel") : "";

  let html = statusPanel + missingWidgetPanel;

  if (useAbsolute) {
    html += widgets.map((widget) => {
      const x = widget.x !== null && widget.x !== undefined ? widget.x : (DEFAULT_COORDINATES[widget.id]?.x ?? 20);
      const y = widget.y !== null && widget.y !== undefined ? widget.y : (DEFAULT_COORDINATES[widget.id]?.y ?? 80);
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

      return `<div class="widget-wrapper${dragClass}${sizeClass}" data-id="${escapeHtml(widget.id)}" data-scale="${wScale}" ${widthAttr} ${heightAttr} style="${style}">
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

  root.innerHTML = html;

  if (useAbsolute && isEditMode) {
    setupDragAndDrop();
    showEditBanner();
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/overlay-state", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    render(await response.json());
  } catch (error) {
    root.innerHTML = panel("Status", `<div class="small-value">overlay unavailable</div>`, "wide status-panel");
  } finally {
    if (!isEditMode) {
      window.setTimeout(refresh, pollMs);
    }
  }
}

refresh();
