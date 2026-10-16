from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from ui.dialogs.supporter_access import SupporterAccessPage


RAW_KEY = "BSK_AAAAAAAA_BBBBBBBB_CCCCCCCC_DDDDDDDD"


def access_state(**changes):
    values = {
        "status": "no_key",
        "active": False,
        "has_key": False,
        "features": (),
        "expires_at": None,
        "next_change_at": None,
        "checked_at": None,
        "key_hint": "",
        "online": False,
        "checking": False,
        "message": "Add a supporter key to unlock all Premium features.",
    }
    values.update(changes)
    return SimpleNamespace(**values)


class FakeAccessController:
    def __init__(self) -> None:
        self.state = access_state()
        self.listeners = []
        self.activated = []
        self.checks = 0
        self.removals = 0

    def add_listener(self, listener) -> None:
        self.listeners.append(listener)

    def remove_listener(self, listener) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)

    def publish(self, state) -> None:
        self.state = state
        for listener in tuple(self.listeners):
            listener(state)

    def activate(self, raw_key: str) -> bool:
        self.activated.append(raw_key)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        self.publish(
            access_state(
                status="active_subscription",
                active=True,
                has_key=True,
                features=("native_hook", "future_feature"),
                expires_at=now + timedelta(days=30),
                checked_at=now,
                key_hint="BSK_AAAAAAAA••••DDDD",
                online=True,
                message="Premium subscription is active.",
            )
        )
        return True

    def check_now(self) -> bool:
        self.checks += 1
        return True

    def remove_key(self) -> None:
        self.removals += 1
        self.publish(access_state())


class SupporterAccessPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.controller = FakeAccessController()
        self.opened = []
        self.page = SupporterAccessPage(
            controller=self.controller,
            open_patreon=lambda: self.opened.append("patreon"),
            open_crypto=lambda: self.opened.append("crypto"),
            open_github=lambda: self.opened.append("github"),
            open_discord=lambda: self.opened.append("discord"),
            crypto_enabled=True,
        )
        self.page.resize(540, 600)
        self.page.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        QApplication.processEvents()

    def test_activation_replaces_the_raw_key_with_safe_state(self) -> None:
        self.assertTrue(self.page.key_entry_panel.isVisible())
        self.assertFalse(self.page.saved_key_panel.isVisible())
        self.assertFalse(self.page.activate_button.isEnabled())

        self.page.key_entry.setText(RAW_KEY)
        self.assertTrue(self.page.activate_button.isEnabled())
        self.page.activate_button.click()
        QApplication.processEvents()

        self.assertEqual(self.controller.activated, [RAW_KEY])
        self.assertEqual(self.page.key_entry.text(), "")
        self.assertFalse(self.page.key_entry_panel.isVisible())
        self.assertTrue(self.page.saved_key_panel.isVisible())
        self.assertEqual(self.page.key_hint.text(), "BSK_AAAAAAAA••••DDDD")
        self.assertNotIn(RAW_KEY, self.page.key_hint.text())
        self.assertEqual(self.page.status_badge.text(), "ACTIVE")
        self.assertEqual(self.page.status_badge.property("tone"), "active")
        self.assertFalse(self.page.access_guide_section.isVisible())

        visible_labels = [
            label.text()
            for label in self.page.findChildren(QLabel)
            if label.isVisible()
        ]
        self.assertNotIn(RAW_KEY, visible_labels)
        self.assertNotIn("ASSIGNED FEATURES", visible_labels)
        self.assertNotIn("Native Hook", visible_labels)
        self.assertNotIn("Future Feature", visible_labels)

    def test_check_cached_state_and_remove_are_distinct_actions(self) -> None:
        self.page.key_entry.setText(RAW_KEY)
        self.page.activate_button.click()
        self.page.check_button.click()
        self.assertEqual(self.controller.checks, 1)

        self.controller.publish(
            access_state(
                status="cached_valid",
                active=True,
                has_key=True,
                features=("native_hook",),
                checked_at=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
                key_hint="BSK_AAAAAAAA••••DDDD",
                online=False,
                message="Using recently verified access.",
            )
        )
        self.assertEqual(self.page.status_badge.text(), "OFFLINE READY")
        self.assertEqual(self.page.status_badge.property("tone"), "cached")

        with patch(
            "ui.dialogs.supporter_access.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ):
            self.page.remove_button.click()
        QApplication.processEvents()

        self.assertEqual(self.controller.removals, 1)
        self.assertTrue(self.page.key_entry_panel.isVisible())
        self.assertFalse(self.page.saved_key_panel.isVisible())
        self.assertEqual(self.page.status_badge.text(), "NO KEY")

    def test_support_methods_are_primary_and_project_links_are_secondary(self) -> None:
        self.assertTrue(self.page.access_guide_section.isVisible())
        self.assertEqual(self.page.patreon_btn.objectName(), "SupportPatreonPrimary")
        self.assertEqual(self.page.crypto_btn.objectName(), "SupportCryptoPrimary")
        self.assertGreater(self.page.patreon_btn.width(), 160)
        self.assertGreater(self.page.crypto_btn.width(), 160)
        self.assertEqual(self.page.github_btn.objectName(), "SupportSecondaryLink")
        self.assertEqual(self.page.discord_btn.objectName(), "SupportSecondaryLink")
        self.assertGreater(self.page.github_btn.width(), 160)
        self.assertGreater(self.page.discord_btn.width(), 160)
        self.assertEqual(self.page.github_btn.height(), 34)
        self.assertEqual(self.page.discord_btn.height(), 34)

        for name, button in (
            ("patreon", self.page.patreon_btn),
            ("crypto", self.page.crypto_btn),
            ("github", self.page.github_btn),
            ("discord", self.page.discord_btn),
        ):
            button.click()
            self.assertEqual(self.opened[-1], name)


if __name__ == "__main__":
    unittest.main()
