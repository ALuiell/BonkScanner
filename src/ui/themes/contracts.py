"""The complete, application-independent contract for built-in appearance providers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractButton, QLabel, QTabWidget, QTextEdit, QWidget

from ui.themes.lifecycle import ThemeResources

if TYPE_CHECKING:
    from ui.themes.package import ThemePackage


@dataclass(frozen=True)
class HeaderArea:
    widget: QWidget
    # Horizontal clear span in header coordinates; layout owns control discovery.
    content_span: Callable[[], tuple[int, int]]
    # Left boundary for reflected light, in the supplied surface's coordinates.
    light_left: Callable[[QWidget], int]


@dataclass(frozen=True)
class TemplateArea:
    widget: QWidget
    # Empty decoration rectangle in widget coordinates, or None on another page.
    available_rect: Callable[[], QRect | None]


@dataclass(frozen=True)
class ThemeHost:
    """Visual anchors only. No app, config, scanner, entitlement or network handle.

    A palette-only provider needs only window. Providers explicitly validate the
    optional anchors they use. Qt geometry/events are deliberately not abstracted
    into another UI framework. Signals and watched surfaces carry layout updates.
    """
    window: QWidget
    header: HeaderArea | None = None
    logo: QLabel | None = None
    premium_badge: QAbstractButton | None = None
    corner_tabs: QTabWidget | None = None
    templates: TemplateArea | None = None
    log_view: QTextEdit | None = None
    layout_widgets: tuple[QWidget, ...] = ()
    layout_signals: tuple = ()


@dataclass(frozen=True)
class SupportContext:
    """Presentation inputs/actions; eligibility and cooldown remain in the app."""
    host: QWidget
    footer: QWidget
    activate: Callable[[], None]
    dismiss: Callable[[], None]
    finished: Callable[[], None]


class FooterIcon(Protocol):
    slot_width: int
    height: int

    def attach(self, surface: QWidget, request_update: Callable[[], None]) -> None: ...
    def detach(self) -> None: ...
    def refresh(self) -> None: ...
    def pulse(self) -> None: ...
    def paint(self, painter: QPainter, start: float, center_y: float, density: float) -> None: ...
    def dispose(self) -> None: ...


class SupportPresentation(Protocol):
    def start(self, *, thank_you: bool = False) -> None: ...
    def stop(self) -> None: ...
    def dispose(self) -> None: ...


class AppearanceProvider:
    """Lightweight construction; all Qt allocations belong in prepare().

    Runtime owns this instance before prepare, so it can dispose on every failure.
    Register prepared components in resources immediately. Providers with partial
    QObject constructors must also protect those constructors. dispose is safe
    before prepare, after partial prepare, and more than once.
    """
    def __init__(self, host: ThemeHost, package: ThemePackage):
        if not isinstance(host, ThemeHost):
            raise TypeError("Appearance providers require a ThemeHost")
        self.host = host
        self.package = package
        self.resources = ThemeResources()
        self.disposed = False
        self.footer_icon: FooterIcon | None = None
        self.footer_height = 28
        # Diagnostic compatibility; the application never drives this component.
        self.decorations = None

    def validate_host(self) -> None:
        pass

    def prepare(self) -> None:
        pass

    def activate(self) -> None:
        pass

    def create_support(self, context: SupportContext) -> SupportPresentation | None:
        return None

    def dispose(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        self.resources.close()
