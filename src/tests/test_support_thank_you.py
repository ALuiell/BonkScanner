"""Premium gratitude has a daily launch cooldown, separate from donation reminders."""
import src  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.footer import (
    SUPPORT_REMINDER_STATE_CONFIG_KEY,
    SUPPORT_THANK_YOU_COOLDOWN_SECONDS,
    SUPPORT_THANK_YOU_STATE_CONFIG_KEY,
    SUPPORT_THANK_YOU_RETRY_MS,
    SUPPORT_THANK_YOU_STARTUP_DELAY_MS,
    _SupportThankYou,
    _read_support_thank_you_state,
    _update_support_thank_you_state,
    build_footer,
)
from ui.shared import resource_path
from ui.styles import build_qt_app_stylesheet

_qt = QApplication.instance() or QApplication([])


class SupportThankYouTests(unittest.TestCase):
    def setUp(self):
        self.access = {"active": True}
        self.listeners = []
        self.persisted = []
        self.thank_you_saved = []
        self.last_thanked_at = 0.0
        self.old_stylesheet = _qt.styleSheet()
        self.addCleanup(_qt.setStyleSheet, self.old_stylesheet)
        _qt.setStyleSheet(build_qt_app_stylesheet(resource_path("media/checkmark.svg")))
        read = patch("ui.footer._read_support_reminder_state", return_value=17.0)
        save = patch("ui.footer._update_support_reminder_state", side_effect=self.save_state)
        read.start()
        save.start()
        self.addCleanup(read.stop)
        self.addCleanup(save.stop)
        for item in (
            patch("ui.footer._read_support_thank_you_state", side_effect=lambda: self.last_thanked_at),
            patch("ui.footer._update_support_thank_you_state", side_effect=self.save_thank_you),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.host = SimpleNamespace(
            has_premium_access=lambda: self.access["active"],
            supporter_access=SimpleNamespace(
                add_listener=self.listeners.append,
                remove_listener=lambda listener: self.listeners.remove(listener),
            ),
        )
        self.frame = build_footer(self.host)
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        layout.addStretch()
        layout.addWidget(self.frame)
        self.window.resize(900, 280)
        self.window.show()
        _qt.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        self.view = self.host.footer
        self.card = self.view._thank_you

    def save_state(self, *, last_shown_at):
        self.persisted.append(last_shown_at)
        return SimpleNamespace(success=True, reason="")

    def save_thank_you(self, *, last_shown_at):
        self.last_thanked_at = last_shown_at
        self.thank_you_saved.append(last_shown_at)
        return SimpleNamespace(success=True, reason="")

    def new_launch_card(self):
        card = _SupportThankYou(
            parent=self.window, footer_frame=self.frame,
            support_link=self.view._support_btn, can_show=lambda: True,
            record_show=self.view._record_support_thank_you_shown,
        )
        self.addCleanup(card.deleteLater)
        self.addCleanup(card.dismiss)
        return card

    def notify(self, active):
        self.access["active"] = active
        for listener in tuple(self.listeners):
            listener(SimpleNamespace(active=active))

    def launch_gratitude(self):
        with patch.object(self.card, "_window_is_ready", return_value=True):
            self.card._mark_startup_due()
        self.assertTrue(self.card.isVisible())

    def assert_sleeping(self):
        self.assertFalse(self.card._timer.isActive())
        self.assertFalse(self.card._startup_timer.isActive())
        self.assertFalse(self.card._activation_timer.isActive())

    def test_existing_effective_premium_schedules_gratitude_without_a_support_ask(self):
        self.assertIsNotNone(self.card)
        self.assertTrue(self.card._startup_timer.isActive())
        self.assertEqual(self.card._startup_timer.interval(), SUPPORT_THANK_YOU_STARTUP_DELAY_MS)
        self.assertFalse(self.card._timer.isActive())
        self.assertIn("Thank you for supporting BonkScanner!", self.card._message.text())
        self.assertEqual(self.card._action.text(), "×")
        self.assertFalse(self.view._support_reminder_can_show())
        self.assertFalse(self.view._reminder._startup_timer.isActive())

    def test_repeated_access_refresh_does_not_postpone_or_repeat_gratitude(self):
        with patch.object(self.card._startup_timer, "start") as start:
            self.notify(True)
            self.notify(True)
        start.assert_not_called()
        self.launch_gratitude()
        with patch.object(self.view._reminder, "dismiss") as dismiss:
            self.notify(True)
        dismiss.assert_not_called()
        self.assertTrue(self.card._playing)
        self.card._animation.setCurrentTime(self.card._animation.duration())
        _qt.processEvents()
        self.notify(True)
        self.card._mark_startup_due()
        self.assertFalse(self.card.isVisible())
        self.assert_sleeping()

    def test_animation_finishes_without_periodic_or_inactivity_repeats(self):
        self.launch_gratitude()
        self.card._animation.setCurrentTime(self.card._animation.duration())
        _qt.processEvents()
        self.assertFalse(self.card.isVisible())
        self.assertFalse(self.card._playing)
        self.assert_sleeping()
        with patch("ui.footer.time.monotonic", side_effect=[100.0, 5000.0]):
            self.card._application_state_changed(Qt.ApplicationInactive)
            self.card._application_state_changed(Qt.ApplicationActive)
        self.assertFalse(self.card._due)
        self.assertFalse(self.card.play(force=True))
        self.assert_sleeping()

    def test_close_is_a_dismissal_without_opening_donation_popup(self):
        self.launch_gratitude()
        self.card._action.click()
        self.assertFalse(self.card.isVisible())
        self.assertIsNone(self.view._popup)
        self.assertEqual(self.card._animation.state(), QAbstractAnimation.Stopped)
        self.assert_sleeping()

    def test_gratitude_does_not_write_support_reminder_cooldown(self):
        before = list(self.persisted)
        self.launch_gratitude()
        self.card.dismiss()
        self.assertEqual(self.persisted, before)

    def test_waits_for_window_and_popup_then_shows_once(self):
        popup = QWidget(self.window)
        popup.show()
        _qt.processEvents()
        self.view._popup = popup
        self.addCleanup(popup.deleteLater)
        self.assertFalse(self.view._thank_you_can_show())
        with patch.object(self.card, "_window_is_ready", return_value=False):
            self.card._mark_startup_due()
        self.assertFalse(self.card._has_shown)
        self.assertFalse(self.card.isVisible())
        self.assertEqual(self.thank_you_saved, [])
        self.assertEqual(self.card._timer.interval(), SUPPORT_THANK_YOU_RETRY_MS)
        popup.hide()
        self.assertTrue(self.view._thank_you_can_show())
        with patch.object(self.card._host_window, "isActiveWindow", return_value=True):
            with patch.object(self.view._support_btn, "underMouse", return_value=False):
                self.assertTrue(self.card._play_if_due())
        self.assertTrue(self.card.isVisible())
        self.assertEqual(len(self.thank_you_saved), 1)

    def test_relaunch_before_24_hours_sleeps_and_boundary_launch_shows(self):
        first_show = 1_000_000.0
        with patch("ui.footer.time.time", return_value=first_show):
            self.launch_gratitude()
        self.card.dismiss()
        self.assertEqual(self.thank_you_saved, [first_show])
        for elapsed in (12 * 3600, SUPPORT_THANK_YOU_COOLDOWN_SECONDS - .001):
            with (self.subTest(elapsed=elapsed),
                  patch("ui.footer.time.time", return_value=first_show + elapsed),
                  patch("ui.footer.time.monotonic", return_value=100.0)):
                card = self.new_launch_card()
                card.start()
                self.assertTrue(card._cooldown_suppressed)
                self.assertFalse(card._startup_timer.isActive())
                self.assertFalse(card._timer.isActive())
                self.assertFalse(card._activation_timer.isActive())
                # A long-running session does not poll or show when 24 h elapse.
                with patch.object(card, "_cooldown_remaining_ms") as checks:
                    card.start()
                    card._application_state_changed(Qt.ApplicationInactive)
                    card._application_state_changed(Qt.ApplicationActive)
                    checks.assert_not_called()
                card._mark_startup_due()
                self.assertFalse(card._due)
        second_show = first_show + SUPPORT_THANK_YOU_COOLDOWN_SECONDS
        with (patch("ui.footer.time.time", return_value=second_show),
              patch("ui.footer.time.monotonic", return_value=100.0)):
            card = self.new_launch_card()
            card.start()
            self.assertTrue(card._startup_timer.isActive())
            with patch.object(card, "_window_is_ready", return_value=True):
                card._mark_startup_due()
        self.assertTrue(card.isVisible())
        self.assertEqual(self.thank_you_saved, [first_show, second_show])

    def test_failed_timestamp_save_does_not_crash_or_repeat_in_same_launch(self):
        with patch("ui.footer._update_support_thank_you_state", return_value=SimpleNamespace(success=False, reason="read only")):
            with patch.object(self.view, "_log_warning") as warning:
                self.launch_gratitude()
        warning.assert_called_once()
        self.card.dismiss()
        self.notify(True)
        self.assertTrue(self.card._has_shown)
        self.assert_sleeping()

    def test_access_loss_cancels_pending_and_visible_gratitude(self):
        self.notify(False)
        self.assertFalse(self.view._thank_you_can_show())
        self.assert_sleeping()
        self.notify(True)
        self.assertTrue(self.card._startup_timer.isActive())
        self.launch_gratitude()
        self.notify(False)
        self.assertFalse(self.card.isVisible())
        self.assert_sleeping()
        self.notify(True)
        self.assert_sleeping()

    def test_opening_support_popup_before_gratitude_keeps_the_launch_pending(self):
        self.view.open_support_popup()
        _qt.processEvents()
        self.assertTrue(self.view._popup.isVisible())
        self.assertTrue(self.card._startup_timer.isActive())
        with patch.object(self.card._host_window, "isActiveWindow", return_value=True):
            self.card._mark_startup_due()
        self.assertTrue(self.card._due)
        self.assertFalse(self.card._has_shown)
        self.view._popup.close()
        with patch.object(self.card._host_window, "isActiveWindow", return_value=True):
            with patch.object(self.view._support_btn, "underMouse", return_value=False):
                self.assertTrue(self.card._play_if_due())

    def test_access_activated_later_in_the_session_is_thanked_once(self):
        self.card.deleteLater()
        self.view._thank_you = None
        self.access["active"] = False
        self.notify(False)
        self.assertIsNone(self.view._thank_you)
        self.notify(True)
        self.card = self.view._thank_you
        self.assertTrue(self.card._startup_timer.isActive())
        self.launch_gratitude()
        self.card.dismiss()
        self.notify(True)
        self.assert_sleeping()

    def test_checking_without_effective_premium_does_not_schedule_gratitude(self):
        self.notify(False)
        for listener in tuple(self.listeners):
            listener(SimpleNamespace(active=True, checking=True))
        self.assertFalse(self.view._thank_you_can_show())
        self.assertFalse(self.card.isVisible())
        self.assert_sleeping()


class SupportThankYouStateTests(unittest.TestCase):
    def test_invalid_and_future_timestamps_do_not_suppress_gratitude(self):
        for raw in (None, [], {}, {"last_shown_at": "bad"}, {"last_shown_at": -1},
                    {"last_shown_at": float("nan")}, {"last_shown_at": float("inf")},
                    {"last_shown_at": 101}):
            with self.subTest(raw=raw), patch("ui.footer.config.user_config", {SUPPORT_THANK_YOU_STATE_CONFIG_KEY: raw}):
                with patch("ui.footer.time.time", return_value=100):
                    self.assertEqual(_read_support_thank_you_state(), 0)

    def test_persistence_roundtrip_preserves_reminder_and_unrelated_config(self):
        candidate = {SUPPORT_REMINDER_STATE_CONFIG_KEY: {"last_shown_at": 17}, "other": 42}
        def save(mutate):
            mutate(candidate)
            return SimpleNamespace(success=True)
        with patch("ui.footer.config.update_config", side_effect=save):
            self.assertTrue(_update_support_thank_you_state(last_shown_at=75).success)
        self.assertEqual(candidate[SUPPORT_REMINDER_STATE_CONFIG_KEY], {"last_shown_at": 17})
        self.assertEqual(candidate["other"], 42)
        with patch("ui.footer.config.user_config", candidate), patch("ui.footer.time.time", return_value=100):
            self.assertEqual(_read_support_thank_you_state(), 75)


if __name__ == "__main__":
    unittest.main()
