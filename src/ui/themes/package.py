"""Validated, local appearance packages. Descriptors never import arbitrary code."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import re

from ui.shared import resource_path

PROVIDERS = frozenset(("none", "halloween"))
PALETTE_ROLES = frozenset(("Window", "Base", "AlternateBase", "Button", "WindowText",
                          "Text", "ButtonText", "Highlight", "HighlightedText"))
HALLOWEEN_ASSETS = frozenset(("forest-left", "forest-right", "bats", "web",
    "skeleton-reclining", "hat", "premium-crown", "header-fire-base",
    "header-pumpkin", "support-spider", "support-spider-thank-you"))
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


@dataclass(frozen=True)
class ThemePackage:
    root: Path
    preset: dict

    @property
    def id(self):
        return self.preset["id"]

    @property
    def provider(self):
        return self.preset.get("runtime_provider", "none")

    def asset(self, name):
        item = self.preset.get("assets", {}).get(name)
        if item is None:
            return ""
        path = self.root / item["path"]
        return str(path) if path.is_file() else ""

    def parameter(self, name):
        return self.preset.get("parameters", {}).get(name, DEFAULT_PARAMETERS[name])

    def color(self, *args):
        """Optional family palette remapping, preserving animated alpha."""
        from PySide6.QtGui import QColor
        original = QColor(*args)
        replacement = self.preset.get("effect_color_map", {}).get(original.name().upper())
        if replacement is None:
            return original
        result = QColor(replacement)
        result.setAlpha(original.alpha())
        return result


def read_package(theme):
    from ui.themes.registry import valid_theme_id
    if not valid_theme_id(theme):
        raise ValueError("Invalid appearance ID")
    root = Path(resource_path(f"media/themes/{theme}"))
    preset = json.loads((root / "preset.json").read_text(encoding="utf-8"))
    if (not isinstance(preset, dict) or type(preset.get("schema_version")) is not int or preset.get("schema_version") != 1
            or preset.get("id") != theme or not isinstance(preset.get("version"), str)
            or preset.get("runtime_provider", "none") not in PROVIDERS):
        raise ValueError("Unsupported appearance package")
    for field in ("color_map", "neutral_color_map", "qt_palette", "effect_color_map"):
        mapping = preset.get(field, {})
        if not isinstance(mapping, dict):
            raise ValueError("Invalid appearance colors")
        for key, value in mapping.items():
            if (not isinstance(key, str) or not isinstance(value, str)
                    or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None
                    or (key not in PALETTE_ROLES if field == "qt_palette"
                        else re.fullmatch(r"#[0-9a-fA-F]{6}", key) is None)):
                raise ValueError("Invalid appearance colors")
        if field == "effect_color_map":
            preset[field] = {key.upper(): value for key, value in mapping.items()}
    preset.setdefault("color_map", {})
    assets = preset.get("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("Invalid appearance resources")
    for item in assets.values():
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or not isinstance(item.get("required", True), bool)):
            raise ValueError("Invalid appearance resource")
        path = PurePosixPath(item["path"])
        if (path.is_absolute() or ".." in path.parts or ":" in item["path"]
                or "\\" in item["path"] or path.suffix != ".svg"
                or not (root / path).resolve().is_relative_to(root.resolve())):
            raise ValueError("Resource must be an SVG inside its package")
        if item.get("required", True) and not (root / path).is_file():
            raise ValueError("Missing required appearance resource")
    if preset.get("runtime_provider") == "halloween" and not HALLOWEEN_ASSETS <= assets.keys():
        raise ValueError("Incomplete Halloween resource descriptor")
    parameters = preset.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Invalid appearance parameters")
    for name, value in parameters.items():
        if (name not in PARAMETERS or isinstance(value, bool) or not isinstance(value, (int, float))
                or not PARAMETERS[name][0] <= value <= PARAMETERS[name][1]):
            raise ValueError("Unsupported appearance parameter")
        if (name.endswith("_ms") or name in ("footer_icon_slot", "footer_link_height", "footer_height")) and not isinstance(value, int):
            raise ValueError("Appearance timer and layout values must be integers")
    return ThemePackage(root, preset)


def original_package():
    # Emergency baseline also works when the installation's descriptors are damaged.
    return ThemePackage(Path(resource_path("media/themes/original")), {
        "schema_version": 1, "version": "1", "id": "original", "color_map": {},
        "runtime_provider": "none"})
