"""A production icon/presentation provider with no header anchors for footer tests."""
from ui.themes.providers.halloween_effects.animation import HalloweenAnimation
from ui.themes.contracts import ThemeHost
from ui.themes.package import read_package
from ui.themes.providers.halloween import HalloweenProvider, WebFooterIcon
from ui.themes.runtime import AppearanceProvider


class FooterAppearance(AppearanceProvider):
    create_support = HalloweenProvider.create_support

    def __init__(self, owner, window, clock=None):
        super().__init__(ThemeHost(window), read_package("halloween"))
        self.clock = self.resources.own(clock or HalloweenAnimation(window, package=self.package))
        self.footer_icon = self.resources.own(WebFooterIcon(self.clock, self.package))
        self.footer_height = self.package.parameter("footer_height")
        self.presentations = []

    def dispose(self):
        super().dispose()
        self.presentations.clear()
