from __future__ import annotations

import os
import json
import tempfile
import unittest
from unittest.mock import patch

import src

from app import config


class GameResetTimeConfigTests(unittest.TestCase):
    def _write_game_config(self, path: str, quick_reset_time: float = 0.05) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"cfGameSettings": {"quick_reset_time": quick_reset_time}},
                handle,
            )

    def test_update_game_reset_time_writes_and_verifies_requested_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                result = config.update_game_reset_time(0.2)

            self.assertTrue(result.success)
            with open(game_config_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["cfGameSettings"]["quick_reset_time"], 0.2)

    def test_update_game_reset_time_reports_missing_game_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = os.path.join(temp_dir, "missing.json")

            with patch.object(config, "get_game_config_path", return_value=missing_path):
                result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("not found", result.reason)

    def test_update_game_reset_time_reports_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_game_config", return_value=False):
                    result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("write", result.reason)

    def test_update_game_reset_time_rejects_unverified_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path, quick_reset_time=0.05)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_game_config", return_value=True):
                    result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("expected 0.20", result.reason)
            self.assertIn("found 0.05", result.reason)

    def test_read_game_quick_reset_time_reports_the_raw_game_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path, quick_reset_time=0.037)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                result = config.read_game_quick_reset_time()

            self.assertTrue(result.success)
            self.assertEqual(result.value, 0.04)


class VerifiedSettingsSaveTests(unittest.TestCase):
    def test_success_updates_and_verifies_both_real_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scanner_path = os.path.join(temp_dir, "scanner.json")
            game_path = os.path.join(temp_dir, "game.json")
            previous = {"RESET_HOLD_DURATION": 0.07}
            candidate = {
                "RESET_HOLD_DURATION": 0.03,
                "RESET_HOLD_SAFETY_MARGIN": 0.02,
            }
            with open(scanner_path, "w", encoding="utf-8") as handle:
                json.dump(previous, handle)
            with open(game_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 0.05}}, handle)

            with patch.object(config, "config_path", scanner_path):
                with patch.object(config, "user_config", previous):
                    with patch.object(config, "get_game_config_path", return_value=game_path):
                        result = config.save_settings_with_game_reset(
                            candidate,
                            0.01,
                            sync_game=True,
                        )

            self.assertTrue(result.success)
            with open(scanner_path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), candidate)
            with open(game_path, "r", encoding="utf-8") as handle:
                saved_game = json.load(handle)
            self.assertEqual(saved_game["cfGameSettings"]["quick_reset_time"], 0.01)

    def test_game_failure_rolls_back_the_scanner_config(self) -> None:
        previous = dict(config.user_config)
        candidate = {**previous, "RESET_HOLD_DURATION": 0.03}
        game_failure = config.GameConfigUpdateResult(False, "game write failed")

        with patch.object(
            config,
            "save_config",
            side_effect=[config.ConfigSaveResult(True), config.ConfigSaveResult(True)],
        ) as save_config:
            with patch.object(
                config,
                "update_game_reset_time",
                return_value=game_failure,
            ):
                result = config.save_settings_with_game_reset(
                    candidate,
                    0.01,
                    sync_game=True,
                )

        self.assertFalse(result.success)
        self.assertIn("game write failed", result.reason)
        self.assertIn("rolled back", result.reason)
        self.assertEqual(save_config.call_args_list[0].args[0], candidate)
        self.assertEqual(save_config.call_args_list[1].args[0], previous)

    def test_scanner_failure_does_not_touch_the_game_config(self) -> None:
        failure = config.ConfigSaveResult(False, "scanner write failed")
        with patch.object(
            config,
            "save_config",
            side_effect=[failure, config.ConfigSaveResult(True)],
        ):
            with patch.object(config, "update_game_reset_time") as update_game_reset_time:
                result = config.save_settings_with_game_reset(
                    {"RESET_HOLD_DURATION": 0.03},
                    0.01,
                    sync_game=True,
                )

        self.assertFalse(result.success)
        self.assertIn("scanner write failed", result.reason)
        self.assertIn("previous BonkScanner config was restored", result.reason)
        update_game_reset_time.assert_not_called()


class PlayerMovementGuardConfigTests(unittest.TestCase):
    def test_missing_setting_defaults_to_disabled(self) -> None:
        self.assertFalse(config.resolve_stop_scanning_on_player_movement(None))

    def test_explicit_setting_is_preserved(self) -> None:
        self.assertTrue(config.resolve_stop_scanning_on_player_movement(True))
        self.assertFalse(config.resolve_stop_scanning_on_player_movement(False))

    def test_invalid_legacy_value_fails_to_disabled(self) -> None:
        self.assertFalse(config.resolve_stop_scanning_on_player_movement("true"))


class TwitchShrineTemplateMigrationTests(unittest.TestCase):
    def test_old_map_scoped_default_is_migrated_to_run_bonus_template(self) -> None:
        normalized = config.normalize_twitch_bot_config(
            {
                "templates": {
                    "shrines": (
                        "Shrines Map {stage}: {charged}/{total} charged | {shrines}"
                    )
                }
            }
        )

        self.assertEqual(
            normalized["templates"]["shrines"],
            config.DEFAULT_TWITCH_BOT["templates"]["shrines"],
        )


class ResetHoldDurationFloorTests(unittest.TestCase):
    """The game threshold is a floor: too-short is raised, longer is kept."""

    def test_stored_value_below_the_game_floor_is_raised(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(0.45, 1.05)
        self.assertEqual(duration, 1.05)
        self.assertEqual(raised_from, 0.45)

    def test_stored_value_above_the_game_floor_is_kept(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(2.0, 1.05)
        self.assertEqual(duration, 2.0)
        self.assertIsNone(raised_from)

    def test_stored_value_equal_to_the_game_floor_is_not_reported_as_raised(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(1.05, 1.05)
        self.assertEqual(duration, 1.05)
        self.assertIsNone(raised_from)

    def test_unreadable_game_config_leaves_the_stored_value_alone(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(0.1, None)
        self.assertEqual(duration, 0.1)
        self.assertIsNone(raised_from)

    def test_values_below_the_supported_settings_minimum_are_raised(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(0.01, None)
        self.assertEqual(duration, config.minimum_reset_hold_duration())
        self.assertIsNone(raised_from)

    def test_missing_stored_value_takes_the_game_floor(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(None, 1.05)
        self.assertEqual(duration, 1.05)
        self.assertIsNone(raised_from)

    def test_missing_stored_value_and_no_game_config_falls_back_to_default(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration(None, None)
        self.assertEqual(duration, config.DEFAULT_RESET_HOLD_DURATION)
        self.assertIsNone(raised_from)

    def test_corrupt_stored_value_is_coerced_then_floored(self) -> None:
        duration, raised_from = config.resolve_reset_hold_duration("not-a-number", 1.05)
        self.assertEqual(duration, 1.05)
        self.assertEqual(raised_from, round(config.DEFAULT_RESET_HOLD_DURATION, 2))

    def test_absent_key_takes_the_game_value_plus_the_safety_margin(self) -> None:
        """The margin is not optional on the fallback path -- holding for exactly
        `quick_reset_time` races the game's own threshold check."""
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 1.0}}, handle)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                game_floor = config.get_game_reset_time()

            duration, raised_from = config.resolve_reset_hold_duration(None, game_floor)

            self.assertAlmostEqual(duration, 1.0 + config.RESET_HOLD_SAFETY_MARGIN, places=6)
            self.assertIsNone(raised_from)

    def test_raising_a_short_stored_value_also_carries_the_safety_margin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 1.0}}, handle)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                game_floor = config.get_game_reset_time()

            duration, raised_from = config.resolve_reset_hold_duration(0.4, game_floor)

            self.assertAlmostEqual(duration, 1.0 + config.RESET_HOLD_SAFETY_MARGIN, places=6)
            self.assertEqual(raised_from, 0.4)

    def test_margin_round_trips_between_hold_duration_and_game_value(self) -> None:
        """What the dialog writes must be what the next read gives back."""
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 0.05}}, handle)

            hold_duration = 1.25
            game_value = config.reset_hold_duration_to_game_value(hold_duration)
            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                self.assertTrue(config.update_game_reset_time(game_value).success)
                read_back = config.get_game_reset_time()

            self.assertAlmostEqual(read_back, hold_duration, places=6)

    def test_a_custom_margin_round_trips_through_the_game_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 0.2}}, handle)

            with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.15):
                with patch.object(config, "get_game_config_path", return_value=game_config_path):
                    self.assertAlmostEqual(config.get_game_reset_time(), 0.35, places=6)
                    game_value = config.reset_hold_duration_to_game_value(0.35)
                    self.assertTrue(config.update_game_reset_time(game_value).success)
                    self.assertAlmostEqual(config.get_game_reset_time(), 0.35, places=6)


class ResetHoldSafetyMarginConfigTests(unittest.TestCase):
    def test_valid_values_are_rounded_to_two_decimals(self) -> None:
        self.assertEqual(config.normalize_reset_hold_safety_margin("0.146"), 0.15)
        self.assertEqual(config.normalize_reset_hold_safety_margin(0.0), 0.0)
        self.assertEqual(config.normalize_reset_hold_safety_margin(1.0), 1.0)

    def test_invalid_values_fall_back_to_the_default(self) -> None:
        for value in (-0.01, 1.01, "invalid", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(
                    config.normalize_reset_hold_safety_margin(value),
                    config.DEFAULT_RESET_HOLD_SAFETY_MARGIN,
                )


class MinimumResetHoldDurationConfigTests(unittest.TestCase):
    def test_minimum_is_the_game_floor_plus_the_selected_margin(self) -> None:
        self.assertEqual(config.minimum_reset_hold_duration(0.0), 0.01)
        self.assertEqual(config.minimum_reset_hold_duration(0.02), 0.03)
        self.assertEqual(config.minimum_reset_hold_duration(0.05), 0.06)

    def test_the_obsolete_absolute_minimum_is_removed_from_saved_config(self) -> None:
        self.assertNotIn("MIN_RESET_HOLD_DURATION", config.user_config)

    def test_short_game_aligned_hold_uses_only_the_dynamic_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 0.01}}, handle)

            with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.02):
                with patch.object(config, "get_game_config_path", return_value=game_config_path):
                    game_floor = config.get_game_reset_time()
                duration, raised_from = config.resolve_reset_hold_duration(0.03, game_floor)

            self.assertAlmostEqual(duration, 0.03, places=6)
            self.assertIsNone(raised_from)


class RefreshResetHoldDurationTests(unittest.TestCase):
    """Import-time is not the only check: the game rewrites its config on exit."""

    def setUp(self) -> None:
        self._saved = (
            config.RESET_HOLD_DURATION,
            config.GAME_RESET_HOLD_FLOOR,
            config.RESET_HOLD_DURATION_RAISED_FROM,
        )
        self._had_saved_user_duration = "RESET_HOLD_DURATION" in config.user_config
        self._saved_user_duration = config.user_config.get("RESET_HOLD_DURATION")

    def tearDown(self) -> None:
        (
            config.RESET_HOLD_DURATION,
            config.GAME_RESET_HOLD_FLOOR,
            config.RESET_HOLD_DURATION_RAISED_FROM,
        ) = self._saved
        if self._had_saved_user_duration:
            config.user_config["RESET_HOLD_DURATION"] = self._saved_user_duration
        else:
            config.user_config.pop("RESET_HOLD_DURATION", None)

    def _refresh_against(self, quick_reset_time: float, current_hold: float):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": quick_reset_time}}, handle)

            config.RESET_HOLD_DURATION = current_hold
            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_config"):
                    return config.refresh_reset_hold_duration()

    def test_a_threshold_raised_mid_session_is_picked_up(self) -> None:
        """The console case: the game now needs longer than we are holding."""
        raised_from = self._refresh_against(quick_reset_time=1.0, current_hold=0.25)

        self.assertEqual(raised_from, 0.25)
        self.assertAlmostEqual(
            config.RESET_HOLD_DURATION,
            1.0 + config.RESET_HOLD_SAFETY_MARGIN,
            places=6,
        )

    def test_an_unchanged_threshold_reports_nothing(self) -> None:
        """Runs on every scan start -- it must not log once per scan."""
        self.assertIsNone(self._refresh_against(quick_reset_time=1.0, current_hold=1.05))
        self.assertAlmostEqual(config.RESET_HOLD_DURATION, 1.05, places=6)

    def test_a_lowered_threshold_does_not_drag_the_hold_down(self) -> None:
        self.assertIsNone(self._refresh_against(quick_reset_time=0.2, current_hold=2.0))
        self.assertAlmostEqual(config.RESET_HOLD_DURATION, 2.0, places=6)

    def test_an_unreadable_game_config_leaves_the_hold_untouched(self) -> None:
        config.RESET_HOLD_DURATION = 0.25
        with patch.object(config, "get_game_config_path", return_value=None):
            with patch.object(config, "save_config"):
                raised_from = config.refresh_reset_hold_duration()

        self.assertIsNone(raised_from)
        self.assertEqual(config.RESET_HOLD_DURATION, 0.25)

    def test_a_correction_is_persisted_so_it_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 1.0}}, handle)

            config.RESET_HOLD_DURATION = 0.25
            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_config") as save_config:
                    config.refresh_reset_hold_duration()

        save_config.assert_called_once()
        self.assertEqual(
            config.user_config["RESET_HOLD_DURATION"],
            round(1.0 + config.RESET_HOLD_SAFETY_MARGIN, 2),
        )

    def test_no_correction_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            with open(game_config_path, "w", encoding="utf-8") as handle:
                json.dump({"cfGameSettings": {"quick_reset_time": 1.0}}, handle)

            config.RESET_HOLD_DURATION = 1.05
            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_config") as save_config:
                    config.refresh_reset_hold_duration()

        save_config.assert_not_called()

    def test_the_notice_is_silent_when_nothing_was_raised(self) -> None:
        self.assertIsNone(config.reset_hold_duration_notice(None))

    def test_the_notice_names_both_the_old_and_the_new_value(self) -> None:
        config.RESET_HOLD_DURATION = 1.05
        notice = config.reset_hold_duration_notice(0.25)
        self.assertIn("0.25", notice)
        self.assertIn("1.05", notice)


class LegacyNativeHookCleanupTests(unittest.TestCase):
    def test_cleanup_removes_legacy_hook_directories_and_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = os.path.join(temp_dir, "AppData", "Local")
            root_dir = os.path.join(local_appdata, "BonkScanner")
            native_hook_dir = os.path.join(root_dir, "native-hook")
            extracted_dir = os.path.join(root_dir, "native-hook-extracted")

            os.makedirs(native_hook_dir)
            os.makedirs(extracted_dir)
            with open(os.path.join(native_hook_dir, "BonkHook.dll"), "w", encoding="utf-8") as handle:
                handle.write("x")
            with open(os.path.join(extracted_dir, "BonkHook.dll"), "w", encoding="utf-8") as handle:
                handle.write("x")

            with patch.dict(os.environ, {"LOCALAPPDATA": local_appdata}, clear=False):
                config.cleanup_legacy_native_hook_cache(
                    os.path.join(extracted_dir, "BonkHook.dll")
                )

            self.assertFalse(os.path.exists(native_hook_dir))
            self.assertFalse(os.path.exists(extracted_dir))
            self.assertFalse(os.path.exists(root_dir))

    def test_cleanup_ignores_saved_dll_path_outside_expected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = os.path.join(temp_dir, "AppData", "Local")
            root_dir = os.path.join(local_appdata, "BonkScanner")
            os.makedirs(root_dir)

            external_dir = os.path.join(temp_dir, "Elsewhere")
            os.makedirs(external_dir)
            external_dll_path = os.path.join(external_dir, "BonkHook.dll")
            with open(external_dll_path, "w", encoding="utf-8") as handle:
                handle.write("x")

            with patch.dict(os.environ, {"LOCALAPPDATA": local_appdata}, clear=False):
                config.cleanup_legacy_native_hook_cache(external_dll_path)

            self.assertTrue(os.path.exists(external_dir))
            self.assertTrue(os.path.exists(external_dll_path))
            self.assertFalse(os.path.exists(root_dir))


class InGameOverlayConfigTests(unittest.TestCase):
    def test_invalid_scale_falls_back_to_widget_default(self) -> None:
        normalized = config.normalize_in_game_overlay_config(
            {
                "widgets": {
                    "scanner": {"scale": "not-a-number"},
                    "recording": {"scale": "inf"},
                    "kps": {"scale": ""},
                    "powerups": {"scale": None},
                    "luck_rarity": {"scale": object(), "show_bar": False},
                }
            }
        )

        defaults = config.DEFAULT_IN_GAME_OVERLAY["widgets"]
        self.assertEqual(normalized["widgets"]["scanner"]["scale"], defaults["scanner"]["scale"])
        self.assertEqual(normalized["widgets"]["recording"]["scale"], defaults["recording"]["scale"])
        self.assertEqual(normalized["widgets"]["kps"]["scale"], defaults["kps"]["scale"])
        self.assertEqual(normalized["widgets"]["powerups"]["scale"], defaults["powerups"]["scale"])
        self.assertEqual(normalized["widgets"]["luck_rarity"]["scale"], defaults["luck_rarity"]["scale"])
        self.assertEqual(normalized["widgets"]["luck_rarity"]["show_bar"], False)


class FastTrackerIntervalConfigTests(unittest.TestCase):
    def test_legacy_chaos_tome_key_is_migrated_to_fast_tracker_interval(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms(
                {"CHAOS_TOME_TRACKER_INTERVAL_MS": 250}
            ),
            250,
        )

    def test_new_fast_tracker_key_takes_precedence_over_legacy_key(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms(
                {
                    "FAST_TRACKER_INTERVAL_MS": 300,
                    "CHAOS_TOME_TRACKER_INTERVAL_MS": 250,
                }
            ),
            300,
        )

    def test_fast_tracker_interval_preserves_minimum_bound(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms({"FAST_TRACKER_INTERVAL_MS": 1}),
            100,
        )


class RecordingSnapshotIntervalConfigTests(unittest.TestCase):
    def test_recording_snapshot_interval_preserves_minimum_bound(self) -> None:
        self.assertEqual(
            config.resolve_player_stats_record_interval_seconds(
                {"PLAYER_STATS_RECORD_INTERVAL_SECONDS": 1}
            ),
            config.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
        )

    def test_recording_snapshot_interval_preserves_larger_value(self) -> None:
        self.assertEqual(
            config.resolve_player_stats_record_interval_seconds(
                {"PLAYER_STATS_RECORD_INTERVAL_SECONDS": 60}
            ),
            60,
        )

    def test_invalid_recording_snapshot_interval_uses_default(self) -> None:
        self.assertEqual(
            config.resolve_player_stats_record_interval_seconds(
                {"PLAYER_STATS_RECORD_INTERVAL_SECONDS": "invalid"}
            ),
            config.DEFAULT_PLAYER_STATS_RECORD_INTERVAL_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
