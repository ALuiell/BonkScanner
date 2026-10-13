"""One active provider per host. No application fields or theme-specific branches."""
import logging

from PySide6.QtCore import QObject, Signal

from ui.themes.contracts import AppearanceProvider, ThemeHost  # AppearanceProvider: legacy import
from ui.themes.package import original_package, read_package
from ui.themes.providers import provider_definition

log = logging.getLogger(__name__)


def create_provider(host: ThemeHost, package) -> AppearanceProvider:
    return provider_definition(package.provider).factory(host, package)


class AppearanceRuntime(QObject):
    disposing = Signal()

    def __init__(self, host: ThemeHost, *, bind_footer=None):
        if not isinstance(host, ThemeHost):
            raise TypeError("AppearanceRuntime requires a ThemeHost")
        super().__init__(host.window)
        self.host = host
        self._bind_footer = bind_footer
        self.active = None
        self.switching = False
        self.disposed = False

    def switch(self, package, apply_style):
        if self.disposed:
            raise RuntimeError("Appearance runtime has been disposed")
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
        # Factories only construct lightweight Python objects. Runtime holds the
        # instance before prepare allocates any Qt resources or installs hooks.
        self.active = create_provider(self.host, package)
        self.active.validate_host()
        self.active.prepare()
        apply_style(package.preset)
        if self._bind_footer is not None:
            self._bind_footer(self.active)
        self.active.activate()

    def _stop(self):
        # Detach consumers while their icons/clocks are still alive. A failing
        # consumer must not prevent cleanup of the provider itself.
        active, self.active = self.active, None
        try:
            if self._bind_footer is not None:
                self._bind_footer(None)
        except Exception:
            log.exception("Cannot detach appearance footer")
        finally:
            if active is not None:
                try:
                    active.dispose()
                except Exception:
                    log.exception("Cannot dispose appearance %s", active.package.id)
                    active.resources.close()

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self.disposing.emit()
        self._stop()


def load_package(theme):
    try:
        return read_package(theme)
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("Cannot load appearance %s; using Default", theme)
        return original_package()
