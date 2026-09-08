from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.supporter_access import SupporterAccessController
from infra.supporter_access_client import (
    AccessResponse,
    InvalidAccessKey,
    SupporterAccessError,
)


RAW_KEY = "BSK_AAAAAAAA_BBBBBBBB_CCCCCCCC_DDDDDDDD"


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def check(self, key):
        self.calls.append(key)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SupporterAccessControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        self.credentials = {"key": ""}
        self.scheduled = []
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache_path = Path(self.temp.name) / "access.json"

    def response(self, *, active=True, status="active_subscription"):
        return AccessResponse(
            active=active,
            status=status,
            features=("native_hook",) if active else (),
            expires_at=self.now + timedelta(days=30) if active else None,
            next_change_at=self.now + timedelta(days=30) if active else None,
            checked_at=self.now,
            cache_seconds=900,
            key_hint="BSK_AAAAAAAA••••DDDD",
        )

    def controller(self, client):
        def schedule(delay, callback):
            if delay == 0:
                callback()
            else:
                self.scheduled.append((delay, callback))

        return SupporterAccessController(
            client=client,
            schedule=schedule,
            is_shutting_down=lambda: False,
            cache_path=self.cache_path,
            now=lambda: self.now,
            worker_launcher=lambda target: target(),
            get_key=lambda: self.credentials["key"],
            set_key=lambda value: self.credentials.__setitem__("key", value),
            delete_key=lambda: self.credentials.__setitem__("key", ""),
        )

    def test_no_key_never_calls_the_service(self):
        client = FakeClient([])
        controller = self.controller(client)

        controller.start()
        controller.check_now()

        self.assertEqual(client.calls, [])
        self.assertEqual(controller.state.status, "no_key")

    def test_activation_stores_key_and_only_non_secret_cache(self):
        client = FakeClient([self.response()])
        controller = self.controller(client)

        self.assertTrue(controller.activate(RAW_KEY.lower()))

        self.assertEqual(self.credentials["key"], RAW_KEY)
        self.assertTrue(controller.has_feature("native_hook"))
        cache_text = self.cache_path.read_text(encoding="utf-8")
        self.assertNotIn(RAW_KEY, cache_text)
        self.assertIn("native_hook", cache_text)

    def test_recent_cache_keeps_feature_during_network_failure(self):
        first = self.controller(FakeClient([self.response()]))
        first.activate(RAW_KEY)
        self.credentials["key"] = RAW_KEY
        second = self.controller(
            FakeClient([SupporterAccessError("The supporter service could not be reached.")])
        )

        self.assertEqual(second.state.status, "cached_valid")
        second.check_now()

        self.assertTrue(second.has_feature("native_hook"))
        self.assertEqual(second.state.status, "cached_valid")
        self.assertFalse(second.state.online)

    def test_offline_grace_expires_closed(self):
        first = self.controller(FakeClient([self.response()]))
        first.activate(RAW_KEY)
        self.credentials["key"] = RAW_KEY
        self.now += timedelta(hours=25)

        second = self.controller(FakeClient([]))

        self.assertFalse(second.has_feature("native_hook"))
        self.assertEqual(second.state.status, "offline_unknown")

    def test_confirmed_invalid_saved_key_closes_cached_access_immediately(self):
        first = self.controller(FakeClient([self.response()]))
        first.activate(RAW_KEY)
        self.credentials["key"] = RAW_KEY
        second = self.controller(
            FakeClient([InvalidAccessKey("This supporter key was not recognized.")])
        )
        self.assertTrue(second.has_feature("native_hook"))

        second.check_now()

        self.assertFalse(second.has_feature("native_hook"))
        self.assertEqual(second.state.status, "invalid")
        self.assertTrue(second.state.online)
        self.assertEqual(second.state.features, ())
        self.assertFalse(self.cache_path.exists())

    def test_remove_key_clears_state_and_cache(self):
        controller = self.controller(FakeClient([self.response()]))
        controller.activate(RAW_KEY)

        controller.remove_key()

        self.assertEqual(self.credentials["key"], "")
        self.assertFalse(self.cache_path.exists())
        self.assertFalse(controller.has_feature("native_hook"))


if __name__ == "__main__":
    unittest.main()
