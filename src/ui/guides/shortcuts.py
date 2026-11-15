"""Localized buttons that open Quick Guide topics."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton

from ui.shared import resource_path

from .guide_locale import bind


def guide_button(text, tooltip, *, premium: bool = False) -> QPushButton:
    button = QPushButton()
    button.setObjectName("GuideShortcut")
    button.setAutoDefault(False)
    button.setCursor(Qt.PointingHandCursor)
    if premium:
        button.setIcon(QIcon(resource_path("media/premium_access_icon.svg")))
    for method, value in (("setText", text), ("setToolTip", tooltip), ("setAccessibleName", tooltip)):
        if callable(value):
            bind(button, value, method=method)
        else:
            getattr(button, method)(value)
    return button
