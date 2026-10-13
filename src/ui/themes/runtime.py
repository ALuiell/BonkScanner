"""One active provider per window; application policy stays outside the skin."""
import logging

from PySide6.QtCore import QObject

from ui.themes.package import original_package, read_package

log = logging.getLogger(__name__)


class AppearanceProvider:
    """A palette-only theme needs no decorative widgets, clocks or caches."""
    def __init__(self, owner, package):
        self.owner = owner
        self.package = package
        self.footer_icon = None
        self.footer_height = 28
        self.decorations = None

    def activate(self):
        pass

    def create_support(self, **callbacks):
        return None

    def dispose(self):
        pass


def create_provider(owner, package):
    # Explicit import is discoverable by PyInstaller; descriptors cannot execute code.
    if package.provider == "halloween":
        from ui.themes.providers.halloween import HalloweenProvider
        return HalloweenProvider(owner, package)
    return AppearanceProvider(owner, package)


class AppearanceRuntime(QObject):
    def __init__(self, owner):
        super().__init__(owner.window)
        self.owner = owner
        self.active = None
        self.switching = False

    def switch(self, package, apply_style):
        if self.switching:
            return self.active.package.id if self.active else "original"
        if self.active is not None and self.active.package == package:
            return package.id
        self.switching = True
        try:
            self._stop()
            try:
                self._activate(package, apply_style)
            except Exception:
                log.exception("Cannot activate appearance %s; restoring Default", package.id)
                self._stop()
                self._activate(original_package(), apply_style)
            return self.active.package.id
        finally:
            self.switching = False

    def _activate(self, package, apply_style):
        apply_style(package.preset)
        self.active = create_provider(self.owner, package)
        self.owner._theme_decorations = self.active.decorations
        footer = getattr(self.owner, "footer", None)
        if footer is not None:
            footer.set_appearance(self.active)
        self.active.activate()

    def _stop(self):
        footer = getattr(self.owner, "footer", None)
        if footer is not None:
            footer.set_appearance(None)
        if self.active is not None:
            self.active.dispose()
            self.active = None
        self.owner._theme_decorations = None

    def dispose(self):
        self._stop()


def load_package(theme):
    try:
        return read_package(theme)
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("Cannot load appearance %s; using Default", theme)
        return original_package()
