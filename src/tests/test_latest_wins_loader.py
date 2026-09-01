from __future__ import annotations

import threading
import unittest

from app.latest_wins_loader import LatestWinsLoader


class LatestWinsLoaderTests(unittest.TestCase):
    def test_one_active_and_only_latest_pending_request_commits(self) -> None:
        started = []
        completed = []
        release = threading.Event()
        last_done = threading.Event()

        def load(value):
            started.append(value)
            if value == "first":
                release.wait(2.0)
            return value.upper()

        def complete(value, error):
            completed.append((value, error))
            last_done.set()

        loader = LatestWinsLoader(schedule=lambda callback: callback())
        loader.submit("first", load=load, complete=complete)
        loader.submit("middle", load=load, complete=complete)
        loader.submit("last", load=load, complete=complete)
        release.set()
        self.assertTrue(last_done.wait(2.0))
        loader.dispose()

        self.assertEqual(started, ["first", "last"])
        self.assertEqual(completed, [("LAST", None)])

    def test_dispose_drops_pending_and_ui_callback(self) -> None:
        release = threading.Event()
        completed = []
        loader = LatestWinsLoader(schedule=lambda callback: callback())
        loader.submit("first", load=lambda value: release.wait(2.0) or value, complete=lambda *args: completed.append(args))
        loader.submit("last", load=lambda value: value, complete=lambda *args: completed.append(args))
        loader.dispose()
        release.set()
        self.assertEqual(completed, [])


if __name__ == "__main__":
    unittest.main()
