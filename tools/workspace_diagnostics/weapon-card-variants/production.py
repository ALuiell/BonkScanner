"""Verify the selected layout using the production Live Stats card and theme."""

# Resolve this checkout and keep diagnostic output separate from source/evidence.
import sys as _diag_sys
from pathlib import Path as _DiagPath
for _diag_parent in _DiagPath(__file__).resolve().parents:
    if (_diag_parent / "workspace_paths.py").is_file():
        _diag_sys.path.insert(0, str(_diag_parent))
        break
from workspace_paths import (REPO_ROOT, CODE_ROOT, output_path, output_directory,
                             session_directory, local_asset_path, stage_recording_fixtures)
_diag_sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "src"), str(REPO_ROOT / "src/tests")]
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = REPO_ROOT
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QFont, QFontDatabase
from core.stats.types import WeaponSnapshot, WeaponStatValue, WEAPON_STAT_SPECS
from ui.styles import build_qt_app_stylesheet
from ui.tabs.player_stats.stat_cards import StatCardsView

app = QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet((ROOT/'src/media/checkmark.svg').as_posix()))

def weapon(wid, name, data, duration=-1):
    stats = {sid: WeaponStatValue(sid, WEAPON_STAT_SPECS[sid].label, value,
                                 WEAPON_STAT_SPECS[sid].value_format) for sid, value in data.items()}
    return WeaponSnapshot(wid, name, 40, tuple(stats), stats, stats, duration, -1)

weapons = (
    weapon(5, 'Axe', {9:4.3, 12:45.6, 16:28.8, 10:2.57}, 8),
    weapon(23, 'Katana', {9:4.72, 12:68.2, 16:21.8, 18:2.51, 19:3.24}, .5),
    weapon(26, 'Dice', {11:5.2, 12:33.6, 16:22, 9:4.09, 18:2.16, 19:1.36}, 5),
)
globals_ = {'Size':1.766, 'Damage':3.197, 'Projectile Count':7, 'Duration':1.482,
            'Crit Chance':.831, 'Crit Damage':1.205, 'Attack Speed':2}
page = QWidget()
layout = QVBoxLayout(page)
status = QLabel(page)
view = StatCardsView(weapons_layout=layout, weapons_status_label=status, tomes_layout=None,
                    tomes_status_label=None, chaos_layout=None, chaos_status_label=None,
                    damage_sources_layout=None, damage_sources_status_label=None)
view.display_weapons(weapons, general_stats=globals_)
for width in (1100, 760, 620, 520):
    page.resize(width, 900)
    page.show()
    for _ in range(3):
        app.processEvents()
    grid = view._weapon_grid
    grid.grab().save(str(output_directory("weapon-card-variants")/f'selected-{width}.png'))
    for card in view._weapon_cards:
        for row in [card._weapon_heading, *card._row_widgets]:
            for label in row.findChildren(QLabel):
                if label.text():
                    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text()), (width, label.text(), label.width())
        raw_positions = {row._weapon_value_label.mapTo(card, row._weapon_value_label.rect().topLeft()).x()
                         for row in [card._weapon_heading, *card._row_widgets]}
        assert len(raw_positions) == 1, raw_positions
    print(width, 'px:', grid._columns, 'columns; label bounds and value alignment OK')
# Missing data, cache reuse and return to the historical view.
cards = tuple(view._weapon_cards)
view.display_weapons(weapons, general_stats={})
assert tuple(view._weapon_cards) == cards
assert all(row._value_label.text() == '—' for card in cards for row in card._row_widgets)
view.display_weapons(weapons)
assert all(card._weapon_heading.isHidden() for card in cards)
view.display_weapons(weapons, general_stats=globals_)
assert all(not card._weapon_heading.isHidden() for card in cards)
page.close()
