"""Independent locale choices preserve data, saved drafts and renderer caches."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
from itertools import product
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
import src
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from app import config
from app.localization import create_localization_translator
from core.localization import (SUPPORTED_LANGUAGES, LANGUAGE_CONFIG_KEY,
    GAME_LANGUAGE_CONFIG_KEY, FOLLOW_INTERFACE_LANGUAGE, normalize_game_language)
from core.stats.weapon_tracker import WeaponTrackerRow, WeaponTrackerMetric
from infra.localization_catalogs import create_translator
from projections.obs_localization import browser_localization
from projections.in_game_html import (build_stats_overlay_html,
    build_weapon_tracker_overlay_html, build_kps_overlay_html_from_values)
from ui import i18n, formatting
from ui.dialogs import SettingsDialog
from ui.localization import localization


@pytest.mark.parametrize("ui_code,game_code", list(product(SUPPORTED_LANGUAGES, repeat=2)))
def test_all_language_combinations_use_independent_catalogs(ui_code, game_code):
    translator = create_translator(language=ui_code, game_language=game_code)
    ui_reference = create_translator(language=ui_code)
    game_reference = create_translator(language=game_code)
    assert translator.text("common.settings") == ui_reference.text("common.settings")
    assert translator.cache_key == (ui_code, game_code)
    for category, name in (("items", "Anvil"), ("stats", "Damage"),
                           ("weapons", "Fire Staff"), ("powerups", "Rage")):
        assert translator.game_name(category, name) == game_reference.game_name(category, name)
    catalog = browser_localization(translator)
    assert catalog["language"] == ui_code and catalog["game_language"] == game_code
    assert catalog["messages"]["Weapon Tracker"] == browser_localization(ui_reference)["messages"]["Weapon Tracker"]
    assert catalog["game"]["stats"]["DMG"] == (
        "DMG" if game_code == "en" else game_reference.game_name("stats", "Damage"))


def test_follow_interface_invalid_preferences_and_atomic_catalog_failure():
    assert normalize_game_language(None) == "en"
    assert normalize_game_language("invalid") == "en"
    assert normalize_game_language(FOLLOW_INTERFACE_LANGUAGE) == FOLLOW_INTERFACE_LANGUAGE
    assert create_translator(language="fr", game_language="invalid").game_language == "en"
    translator = create_translator(language="fr", game_language=FOLLOW_INTERFACE_LANGUAGE)
    assert translator.game_language == "fr"
    translator.set_language("de")
    assert translator.game_language == "de"
    translator.set_game_language("en")
    translator.set_language("ru")
    assert translator.game_language == "en"
    translator.game_name("items", "Anvil")  # Establish a game-catalog consumer.
    with patch.object(translator, "_load_game", side_effect=OSError("broken asset")):
        with pytest.raises(OSError):
            translator.set_languages("pt", "es")
    assert translator.cache_key == ("ru", "en")
    translator.set_game_language(FOLLOW_INTERFACE_LANGUAGE)
    assert translator.game_language == "ru"


@pytest.fixture
def mixed_settings():
    qt = QApplication.instance() or QApplication([])
    service = localization()
    with patch.object(config, "user_config", deepcopy(config.user_config)):
        config.user_config[LANGUAGE_CONFIG_KEY] = "fr"
        config.user_config[GAME_LANGUAGE_CONFIG_KEY] = "en"
        service.apply_saved_language()
        game_value = config.reset_hold_duration_to_game_value(config.RESET_HOLD_DURATION,
            safety_margin=config.RESET_HOLD_SAFETY_MARGIN)
        with patch.object(config, "read_game_quick_reset_time",
            return_value=config.GameConfigReadResult(True, value=game_value)):
            parent = QWidget()
            dialog = SettingsDialog(parent, master=NS())
            yield qt, service, dialog
            dialog.deleteLater()
            parent.deleteLater()
            qt.processEvents()
    service.apply_saved_language()


def test_general_settings_save_both_choices_and_update_existing_game_captions(mixed_settings):
    qt, service, dialog = mixed_settings
    assert dialog.settings_tabs.currentWidget() is dialog.general_settings_page
    assert dialog.general_settings_page.isAncestorOf(dialog.language_selector)
    assert dialog.general_settings_page.isAncestorOf(dialog.game_language_selector)
    assert dialog.game_language_selector.currentData() == "en"
    assert [dialog.game_language_selector.itemData(i) for i in range(8)] == [FOLLOW_INTERFACE_LANGUAGE, *SUPPORTED_LANGUAGES]
    item = i18n.localized(QLabel, i18n.game("items", "Anvil"), dialog)
    stat = i18n.localized(QLabel, i18n.stat("DMG"), dialog)
    # Retained formatted strings need a game-locale cache key, too.
    formatted = formatting.format_items_rich_text(("Anvil",))
    item_html = i18n.localized(QLabel, formatted, dialog)
    assert item.text() == "Anvil" and stat.text() == "DMG"
    before = deepcopy(config.user_config)
    for code in SUPPORTED_LANGUAGES:
        dialog.game_language_selector.setCurrentIndex(dialog.game_language_selector.findData(code))
        with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(True)) as save:
            assert dialog.save(close_dialog=False)
        assert save.call_args.args[0][LANGUAGE_CONFIG_KEY] == "fr"
        assert save.call_args.args[0][GAME_LANGUAGE_CONFIG_KEY] == code
        assert service.translator.cache_key == ("fr", code)
        assert dialog.windowTitle() == create_translator(language="fr").text("common.settings")
        assert item.text() == service.translator.game_name("items", "Anvil")
        assert stat.text() == ("DMG" if code == "en" else service.translator.game_name("stats", "Damage"))
        assert item.text() in item_html.text()
        dialog.reload_from_config()
        assert dialog.game_language_selector.currentData() == code
    for key in ("TEMPLATES", "BUILD_PROGRESSIONS", "TWITCH_BOT"):
        assert config.user_config.get(key) == before.get(key)
    dialog.game_language_selector.setCurrentIndex(0)
    with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(True)):
        assert dialog.save(close_dialog=False)
    assert config.user_config[GAME_LANGUAGE_CONFIG_KEY] == FOLLOW_INTERFACE_LANGUAGE
    assert service.translator.game_language == "fr"
    dialog.language_selector.setCurrentIndex(dialog.language_selector.findData("de"))
    with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(True)):
        assert dialog.save(close_dialog=False)
    assert service.translator.cache_key == ("de", "de")
    assert item.text() == service.translator.game_name("items", "Anvil")


def test_cancel_and_failed_game_only_save_keep_active_pair_and_preserve_draft(mixed_settings):
    qt, service, dialog = mixed_settings
    selector = dialog.game_language_selector
    selector.setCurrentIndex(selector.findData("ru"))
    assert dialog._general_settings_dirty
    assert service.translator.cache_key == ("fr", "en")
    dialog.reject()
    dialog.reload_from_config()
    assert selector.currentData() == "en"
    selector.setCurrentIndex(selector.findData("de"))
    with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(False, "read only")), \
         patch.object(SettingsDialog, "_show_game_reset_notice"):
        assert not dialog.save(close_dialog=False)
    assert service.translator.cache_key == ("fr", "en")
    assert config.user_config[GAME_LANGUAGE_CONFIG_KEY] == "en"
    assert selector.currentData() == "de"


@pytest.mark.parametrize("saved_value", [None, "invalid"])
def test_default_game_language_stays_english_when_only_interface_changes(mixed_settings, saved_value):
    qt, service, dialog = mixed_settings
    if saved_value is None:
        config.user_config.pop(GAME_LANGUAGE_CONFIG_KEY)
    else:
        config.user_config[GAME_LANGUAGE_CONFIG_KEY] = saved_value
    before = deepcopy(config.user_config)
    service.apply_saved_language()
    dialog.reload_from_config()
    assert config.user_config == before  # Reading an old profile does not migrate/write it.
    assert create_localization_translator().cache_key == ("fr", "en")
    assert dialog.game_language_selector.currentData() == "en"
    assert dialog.game_language_selector.findData(FOLLOW_INTERFACE_LANGUAGE) >= 0
    caption = i18n.localized(QLabel, i18n.stat("DMG"), dialog)
    for code in SUPPORTED_LANGUAGES:
        dialog.language_selector.setCurrentIndex(dialog.language_selector.findData(code))
        with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(True)):
            assert dialog.save(close_dialog=False)
        assert service.translator.cache_key == (code, "en")
        assert config.user_config[GAME_LANGUAGE_CONFIG_KEY] == "en"
        assert caption.text() == "DMG"
        assert service.translator.game_name("items", "Anvil") == "Anvil"
        assert browser_localization(service.translator)["game"]["stats"]["DMG"] == "DMG"


@pytest.mark.parametrize("ui_code,game_code", [("fr","en"),("en","de"),("ru","fr")])
def test_native_overlays_use_game_names_and_keep_instructions_in_ui_language(ui_code, game_code):
    translator = create_translator(language=ui_code, game_language=game_code)
    snapshot = NS(stats={"Damage":NS(value=1.5,display_value="150%")})
    pristine = deepcopy(snapshot)
    markup = build_stats_overlay_html(snapshot,["Damage"],0,0,600,False,translator=translator)
    caption = "DMG" if game_code == "en" else translator.game_name("stats","Damage")
    assert caption + ":" in markup and "150%" in markup
    rows=(WeaponTrackerRow(1,"Fire Staff",3,(WeaponTrackerMetric("damage",12,"DMG",120),)),)
    weapon = build_weapon_tracker_overlay_html(rows,translator=translator)
    name = "Fire Staff" if game_code == "en" else translator.game_name("weapons","Fire Staff")
    assert name in weapon and caption in weapon
    kps = build_kps_overlay_html_from_values({"run_avg":12},["run"],translator=translator)
    ui_reference = create_translator(language=ui_code)
    expected = build_kps_overlay_html_from_values({"run_avg":12},["run"],translator=ui_reference)
    assert kps == expected
    assert snapshot == pristine
