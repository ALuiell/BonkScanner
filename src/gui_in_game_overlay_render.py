from __future__ import annotations

from math import isfinite, log
from typing import Any

import run_summary
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
    probabilities = _calculate_luck_rarity_probabilities(luck_value)

    sep = f"<span style='color: #94a3b8; text-shadow: {TEXT_SHADOW};'> | </span>"
    spans: list[str] = []
    for rarity in LUCK_RARITY_ORDER:
        color = ITEM_RARITY_COLOR_MAP.get(rarity, FALLBACK_COLOR)
        probability = probabilities.get(rarity)
        value_text = "--" if probability is None else f"{probability:.2f}%"
        spans.append(
            f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>{value_text}</span>"
        )
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
        pickup_ui, expires_ui = _resolve_powerup_ui_times(effect, current_run_time_seconds)
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


def _resolve_powerup_ui_times(
    effect: Any,
    current_run_time_seconds: float | None,
) -> tuple[str | None, str | None]:
    pickup_ui = None
    expires_ui = None

    if current_run_time_seconds is not None:
        try:
            pickup_offset = float(getattr(effect, "pickup_offset_seconds"))
            expiration_offset = float(getattr(effect, "expiration_offset_seconds"))
        except (AttributeError, TypeError, ValueError):
            pickup_offset = None
            expiration_offset = None
        if pickup_offset is not None and expiration_offset is not None:
            pickup_ui = run_summary.format_elapsed_time(
                max(0.0, float(current_run_time_seconds) + pickup_offset)
            )
            expires_ui = run_summary.format_elapsed_time(
                max(0.0, float(current_run_time_seconds) + expiration_offset)
            )

    if pickup_ui is None or expires_ui is None:
        pickup_ui = getattr(effect, "pickup_ui", None)
        expires_ui = getattr(effect, "expires_ui", None)

    return pickup_ui, expires_ui


def _calculate_luck_rarity_probabilities(luck_value: float | None) -> dict[str, float | None]:
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
