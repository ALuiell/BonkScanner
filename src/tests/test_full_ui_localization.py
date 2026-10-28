"""Language switching must preserve every editable value and action identity."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
import src
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QTabWidget, QWidget, QTableWidget, QDialogButtonBox

from app import config
from core.localization import LANGUAGE_CONFIG_KEY, GAME_LANGUAGE_CONFIG_KEY, FOLLOW_INTERFACE_LANGUAGE, SUPPORTED_LANGUAGES
from core.localization_context import text, using_translator
from infra.localization_catalogs import create_translator
from ui import i18n
from ui.localization import localization


@pytest.fixture
def language_ui():
    qt = QApplication.instance() or QApplication([])
    with patch.object(config, "user_config", deepcopy(config.user_config)):
        service = localization()
        config.user_config[LANGUAGE_CONFIG_KEY] = "en"
        config.user_config[GAME_LANGUAGE_CONFIG_KEY] = FOLLOW_INTERFACE_LANGUAGE
        service.apply_saved_language()
        yield qt, service
        config.user_config[LANGUAGE_CONFIG_KEY] = "en"
        service.apply_saved_language()


def switch(code, service):
    config.user_config[LANGUAGE_CONFIG_KEY] = code
    service.apply_saved_language()


def test_switch_relabels_controls_without_editing_or_emitting_changes(language_ui):
    qt, service = language_ui
    combo = QComboBox()
    i18n.combo_item(combo, i18n.tr("Compact"), "compact")
    i18n.combo_item(combo, i18n.tr("Detailed"), "detailed")
    changed, no_argument = [], []
    i18n.connect_combo_value(combo, changed.append)
    i18n.connect_combo_value(combo, lambda: no_argument.append(True))
    field = QLineEdit("My {build} / Мой білд")
    i18n.display(field, "setPlaceholderText", i18n.tr("Build name"))
    label = i18n.localized(QLabel, i18n.tr("Configure {p0}", p0=field.text()))
    with patch.object(config, "save_config") as save:
        for code in SUPPORTED_LANGUAGES:
            switch(code, service)
            assert combo.currentData() == "compact"
            assert i18n.combo_value(combo) == "Compact"
            assert combo.itemText(0) == str(i18n.tr("Compact"))
            assert combo.itemText(1) == str(i18n.tr("Detailed"))
            assert field.text() == "My {build} / Мой білд"
            assert field.text() in label.text()
        save.assert_not_called()
    assert changed == no_argument == []
    combo.setCurrentIndex(1)
    assert changed == ["Detailed"] and no_argument == [True]
    for widget in (combo, field, label):
        widget.deleteLater()
    qt.processEvents()


def test_translated_tabs_route_by_identity_and_items_do_not_gain_user_data(language_ui):
    qt, service = language_ui
    tabs, combo = QTabWidget(), QComboBox()
    page = QWidget()
    i18n.tab(tabs, page, i18n.tr("Recordings"))
    i18n.combo_item(combo, i18n.tr("Copy"))
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        assert i18n.tab_identity(tabs, 0) == "Recordings"
        assert tabs.widget(0) is page
        assert combo.currentData() is None
        assert i18n.combo_value(combo) == "Copy"
    tabs.deleteLater()
    combo.deleteLater()
    qt.processEvents()


def test_table_headers_and_projection_provenance_retranslate_in_place(language_ui):
    qt, service = language_ui
    table = QTableWidget(0, 1)
    with using_translator(create_translator(language="en")):
        caption = text("Stats")
    label = i18n.localized(QLabel, caption)
    i18n.table_headers(table, [i18n.tr("Items")])
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        assert label.text() == str(i18n.tr("Stats"))
        assert table.horizontalHeaderItem(0).text() == str(i18n.tr("Items"))
    label.deleteLater()
    table.deleteLater()
    qt.processEvents()


def test_native_standard_buttons_follow_the_selected_language(language_ui):
    qt, service = language_ui
    buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        qt.processEvents()
        assert buttons.button(QDialogButtonBox.Cancel).text().replace("&", "") == service.text("common.cancel")
    buttons.deleteLater()
    qt.processEvents()


def test_game_titles_in_a_populated_comparison_retranslate_without_model_changes(language_ui):
    from projections import formatting as canonical_formatting
    from ui import formatting
    from ui.metric_table import MetricSectionView
    qt, service = language_ui
    stat_a = NS(value=15.0, display_value="15", label="Damage")
    stat_b = NS(value=10.0, display_value="10", label="Damage")
    weapon_a = NS(name="Fire Staff", level=3, upgraded_stats={12: stat_a})
    weapon_b = NS(name="Fire Staff", level=2, upgraded_stats={12: stat_b})
    a, b = NS(weapons=(weapon_a,)), NS(weapons=(weapon_b,))
    before = deepcopy((a, b))
    section = formatting.build_compare_runs_weapons_table(a, b).sections[0]
    view = MetricSectionView()
    view.set_section(section)
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        assert view._title_label.text() == service.translator.game_name("weapons", "Fire Staff")
        assert service.translator.game_name("stats", "Damage") in [cells[0].text() for cells in view._rows]
        assert (a, b) == before
        # Locale state is scoped to UI projection calls, never process-wide.
        assert canonical_formatting.build_compare_runs_weapons_table(a, b).sections[0].title == "Fire Staff"
    view.deleteLater()
    qt.processEvents()


def test_renamed_and_custom_templates_remain_user_text(language_ui):
    qt, service = language_ui
    original = deepcopy(config.DEFAULT_TEMPLATES[0])
    renamed = dict(original, name="My {Light} / Save")
    custom = dict(original, id=999999, name="Light")
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        assert i18n.template_name(renamed) == renamed["name"]
        assert i18n.template_name(custom) == custom["name"]
        assert renamed["name"] == "My {Light} / Save"


def test_collapsed_rail_translates_captions_and_keeps_action_names(language_ui):
    from ui.layout import _build_collapsed_rail, _rebuild_rail_dots
    qt, service = language_ui
    builtin = deepcopy(config.DEFAULT_TEMPLATES[0])
    custom = dict(builtin, id=999999, name="My {build}")
    calls = []
    panel = NS(set_template_active=lambda name, checked: calls.append((name, checked)),
               rail_tier_entries=lambda: [("Light", "#ffffff", False)],
               set_tier_active=lambda name, checked: calls.append((name, checked)))
    with patch.object(config, "TEMPLATES", [builtin, custom]), patch.object(
        config, "ACTIVE_TEMPLATES", []
    ), patch.object(config, "EVALUATION_MODE", "templates"):
        rail = _build_collapsed_rail(NS(_templates_panel=panel))
        _rebuild_rail_dots(rail, NS(_templates_panel=panel))
        first, second = rail._dots_holder.tiles()
        for code in SUPPORTED_LANGUAGES:
            switch(code, service)
            assert rail._eyebrow.text() == str(i18n.tr("TEMPLATES"))
            assert first.toolTip().startswith(str(i18n.template_name(builtin)) + "\n")
            assert second.toolTip().startswith("My {build}\n")
        first.click()
        assert calls == [(builtin["name"], True)]
        config.EVALUATION_MODE = "scores"
        _rebuild_rail_dots(rail, NS(_templates_panel=panel))
        score_tile = rail._dots_layout.itemAt(0).widget()
        for code in SUPPORTED_LANGUAGES:
            switch(code, service)
            assert rail._eyebrow.text() == str(i18n.tr("Scores")).upper()
            assert score_tile.toolTip() == str(i18n.preset_name("Light"))
        score_tile.click()
        assert calls[-1] == ("Light", True)
        rail.deleteLater()
        qt.processEvents()


def test_timeline_names_and_powerup_details_follow_language_without_changing_history(language_ui):
    from PySide6.QtCore import QRectF
    from core.powerup_history import PowerupHistory, PowerupObservation, RecordedEffect
    from projections.powerup_history import PowerupProjection
    from projections.scrubber import Marker
    from ui.powerup_timeline import PowerupTimelineRow
    from ui.timeline_visuals import build_marker_glyphs, stage_caption
    from ui.tabs.compare_runs.timeline_legend import _SeriesLegendItem
    qt, service = language_ui
    history = PowerupHistory(tuple(PowerupObservation(i, i, i, "run", True,
        (RecordedEffect(1, 0, 5),)) for i in range(4)))
    before = deepcopy(history)
    projection = PowerupProjection(history)
    row = PowerupTimelineRow()
    row.set_state(projection, 3, axis_a=3)
    legend = _SeriesLegendItem()
    legend.set_key("Damage")
    marker = Marker(0, "banish", "#ffffff", "Banish: Anvil", item_name="Anvil")
    glyph = build_marker_glyphs((marker,), (0.0,), QRectF(0, 0, 100, 30))[0]
    for code in SUPPORTED_LANGUAGES:
        switch(code, service)
        assert service.translator.game_name("items", "Anvil") in str(glyph.tooltip)
        assert row.entries[0][4].startswith(service.translator.game_name("powerups", "Rage"))
        assert legend._name.text() == ("DMG" if code == "en" else service.translator.game_name("stats", "Damage"))
        assert "2" in stage_caption(NS(stage_index=1, label="Stage 2"))
        assert history == before
        assert marker.text == "Banish: Anvil"
    row.deleteLater()
    legend.deleteLater()
    qt.processEvents()
