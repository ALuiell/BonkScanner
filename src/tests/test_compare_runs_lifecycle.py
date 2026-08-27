from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src  # noqa: F401 -- repository path bootstrap

from app import config
from tests.support.compare_runs import build_compare_runs_tab
from ui.tabs.compare_runs import tab as compare_runs_tab


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:
        self.value = value

    def text(self) -> str:
        return self.value


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class CompareRunsLifecycleTests(unittest.TestCase):
    def test_loader_thread_start_failure_becomes_visible_state(self) -> None:
        view = build_compare_runs_tab(schedule=lambda callback: callback())
        view._run_a_status_label = _FakeLabel()

        with patch.object(
            compare_runs_tab.threading,
            "Thread",
            side_effect=RuntimeError("thread unavailable"),
        ):
            view.load_compare_run("a", "run-a.jsonl")

        self.assertIn(
            "Could not load recording: thread unavailable",
            view._run_a_status_label.text(),
        )
        self.assertIsNone(view._vod_a)

    def test_queued_load_result_is_ignored_after_tab_destruction(self) -> None:
        scheduled = []
        view = build_compare_runs_tab(schedule=scheduled.append)
        view._run_a_status_label = _FakeLabel()
        loaded = SimpleNamespace(snapshots=())

        with patch.object(compare_runs_tab, "load_vod", return_value=loaded), patch.object(
            compare_runs_tab.threading, "Thread", _ImmediateThread
        ):
            view.load_compare_run("a", "run-a.jsonl")

        self.assertEqual(1, len(scheduled))
        view._on_tab_destroyed()
        scheduled.pop()()

        self.assertIsNone(view._vod_a)
        self.assertIn("Loading recording…", view._run_a_status_label.text())

    def test_library_repaint_is_ignored_after_tab_destruction(self) -> None:
        view = build_compare_runs_tab()
        dead_list = SimpleNamespace(
            clear=lambda: (_ for _ in ()).throw(RuntimeError("deleted widget"))
        )
        view._run_a_list_frame = dead_list
        view._run_b_list_frame = dead_list

        view._on_tab_destroyed()
        view.refresh_compare_runs_list()

        self.assertTrue(view._disposed)

    def test_malformed_render_is_contained_inside_the_ui_callback(self) -> None:
        view = build_compare_runs_tab()
        view._run_a_status_label = _FakeLabel()
        loaded = SimpleNamespace(snapshots=(object(),))
        view.refresh_compare_runs_ui = MagicMock(
            side_effect=ValueError("bad snapshot payload")
        )

        with patch.object(compare_runs_tab, "load_vod", return_value=loaded):
            view.load_compare_run("a", "run-a.jsonl")

        self.assertIsNone(view._vod_a)
        self.assertIn(
            "Could not display recording: bad snapshot payload",
            view._run_a_status_label.text(),
        )

    def test_error_state_survives_a_secondary_diff_renderer_failure(self) -> None:
        messages = []
        view = build_compare_runs_tab(
            log=lambda message, **kwargs: messages.append((message, kwargs))
        )
        view._run_a_status_label = _FakeLabel()
        view._refresh_compare_runs_diff = MagicMock(
            side_effect=ValueError("corrupt diff")
        )

        view._report_compare_run_state("a", "Could not display recording")

        self.assertIn(
            "Could not display recording", view._run_a_status_label.text()
        )
        self.assertIn("corrupt diff", messages[0][0])
        self.assertEqual("warning", messages[0][1]["tag"])

    def test_failed_config_write_rolls_back_and_is_logged(self) -> None:
        messages = []
        view = build_compare_runs_tab(
            log=lambda message, **kwargs: messages.append((message, kwargs))
        )
        user_config = {"unrelated": True}

        with patch.object(config, "user_config", user_config), patch.object(
            config, "save_config", side_effect=OSError("disk full")
        ):
            saved = view._save_compare_run_config_value(
                "compact timeline state", "compare_test", True
            )

        self.assertFalse(saved)
        self.assertEqual({"unrelated": True}, user_config)
        self.assertIn("disk full", messages[0][0])
        self.assertEqual("warning", messages[0][1]["tag"])

    def test_unsuccessful_config_result_also_rolls_back(self) -> None:
        messages = []
        view = build_compare_runs_tab(
            log=lambda message, **kwargs: messages.append((message, kwargs))
        )
        user_config = {"compare_test": "old"}

        with patch.object(config, "user_config", user_config), patch.object(
            config,
            "save_config",
            return_value=config.ConfigSaveResult(False, "verification failed"),
        ):
            saved = view._save_compare_run_config_value(
                "compact timeline state", "compare_test", "new"
            )

        self.assertFalse(saved)
        self.assertEqual("old", user_config["compare_test"])
        self.assertIn("verification failed", messages[0][0])

    def test_series_persistence_failure_does_not_escape_the_menu_slot(self) -> None:
        messages = []
        view = build_compare_runs_tab(
            log=lambda message, **kwargs: messages.append((message, kwargs))
        )
        view._timeline_series_slots = SimpleNamespace(
            set_slot=lambda *_args: (_ for _ in ()).throw(
                OSError("config unavailable")
            )
        )

        view._set_series_slot(0, ("Damage",))

        self.assertIn("config unavailable", messages[0][0])
        self.assertEqual("warning", messages[0][1]["tag"])

    def test_default_diff_timer_is_owned_by_the_qt_page(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QTabWidget

            from app import config
            from ui.tabs.compare_runs.tab import CompareRunsTab

            config.save_config = lambda _payload: None

            class Library:
                index = ()
                def ensure_refresh(self):
                    return None

            app = QApplication([])
            tabs = QTabWidget()
            view = CompareRunsTab(
                tabview=tabs,
                vod_library=Library(),
                is_active=lambda: True,
            )
            view.build()
            view.build_now()

            delivered = []
            view._diff_throttle.cancel()
            view._diff_throttle.request(lambda: None)
            view._diff_throttle.request(lambda: delivered.append(True))
            assert view._diff_throttle.has_pending

            view._tab.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(100)
            QCoreApplication.processEvents()

            assert view._disposed
            assert not view._diff_throttle.has_pending
            assert delivered == []
            print("BLOCK10_COMPARE_RUNS_QT_CONTEXT_OK")
            """
        )
        environment = os.environ.copy()
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("BLOCK10_COMPARE_RUNS_QT_CONTEXT_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
