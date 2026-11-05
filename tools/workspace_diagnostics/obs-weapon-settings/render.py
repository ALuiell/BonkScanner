
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
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QTabWidget

from test_gui_run_control import build_overlay_test_component
from ui.styles import build_qt_app_stylesheet


app = QApplication.instance() or QApplication([])
root = REPO_ROOT
for name in ("segoeui.ttf", "segoeuib.ttf"):
    QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{name}")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(
    build_qt_app_stylesheet((root / "src/media/checkmark.svg").as_posix())
)
overlay = build_overlay_test_component()
overlay.build()


def capture(dialog):
    tabs = dialog.findChild(QTabWidget, "subTabs")
    tabs.setCurrentIndex(1)
    dialog.show()
    for _ in range(5):
        app.processEvents()
    group = next(
        child
        for child in dialog.findChildren(QGroupBox)
        if child.title() == "Weapon Tracker"
    )
    group.grab().save(str(output_directory("obs-weapon-settings") / "weapon-tracker-sections.png"))
    dialog.grab().save(str(output_directory("obs-weapon-settings") / "widget-settings-dialog.png"))
    return QDialog.Accepted


with patch.object(QDialog, "exec", capture):
    overlay.open_overlay_widget_settings_dialog()

overlay.overlay_preview_timer.stop()
overlay.tab_overlay.deleteLater()
