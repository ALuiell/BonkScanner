from __future__ import annotations

import re

try:
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextEdit, QVBoxLayout
except Exception:
    QDialog = None
    QDialogButtonBox = None
    QLabel = None
    QPushButton = None
    QTextEdit = None
    QVBoxLayout = None


def show_update_dialog(parent, latest_version: str, release_notes: str) -> bool | None:
    if QDialog is None:
        print(f"Update available: v{latest_version}")
        print(release_notes)
        return None

    dialog = QDialog(parent)
    dialog.setWindowTitle("Update Available")
    dialog.resize(560, 420)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"A new version (v{latest_version}) is available!"))

    notes = QTextEdit()
    notes.setReadOnly(True)
    _set_release_notes_content(notes, release_notes)
    layout.addWidget(notes, 1)

    layout.addWidget(QLabel("Would you like to download and install it now?"))

    buttons = QDialogButtonBox()
    yes_btn = QPushButton("Yes, Update")
    skip_btn = QPushButton("Skip for now")
    buttons.addButton(yes_btn, QDialogButtonBox.AcceptRole)
    buttons.addButton(skip_btn, QDialogButtonBox.RejectRole)
    accepted = {"value": None}

    def on_yes():
        accepted["value"] = True
        dialog.accept()

    def on_skip():
        accepted["value"] = False
        dialog.reject()

    yes_btn.clicked.connect(on_yes)
    skip_btn.clicked.connect(on_skip)
    layout.addWidget(buttons)
    dialog.exec()
    return accepted["value"]


def _set_release_notes_content(notes: QTextEdit, release_notes: str) -> None:
    if _looks_like_html(release_notes):
        set_html = getattr(notes, "setHtml", None)
        if callable(set_html):
            try:
                set_html(release_notes)
                return
            except Exception:
                pass

    set_markdown = getattr(notes, "setMarkdown", None)
    if callable(set_markdown):
        try:
            set_markdown(release_notes)
            return
        except Exception:
            pass

    notes.setPlainText(release_notes)


def _looks_like_html(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r"<[A-Za-z][^>]*>", text) is not None
