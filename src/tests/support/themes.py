"""A production icon/presentation provider with no header anchors for footer tests."""
from ui.themes.animation import HalloweenAnimation
from ui.themes.package import read_package
from ui.themes.providers.halloween import HalloweenProvider, WebFooterIcon
from ui.themes.runtime import AppearanceProvider


class FooterAppearance(AppearanceProvider):
    create_support = HalloweenProvider.create_support

    def __init__(self, owner, window, clock=None):
        super().__init__(owner, read_package("halloween"))
        self.clock = clock or HalloweenAnimation(window, package=self.package)
        self.footer_icon = WebFooterIcon(self.clock, self.package)
        self.footer_height = self.package.parameter("footer_height")
        self.presentations = []

    def dispose(self):
        self.clock.dispose()
        for item in self.presentations:
            item.dispose()
        self.presentations.clear()
