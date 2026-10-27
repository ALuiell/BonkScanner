"""Two deterministic Qt layout trials using the app's card theme."""

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
ROOT = REPO_ROOT
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout
from ui.styles import build_qt_app_stylesheet

DATA = (
    ('Axe', [('Size', '×4.3', '×7.59'), ('Damage', '45.6', '145.78'),
             ('Projectiles', '28.8', '35'), ('Duration', '2.57s', '3.81s')]),
    ('Katana', [('Size', '×4.72', '×8.33'), ('Damage', '68.2', '218.04'),
                ('Projectiles', '21.8', '28'), ('Crit Chance', '251%', '334.1%'),
                ('Crit Damage', '×3.24', '×8.89')]),
    ('Dice', [('Speed', '×5.2', None), ('Damage', '33.6', '107.42'),
              ('Projectiles', '22', '29'), ('Size', '×4.09', '×7.22'),
              ('Crit Chance', '216%', '299.1%'), ('Crit Damage', '×1.36', '×5.13')]),
)

app = QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet((ROOT/'src/media/checkmark.svg').as_posix()))

def label(text, parent, color, size=13, bold=False):
    result = QLabel(text, parent)
    result.setStyleSheet(f'color:{color}; font-size:{size}px; font-weight:{700 if bold else 400}; background:transparent;')
    return result

for variant in ('slash', 'columns'):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    if variant == 'slash':
        layout.addWidget(label('Weapon / With globals', page, '#98A7BA', 12))
    grid = QGridLayout()
    grid.setSpacing(8)
    layout.addLayout(grid)
    for i, (name, stats) in enumerate(DATA):
        card = QFrame(page)
        card.setObjectName('StatCard')
        body = QVBoxLayout(card)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(label(name, card, '#F3F4F6', 15, True), 1)
        heading.addWidget(label('Lv. 40', card, '#98A7BA', 12, True))
        body.addLayout(heading)
        rows = QGridLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setHorizontalSpacing(8)
        rows.setVerticalSpacing(6)
        rows.setColumnStretch(0, 1)
        body.addLayout(rows)
        if variant == 'columns':
            for col, text in ((1, 'Weapon'), (3, 'Total')):
                item = label(text, card, '#98A7BA', 11)
                item.setAlignment(Qt.AlignRight)
                rows.addWidget(item, 0, col)
        for j, (stat, raw, total) in enumerate(stats, 1):
            rows.addWidget(label(stat, card, '#B5C0CE', 13), j, 0)
            if variant == 'columns':
                for col, text, color, size, bold in (
                    (1, raw, '#98A7BA', 13, False),
                    (2, '/', '#64748B', 12, False),
                    (3, total if total is not None else '—', '#F3F4F6' if total else '#64748B', 14, total is not None),
                ):
                    item = label(text, card, color, size, bold)
                    item.setAlignment(Qt.AlignRight)
                    rows.addWidget(item, j, col)
            else:
                content = f'<span style="color:#98A7BA;font-size:13px;">{raw}</span>'
                if total is not None:
                    content += f' <span style="color:#64748B;">/</span> <b style="color:#F3F4F6;">{total}</b>'
                item = QLabel(content, card)
                item.setAlignment(Qt.AlignRight)
                rows.addWidget(item, j, 1)
        body.addStretch(1)
        grid.addWidget(card, i // 2, i % 2)
    layout.addStretch(1)
    for width in (1100, 620):
        page.resize(width, 530)
        page.show()
        app.processEvents()
        page.grab().save(str(output_directory("weapon-card-variants")/f'{variant}-{width}.png'))
    page.close()
print('Rendered both variants at 1100 and 620 px')
