"""Deterministic renders of production widgets; no game, network or user config writes."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from tempfile import TemporaryDirectory

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'src/tests')]
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget, QGroupBox, QTabWidget, QScrollArea
from app import config
from app.config_repository import ConfigRepository
from core.stats.types import WeaponSnapshot, WeaponStatValue, WEAPON_STAT_SPECS
from core.stats.weapon_tracker import calculate_weapon_tracker_rows, WEAPON_TRACKER_METRIC_ORDER
from projections.obs import weapon_tracker_payload
from projections.in_game_html import build_weapon_tracker_overlay_html
from ui.styles import build_qt_app_stylesheet
from ui.tabs.player_stats.stat_cards import StatCardsView
from gui_in_game_overlay_window import DraggableOverlayWidget
from gui_in_game_overlay_settings import WeaponTrackerSettingsDialog

app = QApplication([])
for filename in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf', 'verdanab.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + filename)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet((ROOT / 'src/media/checkmark.svg').as_posix()))

def weapon(wid, name, stats, max_duration=-1, max_size=-1):
    full = {sid: WeaponStatValue(sid, WEAPON_STAT_SPECS[sid].label, value,
                                WEAPON_STAT_SPECS[sid].value_format)
            for sid, value in stats.items()}
    return WeaponSnapshot(wid, name, 15, tuple(full), full, full, max_duration, max_size)

weapons = (
    weapon(5, 'Axe', {12:120, 16:80, 9:2, 10:4, 18:.20, 19:.75}, 8, 3),
    weapon(28, 'Corrupt Sword', {12:150, 16:5, 9:1.8, 18:.15, 19:1.0}, .5, 2),
    weapon(29, 'Shotgun', {12:180, 16:25, 9:1.6, 18:.25, 19:.50}),
    weapon(25, 'Bluetooth Dagger', {12:75, 16:8, 9:1.4, 18:.25, 19:.50, 45:3}),
)
stats = {'Damage':3.5, 'Projectile Count':2, 'Size':2, 'Duration':3,
         'Crit Chance':.60, 'Crit Damage':2.5, 'Thorns':15, 'Attack Speed':8}
rows = calculate_weapon_tracker_rows(weapons, stats, WEAPON_TRACKER_METRIC_ORDER)
metrics = {}

def save(widget, name):
    widget.show()
    for _ in range(4):
        app.processEvents()
    widget.grab().save(str(OUT / (name + '.png')))
    metrics[name] = {'width':widget.width(), 'height':widget.height()}

with TemporaryDirectory() as temp:
    repo = ConfigRepository(Path(temp) / 'config.json')
    with patch.multiple(config, config_path=str(repo.path), _repository=repo,
        user_config={}, OVERLAY=config.normalize_overlay_config({}),
        IN_GAME_OVERLAY=config.normalize_in_game_overlay_config({}),
        TWITCH_BOT=config.normalize_twitch_bot_config({})):
        config.user_config.update(OVERLAY=config.OVERLAY, IN_GAME_OVERLAY=config.IN_GAME_OVERLAY,
                                  TWITCH_BOT=config.TWITCH_BOT)
        page = QWidget()
        page.setObjectName('LiveStatsPage')
        layout = QVBoxLayout(page)
        group = QGroupBox('Weapons', page)
        layout.addWidget(group)
        card_layout = QVBoxLayout(group)
        view = StatCardsView(weapons_layout=card_layout, weapons_status_label=QLabel(group),
            tomes_layout=None, tomes_status_label=None, chaos_layout=None,
            chaos_status_label=None, damage_sources_layout=None, damage_sources_status_label=None)
        view.display_weapons(weapons, general_stats=stats)
        for width in (760, 520):
            page.resize(width, 890)
            save(page, 'live-' + str(width))
            view._weapon_grid.grab().save(str(OUT / ('weapon-pairs-' + str(width) + '.png')))
            metrics['live-' + str(width)]['clipped_labels'] = [
                {'text':l.text(), 'width':l.width(), 'needed':l.minimumSizeHint().width()}
                for l in page.findChildren(QLabel) if l.isVisible() and l.width() + 1 < l.minimumSizeHint().width()]
        page.close()

        surface = QWidget()
        surface.resize(1920,1080)
        native = DraggableOverlayWidget('weapon_tracker', surface)
        native.set_edit_mode(False)
        for layout_kind in ('compact','detailed'):
            for caps in (False, True):
                native.set_text(build_weapon_tracker_overlay_html(rows, layout=layout_kind, show_caps=caps))
                native.show()
                native.adjustSize()
                save(native, f'native-{layout_kind}-{int(caps)}')
        surface.close()
        dialog = WeaponTrackerSettingsDialog(SimpleNamespace(apply_in_game_overlay_settings=MagicMock()))
        save(dialog, 'native-settings')
        dialog.close()

        from test_gui_run_control import build_overlay_test_component
        component = build_overlay_test_component()
        component.build()
        def capture_dialog(dialog):
            tabs = dialog.findChild(QTabWidget)
            tabs.setCurrentIndex(1)
            save(dialog, 'obs-settings')
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', capture_dialog):
            component.open_overlay_widget_settings_dialog()
        component.overlay_preview_timer.stop()
        component.tab_overlay.close()
        from ui.dialogs import TwitchCommandSettingsDialog
        twitch_parent = QWidget()
        twitch = TwitchCommandSettingsDialog(twitch_parent)
        check = twitch.weapons_include_globals_cb
        for tabs in twitch.findChildren(QTabWidget):
            ancestor = check.parentWidget()
            while ancestor is not None:
                if tabs.indexOf(ancestor) >= 0:
                    tabs.setCurrentWidget(ancestor)
                    break
                ancestor = ancestor.parentWidget()
        twitch.show()
        app.processEvents()
        ancestor = check.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                ancestor.ensureWidgetVisible(check, 0, 100)
                break
            ancestor = ancestor.parentWidget()
        save(twitch, 'twitch-settings')
        twitch.close()

css = (ROOT / 'src/media/overlay/overlay.css').read_text(encoding='utf-8')
js = (ROOT / 'src/media/overlay/overlay.js').read_text(encoding='utf-8')
for mode in ('compact', 'detailed'):
    for caps in (False, True):
        cfg = {'id':'weapon_tracker','enabled':True,'order':1,'show_caps':caps,'layout':mode,
               'selected_stats':list(WEAPON_TRACKER_METRIC_ORDER), 'show_header':True,
               'show_border':True,'background_opacity':.4, 'scale':1, 'width':510, 'x':10, 'y':10}
        state = {'status':'live', 'canvas_width':1040,'canvas_height':1050, 'widgets':{
            'weapon_tracker':cfg,
            'stats':{'id':'stats','enabled':True,'order':2,'x':545,'y':10,'width':450,
                     'show_header':True,'show_border':True,'background_opacity':.4}},
            'weapon_tracker':weapon_tracker_payload(SimpleNamespace(weapons=weapons,stats=stats)),
            'stats':[{'display_label':'DMG','value':'×3.5'}, {'display_label':'AS','value':'×8'},
                     {'display_label':'CRIT','value':'60%'}]}
        html = '<!doctype html><meta charset="utf-8"><style>' + css + '</style>'
        html += '<body style="background:#182432"><main id="overlay" class="overlay-shell"></main><script>'
        html += 'window.fetch=async()=>({ok:true,json:async()=>(' + json.dumps(state) + ')});'
        html += js + '</script></body>'
        (OUT / f'obs-{mode}-{int(caps)}.html').write_text(html, encoding='utf-8')
(OUT / 'visual-metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
print(json.dumps(metrics,indent=2))
