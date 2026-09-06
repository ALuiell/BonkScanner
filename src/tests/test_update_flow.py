from __future__ import annotations

import unittest
from unittest.mock import patch

import src  # noqa: F401

from app import config
from app import update_flow
from infra.updater import ReleaseInfo


DIGEST = "1" * 64
DOWNLOAD_URL = (
    "https://github.com/ALuiell/BonkScanner/releases/download/v99.0.0/BonkScanner.exe"
)


def release(version: str) -> ReleaseInfo:
    return ReleaseInfo(version, "notes", DOWNLOAD_URL, 1024, DIGEST)


class UpdateFlowTests(unittest.TestCase):
    def _check(
        self,
        release_version: str,
        skipped_version: str,
        *,
        force=False,
        current_version: str | None = None,
    ):
        if current_version is None:
            current_version = update_flow.CURRENT_VERSION
        with (
            patch.object(update_flow, "CURRENT_VERSION", current_version),
            patch.object(
                update_flow.updater,
                "frozen_exe_path",
                return_value="BonkScanner.exe",
            ),
            patch.object(
                update_flow.updater,
                "fetch_latest_release",
                return_value=release(release_version),
            ),
            patch.object(update_flow.config, "SKIPPED_UPDATE_VERSION", skipped_version),
        ):
            return update_flow.check_for_update(force_check=force)

    def test_skipped_preference_does_not_mark_current_version_available(self):
        result = self._check(update_flow.CURRENT_VERSION, update_flow.CURRENT_VERSION)

        self.assertEqual("current", result.state)
        self.assertEqual(update_flow.CURRENT_VERSION, result.version)
        self.assertFalse(result.should_prompt)

    def test_public_release_is_not_newer_than_its_test_revision(self):
        result = self._check("3.1.2", "", current_version="3.1.2.1")

        self.assertEqual("current", result.state)
        self.assertEqual("3.1.2.1", result.version)

    def test_next_public_release_is_newer_than_test_revision(self):
        result = self._check("3.1.3", "", current_version="3.1.2.1")

        self.assertEqual("available", result.state)
        self.assertEqual("3.1.3", result.version)
        self.assertTrue(result.should_prompt)

    def test_skipped_newer_version_remains_available_without_prompt(self):
        result = self._check("99.0.0", "99.0.0")

        self.assertEqual("available", result.state)
        self.assertEqual("99.0.0", result.version)
        self.assertFalse(result.should_prompt)
        self.assertIsNotNone(result.release)

    def test_manual_check_prompts_for_a_previously_skipped_release(self):
        result = self._check("99.0.0", "99.0.0", force=True)

        self.assertTrue(result.should_prompt)

    def test_source_run_reports_updater_unavailable_without_network(self):
        with (
            patch.object(update_flow.updater, "frozen_exe_path", return_value=None),
            patch.object(update_flow.updater, "fetch_latest_release") as fetch,
        ):
            result = update_flow.check_for_update()

        self.assertEqual("unavailable", result.state)
        fetch.assert_not_called()

    def test_invalid_release_response_becomes_unknown_with_reason(self):
        with (
            patch.object(
                update_flow.updater,
                "frozen_exe_path",
                return_value="BonkScanner.exe",
            ),
            patch.object(
                update_flow.updater,
                "fetch_latest_release",
                side_effect=RuntimeError("bad release"),
            ),
        ):
            result = update_flow.check_for_update()

        self.assertEqual("unknown", result.state)
        self.assertIn("bad release", result.error)

    def test_frozen_executable_probe_failure_becomes_unknown(self):
        with patch.object(
            update_flow.updater,
            "frozen_exe_path",
            side_effect=RuntimeError("bad executable probe"),
        ):
            result = update_flow.check_for_update()

        self.assertEqual("unknown", result.state)
        self.assertIn("bad executable probe", result.error)

    def test_skip_choice_is_persisted_explicitly(self):
        user_config = {}
        with (
            patch.object(update_flow.config, "SKIPPED_UPDATE_VERSION", ""),
            patch.object(update_flow.config, "user_config", user_config),
            patch.object(
                update_flow.config,
                "save_settings_with_game_reset",
                return_value=config.SettingsSaveResult(True),
            ) as save,
        ):
            result = update_flow.skip_update_version("3.2.1")

            self.assertEqual("3.2.1", update_flow.config.SKIPPED_UPDATE_VERSION)
            self.assertTrue(result.success)

        save.assert_called_once_with(
            {"SKIPPED_UPDATE_VERSION": "3.2.1"},
            None,
            sync_game=False,
        )

    def test_failed_skip_persistence_keeps_runtime_value(self):
        failure = config.SettingsSaveResult(False, "disk full")
        with (
            patch.object(update_flow.config, "SKIPPED_UPDATE_VERSION", "3.1.0"),
            patch.object(
                update_flow.config,
                "save_settings_with_game_reset",
                return_value=failure,
            ),
        ):
            result = update_flow.skip_update_version("3.2.1")

            self.assertIs(result, failure)
            self.assertEqual("3.1.0", update_flow.config.SKIPPED_UPDATE_VERSION)

    def test_version_parser_normalizes_release_and_accepts_test_revision(self):
        self.assertEqual((3, 2, 1, 0), update_flow.parse_version("v3.2.1"))
        self.assertEqual((3, 2, 1, 4), update_flow.parse_version("3.2.1.4"))

    def test_version_parser_rejects_unsupported_shapes(self):
        with self.assertRaises(ValueError):
            update_flow.parse_version("3.2.1-beta")
        with self.assertRaises(ValueError):
            update_flow.parse_version("3.2")
        with self.assertRaises(ValueError):
            update_flow.parse_version("3.2.1.4.5")


if __name__ == "__main__":
    unittest.main()
