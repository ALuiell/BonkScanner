import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT/'src'), str(ROOT/'src/tests')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from app import config
from app.config_repository import ConfigRepository
from ui.styles import build_qt_app_stylesheet
from test_gui_run_control import build_in_game_overlay_test_component
from gui_in_game_overlay_settings import WeaponTrackerSettingsDialog
app = QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet((ROOT/'src/media/checkmark.svg').as_posix()))
with TemporaryDirectory() as tmp:
    repo = ConfigRepository(Path(tmp)/'config.json')
    with patch.multiple(config, _repository=repo, config_path=str(repo.path), user_config={},
                        IN_GAME_OVERLAY=config.normalize_in_game_overlay_config({})):
        overlay = build_in_game_overlay_test_component(find_game_window=lambda _name: None)
        page = overlay.build()
        overlay.igo_target_window_timer.stop()
        overlay.apply_in_game_overlay_settings = MagicMock()
        page.resize(1120, 1000)
        page.show()
        app.processEvents()
        page.grab().save(str(ROOT/'scratch/caps-checkbox-move/tab.png'))
        checkbox = overlay.igo_weapon_tracker_caps_cb
        holder = checkbox.parentWidget()
        for i in range(holder.layout().count()):
            widget = holder.layout().itemAt(i).widget()
            if widget:
                assert widget.geometry().right() < holder.width(), (widget, holder.width())
        holder.grab().save(str(ROOT/'scratch/caps-checkbox-move/options.png'))
        dialog = WeaponTrackerSettingsDialog(overlay, page)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(ROOT/'scratch/caps-checkbox-move/dialog.png'))
        print('Rendered production tab, options and dialog; row bounds OK')
        dialog.close()
        page.close()
