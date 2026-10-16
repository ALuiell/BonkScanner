"""Exercise the production seasonal presentation through the real footer."""
import src  # noqa: F401
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.footer import FOOTER_HEIGHT, build_footer
from src.tests.support.themes import FooterAppearance
from ui.themes.providers.halloween_effects.support import CLIMB_SECONDS, READ_SECONDS, TOTAL_SECONDS

qt = QApplication.instance() or QApplication([])


class HalloweenSupportTests(unittest.TestCase):
    def setUp(self):
        self.premium = False
        self.saved = []
        self.suppressed = []
        self.listeners = []
        for p in (
            patch('ui.footer._read_support_reminder_state', return_value=0.0),
            patch('ui.footer._update_support_reminder_state', side_effect=self.save),
            patch('ui.footer._read_support_thank_you_state', return_value=0.0),
            patch('ui.footer._update_support_thank_you_state', return_value=SimpleNamespace(success=True, reason='')),
            patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationActive),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.app = SimpleNamespace(
            has_premium_access=lambda: self.premium,
            supporter_access=SimpleNamespace(add_listener=self.listeners.append),
            _theme_decorations=SimpleNamespace(set_skeleton_suppressed=self.suppressed.append),
        )
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        self.frame = build_footer(self.app)
        layout.addWidget(self.frame)
        self.window.resize(1060, 650)
        self.window.show()
        qt.processEvents()
        self.view = self.app.footer
        self.provider = FooterAppearance(self.app, self.window)
        self.clock = self.provider.clock
        self.view.set_appearance(self.provider)
        self.clock.set_enabled(True)
        qt.processEvents()
        self.card = self.view._reminder
        self.link = self.view._support_btn
        self.addCleanup(self.cleanup)

    def save(self, *, last_shown_at):
        self.saved.append(last_shown_at)
        return SimpleNamespace(success=True, reason='')

    def cleanup(self):
        for card in (self.view._reminder, self.view._thank_you):
            if card is not None:
                card.dismiss()
        self.view.set_appearance(None)
        self.provider.dispose()
        self.window.close()
        self.window.deleteLater()
        qt.processEvents()

    def show_card(self):
        self.assertTrue(self.card.play(force=True))
        return self.card._presentation

    def settle_at(self, spider, elapsed):
        spider.elapsed = elapsed
        spider._render()
        qt.processEvents()

    def test_shoot_then_climb_and_full_reading_time_before_automatic_close(self):
        spider = self.show_card()
        self.assertEqual(spider.art.asset_name, 'support-spider.svg')
        self.assertFalse(self.card.isVisible())  # The old card is not painted underneath.
        positions = []
        for elapsed in (0, .55, .65, 1, 2, 3, 4, CLIMB_SECONDS):
            self.settle_at(spider, elapsed)
            positions.append(spider.y)
            self.assertEqual(spider.plaque.isVisible(), elapsed > .65)
        self.assertEqual(positions, sorted(positions, reverse=True))
        self.assertTrue(spider.plaque.action.isVisible())
        self.assertLess(spider.plaque.geometry().bottom(), self.frame.y())
        self.assertEqual(self.suppressed, [])
        self.assertEqual(self.card._animation.state(), QAbstractAnimation.Stopped)
        self.settle_at(spider, CLIMB_SECONDS + READ_SECONDS - .01)
        self.assertTrue(self.card._playing)
        spider.elapsed = TOTAL_SECONDS
        spider._last = time.monotonic()
        spider._tick()
        self.assertFalse(self.card._playing)
        self.assertFalse(spider.timer.isActive())
        self.assertFalse(spider.art.isVisible())
        self.assertTrue(self.card._timer.isActive())
        self.assertEqual(self.suppressed, [])

    def test_premium_startup_uses_the_same_spider_once_without_donation_action(self):
        self.premium = True
        self.view._on_supporter_access_changed()
        thanks = self.view._thank_you
        saved_before = list(self.saved)
        with patch.object(thanks, '_window_is_ready', return_value=True):
            thanks._mark_startup_due()
        spider = thanks._presentation
        self.settle_at(spider, CLIMB_SECONDS)
        self.assertTrue(spider.plaque.isVisible())
        self.assertTrue(spider.thank_you)
        self.assertEqual(spider.art.asset_name, 'support-spider-thank-you.svg')
        self.assertFalse(spider.plaque.action.isVisible())
        self.assertEqual(self.saved, saved_before)
        self.view._on_supporter_access_changed()
        self.assertEqual(spider.elapsed, CLIMB_SECONDS)
        spider.plaque.close_button.click()
        self.assertFalse(thanks._playing)
        self.view._on_supporter_access_changed()
        self.assertFalse(thanks._startup_timer.isActive())
        self.assertFalse(thanks.play(force=True))

    def test_expression_switches_visual_face_and_keeps_a_single_reusable_cache(self):
        spider = self.show_card()
        self.settle_at(spider, CLIMB_SECONDS)
        spider.art.grab()
        angry = spider.art.raster.toImage()
        renderer = spider.art.renderer
        spider.stop()
        spider.start(thank_you=True)
        self.settle_at(spider, CLIMB_SECONDS)
        spider.art.grab()
        self.assertNotEqual(spider.art.raster.toImage(), angry)
        grateful_key = spider.art.raster.cacheKey()
        for _ in range(3):
            spider.art.grab()
            self.assertEqual(spider.art.raster.cacheKey(), grateful_key)
        spider.stop()
        spider.start(thank_you=True)
        self.settle_at(spider, CLIMB_SECONDS)
        spider.art.grab()
        self.assertEqual(spider.art.raster.cacheKey(), grateful_key)
        spider.stop()
        spider.start(thank_you=False)
        self.settle_at(spider, CLIMB_SECONDS)
        spider.art.grab()
        self.assertEqual(spider.art.raster.toImage(), angry)
        self.assertIs(spider.art.renderer, renderer)

    def test_support_button_opens_the_real_popup_without_hiding_corner(self):
        spider = self.show_card()
        self.settle_at(spider, CLIMB_SECONDS)
        spider.plaque.action.click()
        qt.processEvents()
        self.assertTrue(self.view._popup.isVisible())
        self.assertFalse(spider.timer.isActive())
        self.assertFalse(spider.art.isVisible())
        self.assertEqual(self.suppressed, [])

    def test_original_theme_cancels_spider_and_restores_legacy_card_and_footer(self):
        spider = self.show_card()
        self.settle_at(spider, 2)
        self.view.set_appearance(None)
        self.provider.dispose()
        self.assertFalse(spider.running)
        self.assertFalse(spider.art.isVisible())
        self.assertFalse(self.clock.timer.isActive())
        self.assertFalse(self.clock.wake.isActive())
        self.assertEqual(self.frame.height(), FOOTER_HEIGHT)
        self.assertEqual(self.suppressed, [])
        self.assertTrue(self.card.play(force=True))
        self.assertTrue(self.card.isVisible())
        self.assertEqual(self.card._animation.state(), QAbstractAnimation.Running)

    def test_background_pauses_and_resume_does_not_skip_reading_time(self):
        spider = self.show_card()
        self.settle_at(spider, 2)
        spider._application_state_changed(Qt.ApplicationInactive)
        self.clock.set_enabled(False)
        self.assertFalse(spider.timer.isActive())
        self.assertFalse(self.clock.timer.isActive())
        self.assertFalse(self.clock.wake.isActive())
        with patch('ui.themes.providers.halloween_effects.support.time.monotonic', return_value=10000):
            spider._application_state_changed(Qt.ApplicationActive)
            spider._tick()
        self.assertEqual(spider.elapsed, 2)
        self.assertTrue(spider.timer.isActive())
        self.window.hide()
        qt.processEvents()
        self.assertFalse(spider.timer.isActive())
        self.assertFalse(self.clock.timer.isActive())
        self.assertFalse(self.clock.wake.isActive())

    def test_resize_keeps_plaque_inside_footer_and_reuses_svg_raster(self):
        spider = self.show_card()
        self.settle_at(spider, CLIMB_SECONDS)
        spider.art.grab()
        cache_key = spider.art.raster.cacheKey()
        for size in ((480, 360), (1680, 950), (1060, 650)):
            self.window.resize(*size)
            qt.processEvents()
            self.settle_at(spider, CLIMB_SECONDS)
            self.assertGreaterEqual(spider.plaque.x(), 0)
            self.assertLess(spider.plaque.geometry().right(), self.window.width())
            self.assertLess(spider.plaque.geometry().bottom(), self.frame.y())
            spider.art.grab()
            self.assertEqual(spider.art.raster.cacheKey(), cache_key)
        self.assertEqual(self.suppressed, [])

    def test_plaque_text_raster_reuses_frames_and_refreshes_for_message_and_width(self):
        spider = self.show_card()
        self.assertFalse(spider.plaque.raster.isNull())
        self.settle_at(spider, 2.0)
        spider.plaque.grab()
        original_key = spider.plaque.raster.cacheKey()

        self.settle_at(spider, 2.5)
        spider.plaque.grab()
        self.assertEqual(spider.plaque.raster.cacheKey(), original_key)

        spider.stop()
        spider.start(thank_you=True)
        self.settle_at(spider, 2.0)
        spider.plaque.grab()
        thank_you_key = spider.plaque.raster.cacheKey()
        self.assertNotEqual(thank_you_key, original_key)

        spider.plaque.resize(286, 124)
        spider.plaque.grab()
        self.assertEqual(spider.plaque.width(), 286)
        self.assertNotEqual(spider.plaque.raster.cacheKey(), thank_you_key)

    def test_web_pulse_has_no_continuous_idle_timer_or_parallel_heartbeat(self):
        self.link.pulse_theme_icon()
        self.assertTrue(self.clock.timer.isActive())
        self.assertEqual(self.link._ambient_heartbeat.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.link._hover_heartbeat.state(), QAbstractAnimation.Stopped)
        self.clock.started -= 2
        self.clock.tick()
        self.assertFalse(self.clock.timer.isActive())
        self.assertTrue(self.clock.wake.isActive())
        self.assertEqual(self.clock.wake.interval(), 4500)
        self.view.set_supporters([SimpleNamespace(name='Test supporter')])
        self.assertIn('1 supporters', self.link.caption())
        self.assertGreaterEqual(self.link.width(), self.link.fontMetrics().horizontalAdvance(self.link.caption()) + 40)

    def test_web_keeps_its_passive_cycles_while_the_spider_message_is_visible(self):
        self.show_card()
        self.clock.started -= 2
        self.clock.tick()
        self.assertFalse(self.clock.timer.isActive())
        self.assertTrue(self.clock.wake.isActive())
        self.assertEqual(self.link._ambient_heartbeat.state(), QAbstractAnimation.Stopped)
