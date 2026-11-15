"""Open the guide from the scanner and route its actions to native screens."""
from functools import partial

from PySide6.QtCore import QPoint, Qt

from ui import i18n as l10n
from ui.dialogs import SettingsDialog
from ui.dialogs.shell import show_app_notice

from .guide_locale import message
from .guides import QuickGuide


def open_quick_guide(app, topic, *, owner=None, overlay_widgets) -> QuickGuide:
    owner = owner if owner is not None else app.window
    current = getattr(owner, "_quick_guide", None)
    if current is not None and current.isVisible():
        current.select(topic)
        current.raise_()
        current.activateWindow()
        return current

    dialog = QuickGuide(owner, app=app, overlay_widgets=overlay_widgets)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    if owner is not app.window:
        dialog.setWindowModality(Qt.WindowModal)
    dialog.select(topic)
    dialog.action_requested.connect(partial(_route, app, dialog, owner))
    dialog.finished.connect(lambda: setattr(owner, "_quick_guide", None))
    owner._quick_guide = dialog
    _place(dialog, owner)
    dialog.show()
    return dialog


def _place(dialog, owner) -> None:
    available = owner.screen().availableGeometry()
    dialog.resize(min(1060, available.width() - 40), min(dialog.height(), available.height() - 80))
    center = owner.frameGeometry().center()
    x = max(available.left(), min(center.x() - dialog.width() // 2, available.right() - dialog.width()))
    y = max(available.top(), min(center.y() - dialog.height() // 2, available.bottom() - dialog.height() - 28))
    dialog.move(QPoint(x, y))


def _select_tab(app, name: str) -> None:
    tabs = app.tabview
    for index in range(tabs.count()):
        if l10n.tab_identity(tabs, index) == name:
            tabs.setCurrentIndex(index)
            return


def _open_settings(app, owner, page: str) -> None:
    if owner is app.window:
        app.open_settings_dialog(page=page)
    elif isinstance(owner, SettingsDialog):
        owner.show_page(page)
    else:
        settings = SettingsDialog(owner, master=app)
        settings.setAttribute(Qt.WA_DeleteOnClose)
        settings.show_page(page)
        settings.open()


def _route(app, dialog, owner, route: str) -> None:
    category, destination = route.split(":", 1)
    try:
        if category == "obs" and not app._overlay.start_overlay_server():
            show_app_notice(dialog, title=message("guide.title"), message=message("demo.obs_error"))
            return
        dialog.accept()
        if category == "tab":
            _select_tab(app, destination)
        elif category == "obs":
            _select_tab(app, "OBS")
            app._overlay._open_overlay_layout_editor()
        elif category == "settings":
            _open_settings(app, owner, destination)
        elif category == "history":
            if destination == "roll":
                app._scanner._open_roll_analytics_dialog()
            else:
                app._scanner._open_merchant_analytics_dialog()
    except Exception as exc:
        app._log_dialog_failure("Quick Guide", exc)
