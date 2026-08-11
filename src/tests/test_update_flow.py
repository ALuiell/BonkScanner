from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import src  # noqa: F401  -- puts src/ on the path, as the other tests do

from app import update_flow
from infra.updater import ReleaseInfo


class UpdateFlowTests(unittest.TestCase):
    def _check(self, release_version: str, skipped_version: str):
        report = Mock()
        confirm = Mock()
        release = ReleaseInfo(release_version, "notes", "https://example.test/update.exe")

        with (
            patch.object(update_flow.updater, "frozen_exe_path", return_value="BonkScanner.exe"),
            patch.object(update_flow.updater, "fetch_latest_release", return_value=release),
            patch.object(update_flow.config, "SKIPPED_UPDATE_VERSION", skipped_version),
        ):
            update_flow.check_and_update(confirm=confirm, report=report)

        return report, confirm

    def test_skipped_preference_does_not_mark_current_version_available(self):
        report, confirm = self._check(update_flow.CURRENT_VERSION, update_flow.CURRENT_VERSION)

        report.assert_called_once_with("current", update_flow.CURRENT_VERSION)
        confirm.assert_not_called()

    def test_skipped_newer_version_remains_available_without_prompt(self):
        report, confirm = self._check("99.0.0", "99.0.0")

        report.assert_called_once_with("available", "99.0.0")
        confirm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
