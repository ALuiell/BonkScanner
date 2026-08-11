from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

import src


SRC_ROOT = Path(__file__).resolve().parents[1]


class CrashJournalTests(unittest.TestCase):
    def _run(self, code: str, temp_dir: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        env["BONKSCANNER_CRASH_LOG_DIR"] = str(temp_dir / "installed" / "logs")
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            cwd=SRC_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_clean_exit_leaves_no_pending_journal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp_dir = Path(raw_temp)
            result = self._run(
                """
                from infra.crash_journal import install_crash_journal, mark_clean_exit
                pending = install_crash_journal()
                assert pending is not None and pending.exists()
                mark_clean_exit()
                assert not pending.exists()
                """,
                temp_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unclean_exit_is_promoted_on_next_launch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp_dir = Path(raw_temp)
            first = self._run(
                """
                from infra.crash_journal import install_crash_journal, log_runtime_event
                install_crash_journal()
                log_runtime_event("test.before_abort")
                """,
                temp_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            pending = list((temp_dir / "BonkScanner").glob("pending-*.log"))
            self.assertEqual(len(pending), 1)

            second = self._run(
                """
                from infra.crash_journal import install_crash_journal, mark_clean_exit
                install_crash_journal()
                mark_clean_exit()
                """,
                temp_dir,
            )
            self.assertEqual(second.returncode, 0, second.stderr)

            promoted = sorted((temp_dir / "installed" / "logs").glob("crash-*.log"))
            self.assertTrue(promoted)
            latest = promoted[-1]
            self.assertIn("test.before_abort", latest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
