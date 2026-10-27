"""Render production response cards and exercise their existing save/reset paths."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QScrollArea, QLabel
from PySide6.QtGui import QFont, QFontDatabase
from app import config
from app.config_repository import ConfigRepository
from ui.dialogs import TwitchCommandSettingsDialog
from ui.styles import build_qt_app_stylesheet

app = QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet((ROOT / 'src/media/checkmark.svg').as_posix()))
output = Path(__file__).parent
with TemporaryDirectory() as temp:
    repo = ConfigRepository(Path(temp) / 'config.json')
    with patch.multiple(config, TWITCH_BOT=config.normalize_twitch_bot_config({}),
                        user_config={}, _repository=repo, config_path=str(repo.path)):
        parent = QWidget()
        dialog = TwitchCommandSettingsDialog(parent)
        original = deepcopy(config.TWITCH_BOT)
        page = dialog.tabs.widget(0)
        cards = page.findChildren(QFrame, 'card')
        assert len(cards) == 13, len(cards)
        keys = [key for key, entry in dialog.templates_entries.items() if page.isAncestorOf(entry)]
        assert len(keys) == 13
        weapon_card = dialog.templates_entries['weapons'].parentWidget()
        assert weapon_card.isAncestorOf(dialog.weapons_include_globals_cb)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / 'response-templates.png'))
        scroll = page.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        for card in cards:
            assert card.width() <= scroll.viewport().width()
            for label in card.findChildren(QLabel):
                assert label.geometry().right() < card.width()
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        dialog.grab().save(str(output / 'response-templates-bottom.png'))
        for key in keys:
            dialog.templates_entries[key].setText('Edited ' + key + ': {value}')
        dialog.weapons_include_globals_cb.setChecked(True)
        dialog.reject()
        assert config.TWITCH_BOT == original
        assert not repo.path.exists()

        dialog = TwitchCommandSettingsDialog(parent)
        for key in keys:
            dialog.templates_entries[key].setText('Edited ' + key + ': {value}')
        dialog.weapons_include_globals_cb.setChecked(True)
        dialog.save()
        saved = repo.load().snapshot['TWITCH_BOT']
        for key in keys:
            assert saved['templates'][key] == 'Edited ' + key + ': {value}'
        assert saved['weapons_include_globals'] is True

        dialog = TwitchCommandSettingsDialog(parent)
        for key in keys:
            assert dialog.templates_entries[key].text() == saved['templates'][key]
        dialog.reset_to_defaults()
        for key in keys:
            assert dialog.templates_entries[key].text() == config.DEFAULT_TWITCH_BOT['templates'].get(key, '')
        assert not dialog.weapons_include_globals_cb.isChecked()
        dialog.save()
        assert not repo.load().snapshot['TWITCH_BOT']['weapons_include_globals']
        dialog.close()
        parent.close()
print('13 cards: bounds, grouping, cancel, save, reload and reset OK; config isolated')
