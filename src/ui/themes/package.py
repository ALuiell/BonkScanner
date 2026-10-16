"""Validated, local appearance packages. Descriptors never import arbitrary code."""
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
import json
import re

from ui.shared import resource_path

PALETTE_ROLES = frozenset(("Window", "Base", "AlternateBase", "Button", "WindowText",
                          "Text", "ButtonText", "Highlight", "HighlightedText"))


@dataclass(frozen=True)
class ThemePackage:
    root: Path
    preset: dict
    options: Mapping = field(init=False, repr=False)

    def __post_init__(self):
        from ui.themes.providers import provider_definition
        options = provider_definition(self.provider).validate(self.preset)
        object.__setattr__(self, "options", MappingProxyType(dict(options)))

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
        return self.options[name]

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
            or not valid_theme_id(preset.get("runtime_provider", "none"))):
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
                or "\\" in item["path"] or path.suffix not in (".svg", ".png")
                or not (root / path).resolve().is_relative_to(root.resolve())):
            raise ValueError("Resource must be an SVG or PNG inside its package")
        if item.get("required", True) and not (root / path).is_file():
            raise ValueError("Missing required appearance resource")
    if not isinstance(preset.get("parameters", {}), dict):
        raise ValueError("Invalid appearance parameters")
    return ThemePackage(root, preset)


def original_package():
    # Emergency baseline also works when the installation's descriptors are damaged.
    return ThemePackage(Path(resource_path("media/themes/original")), {
        "schema_version": 1, "version": "1", "id": "original", "color_map": {},
        "runtime_provider": "none"})
