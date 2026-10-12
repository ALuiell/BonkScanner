"""Reusable desktop theme presets; selection is independent of the calendar."""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from ui.shared import resource_path

THEME_CONFIG_KEY = "USE_ORIGINAL_THEME"


def selected_theme() -> str:
    """Older profiles receive Halloween; an explicit Original choice survives updates."""
    with config.config_lock:
        original = config.user_config.get(THEME_CONFIG_KEY, False)
    return "original" if original is True else "halloween"


def load_preset(theme: str) -> dict:
    if theme not in ("original", "halloween"):
        raise ValueError(f"Unknown desktop theme: {theme}")
    path = Path(resource_path(f"media/themes/{theme}/preset.json"))
    try:
        preset = json.loads(path.read_text(encoding="utf-8"))
        if preset.get("id") != theme or not isinstance(preset.get("color_map"), dict):
            raise ValueError("Invalid theme preset")
        for mapping in (preset["color_map"], preset.get("neutral_color_map", {})):
            if not isinstance(mapping, dict) or any(
                not isinstance(value, str) or not isinstance(key, str)
                or re.fullmatch(r"#[0-9a-fA-F]{6}", key) is None
                or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None
                for key, value in mapping.items()
            ):
                raise ValueError("Invalid theme colors")
        return preset
    except (OSError, ValueError, TypeError, AttributeError):
        # A partially upgraded installation still has its original appearance.
        return {"id": "original", "color_map": {}, "decorations": False}


_COLORS = re.compile(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)")


def remap_colors(sheet: str, mapping: dict[str, str]) -> str:
    """One pass prevents a target token from being remapped a second time."""
    normalized = {key.upper(): value for key, value in mapping.items()}

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token.startswith("#"):
            return normalized.get(token.upper(), token)
        components = token[token.index("(") + 1:-1].split(",")
        source = "#{:02X}{:02X}{:02X}".format(*(int(value.strip()) for value in components[:3]))
        target = normalized.get(source)
        if target is None:
            return token
        color = QColor(target)
        alpha = f",{components[3].strip()}" if len(components) == 4 else ""
        return f"{token[:token.index('(')]}({color.red()},{color.green()},{color.blue()}{alpha})"

    return _COLORS.sub(replace, sheet)


def theme_stylesheet(original: str, theme: str) -> str:
    preset = load_preset(theme)
    if preset["id"] == "original":
        return original
    sheet = remap_colors(original, preset["color_map"])
    override = Path(resource_path(f"media/themes/{theme}/overrides.qss"))
    try:
        sheet += "\n" + override.read_text(encoding="utf-8")
    except OSError:
        pass
    return sheet


class _ThemeController(QObject):
    """Adapt neutral local styles, including dialogs created after a switch."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self.preset = load_preset("original")
        self.original_palette = QPalette(application.palette())
        self._updating = False
        application.installEventFilter(self)

    def _adapt_widget(self, widget: QWidget) -> None:
        if widget.objectName() in ("TemplateName", "ScoreTierName"):
            return
        current = widget.styleSheet()
        previous = widget.property("_desktopThemeLastSheet")
        if current != previous:
            widget.setProperty("_desktopThemeOriginalSheet", current)
        original = widget.property("_desktopThemeOriginalSheet")
        if original is None:
            original = current
        # Template and rarity identity colors are never transformed locally.
        mapping = self.preset.get("neutral_color_map", {})
        desired = remap_colors(original, mapping)
        widget.setProperty("_desktopThemeLastSheet", desired)
        if desired != current:
            widget.setStyleSheet(desired)

    def eventFilter(self, watched, event):  # noqa: N802
        if not self._updating and isinstance(watched, QWidget) and event.type() in (
            QEvent.Polish, QEvent.Show, QEvent.StyleChange,
        ):
            self._updating = True
            try:
                self._adapt_widget(watched)
            finally:
                self._updating = False
        return False


def apply_theme(owner) -> str:
    """Apply a saved desktop selection and refresh its existing decoration layer."""
    from ui.styles import build_qt_app_stylesheet
    from ui.themes.decorations import ThemeDecorations

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("A QApplication is required to apply a theme")
    theme = selected_theme()
    preset = load_preset(theme)
    controller = getattr(application, "_desktop_theme_controller", None)
    if controller is None:
        controller = _ThemeController(application)
        application._desktop_theme_controller = controller
    controller.preset = preset
    checkmark = resource_path("media/checkmark.svg").replace("\\", "/")
    application.setStyleSheet(build_qt_app_stylesheet(checkmark, theme=theme))
    palette = QPalette(controller.original_palette)
    if preset["id"] != "original":
        for role, color in (
            (QPalette.Window, "#15111C"), (QPalette.Base, "#120F19"),
            (QPalette.AlternateBase, "#211A2D"), (QPalette.Button, "#211A2D"),
            (QPalette.WindowText, "#F0EBF7"), (QPalette.Text, "#F0EBF7"),
            (QPalette.ButtonText, "#F0EBF7"), (QPalette.Highlight, "#8058BA"),
            (QPalette.HighlightedText, "#F0EBF7"),
        ):
            palette.setColor(role, QColor(color))
    application.setPalette(palette)
    controller._updating = True
    try:
        for widget in application.allWidgets():
            controller._adapt_widget(widget)
    finally:
        controller._updating = False
    decorations = getattr(owner, "_theme_decorations", None)
    if decorations is None:
        decorations = ThemeDecorations(owner)
        owner._theme_decorations = decorations
    decorations.set_enabled(bool(preset.get("decorations", False)))
    footer = getattr(owner, "footer", None)
    if footer is not None:
        footer.set_halloween_animation(decorations.animation)
        footer.set_theme(preset["id"])
    owner._visual_theme = preset["id"]
    return preset["id"]
