from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import src  # noqa: F401

from app import config
from app.config_repository import ConfigRepository
from app.settings import ConfigRecordingSettings


class ConfigRepositoryTests(unittest.TestCase):
    def test_commit_load_snapshot_and_update_are_transactional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ConfigRepository(Path(directory) / "config.json")

            self.assertTrue(repository.commit({"value": 1}).success)
            self.assertEqual(repository.load().snapshot, {"value": 1})
            self.assertTrue(
                repository.update(lambda candidate: candidate.update(value=2)).success
            )
            self.assertEqual(repository.snapshot(), {"value": 2})

    def test_failed_commit_does_not_replace_runtime_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ConfigRepository(Path(directory) / "config.json")
            self.assertTrue(repository.commit({"value": 1}).success)

            with patch("app.config_repository.os.replace", side_effect=PermissionError("read only")):
                result = repository.commit({"value": 2})

            self.assertFalse(result.success)
            self.assertEqual(repository.snapshot(), {"value": 1})

    def test_failed_readback_restores_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = ConfigRepository(path)
            self.assertTrue(repository.commit({"value": 1}).success)

            with patch.object(Path, "read_text", side_effect=OSError("readback failed")):
                result = repository.commit({"value": 2})

            self.assertFalse(result.success)
            self.assertEqual(repository.snapshot(), {"value": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    def test_update_config_publishes_only_after_verified_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ConfigRepository(Path(directory) / "config.json")
            self.assertTrue(repository.commit({"value": 1}).success)
            previous = {
                "repository": config._repository,
                "lock": config.config_lock,
                "path": config.config_path,
                "snapshot": config.user_config,
            }
            runtime_snapshot = {"value": 1}
            try:
                config._repository = repository
                config.config_lock = repository.lock
                config.config_path = str(repository.path)
                config.user_config = runtime_snapshot
                with patch(
                    "app.config_repository.os.replace",
                    side_effect=PermissionError("read only"),
                ):
                    result = config.update_config(
                        lambda candidate: candidate.__setitem__("value", 2)
                    )
                self.assertFalse(result.success)
                self.assertEqual(runtime_snapshot, {"value": 1})
                self.assertEqual(repository.snapshot(), {"value": 1})
            finally:
                config._repository = previous["repository"]
                config.config_lock = previous["lock"]
                config.config_path = previous["path"]
                config.user_config = previous["snapshot"]

    def test_config_module_has_no_import_time_persistence_calls(self) -> None:
        tree = ast.parse(Path(config.__file__).read_text(encoding="utf-8"))
        forbidden = {
            "load_config",
            "save_config",
            "cleanup_legacy_native_hook_cache",
            "get_game_reset_time",
        }
        calls = []
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for node in ast.walk(statement):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in forbidden:
                        calls.append(node.func.id)
        self.assertEqual(calls, [])

    def test_initialize_loads_normalises_and_persists_explicitly(self) -> None:
        previous = {
            "repository": config._repository,
            "lock": config.config_lock,
            "path": config.config_path,
            "existed": config.CONFIG_FILE_EXISTED_AT_STARTUP,
            "snapshot": deepcopy(config.user_config),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = ConfigRepository(path)
            self.assertTrue(
                repository.commit(
                    {
                        "HOTKEY": "f7",
                        "PROCESS_NAME": "Game.exe",
                        "RESET_HOLD_DURATION": 0.7,
                    }
                ).success
            )
            try:
                with patch.object(config, "get_game_reset_time", return_value=0.5), patch.object(
                    config, "cleanup_legacy_native_hook_cache"
                ):
                    result = config.initialize_config(repository)
                self.assertTrue(result.existed)
                self.assertEqual(config.HOTKEY, "f7")
                self.assertEqual(config.PROCESS_NAME, "Game.exe")
                self.assertEqual(config.RESET_HOLD_DURATION, 0.7)
                self.assertEqual(repository.load().snapshot["HOTKEY"], "f7")
            finally:
                config._repository = previous["repository"]
                config.config_lock = previous["lock"]
                config.config_path = previous["path"]
                config.CONFIG_FILE_EXISTED_AT_STARTUP = previous["existed"]
                with patch.object(config, "get_game_reset_time", return_value=None), patch.object(
                    config, "cleanup_legacy_native_hook_cache"
                ):
                    config._apply_loaded_config(
                        previous["snapshot"],
                        config_existed=previous["existed"],
                    )

    def test_legacy_vod_index_moves_to_its_own_cache_file(self) -> None:
        previous = deepcopy(config.user_config)
        with tempfile.TemporaryDirectory() as directory:
            settings = ConfigRecordingSettings(
                index_path=Path(directory) / "vod_metadata_index.json"
            )
            legacy = {"version": 1, "records": [{"path": "recording.jsonl"}]}
            config.user_config["_VOD_METADATA_INDEX"] = deepcopy(legacy)
            try:
                with patch.object(
                    config,
                    "save_config",
                    return_value=config.ConfigSaveResult(True),
                ):
                    self.assertEqual(settings.read_metadata_index(), legacy)
                self.assertNotIn("_VOD_METADATA_INDEX", config.user_config)
                self.assertEqual(settings.read_metadata_index(), legacy)
            finally:
                config.user_config.clear()
                config.user_config.update(previous)


if __name__ == "__main__":
    unittest.main()
