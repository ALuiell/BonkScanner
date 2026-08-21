from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import src  # noqa: F401

from app import config
from core.json_safety import loads_strict_json


class StrictJsonInputTests(unittest.TestCase):
    def test_external_json_rejects_non_standard_and_overflowing_numbers(self) -> None:
        for payload in (b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e400}'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    loads_strict_json(payload)


class ConfigJsonIntegrityTests(unittest.TestCase):
    def test_save_config_is_atomic_and_emits_only_standard_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            with patch.object(config, "config_path", str(path)):
                config.save_config(
                    {
                        "finite": 1.5,
                        "unknowns": [float("nan"), float("inf"), float("-inf")],
                    }
                )

            text = path.read_text(encoding="utf-8")
            payload = json.loads(
                text,
                parse_constant=lambda constant: self.fail(
                    f"config emitted non-standard JSON constant {constant}"
                ),
            )
            self.assertEqual(payload["finite"], 1.5)
            self.assertEqual(payload["unknowns"], [None, None, None])
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_failed_serialization_does_not_truncate_the_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            original = '{"preserved": true}\n'
            path.write_text(original, encoding="utf-8")

            with patch.object(config, "config_path", str(path)):
                config.save_config({"unsupported": object()})

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_load_config_maps_legacy_non_finite_numbers_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                '{"nan":NaN,"positive":Infinity,"negative":-Infinity,"overflow":1e400}',
                encoding="utf-8",
            )

            with patch.object(config, "config_path", str(path)):
                loaded = config.load_config()

            self.assertEqual(
                loaded,
                {"nan": None, "positive": None, "negative": None, "overflow": None},
            )

    def test_load_config_rejects_a_non_object_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('["valid JSON", "not a config object"]', encoding="utf-8")

            with patch.object(config, "config_path", str(path)):
                self.assertEqual(config.load_config(), {})

    def test_game_reset_update_rejects_non_finite_before_writing(self) -> None:
        with patch.object(config, "get_game_config_path", return_value="config.json"), patch.object(
            config.os.path, "exists", return_value=True
        ), patch.object(config, "load_game_config", return_value={"cfGameSettings": {}}), patch.object(
            config, "save_game_config"
        ) as save_game_config:
            result = config.update_game_reset_time(float("inf"))

        self.assertFalse(result.success)
        self.assertIn("finite", result.reason)
        save_game_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
