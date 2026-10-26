"""Keep one QApplication alive across mixed unittest and pytest-qt tests."""
from __future__ import annotations

import os
import pytest
from PySide6.QtCore import QCoreApplication, QEvent

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _session_qapplication(qapp):
    """Give manual QApplication.instance() users pytest-qt's session owner."""
    return qapp


@pytest.fixture(autouse=True)
def _finish_deferred_qt_cleanup(_session_qapplication):
    """Release per-test windows and pending deletes before the next event loop.

    Plain unittest GUI cases do not register their windows with qtbot. Leaving
    those windows alive leaked layout callbacks into later tests and made
    global stylesheet changes repeatedly polish every earlier dialog.
    """
    existing = set(_session_qapplication.topLevelWidgets())
    yield
    for widget in _session_qapplication.topLevelWidgets():
        if widget not in existing:
            widget.hide()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
