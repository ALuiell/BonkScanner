"""Halloween resource requirements, defaults and bounds; not engine policy."""
HALLOWEEN_ASSETS = frozenset(("forest-left", "forest-right", "bats", "web",
    "skeleton-reclining", "hat", "premium-crown", "header-fire-base",
    "header-pumpkin", "dark-moop-face", "support-spider", "support-spider-thank-you"))
PARAMETERS = {
    "pulse_pause_ms": (100, 3600000), "pulse_frame_ms": (16, 100),
    "footer_icon_scale": (.2, 1), "footer_icon_slot": (32, 60),
    "footer_link_height": (40, 64), "footer_height": (44, 72),
    "forest_height": (50, 120), "forest_left_width": (100, 400),
    "web_width": (50, 160), "web_height": (70, 220),
    "skeleton_max_width": (250, 500), "skeleton_right_margin": (8, 80),
    "skeleton_bottom_margin": (8, 80),
    "support_thread_seconds": (.3, 2), "support_climb_seconds": (1, 10),
    "support_read_seconds": (4, 30), "support_exit_seconds": (.2, 2),
}
DEFAULT_PARAMETERS = {
    "pulse_pause_ms": 4500, "pulse_frame_ms": 33,
    "footer_icon_scale": .8, "footer_icon_slot": 40,
    "footer_link_height": 44, "footer_height": 48,
    "forest_height": 86, "forest_left_width": 240,
    "web_width": 108, "web_height": 148,
    "skeleton_max_width": 340, "skeleton_right_margin": 16,
    "skeleton_bottom_margin": 18, "support_thread_seconds": .65,
    "support_climb_seconds": 4.4, "support_read_seconds": 8,
    "support_exit_seconds": .45,
}


def validate(preset):
    """Return resolved options; preserve the published v1 preset format."""
    assets = preset.get("assets", {})
    if not HALLOWEEN_ASSETS <= assets.keys():
        raise ValueError("Incomplete Halloween resource descriptor")
    parameters = preset.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Invalid Halloween parameters")
    for name, value in parameters.items():
        if (name not in PARAMETERS or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not PARAMETERS[name][0] <= value <= PARAMETERS[name][1]):
            raise ValueError(f"Unsupported Halloween parameter: {name}")
        if (name.endswith("_ms") or name in ("footer_icon_slot", "footer_link_height", "footer_height")) and not isinstance(value, int):
            raise ValueError("Halloween timer and layout values must be integers")
    return {**DEFAULT_PARAMETERS, **parameters}
