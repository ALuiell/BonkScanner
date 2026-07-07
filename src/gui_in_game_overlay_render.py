from __future__ import annotations

from math import isfinite, log
from typing import Any

from gui_styles import ITEM_RARITY_COLOR_MAP

TEXT_SHADOW = "-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000"
POWERUP_COLORS: dict[str, str] = {
    "Rage": "#e879f9",
    "Shield": "#4ade80",
    "Stonks": "#fde047",
    "Clock": "#7dd3fc",
    "Timestomp": "#22d3ee",
}
CRITICAL_COLOR = "#ff4444"
HEADER_COLOR = "#ffffff"
FALLBACK_COLOR = "#d8b4fe"
LUCK_RARITY_BASE_WEIGHTS: dict[str, float] = {
    "COMMON": 70.0,
    "UNCOMMON": 15.0,
    "RARE": 6.0,
    "LEGENDARY": 1.5,
}
LUCK_RARITY_ORDER: tuple[str, ...] = ("LEGENDARY", "RARE", "UNCOMMON", "COMMON")
_LUCK_RARITY_EXPONENTS: dict[str, int] = {
    "COMMON": 3,
    "UNCOMMON": 2,
    "RARE": 1,
    "LEGENDARY": 0,
}

_KPS_METRICS: dict[str, tuple[str, str]] = {
    "instant": ("current_ui_kps", "KPS"),
    "60s": ("current_minute_avg_kps", "60s"),
    "5m": ("current_five_minute_avg_kps", "5m"),
    "run": ("current_run_avg_kps", "Run"),
}


def build_kps_overlay_html(run_tracker: Any, metrics_cfg: list[str] | tuple[str, ...]) -> str:
    sep = f"<span style='color: #94a3b8; text-shadow: {TEXT_SHADOW};'> | </span>"
    spans: list[str] = []

    for metric_id in metrics_cfg:
        metric_info = _KPS_METRICS.get(metric_id)
        if metric_info is None:
            continue
        method_name, label = metric_info
        reader = getattr(run_tracker, method_name, None)
        value = reader() if callable(reader) else None
        value_text = f"{value}" if value is not None else "--"
        spans.append(
            f"<span style='color: white; text-shadow: {TEXT_SHADOW};'>{label} {value_text}</span>"
        )

    return sep.join(spans)


def build_status_indicator_html(label: str, is_active: bool) -> str:
    color = "#22c55e" if is_active else "#ef4444"
    return (
        f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>"
        f"{label} &#9679;</span>"
    )


def build_luck_rarity_overlay_html(snapshot: Any) -> str:
    stats = getattr(snapshot, "stats", None)
    luck_stat = stats.get("Luck") if isinstance(stats, dict) else None
    luck_value = getattr(luck_stat, "value", None)
    probabilities = calculate_luck_rarity_probabilities(luck_value)
    return build_luck_rarity_overlay_html_for_probabilities(probabilities)


def build_luck_rarity_overlay_html_for_probabilities(
    probabilities: dict[str, float | None],
) -> str:

    sep = f"<span style='color: #94a3b8; text-shadow: {TEXT_SHADOW};'> | </span>"
    spans: list[str] = []
    for rarity in LUCK_RARITY_ORDER:
        color = ITEM_RARITY_COLOR_MAP.get(rarity, FALLBACK_COLOR)
        probability = probabilities.get(rarity)
        value_text = "--" if probability is None else f"{probability:.2f}%"
        spans.append(f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>{value_text}</span>")
    return sep.join(spans)


def build_powerups_overlay_html(
    snapshot: Any,
    *,
    edit_mode: bool = False,
    current_run_time_seconds: float | None = None,
) -> str:
    """Build overlay HTML for active powerups.

    Returns an empty string if none are active. In edit mode returns a placeholder
    so the widget stays visible and draggable.
    """
    active = list(getattr(snapshot, "active", None) or [])
    if not active:
        if edit_mode:
            return (
                f"<span style='color: {HEADER_COLOR}; opacity: 0.5; "
                f"text-shadow: {TEXT_SHADOW};'>Powerups (preview)</span>"
            )
        return ""

    pm_display = str(getattr(snapshot, "powerup_multiplier_display", "--") or "--")
    header = f"Powerups (PM {pm_display})" if pm_display != "--" else "Powerups"
    lines = [f"<span style='color: {HEADER_COLOR}; text-shadow: {TEXT_SHADOW};'>{header}</span>"]

    for effect in active:
        name = str(getattr(effect, "name", "?"))
        remaining = max(0.0, float(getattr(effect, "remaining_seconds", 0)))
        pickup_ui = getattr(effect, "pickup_ui", None)
        expires_ui = getattr(effect, "expires_ui", None)
        secs = int(round(remaining))
        time_str = f"{secs}s"

        if pickup_ui is not None and expires_ui is not None:
            detail = f"{pickup_ui} → {expires_ui} ({time_str})"
        else:
            detail = f"({time_str})"

        color = CRITICAL_COLOR if remaining < 5 else POWERUP_COLORS.get(name, FALLBACK_COLOR)
        lines.append(
            f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>"
            f"{name}: {detail}</span>"
        )

    return "<br>".join(lines)


def calculate_luck_rarity_probabilities(luck_value: float | None) -> dict[str, float | None]:
    if luck_value is None:
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    try:
        luck_value = float(luck_value)
    except (TypeError, ValueError):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    if not isfinite(luck_value):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    adjusted_luck = max(luck_value, -0.999999999)
    strength = log(adjusted_luck + 1.0) * 1.5

    weights: dict[str, float] = {}
    for rarity, base_weight in LUCK_RARITY_BASE_WEIGHTS.items():
        exponent = _LUCK_RARITY_EXPONENTS[rarity] * strength
        weights[rarity] = base_weight * (1.5 ** (-exponent))

    total_weight = sum(weights.values())
    if total_weight <= 0 or not isfinite(total_weight):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    return {
        rarity: (weights[rarity] / total_weight) * 100.0
        for rarity in LUCK_RARITY_ORDER
    }


def build_stats_overlay_html(
    snapshot: Any,
    selected_stats: list[str],
    stage_index: int,
    stage_timer_seconds: float,
    stage_time_seconds: float,
    is_graveyard: bool,
) -> str:
    if snapshot is None:
        return ""
    stats = getattr(snapshot, "stats", {}) or {}
    if not isinstance(stats, dict):
        return ""

    lines = []
    for label in selected_stats:
        stat = stats.get(label)
        if stat is None:
            continue

        display_val = getattr(stat, "display_value", "--")
        raw_val = getattr(stat, "value", None)
        try:
            raw_val = float(raw_val) if raw_val is not None else None
        except (TypeError, ValueError):
            raw_val = None

        color = "#16e7ff"  # Cyan by default
        cap_suffix = ""

        if not is_graveyard and raw_val is not None:
            if label == "Difficulty":
                is_after_2m_ghosts = stage_timer_seconds >= (stage_time_seconds + 120.0)

                cap = None
                if stage_index == 0:
                    cap = 4.95 if is_after_2m_ghosts else 5.71
                elif stage_index == 1:
                    cap = 4.38 if is_after_2m_ghosts else 5.14
                elif stage_index == 2:
                    cap = 3.81 if is_after_2m_ghosts else 4.57

                if cap is not None:
                    cap_pct = int(round(cap * 100))
                    cap_suffix = f" / {cap_pct}%"
                    if raw_val >= cap:
                        color = "#ff4d4d"  # Red
            elif label == "XP Gain":
                cap = 10.0
                cap_suffix = " / 10x"
                if raw_val >= cap:
                    color = "#ff4d4d"  # Red

        lines.append(
            f"<span style='color: #ffffff; text-shadow: {TEXT_SHADOW};'>{label}: </span>"
            f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>{display_val}{cap_suffix}</span>"
        )

    return "<br>".join(lines)


def build_event_timer_overlay_html(
    stage_index: int,
    stage_timer_seconds: float,
    stage_time_seconds: float,
    is_graveyard: bool,
    warning_seconds: int = 15,
) -> str:
    if is_graveyard:
        return ""
    if stage_index not in (0, 1, 2):
        return ""

    remaining_time = stage_time_seconds - stage_timer_seconds
    if remaining_time <= 0:
        return ""

    if stage_index in (0, 1):
        events = [
            ("boss", 420.0, 0.0),
            ("wave", 360.0, 30.0),
            ("wave", 180.0, 30.0),
            ("boss", 120.0, 0.0),
        ]
    else:  # stage_index == 2
        events = [
            ("boss", 390.0, 0.0),
            ("wave", 330.0, 30.0),
            ("wave", 240.0, 30.0),
            ("boss", 180.0, 0.0),
        ]

    # Check active waves first
    for ev_type, start_rem, duration in events:
        if duration > 0.0:
            end_rem = start_rem - duration
            if end_rem <= remaining_time <= start_rem:
                wave_rem = remaining_time - end_rem
                secs = int(round(wave_rem))
                return f"<span style='color: #ff4d4d; text-shadow: {TEXT_SHADOW}; font-weight: bold;'>Wave active: {secs}s</span>"

    # Check upcoming warnings next
    upcoming_events = []
    for ev_type, start_rem, duration in events:
        if remaining_time > start_rem:
            diff = remaining_time - start_rem
            if diff <= warning_seconds:
                upcoming_events.append((diff, ev_type))

    if upcoming_events:
        upcoming_events.sort()
        diff, ev_type = upcoming_events[0]
        secs = int(round(diff))
        label = "Boss" if ev_type == "boss" else "Wave"
        return f"<span style='color: #ff9f1c; text-shadow: {TEXT_SHADOW}; font-weight: bold;'>{label} in {secs}s</span>"

    return ""
