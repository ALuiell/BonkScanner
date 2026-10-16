"""BonkScanner layout adapter. Only this module discovers application internals."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QFrame, QTextEdit

from ui.themes.contracts import HeaderArea, TemplateArea, ThemeHost


def build_theme_host(owner) -> ThemeHost:
    window = owner.window
    header = window.findChild(QFrame, "headerBar")
    status = header.findChild(QFrame, "headerStatusCluster") if header is not None else None
    # The cluster is a QWidget in lightweight layouts and UI fixtures.
    if header is not None and status is None:
        from PySide6.QtWidgets import QWidget
        status = header.findChild(QWidget, "headerStatusCluster")
    record = getattr(owner, "rec_flag", None)
    left_tabs = getattr(owner, "left_tabview", None)
    right_tabs = getattr(owner, "tabview", None)
    panel = getattr(owner, "_templates_panel", None)
    add_button = getattr(panel, "add_btn", None)
    log_box = getattr(owner, "log_box", None)
    editor = log_box.findChild(QTextEdit) if log_box is not None else None

    header_area = None
    if header is not None and status is not None and record is not None:
        def content_span():
            return status.geometry().right() + 16, record.geometry().left()

        def light_left(surface):
            return status.mapTo(surface, QPoint(status.width(), 0)).x() + 8

        header_area = HeaderArea(header, content_span, light_left)

    templates = None
    if left_tabs is not None and add_button is not None:
        def available_rect():
            if not left_tabs.isVisible() or left_tabs.currentIndex() != 0:
                return None
            page = left_tabs.currentWidget()
            if page is None:
                return None
            bottom = add_button.mapTo(left_tabs, add_button.rect().topLeft()).y() - 6
            rows = page.findChildren(QFrame, "TemplateRow")
            row_bottom = max((row.mapTo(left_tabs, row.rect().bottomLeft()).y()
                              for row in rows if row.isVisible()), default=0)
            top = row_bottom + 14
            return QRect(2, top, left_tabs.width(), max(0, bottom - top))

        templates = TemplateArea(left_tabs, available_rect)

    signals = []
    if left_tabs is not None:
        signals.append(left_tabs.currentChanged)
    if editor is not None:
        signals.extend((editor.document().contentsChanged, editor.verticalScrollBar().valueChanged))
    widgets = tuple(widget for widget in (window, header, left_tabs, right_tabs, editor)
                    if widget is not None)
    return ThemeHost(
        window=window, header=header_area,
        logo=getattr(owner, "logo_label", None),
        premium_badge=getattr(owner, "premium_access_badge", None),
        corner_tabs=right_tabs, templates=templates, log_view=editor,
        layout_widgets=widgets, layout_signals=tuple(signals),
    )
