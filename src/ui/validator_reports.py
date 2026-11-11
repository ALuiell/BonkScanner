"""Compact report actions and the Validator run list."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from PySide6.QtCore import QDateTime, QLocale, QPointF, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ui import i18n as l10n


@lru_cache(maxsize=24)
def validator_icon(kind, color, size=14):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 16, size / 16)
    painter.setPen(QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == 'copy':
        painter.drawRoundedRect(QRectF(6, 5, 7.5, 8.5), 1.4, 1.4)
        path = QPainterPath(QPointF(3.5, 11))
        path.lineTo(3.5, 3.5)
        path.quadTo(3.5, 2, 5, 2)
        path.lineTo(11, 2)
        painter.drawPath(path)
    elif kind == 'open':
        painter.drawLine(QPointF(4, 12), QPointF(12, 4))
        painter.drawLine(QPointF(7, 4), QPointF(12, 4))
        painter.drawLine(QPointF(12, 4), QPointF(12, 9))
    elif kind == 'shield':
        path = QPainterPath(QPointF(8, 2))
        path.lineTo(13, 4)
        path.lineTo(13, 7)
        path.cubicTo(13, 10, 11, 12, 8, 14)
        path.cubicTo(5, 12, 3, 10, 3, 7)
        path.lineTo(3, 4)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == 'dot':
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(2, 2, 12, 12))
    painter.end()
    return QIcon(pixmap)


def report_status(report):
    return {
        'active': l10n.tr('Observing'),
        'retrying': l10n.tr('Retrying delivery'),
        'finish_pending': l10n.tr('Sending final data'),
        'finish_unconfirmed': l10n.tr('Completion is unconfirmed'),
        'finished': l10n.tr('Report ready'),
        'interrupted': l10n.tr('Interrupted'),
        'expired': l10n.tr('Observation interrupted'),
        'failed': l10n.tr('Delivery interrupted'),
    }.get(report.status, l10n.tr('Waiting'))


def _warning(report):
    return report.status in ('interrupted', 'expired', 'failed', 'finish_unconfirmed', 'retrying')


def _action(text, kind, hint, *, inline=False):
    button = l10n.localized(QPushButton, text)
    button.setObjectName('validatorInlineAction' if inline else 'validatorHistoryAction')
    button.setCursor(Qt.PointingHandCursor)
    button.setIcon(validator_icon(kind, '#A2CCED'))
    button.setIconSize(QSize(13, 13))
    l10n.display(button, 'setToolTip', hint)
    l10n.display(button, 'setAccessibleName', hint)
    if not text:
        button.setFixedWidth(28)
    return button


class ValidatorReportStrip(QFrame):
    def __init__(self, current_report, *, copy=False):
        super().__init__()
        self.setObjectName('validatorReportStrip')
        self._current_report = current_report
        self._copy = copy
        self._url = ''
        self._display = None
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 2, 4, 2)
        row.setSpacing(6)
        self._marker = QLabel()
        self._marker.setFixedSize(13, 13)
        self._marker.setAlignment(Qt.AlignCenter)
        self._status = QLabel()
        self._divider = QFrame()
        self._divider.setObjectName('validatorDivider')
        self._divider.setFixedSize(1, 13)
        self._action_hint = l10n.tr('Copy Validator report link') if copy else l10n.tr('Open Validator report')
        self.action = _action(
            l10n.tr('Copy link') if copy else l10n.tr('Report'),
            'copy' if copy else 'open',
            self._action_hint,
            inline=True,
        )
        self.action.clicked.connect(self._activate)
        for widget in (self._marker, self._status, self._divider, self.action):
            row.addWidget(widget)
        self.hide()

    def update_report(self, report, fallback=None, *, last=False):
        label = fallback if report is None else report_status(report)
        detail = label
        if report and last:
            detail = l10n.tr('Last report: {p0}', p0=label)
            if report.status == 'finished':
                label = l10n.tr('Last report')
        partial = bool(report and report.partial)
        warning = bool(report and _warning(report))
        if report and report.status == 'finished' and partial and not self._copy:
            label = l10n.tr('Partial coverage')
            detail = label
            warning = True
        url = report.url if report is not None else ''
        display = (str(label) if label is not None else '', url, partial, warning)
        if display == self._display:
            return
        self._display = display
        self._url = url
        l10n.display(self.action, 'setToolTip', self._action_hint)
        self.setVisible(label is not None)
        self.action.setVisible(bool(url))
        self._divider.setVisible(bool(url))
        if label is None:
            return
        color = '#DFB773' if warning else '#A1CCEA'
        kind = 'shield' if self._copy else 'dot'
        size = 13 if self._copy else 8
        self._marker.setPixmap(validator_icon(kind, color, size).pixmap(QSize(size, size)))
        l10n.display(self._status, 'setText', label)
        self._status.setStyleSheet(f'color: {color}; background: transparent;')
        detail = str(detail)
        if partial and detail != str(l10n.tr('Partial coverage')):
            detail = f'{detail} · {l10n.tr("Partial coverage")}'
        self.setToolTip(f'{l10n.tr("Live Validator")} · {detail}')

    def _activate(self):
        displayed = self._url
        report = self._current_report()
        if not displayed or report is None or report.url != displayed:
            return
        if self._copy:
            QApplication.clipboard().setText(displayed)
            l10n.display(self.action, 'setToolTip', l10n.tr('Link copied'))
        else:
            QDesktopServices.openUrl(QUrl(displayed))


class _RunTitle(QLabel):
    def __init__(self):
        super().__init__()
        self.setObjectName('validatorRunName')
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._title = ''

    def set_title(self, title):
        self._title = title
        self.setToolTip(title)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._title, Qt.ElideRight, self.contentsRect().width()))


def _columns(layout, cells):
    for column, (cell, stretch) in enumerate(zip(cells, (28, 11, 17, 26, 0))):
        layout.addWidget(cell, 0, column)
        layout.setColumnStretch(column, stretch)
    layout.setColumnMinimumWidth(4, 110)


class _ReportRow(QFrame):
    def __init__(self, url):
        super().__init__()
        self.setObjectName('validatorHistoryRow')
        self._title = _RunTitle()
        self._kills = QLabel()
        self._kills.setObjectName('validatorRunKills')
        self._date = QLabel()
        self._date.setObjectName('validatorHistoryMuted')
        status = QWidget()
        status.setObjectName('validatorHistoryCell')
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(1)
        status_line = QHBoxLayout()
        status_line.setSpacing(5)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._status = QLabel()
        self._partial = l10n.localized(QLabel, l10n.tr('Partial coverage'))
        self._partial.setIndent(13)
        self._partial.setObjectName('validatorCoverageNote')
        status_line.addWidget(self._dot)
        status_line.addWidget(self._status)
        status_line.addStretch()
        status_layout.addLayout(status_line)
        status_layout.addWidget(self._partial)
        actions = QWidget()
        actions.setObjectName('validatorHistoryCell')
        links = QHBoxLayout(actions)
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(5)
        open_button = _action(l10n.tr('Open'), 'open', l10n.tr('Open Validator report'))
        copy_button = _action('', 'copy', l10n.tr('Copy Validator report link'))
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(url))
        links.addWidget(open_button)
        links.addWidget(copy_button)
        links.addStretch()
        self._cells = (self._title, self._kills, self._date, status, actions)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(12, 7, 9, 7)
        self._layout.setHorizontalSpacing(10)
        self._layout.setVerticalSpacing(4)
        self._dividers = []
        for cell in self._cells[1:]:
            divider = QFrame(cell)
            divider.setObjectName('validatorDivider')
            divider.setFixedSize(1, 24)
            divider.move(0, 2)
            self._dividers.append(divider)
        self.set_compact(False)

    def set_compact(self, compact):
        for cell in self._cells:
            self._layout.removeWidget(cell)
            cell.setContentsMargins(0 if compact else 10, 0, 0, 0)
            if cell.layout() is not None:
                cell.layout().setContentsMargins(0 if compact else 10, 0, 0, 0)
        if compact:
            title, kills, date, status, actions = self._cells
            for column, cell in enumerate((kills, date, status)):
                self._layout.addWidget(cell, 1, column)
            self._layout.addWidget(title, 0, 0, 1, 3)
            self._layout.addWidget(actions, 0, 3)
            for column in range(5):
                self._layout.setColumnStretch(column, 0)
            self._layout.setColumnMinimumWidth(4, 0)
            self._layout.setColumnStretch(2, 1)
        else:
            _columns(self._layout, self._cells)
        for divider in self._dividers:
            divider.setVisible(not compact)

    def update_report(self, report):
        self._title.set_title(report.name or str(l10n.tr('Run')))
        locale = QLocale(l10n.active_translator().language)
        self._kills.setText(locale.toString(report.kills) if report.kills is not None else '—')
        started = datetime.fromisoformat(report.started)
        self._date.setText(locale.toString(QDateTime(started.astimezone()), 'dd MMM · HH:mm'))
        status = report_status(report)
        l10n.display(self._status, 'setText', status)
        color = '#DFB773' if _warning(report) else '#8DBDE6'
        self._dot.setPixmap(validator_icon('dot', color, 8).pixmap(self._dot.size()))
        self._status.setStyleSheet('color: #DFB773;' if _warning(report) else 'color: #CBDCED;')
        self._partial.setVisible(report.partial)


class ValidatorHistory(QWidget):
    def __init__(self):
        super().__init__()
        self._rows = {}
        self._reports = None
        self._language = None
        self._compact = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 3, 0, 0)
        self._layout.setSpacing(7)
        title = l10n.localized(QLabel, l10n.tr('Recent reports'))
        title.setObjectName('validatorHistoryTitle')
        self._layout.addWidget(title)
        self._headers = QWidget()
        columns = QGridLayout(self._headers)
        columns.setContentsMargins(12, 0, 9, 0)
        columns.setHorizontalSpacing(10)
        headings = []
        for source in ('Run', 'Kills', 'Date', 'Validator status', 'Link'):
            label = l10n.localized(QLabel, l10n.tr(source))
            label.setObjectName('validatorHistoryMuted')
            label.setContentsMargins(10, 0, 0, 0)
            headings.append(label)
        _columns(columns, headings)
        self._layout.addWidget(self._headers)
        self._empty = l10n.localized(QLabel, l10n.tr('No Validator reports yet'))
        self._empty.setObjectName('dialogHint')
        self._layout.addWidget(self._empty)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = event.size().width() < 680
        if compact != self._compact:
            self._compact = compact
            self._headers.setVisible(bool(self._reports) and not compact)
            for row in self._rows.values():
                row.set_compact(compact)

    def update_reports(self, reports):
        language = l10n.active_translator().language
        if reports == self._reports and language == self._language:
            return
        self._reports = reports
        self._language = language
        existing = set(self._rows)
        for index, report in enumerate(reports):
            row = self._rows.get(report.url)
            if row is None:
                row = self._rows[report.url] = _ReportRow(report.url)
                row.set_compact(self._compact)
            self._layout.insertWidget(index + 3, row)
            row.update_report(report)
            existing.discard(report.url)
        for url in existing:
            self._rows.pop(url).deleteLater()
        self._headers.setVisible(bool(reports) and not self._compact)
        self._empty.setVisible(not reports)
