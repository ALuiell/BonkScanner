"""The footer links' centre-out trace and the Support heartbeat."""

import src  # noqa: F401  -- puts src/ on the path, as the other tests do

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QPointF,
    QSequentialAnimationGroup,
    Qt,
)
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app import config
from ui.footer import (
    FOOTER_HEIGHT,
    HEART_PASSIVE_PAUSE_MS,
    SUPPORT_REMINDER_ACTIVATION_DELAY_MS,
    SUPPORT_REMINDER_BEAT_LEAD_IN_MS,
    SUPPORT_REMINDER_COOLDOWN_SECONDS,
    SUPPORT_REMINDER_EDGE_MARGIN,
    SUPPORT_REMINDER_LONG_INACTIVE_SECONDS,
    SUPPORT_REMINDER_INTERVAL_MS,
    SUPPORT_REMINDER_MAX_WIDTH,
    SUPPORT_REMINDER_RETRY_MS,
    SUPPORT_REMINDER_SLIDE_IN_MS,
    SUPPORT_REMINDER_STATE_CONFIG_KEY,
    SUPPORT_REMINDER_STARTUP_MAX_DELAY_MS,
    SUPPORT_REMINDER_STARTUP_MIN_DELAY_MS,
    _AnimatedFooterLink,
    _SupportFooterLink,
    _read_support_reminder_state,
    _update_support_reminder_state,
    build_footer,
)
from ui.shared import resource_path
from ui.styles import build_qt_app_stylesheet

_app = QApplication.instance() or QApplication([])


class SupportReminderStateTests(unittest.TestCase):
    def test_invalid_persisted_values_are_treated_as_fresh_state(self):
        with patch.dict(
            config.user_config,
            {
                SUPPORT_REMINDER_STATE_CONFIG_KEY: {
                    "launch_count": "not-a-number",
                    "last_shown_at": float("nan"),
                }
            },
            clear=True,
        ):
            self.assertEqual(_read_support_reminder_state(), 0.0)

    def test_future_timestamp_is_clamped_to_the_current_wall_clock(self):
        with (
            patch.dict(
                config.user_config,
                {
                    SUPPORT_REMINDER_STATE_CONFIG_KEY: {
                        "launch_count": 6,
                        "last_shown_at": 500.0,
                    }
                },
                clear=True,
            ),
            patch("ui.footer.time.time", return_value=100.0),
        ):
            self.assertEqual(_read_support_reminder_state(), 100.0)

    def test_state_update_preserves_other_fields_and_unrelated_config(self):
        captured = {}

        def update_config(mutate):
            candidate = {
                SUPPORT_REMINDER_STATE_CONFIG_KEY: {
                    "launch_count": 4,
                    "last_shown_at": 8.0,
                    "future_field": "keep",
                },
                "UNRELATED": {"keep": True},
            }
            mutate(candidate)
            captured.update(candidate)
            return SimpleNamespace(success=True, reason="")

        with patch("ui.footer.config.update_config", side_effect=update_config):
            result = _update_support_reminder_state(last_shown_at=9.0)

        self.assertTrue(result.success)
        self.assertEqual(
            captured[SUPPORT_REMINDER_STATE_CONFIG_KEY],
            {
                "last_shown_at": 9.0,
                "future_field": "keep",
            },
        )
        self.assertEqual(captured["UNRELATED"], {"keep": True})


class FooterAnimationTests(unittest.TestCase):
    def setUp(self):
        self.reminder_state = {"last_shown_at": 0.0}

        def read_reminder_state():
            return self.reminder_state["last_shown_at"]

        def update_reminder_state(*, last_shown_at):
            self.reminder_state["last_shown_at"] = last_shown_at
            return SimpleNamespace(success=True, reason="")

        read_patch = patch(
            "ui.footer._read_support_reminder_state",
            side_effect=read_reminder_state,
        )
        update_patch = patch(
            "ui.footer._update_support_reminder_state",
            side_effect=update_reminder_state,
        )
        read_patch.start()
        update_patch.start()
        self.addCleanup(read_patch.stop)
        self.addCleanup(update_patch.stop)

        previous_stylesheet = _app.styleSheet()
        self.addCleanup(_app.setStyleSheet, previous_stylesheet)
        checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
        _app.setStyleSheet(build_qt_app_stylesheet(checkmark_path))

        self.host = SimpleNamespace()
        self.frame = build_footer(self.host)
        self.window = QWidget()
        window_layout = QVBoxLayout(self.window)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)
        window_layout.addStretch(1)
        window_layout.addWidget(self.frame)
        self.window.resize(900, 260)
        self.window.show()
        _app.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
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

    def test_periodic_reminder_starts_with_a_fixed_one_hour_wait(self):
        reminder = self.host.footer._reminder

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.objectName(), "supportReminder")
        self.assertIs(reminder.parentWidget(), self.frame.parentWidget())
        self.assertFalse(reminder.isVisible())
        self.assertTrue(reminder._timer.isActive())
        self.assertEqual(reminder._timer.timerType(), Qt.PreciseTimer)
        self.assertEqual(reminder._startup_timer.timerType(), Qt.PreciseTimer)
        self.assertEqual(reminder._activation_timer.timerType(), Qt.PreciseTimer)
        self.assertEqual(reminder._last_interval_ms, SUPPORT_REMINDER_INTERVAL_MS)
        self.assertEqual(reminder._timer.interval(), 60 * 60 * 1000)
        self.assertEqual(reminder._action.objectName(), "supportReminderButton")
        self.assertIn("Updates are fueled", reminder._message.text())
        reminder._message.ensurePolished()
        reminder._action.ensurePolished()
        self.assertEqual(reminder._message.font().pixelSize(), 13)
        self.assertEqual(reminder._action.font().pixelSize(), 13)
        self.assertEqual(reminder._animation.duration(), 8_000)
        heartbeats = [
            reminder._animation.animationAt(index)
            for index in range(reminder._animation.animationCount())
            if isinstance(
                reminder._animation.animationAt(index),
                QSequentialAnimationGroup,
            )
        ]
        self.assertEqual(len(heartbeats), 4)
        self.assertTrue(
            all(heartbeat.animationCount() == 5 for heartbeat in heartbeats)
        )

    def test_every_launch_schedules_the_four_second_startup_reminder(self):
        reminder = self.host.footer._reminder

        self.assertTrue(reminder._startup_timer.isActive())
        self.assertEqual(
            reminder._last_startup_delay_ms,
            4_000,
        )
        self.assertEqual(SUPPORT_REMINDER_STARTUP_MIN_DELAY_MS, 4_000)
        self.assertEqual(SUPPORT_REMINDER_STARTUP_MAX_DELAY_MS, 4_000)

        reminder.start()
        self.assertTrue(reminder._startup_timer.isActive())

    def test_startup_reminder_bypasses_the_shared_cooldown(self):
        reminder = self.host.footer._reminder
        reminder._last_shown_at = 50_000.0
        reminder._last_shown_monotonic = 1_000.0

        with (
            patch("ui.footer.time.time", return_value=50_001.0),
            patch("ui.footer.time.monotonic", return_value=1_001.0),
            patch.object(reminder, "_window_is_ready", return_value=True),
        ):
            reminder._mark_startup_due()

        self.assertTrue(reminder.isVisible())
        self.assertFalse(reminder._due)
        self.assertFalse(reminder._due_bypasses_cooldown)
        reminder.dismiss()

    def test_startup_cooldown_exemption_survives_an_inactive_window_retry(self):
        reminder = self.host.footer._reminder
        reminder._last_shown_at = 50_000.0
        reminder._last_shown_monotonic = 1_000.0

        with patch.object(reminder, "_window_is_ready", return_value=False):
            reminder._mark_startup_due()

        self.assertTrue(reminder._due)
        self.assertTrue(reminder._due_bypasses_cooldown)
        self.assertTrue(reminder._timer.isActive())

        with (
            patch("ui.footer.time.time", return_value=50_001.0),
            patch("ui.footer.time.monotonic", return_value=1_001.0),
            patch.object(reminder, "_window_is_ready", return_value=True),
        ):
            self.assertTrue(reminder._play_if_due())

        self.assertTrue(reminder.isVisible())
        self.assertFalse(reminder._due_bypasses_cooldown)
        reminder.dismiss()

    def test_successful_show_records_timestamp_and_stops_competing_triggers(self):
        reminder = self.host.footer._reminder
        reminder._due = True
        reminder._activation_timer.start()

        with patch("ui.footer.time.time", return_value=12_345.0):
            self.assertTrue(reminder.play(force=True))

        self.assertEqual(self.reminder_state["last_shown_at"], 12_345.0)
        self.assertFalse(reminder._timer.isActive())
        self.assertFalse(reminder._startup_timer.isActive())
        self.assertFalse(reminder._activation_timer.isActive())
        reminder.dismiss()

    def test_shared_cooldown_delays_a_due_trigger_until_thirty_minutes(self):
        reminder = self.host.footer._reminder
        now = 50_000.0
        reminder._last_shown_at = now - 10 * 60
        reminder._due = True

        with (
            patch("ui.footer.time.time", return_value=now),
            patch.object(reminder, "_window_is_ready", return_value=True),
        ):
            self.assertFalse(reminder._play_if_due())

        self.assertTrue(reminder._due)
        self.assertFalse(reminder.isVisible())
        self.assertTrue(reminder._timer.isActive())
        self.assertEqual(reminder._timer.interval(), 20 * 60 * 1000)

        with (
            patch(
                "ui.footer.time.time",
                return_value=now + SUPPORT_REMINDER_COOLDOWN_SECONDS,
            ),
            patch.object(reminder, "_window_is_ready", return_value=True),
        ):
            self.assertTrue(reminder._play_if_due())
        reminder.dismiss()

    def test_current_session_cooldown_uses_monotonic_time_after_clock_jump(self):
        reminder = self.host.footer._reminder
        reminder._last_shown_at = 1_000.0
        reminder._last_shown_monotonic = 5_000.0

        with (
            patch("ui.footer.time.time", return_value=1_000_000.0),
            patch("ui.footer.time.monotonic", return_value=5_600.0),
        ):
            self.assertEqual(reminder._cooldown_remaining_ms(), 20 * 60 * 1000)

    def test_clock_rollback_is_rebased_once_instead_of_repeating_cooldown(self):
        reminder = self.host.footer._reminder
        reminder._last_shown_at = 200.0
        reminder._last_shown_monotonic = None

        with (
            patch("ui.footer.time.time", return_value=100.0),
            patch("ui.footer.time.monotonic", return_value=1_000.0),
        ):
            self.assertEqual(
                reminder._cooldown_remaining_ms(),
                SUPPORT_REMINDER_COOLDOWN_SECONDS * 1000,
            )

        with (
            patch("ui.footer.time.time", return_value=100.0),
            patch(
                "ui.footer.time.monotonic",
                return_value=1_000.0 + SUPPORT_REMINDER_COOLDOWN_SECONDS,
            ),
        ):
            self.assertEqual(reminder._cooldown_remaining_ms(), 0)

    def test_return_after_long_inactivity_creates_an_independent_due_trigger(self):
        reminder = self.host.footer._reminder
        reminder._timer.stop()
        reminder._startup_timer.stop()
        reminder._due = False

        with patch(
            "ui.footer.time.monotonic",
            side_effect=[100.0, 100.0 + SUPPORT_REMINDER_LONG_INACTIVE_SECONDS],
        ):
            reminder._application_state_changed(Qt.ApplicationInactive)
            reminder._application_state_changed(Qt.ApplicationActive)

        self.assertTrue(reminder._due)
        self.assertTrue(reminder._activation_timer.isActive())
        self.assertFalse(reminder._timer.isActive())
        self.assertFalse(reminder._startup_timer.isActive())

    def test_short_inactivity_does_not_create_a_reminder_trigger(self):
        reminder = self.host.footer._reminder
        reminder._timer.stop()
        reminder._startup_timer.stop()
        reminder._due = False

        with patch(
            "ui.footer.time.monotonic",
            side_effect=[100.0, 100.0 + SUPPORT_REMINDER_LONG_INACTIVE_SECONDS - 1],
        ):
            reminder._application_state_changed(Qt.ApplicationInactive)
            reminder._application_state_changed(Qt.ApplicationActive)

        self.assertFalse(reminder._due)
        self.assertFalse(reminder._activation_timer.isActive())

    def test_reminder_double_beat_moves_card_and_both_hearts_together(self):
        reminder = self.host.footer._reminder

        self.assertTrue(reminder.play(force=True))
        self.assertFalse(reminder.play(force=True))
        self.assertTrue(reminder.isVisible())
        self.assertEqual(
            self.support._ambient_heartbeat.state(),
            QAbstractAnimation.Stopped,
        )

        reminder._animation.setCurrentTime(SUPPORT_REMINDER_SLIDE_IN_MS)
        _app.processEvents()
        resting_y = reminder.y()
        reminder._animation.setCurrentTime(
            SUPPORT_REMINDER_SLIDE_IN_MS
            + SUPPORT_REMINDER_BEAT_LEAD_IN_MS
            + 50
        )
        _app.processEvents()

        self.assertGreater(reminder.pulseOffset, 0.0)
        self.assertLess(reminder.y(), resting_y)
        self.assertGreater(reminder._heart.heartScale, 1.0)
        self.assertGreater(self.support.heartScale, 1.0)

        reminder.dismiss()
        self.assertFalse(reminder.isVisible())
        self.assertEqual(reminder.pulseOffset, 0.0)
        self.assertEqual(reminder._heart.heartScale, 1.0)
        self.assertEqual(self.support.heartScale, 1.0)
        self.assertEqual(
            self.support._ambient_heartbeat.state(),
            QAbstractAnimation.Running,
        )
        self.assertTrue(reminder._timer.isActive())

    def test_due_reminder_waits_for_an_inactive_window_then_can_resume(self):
        reminder = self.host.footer._reminder
        reminder._timer.stop()

        with patch.object(reminder, "_window_is_ready", return_value=False):
            reminder._mark_due()

        self.assertTrue(reminder._due)
        self.assertFalse(reminder.isVisible())
        self.assertTrue(reminder._timer.isActive())

        with patch.object(reminder, "_window_is_ready", return_value=True):
            self.assertTrue(reminder._play_if_due())

        self.assertFalse(reminder._due)
        self.assertTrue(reminder.isVisible())
        reminder.dismiss()

    def test_reminder_reflows_inside_a_narrow_window_without_touching_the_footer(self):
        reminder = self.host.footer._reminder
        self.window.resize(360, 260)
        _app.processEvents()

        self.assertTrue(reminder.play(force=True))
        reminder._animation.setCurrentTime(SUPPORT_REMINDER_SLIDE_IN_MS)
        _app.processEvents()

        parent = reminder.parentWidget()
        self.assertEqual(
            reminder.width(),
            min(
                SUPPORT_REMINDER_MAX_WIDTH,
                parent.width() - 2 * SUPPORT_REMINDER_EDGE_MARGIN,
            ),
        )
        self.assertGreaterEqual(reminder.x(), SUPPORT_REMINDER_EDGE_MARGIN)
        self.assertLessEqual(
            reminder.geometry().right(),
            parent.width() - SUPPORT_REMINDER_EDGE_MARGIN,
        )
        self.assertLess(reminder.geometry().bottom(), self.frame.y())
        self.assertTrue(reminder._message.wordWrap())
        reminder.dismiss()

    def test_window_activation_cancels_retry_before_starting_its_grace_period(self):
        reminder = self.host.footer._reminder
        reminder._due = True
        reminder._timer.start(SUPPORT_REMINDER_RETRY_MS)

        reminder.eventFilter(
            reminder._host_window,
            QEvent(QEvent.WindowActivate),
        )

        self.assertFalse(reminder._timer.isActive())
        self.assertTrue(reminder._activation_timer.isActive())
        self.assertEqual(
            reminder._activation_timer.interval(),
            SUPPORT_REMINDER_ACTIVATION_DELAY_MS,
        )

    def test_visible_support_popup_blocks_the_periodic_reminder(self):
        reminder = self.host.footer._reminder
        popup = QWidget(self.window)
        popup.show()
        _app.processEvents()
        self.host.footer._popup = popup
        self.addCleanup(popup.deleteLater)
        self.addCleanup(popup.close)

        self.assertFalse(self.host.footer._support_reminder_can_show())
        self.assertFalse(reminder._can_show())

        popup.hide()
        self.assertTrue(self.host.footer._support_reminder_can_show())

    def test_natural_animation_finish_hides_and_reschedules(self):
        reminder = self.host.footer._reminder
        self.assertTrue(reminder.play(force=True))

        reminder._animation.setCurrentTime(reminder._animation.duration())
        _app.processEvents()

        self.assertFalse(reminder.isVisible())
        self.assertFalse(reminder._playing)
        self.assertEqual(self.support.heartScale, 1.0)
        self.assertTrue(reminder._timer.isActive())
        self.assertFalse(reminder._startup_timer.isActive())
        self.assertFalse(reminder._activation_timer.isActive())

    def test_reminder_support_button_opens_one_popup_and_dismisses_the_card(self):
        reminder = self.host.footer._reminder
        self.assertTrue(reminder.play(force=True))

        reminder._action.click()
        _app.processEvents()

        self.assertFalse(reminder.isVisible())
        self.assertTrue(reminder._timer.isActive())
        self.assertIsNotNone(self.host.footer._popup)
        self.assertTrue(self.host.footer._popup.isVisible())
        self.host.footer._popup.close()


if __name__ == "__main__":
    unittest.main()
