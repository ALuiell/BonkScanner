"""Live Validator controls and header status for the Scanner window."""
from __future__ import annotations

import os
from urllib.parse import quote

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app import config
from ui import i18n as l10n


SETTINGS_KEY = 'LIVE_VALIDATOR'


def _preferences(settings):
    values = settings.get(SETTINGS_KEY)
    return values if isinstance(values, dict) else {}


class ValidatorTab(QScrollArea):
    def __init__(self, controller, header_button, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.header_button = header_button
        self._startup_checked = False
        self._active_base = ''
        self._current_link = ''
        self._copied_link = ''

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        title = l10n.localized(QLabel, l10n.tr('Live Validator'))
        title.setObjectName('validatorTitle')
        layout.addWidget(title)

        settings = _preferences(config.user_config)
        self.autostart = l10n.localized(QCheckBox, l10n.tr('Start Validator with Scanner'))
        self.autostart.setChecked(settings.get('autostart') is True)
        self.autostart.toggled.connect(self._save_autostart)
        layout.addWidget(self.autostart)
        self.autostart_hint = l10n.localized(
            QLabel, l10n.tr('Windows will ask for administrator permission each time Scanner starts.')
        )
        self.autostart_hint.setObjectName('dialogHint')
        self.autostart_hint.setWordWrap(True)
        layout.addWidget(self.autostart_hint)
        self.autostart_hint.setVisible(self.autostart.isChecked())
        self.settings_feedback = self._plain_label()
        self.settings_feedback.hide()
        layout.addWidget(self.settings_feedback)

        run_card = QFrame()
        run_card.setObjectName('validatorRunCard')
        run_layout = QVBoxLayout(run_card)
        run_layout.setContentsMargins(12, 12, 12, 12)
        run_title = l10n.localized(QLabel, l10n.tr('Current run'))
        run_title.setObjectName('groupTitle')
        run_layout.addWidget(run_title)
        self.state = self._plain_label()
        run_layout.addWidget(self.state)
        self.delivery = self._plain_label()
        self.delivery.setObjectName('dialogHint')
        run_layout.addWidget(self.delivery)
        link_row = QHBoxLayout()
        self.run_id = QLineEdit()
        self.run_id.setReadOnly(True)
        l10n.display(self.run_id, 'setAccessibleName', l10n.tr('Public session ID:'))
        self.copy_link = l10n.localized(QPushButton, l10n.tr('Copy link'))
        self.copy_link.setObjectName('primary')
        self.copy_link.clicked.connect(self._copy_link)
        link_row.addWidget(self.run_id, 1)
        link_row.addWidget(self.copy_link)
        run_layout.addLayout(link_row)
        self.copy_feedback = self._plain_label()
        self.copy_feedback.setObjectName('dialogHint')
        self.copy_feedback.hide()
        run_layout.addWidget(self.copy_feedback)
        layout.addWidget(run_card)

        actions = QHBoxLayout()
        self.enable = l10n.localized(QPushButton, l10n.tr('Enable Validator'))
        self.enable.setObjectName('primary')
        self.enable.clicked.connect(self._enable)
        self.disable = l10n.localized(QPushButton, l10n.tr('Stop for this launch'))
        self.disable.clicked.connect(self._disable)
        self.diagnostics_toggle = l10n.localized(QPushButton, l10n.tr('Diagnostics'))
        self.diagnostics_toggle.setCheckable(True)
        actions.addWidget(self.enable)
        actions.addWidget(self.disable)
        actions.addStretch()
        actions.addWidget(self.diagnostics_toggle)
        layout.addLayout(actions)

        self.diagnostics = self._build_diagnostics(settings)
        self.diagnostics.hide()
        self.diagnostics_toggle.toggled.connect(self.diagnostics.setVisible)
        layout.addWidget(self.diagnostics)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @staticmethod
    def _plain_label():
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        return label

    def _build_diagnostics(self, settings):
        panel = QFrame()
        panel.setObjectName('card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        self.coverage = self._plain_label()
        layout.addWidget(self.coverage)
        url_label = l10n.localized(QLabel, l10n.tr('Validator service:'))
        layout.addWidget(url_label)
        stored_url = settings.get('service_url')
        saved_url = stored_url if isinstance(stored_url, str) else os.environ.get('BONKSCANNER_VALIDATOR_URL', '')
        self.url = QLineEdit(saved_url)
        self.url.setPlaceholderText('https://…')
        url_label.setBuddy(self.url)
        layout.addWidget(self.url)
        self.local_test = l10n.localized(QCheckBox, l10n.tr('Allow a local test receiver'))
        self.local_test.setChecked(isinstance(stored_url, str) and settings.get('allow_loopback') is True)
        layout.addWidget(self.local_test)
        self.save_service = l10n.localized(QPushButton, l10n.tr('Save service settings'))
        self.save_service.clicked.connect(self._save_service)
        layout.addWidget(self.save_service, alignment=Qt.AlignLeft)
        return panel

    def start_if_configured(self):
        if self._startup_checked:
            return
        self._startup_checked = True
        if self.autostart.isChecked():
            self._enable()

    def _save_preferences(self, **changes):
        def update(settings):
            settings[SETTINGS_KEY] = {**_preferences(settings), **changes}

        if not config.profile_read_only_reason() and config.update_config(update).success:
            return True
        self._show_settings_feedback(l10n.tr('Could not save Validator settings.'))
        return False

    def _show_settings_feedback(self, message):
        l10n.display(self.settings_feedback, 'setText', message)
        self.settings_feedback.show()

    def _save_autostart(self, enabled):
        if self._save_preferences(autostart=enabled):
            self.settings_feedback.hide()
        else:
            with QSignalBlocker(self.autostart):
                self.autostart.setChecked(_preferences(config.user_config).get('autostart') is True)
        self.autostart_hint.setVisible(self.autostart.isChecked())

    def _endpoint(self):
        return self.url.text().strip().rstrip('/'), self.local_test.isChecked()

    def _save_service(self):
        from bonkscanner_validator.transport import parse_service_url

        base, allow_loopback = self._endpoint()
        try:
            parse_service_url(base, allow_loopback=allow_loopback)
        except ValueError:
            self._show_settings_feedback(l10n.tr('Invalid service address'))
            return
        if self._save_preferences(service_url=base, allow_loopback=allow_loopback):
            self._show_settings_feedback(l10n.tr('Validator service settings saved.'))

    def _enable(self):
        base, allow_loopback = self._endpoint()
        if self.controller.enable(base, allow_loopback=allow_loopback):
            self._active_base = base
        self.refresh()

    def _disable(self):
        self.controller.disable(timeout=0)
        self.refresh()

    def _copy_link(self):
        displayed_link = self._current_link
        # A run can end between painting the button and handling the click.
        self.refresh()
        if displayed_link and self._current_link == displayed_link:
            QApplication.clipboard().setText(displayed_link)
            self._copied_link = displayed_link
            l10n.display(self.copy_feedback, 'setText', l10n.tr('Link copied'))
            self.copy_feedback.show()

    def refresh(self):
        snapshot = self.controller.snapshot()
        state = snapshot['state']
        coverage = snapshot['coverage']
        if state == 'observing' and any(
            channel.get('status') in ('partial', 'unknown') for channel in coverage.values()
        ):
            state = 'partial'
        labels = {
            'disabled': (l10n.tr('Off'), l10n.tr('Validator is off'), 'idle'),
            'starting': (l10n.tr('Starting'), l10n.tr('Waiting for administrator confirmation'), 'pending'),
            'waiting_game': (l10n.tr('Waiting for run'), l10n.tr('Waiting for a supported game run'), 'pending'),
            'observing': (l10n.tr('Observing'), l10n.tr('Observing the current run'), 'active'),
            'partial': (l10n.tr('Limited'), l10n.tr('Partial coverage'), 'warning'),
            'unsupported': (l10n.tr('Unavailable'), l10n.tr('Unsupported game profile'), 'warning'),
            'stopping': (l10n.tr('Stopping'), l10n.tr('Stopping'), 'idle'),
            'stopped': (l10n.tr('Off'), l10n.tr('Observer stopped'), 'warning'),
        }
        short, detail, tone = labels.get(state, (l10n.tr('Unknown'), l10n.tr('Unknown'), 'warning'))
        error_labels = {
            'invalid_service_url': l10n.tr('Invalid service address'),
            'queue_capacity': l10n.tr('Queue capacity reached'),
            'ipc_queue_capacity': l10n.tr('Observation interrupted: local queue capacity reached'),
            'observer_not_started': l10n.tr('Administrator permission was not granted.'),
            'observer_stopped': l10n.tr('Observation interrupted'),
            'delivery_failed': l10n.tr('Delivery interrupted'),
            'finish_unconfirmed': l10n.tr('Completion is unconfirmed'),
        }
        error = snapshot['error']
        if error:
            detail = f"{detail} · {error_labels.get(error, l10n.tr('Incomplete observation'))}"
            tone = 'warning'
        self.state.setText(detail)
        caption = l10n.tr('Validator · {p0}', p0=short)
        self.header_button.setText(f'●  {caption}')
        self.header_button.setAccessibleName(caption)
        self.header_button.setToolTip(detail)
        if self.header_button.property('tone') != tone:
            self.header_button.setProperty('tone', tone)
            self.header_button.style().unpolish(self.header_button)
            self.header_button.style().polish(self.header_button)

        channel_names = {'processAccess': l10n.tr('Process access'),
                         'environment': l10n.tr('Game environment'),
                         'fileIntegrity': l10n.tr('File integrity')}
        coverage_states = {'active': l10n.tr('Observing'), 'complete': l10n.tr('Complete'),
                           'partial': l10n.tr('Partial coverage'), 'unknown': l10n.tr('Unknown')}
        self.coverage.setText(' · '.join(
            f'{channel_names.get(name, name)}: {coverage_states.get(value.get("status"), l10n.tr("Unknown"))}'
            for name, value in coverage.items()
        ) or l10n.tr('Coverage: unknown'))
        self._refresh_delivery(snapshot)

        self.enable.setVisible(not snapshot['enabled'])
        self.enable.setEnabled(not snapshot['busy'])
        self.disable.setVisible(snapshot['enabled'])
        self.disable.setEnabled(snapshot['enabled'])
        for widget in (self.url, self.local_test, self.save_service):
            widget.setEnabled(not snapshot['busy'])

    def _refresh_delivery(self, snapshot):
        delivery = snapshot['delivery'] or {}
        runs = delivery.get('runs', {})
        active_id = snapshot.get('active_run_id')
        current = runs.get(active_id, {}) if snapshot['enabled'] else {}
        session_id = current.get('session_id')
        if not self._active_base or current.get('finish_requested') or current.get('status') not in ('active', 'retrying'):
            session_id = None
        self.run_id.setVisible(bool(session_id))
        self.run_id.setText(session_id or '')
        self.copy_link.setVisible(bool(session_id))
        self.copy_link.setEnabled(bool(session_id))
        self._current_link = (
            f"{self._active_base}/v2/sessions/{quote(session_id, safe='')}" if session_id else ''
        )
        if self._current_link != self._copied_link:
            self._copied_link = ''
            self.copy_feedback.hide()

        delivery_states = {'offline': l10n.tr('Offline'), 'enrolling': l10n.tr('Registering session'),
                           'active': l10n.tr('Connected'), 'retrying': l10n.tr('Retrying delivery'),
                           'finish_pending': l10n.tr('Sending final data'),
                           'finish_unconfirmed': l10n.tr('Completion is unconfirmed'),
                           'expired': l10n.tr('Observation interrupted'),
                           'finished': l10n.tr('Completion confirmed'), 'failed': l10n.tr('Delivery interrupted')}
        last = next(reversed(runs.values()), {}) if not active_id else {}
        if not delivery.get('configured'):
            message = l10n.tr('Service not configured; local observation only')
        elif last.get('finish_requested'):
            status = last.get('status')
            if status in ('active', 'enrolling'):
                status = 'finish_pending'
            message = l10n.tr('Last report: {p0}', p0=delivery_states.get(status, l10n.tr('Waiting')))
        else:
            message = l10n.tr('Delivery: {p0}', p0=delivery_states.get(current.get('status'), l10n.tr('Waiting')))
        self.delivery.setText(message)

    def add_to(self, tabs):
        l10n.tab(tabs, self, l10n.tr('Validator'))
        self.header_button.clicked.connect(lambda: tabs.setCurrentWidget(self))
