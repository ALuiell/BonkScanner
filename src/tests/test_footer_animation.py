"""The footer links' centre-out trace and the Support heartbeat."""

import src  # noqa: F401  -- puts src/ on the path, as the other tests do

import unittest
from types import SimpleNamespace

from PySide6.QtCore import QAbstractAnimation, QEvent, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

from ui.footer import (
    FOOTER_HEIGHT,
    HEART_PASSIVE_PAUSE_MS,
    _AnimatedFooterLink,
    _SupportFooterLink,
    build_footer,
)
from ui.shared import resource_path
from ui.styles import build_qt_app_stylesheet

_app = QApplication.instance() or QApplication([])


class FooterAnimationTests(unittest.TestCase):
    def setUp(self):
        previous_stylesheet = _app.styleSheet()
        self.addCleanup(_app.setStyleSheet, previous_stylesheet)
        checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
        _app.setStyleSheet(build_qt_app_stylesheet(checkmark_path))

        self.host = SimpleNamespace()
        self.frame = build_footer(self.host)
        self.frame.resize(900, FOOTER_HEIGHT)
        self.frame.show()
        _app.processEvents()
        self.addCleanup(self.frame.deleteLater)
        self.addCleanup(self.frame.close)

        self.support = self.host.footer._support_btn

    def test_links_use_the_selected_bright_rest_and_hover_colours(self):
        links = {
            button.property("linkRole"): button
            for button in self.frame.findChildren(_AnimatedFooterLink)
            if not isinstance(button, _SupportFooterLink)
        }

        self.assertEqual(set(links), {"github", "discord"})
        self.assertEqual(links["github"].restColor.name(), "#b9c2ce")
        self.assertEqual(links["github"].hoverColor.name(), "#edf1f5")
        self.assertEqual(links["discord"].restColor.name(), "#aebbff")
        self.assertEqual(links["discord"].hoverColor.name(), "#cdd3ff")
        self.assertEqual(self.support.restColor.name(), "#ff6f61")
        self.assertEqual(self.support.hoverColor.name(), "#ff978c")

    def test_support_heart_is_larger_without_growing_the_footer(self):
        self.assertGreater(
            self.support._heart_font().pixelSize(), self.support.font().pixelSize()
        )
        self.assertLessEqual(self.support.sizeHint().height(), FOOTER_HEIGHT)

    def test_supporter_count_updates_the_separately_painted_caption(self):
        self.host.footer.set_supporters(["one", "two"])
        self.assertEqual(self.support.text(), "♥  2 supporters")
        self.assertEqual(self.support.caption(), "2 supporters")

        self.host.footer.set_supporters(())
        self.assertEqual(self.support.text(), "♥  Support")
        self.assertEqual(self.support.caption(), "Support")

    def test_hover_owns_the_heartbeat_then_restores_the_full_passive_pause(self):
        self.assertEqual(
            self.support._ambient_heartbeat.state(), QAbstractAnimation.Running
        )
        self.assertEqual(
            self.support._ambient_heartbeat.currentAnimation().duration(),
            HEART_PASSIVE_PAUSE_MS,
        )

        enter = QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2))
        QApplication.sendEvent(self.support, enter)

        self.assertEqual(
            self.support._ambient_heartbeat.state(), QAbstractAnimation.Stopped
        )
        self.assertEqual(
            self.support._hover_heartbeat.state(), QAbstractAnimation.Running
        )
        self.assertEqual(self.support._hover_animation.endValue(), 1.0)

        QApplication.sendEvent(self.support, QEvent(QEvent.Leave))

        self.assertEqual(
            self.support._hover_heartbeat.state(), QAbstractAnimation.Stopped
        )
        self.assertEqual(
            self.support._ambient_heartbeat.state(), QAbstractAnimation.Running
        )
        self.assertEqual(
            self.support._ambient_heartbeat.currentAnimation().duration(),
            HEART_PASSIVE_PAUSE_MS,
        )
        self.assertEqual(self.support._hover_animation.endValue(), 0.0)

    def test_hidden_footer_stops_the_passive_repaint_loop(self):
        self.frame.hide()
        _app.processEvents()

        self.assertEqual(
            self.support._ambient_heartbeat.state(), QAbstractAnimation.Stopped
        )
        self.assertEqual(self.support.heartScale, 1.0)
        self.assertEqual(self.support.hoverProgress, 0.0)


if __name__ == "__main__":
    unittest.main()
