"""Failure and re-entry rules for the shared lazy page shells."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401 -- path bootstrap


class SharedPageLifecycleTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QLabel
            from ui.shared import LazyPage, StagedLoadingPage

            app = QApplication([])
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lazy_page_is_reentrant_and_retries_after_failure(self) -> None:
        self._run(
            """
            attempts = []
            should_fail = [True]
            page = None

            def populate():
                attempts.append("run")
                page.build_now()  # re-entry must not populate a second time
                if should_fail[0]:
                    raise RuntimeError("temporary failure")

            page = LazyPage(populate)
            try:
                page.build_now()
            except RuntimeError:
                pass
            else:
                raise AssertionError("the population failure was hidden")

            assert attempts == ["run"], attempts
            assert not page.is_built

            should_fail[0] = False
            page.build_now()
            assert attempts == ["run", "run"], attempts
            assert page.is_built
            page.build_now()
            assert attempts == ["run", "run"], attempts
            """
        )

    def test_staged_timer_failure_is_contained_and_shown(self) -> None:
        self._run(
            """
            def populate(_workspace):
                yield
                raise ValueError("broken stage")

            page = StagedLoadingPage(populate, object_prefix="FailureProbe")
            failures = []
            page.failed.connect(failures.append)
            page.resize(500, 300)
            page.show()
            app.processEvents()
            page._timer.stop()

            page._advance()
            page._timer.stop()
            page._advance()  # a Qt timer slot must not let this escape

            assert page.is_failed
            assert not page.is_built
            assert not page._timer.isActive()
            assert len(failures) == 1 and isinstance(failures[0], ValueError)
            error = page.findChild(QLabel, "FailureProbeLoadingError")
            assert error is not None and "could not be loaded" in error.text()
            """
        )

    def test_synchronous_staged_build_still_reports_the_original_error(self) -> None:
        self._run(
            """
            def populate(_workspace):
                yield
                raise LookupError("missing input")

            page = StagedLoadingPage(populate, object_prefix="SyncFailureProbe")
            try:
                page.build_now()
            except LookupError as exc:
                assert str(exc) == "missing input"
            else:
                raise AssertionError("build_now hid the original exception")

            assert page.is_failed
            assert not page.is_built
            original_layout = page.layout()
            original_workspace = page._workspace
            try:
                page.build_now()
            except RuntimeError as exc:
                assert isinstance(exc.__cause__, LookupError)
            else:
                raise AssertionError("a failed page attempted a partial rebuild")
            assert page.layout() is original_layout
            assert page._workspace is original_workspace
            """
        )

    def test_staged_page_ignores_reentrant_build_requests(self) -> None:
        self._run(
            """
            calls = []
            page = None

            def populate(_workspace):
                calls.append("first")
                page.build_now()
                yield
                calls.append("second")
                yield

            page = StagedLoadingPage(populate, object_prefix="ReentryProbe")
            page.build_now()
            assert page.is_built
            assert calls == ["first", "second"], calls
            """
        )


if __name__ == "__main__":
    unittest.main()
