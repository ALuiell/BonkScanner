"""Qt-free demand predicates shared by refresh and memory acquisition."""

from __future__ import annotations

from app import config


def in_game_overlay_widget_enabled(widget_id: str) -> bool:
    overlay = getattr(config, "IN_GAME_OVERLAY", {}) or {}
    if not overlay.get("enabled", False):
        return False
    widgets = overlay.get("widgets", {}) or {}
    if not isinstance(widgets, dict):
        return False
    widget_cfg = widgets.get(widget_id, {})
    return isinstance(widget_cfg, dict) and bool(widget_cfg.get("enabled", False))


def in_game_overlay_weapon_tracker_active() -> bool:
    """Whether Weapon Tracker currently consumes a full weapon sample."""
    if not in_game_overlay_widget_enabled("weapon_tracker"):
        return False
    widgets = (getattr(config, "IN_GAME_OVERLAY", {}) or {}).get("widgets", {})
    widget_cfg = widgets.get("weapon_tracker", {}) if isinstance(widgets, dict) else {}
    return isinstance(widget_cfg, dict) and bool(widget_cfg.get("selected_stats", ()))


def in_game_overlay_requires_player_stats_refresh() -> bool:
    # Luck Rarity rides the narrow one-second Luck source and deliberately does
    # not demand this full 10-second snapshot.
    return (
        in_game_overlay_widget_enabled("stats")
        or in_game_overlay_widget_enabled("event_timer")
        or in_game_overlay_widget_enabled("build_progression")
        or in_game_overlay_weapon_tracker_active()
    )
