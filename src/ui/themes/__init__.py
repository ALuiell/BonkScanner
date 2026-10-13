"""Reusable desktop theme presets; selection is independent of the calendar."""
from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from ui.shared import resource_path
from ui.themes.registry import theme_catalog, valid_theme_id

THEME_CONFIG_KEY = "DESKTOP_THEME_ID"
LEGACY_THEME_CONFIG_KEY = "USE_ORIGINAL_THEME"
_PALETTE_ROLES = {name: getattr(QPalette, name) for name in (
    "Window", "Base", "AlternateBase", "Button", "WindowText", "Text",
    "ButtonText", "Highlight", "HighlightedText",
)}


def selected_theme() -> str:
    """Retain the desired ID even if a later release removes or restricts it."""
    with config.config_lock:
        requested = config.user_config.get(THEME_CONFIG_KEY)
        if valid_theme_id(requested):
            return requested
        if THEME_CONFIG_KEY not in config.user_config:
            original = config.user_config.get(LEGACY_THEME_CONFIG_KEY)
            if original is True:
                return "original"
            if original is False:
                return "halloween"
    return theme_catalog().default_theme


def premium_access_for_themes(owner) -> bool:
    if not any(entry.access == "premium" for entry in theme_catalog().themes):
        return False
    checker = getattr(owner, "has_premium_access", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:
        return False


def resolved_theme(owner) -> str:
    return theme_catalog().resolve(selected_theme(), premium=premium_access_for_themes(owner))


def load_preset(theme: str) -> dict:
    if theme_catalog().get(theme) is None:
        raise ValueError(f"Unknown desktop theme: {theme}")
    from ui.themes.runtime import load_package
    return load_package(theme).preset


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


class _ThemeAccessBinding(QObject):
    """Restricted catalogs subscribe and sleep until the next local deadline."""
    def __init__(self, owner, access):
        super().__init__(owner.window)
        self.owner = owner
        self.access = access
        self.closed = False
        self.listener = self.refresh
        self.expiry_timer = QTimer(self)
        self.expiry_timer.setSingleShot(True)
        self.expiry_timer.setTimerType(Qt.PreciseTimer)
        self.expiry_timer.timeout.connect(self.refresh)
        owner.window.destroyed.connect(self.close)
        runtime = getattr(owner, "_appearance_runtime", None)
        if runtime is not None:
            runtime.disposing.connect(self.close)
        access.add_listener(self.listener)
        self._arm_expiry()

    def _arm_expiry(self):
        self.expiry_timer.stop()
        remaining = getattr(self.access, "premium_access_remaining_seconds", None)
        seconds = remaining() if callable(remaining) else None
        if seconds is not None and math.isfinite(seconds) and seconds > 0:
            # Qt intervals are signed 32-bit milliseconds. Long subscriptions
            # wake at that limit and re-arm; ordinary refreshes replace one timer.
            self.expiry_timer.start(min(2_147_483_647, max(1, math.ceil(seconds * 1000))))

    def refresh(self, *_args):
        if self.closed:
            return
        if getattr(self.owner, "_is_shutting_down", False):
            self.close()
            return
        try:
            if getattr(self.owner, "_visual_theme", None) != resolved_theme(self.owner):
                apply_theme(self.owner)
        finally:
            if not self.closed:
                self._arm_expiry()

    def close(self, *_args):
        if not self.closed:
            self.closed = True
            self.expiry_timer.stop()
            self.access.remove_listener(self.listener)
            self.deleteLater()


def _bind_theme_access(owner):
    restricted = any(entry.access == "premium" for entry in theme_catalog().themes)
    binding = getattr(owner, "_theme_access_binding", None)
    if not restricted:
        if binding is not None:
            binding.close()
        return
    access = getattr(owner, "supporter_access", None)
    if (binding is None or binding.closed) and callable(getattr(access, "add_listener", None)) and callable(getattr(access, "remove_listener", None)):
        owner._theme_access_binding = _ThemeAccessBinding(owner, access)


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
        if self.preset.get("neutral_color_map") and not self._updating and isinstance(watched, QWidget) and event.type() in (
            QEvent.Polish, QEvent.Show, QEvent.StyleChange,
        ):
            self._updating = True
            try:
                self._adapt_widget(watched)
            finally:
                self._updating = False
        return False


def apply_theme(owner) -> str:
    """Resolve policy, then switch the complete local appearance package."""
    from ui.styles import build_qt_app_stylesheet
    from ui.themes.runtime import AppearanceRuntime, load_package

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("A QApplication is required to apply a theme")
    controller = getattr(application, "_desktop_theme_controller", None)
    if controller is None:
        controller = _ThemeController(application)
        application._desktop_theme_controller = controller

    def apply_style(preset):
        controller.preset = preset
        checkmark = resource_path("media/checkmark.svg").replace("\\", "/")
        # Apply the already validated descriptor, including fallback packages.
        sheet = remap_colors(build_qt_app_stylesheet(checkmark, theme="original"), preset["color_map"])
        override = Path(resource_path(f"media/themes/{preset['id']}/overrides.qss"))
        if preset["id"] != "original" and override.is_file():
            sheet += "\n" + override.read_text(encoding="utf-8")
        palette = QPalette(controller.original_palette)
        for role, color in preset.get("qt_palette", {}).items():
            palette.setColor(_PALETTE_ROLES[role], QColor(color))
        controller._updating = True
        try:
            # Global repolish must finish before adapting local widget sheets.
            # Mutating them inside StyleChange can re-enter Qt's style traversal.
            application.setStyleSheet(sheet)
            application.setPalette(palette)
            for widget in application.allWidgets():
                controller._adapt_widget(widget)
        finally:
            controller._updating = False

    runtime = getattr(owner, "_appearance_runtime", None)
    if runtime is None:
        from ui.themes.host import build_theme_host
        footer = getattr(owner, "footer", None)
        runtime = AppearanceRuntime(build_theme_host(owner),
                                    bind_footer=footer.set_appearance if footer is not None else None)
        owner._appearance_runtime = runtime
    owner._visual_theme = runtime.switch(load_package(resolved_theme(owner)), apply_style)
    owner._theme_decorations = runtime.active.decorations  # Legacy diagnostic handle.
    _bind_theme_access(owner)
    return owner._visual_theme
