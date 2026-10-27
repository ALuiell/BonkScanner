
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
import json
import sys
from pathlib import Path
root = REPO_ROOT
sys.path[:0] = [str(root), str(root / 'src'), str(root / 'src/tests')]
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from core.stats.weapon_tracker import calculate_weapon_tracker_rows, WEAPON_TRACKER_METRIC_ORDER
from projections.obs import weapon_tracker_payload
from projections.in_game_html import build_weapon_tracker_overlay_html
from test_weapon_tracker_projection import _weapon, _globals
from types import SimpleNamespace
from ui.styles import build_qt_app_stylesheet
from ui.tabs.player_stats.stat_cards import StatCardsView
app = QApplication([])
for filename in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + filename)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet(str(root / 'src/media/checkmark.svg')))
weapons = (_weapon(values={9: 2, 12: 50, 16: 25, 18: .2, 19: .5}),
           _weapon(weapon_id=29, name='Shotgun', values={9: 1.5, 12: 30, 16: 19, 18: .1, 19: 0}))
stats = _globals(**{'Attack Speed': 2})
window = QWidget()
layout = QVBoxLayout(window)
status = QLabel(window)
view = StatCardsView(weapons_layout=layout, weapons_status_label=status,
                    tomes_layout=None, tomes_status_label=None, chaos_layout=None,
                    chaos_status_label=None, damage_sources_layout=None, damage_sources_status_label=None)
view.display_weapons(weapons, general_stats=stats)
window.resize(760, 460)
window.show()
app.processEvents()
window.grab().save(str(output_path('weapon-live-qa.png')))
native = QLabel()
native.setStyleSheet('background:#121820; padding:12px; font-size:14px')
native.setText(build_weapon_tracker_overlay_html(calculate_weapon_tracker_rows(weapons, stats, WEAPON_TRACKER_METRIC_ORDER), show_caps=True))
native.resize(native.sizeHint())
native.grab().save(str(output_path('weapon-native-qa.png')))
state = {'status': 'live', 'widgets': {'weapon_tracker': {
    'id': 'weapon_tracker', 'enabled': True, 'order': 1, 'show_caps': True,
    'layout': 'compact', 'selected_stats': list(WEAPON_TRACKER_METRIC_ORDER),
    'background_opacity': .4, 'show_header': True, 'show_border': True,
    'width': 800, 'x': 20, 'y': 20,
}}, 'weapon_tracker': weapon_tracker_payload(SimpleNamespace(weapons=weapons, stats=stats))}
css = (root / 'src/media/overlay/overlay.css').read_text(encoding='utf-8')
js = (root / 'src/media/overlay/overlay.js').read_text(encoding='utf-8')
html = '<!doctype html><style>' + css + '</style><body style="background:#182432"><main id="overlay"></main><script>'
html += 'const fixture = ' + json.dumps(state) + '; window.fetch = async () => ({ok:true,json:async()=>fixture});'
html += js + '</script></body>'
(output_path('weapon-obs-qa.html')).write_text(html, encoding='utf-8')
window.close()
