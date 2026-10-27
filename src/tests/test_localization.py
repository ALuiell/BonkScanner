from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch

import src  # noqa: F401
from app import config
from app.config_repository import ConfigRepository
from app.localization import selected_language
from core.localization import LANGUAGE_CONFIG_KEY, SUPPORTED_LANGUAGES, Translator, normalize_language
from infra.localization_catalogs import create_translator, localization_directory


class LocalizationTests(unittest.TestCase):
    def test_missing_or_broken_ui_translation_falls_back_with_parameters(self):
        catalogs = {
            "en": {"count": "Recorded {count} runs", "save": "Save"},
            "uk": {"count": "Recorded {wrong} runs", "save": ""},
        }
        translator = Translator(catalogs.__getitem__, lambda _: {}, {}, language="uk")
        self.assertEqual(translator.text("count", count=4), "Recorded 4 runs")
        self.assertEqual(translator.text("save"), "Save")
        with self.assertRaises(KeyError):
            translator.text("count")
        self.assertEqual(normalize_language("unknown"), "en")
        self.assertEqual(normalize_language(None), "en")

    def test_game_strings_keep_table_context_and_fall_back_without_changing_source(self):
        translator = create_translator(language="uk")
        self.assertEqual(translator.game_text("Rarities", "Legendary"), "Легендарний")
        english = create_translator().game_text("Maps", "CRYPT_DESC")
        self.assertEqual(translator.game_text("Maps", "CRYPT_DESC"), english)
        self.assertEqual(translator.game_text("Hats", "FROG2_DESC", default="Unknown hat"), "Unknown hat")
        self.assertIn("{value", translator.game_text("Tomes", "TOME_BALANCE_DESC"))
        self.assertEqual(translator.game_name("weapons", "Fire Staff"), "Вогняний Посох")
        self.assertEqual(translator.game_name("tomes", "Damage"), "Том Шкоди")
        self.assertEqual(translator.game_name("tomes", "Bounce"), "Bounce")
        self.assertEqual(translator.game_name("items", "The One Ring"), "Золоте Кільце")

    def test_all_ui_catalogs_cover_same_keys_and_placeholders_and_aliases_resolve(self):
        root = localization_directory()
        catalogs = {code: json.loads((root / "ui" / f"{code}.json").read_text(encoding="utf-8"))
                    for code in SUPPORTED_LANGUAGES}
        english = catalogs["en"]
        for code, catalog in catalogs.items():
            self.assertEqual(set(catalog), set(english), code)
            for key, text in catalog.items():
                self.assertTrue(text.strip(), (code, key))
                fields = lambda message: {field for _, field, _, _ in Formatter().parse(message) if field is not None}
                self.assertEqual(fields(text), fields(english[key]), (code, key))
        game = json.loads((root / "game/en.json").read_text(encoding="utf-8"))["tables"]
        aliases = json.loads((root / "game_aliases.json").read_text(encoding="utf-8"))
        for entries in aliases.values():
            for reference in entries.values():
                self.assertIn(reference["key"], game[reference["table"]]["entries"])

    def test_catalogs_are_cached_and_language_change_does_not_load_game_data(self):
        calls = []
        def load_ui(code):
            calls.append(code)
            return {"save": code}
        translator = Translator(load_ui, lambda _: self.fail("Game data loaded for UI text"), {})
        self.assertEqual(translator.text("save"), "en")
        self.assertEqual(translator.text("save"), "en")
        self.assertTrue(translator.set_language("ru"))
        self.assertEqual(translator.text("save"), "ru")
        self.assertFalse(translator.set_language("ru"))
        self.assertEqual(calls, ["en", "ru"])

    def test_packaged_assets_use_meipass(self):
        with patch("infra.localization_catalogs.sys._MEIPASS", "bundled", create=True):
            self.assertEqual(localization_directory(), Path("bundled/media/localization"))

    def test_preference_survives_reload_and_secondary_changes_stay_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ConfigRepository(Path(directory) / "config.json")
            repository.load()
            snapshot = deepcopy(config.user_config)
            snapshot[LANGUAGE_CONFIG_KEY] = "en"
            self.assertTrue(repository.commit(snapshot).success)
            with patch.object(config, "_repository", repository), \
                    patch.object(config, "config_path", str(repository.path)), \
                    patch.object(config, "config_lock", repository.lock), \
                    patch.object(config, "user_config", deepcopy(snapshot)):
                result = config.save_settings_with_game_reset({LANGUAGE_CONFIG_KEY: "de"}, None, sync_game=False)
                self.assertTrue(result.success)
                self.assertEqual(selected_language(), "de")
                self.assertEqual(ConfigRepository(repository.path).load().snapshot[LANGUAGE_CONFIG_KEY], "de")
                repository.read_only_reason = "Secondary instance"
                result = config.update_config(lambda candidate: candidate.update({LANGUAGE_CONFIG_KEY: "ru"}))
                # Existing secondary-instance semantics allow session-only
                # preferences while protecting the owning profile on disk.
                self.assertTrue(result.success)
                self.assertEqual(selected_language(), "ru")
                self.assertEqual(ConfigRepository(repository.path).load().snapshot[LANGUAGE_CONFIG_KEY], "de")
