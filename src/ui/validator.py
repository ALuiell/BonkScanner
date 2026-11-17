"""Live Validator controls and header status for the Scanner window."""
from __future__ import annotations

import math
import ntpath
import os
from urllib.parse import urlsplit

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app import config
from app.validator_reports import report_available, report_url
from ui import i18n as l10n
from ui.validator_reports import ValidatorHistory, ValidatorReportStrip, validator_icon


SETTINGS_KEY = 'LIVE_VALIDATOR'


def _preferences(settings):
    values = settings.get(SETTINGS_KEY)
    return values if isinstance(values, dict) else {}


class ValidatorTab(QScrollArea):
    def __init__(self, controller, header_button, parent=None, *, reports=None, recordings=lambda: ()):
        super().__init__(parent)
        self.controller = controller
        self.header_button = header_button
        self.header_button.setText('VAL')
        self.header_button.setIconSize(QSize(10, 10))
        self._reports = reports
        self._recordings = recordings
        self._known_recordings = ()
        self._live_strip = None
        self._refresh_recording_report = None
        self._startup_checked = False
        self._active_base = ''
        self._current_link = ''
        self._copied_link = ''
        self._rendered_diagnostics = None

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
        self.report_actions = QWidget()
        link_row = QHBoxLayout(self.report_actions)
        link_row.setContentsMargins(0, 0, 0, 0)
        self.open_report = l10n.localized(QPushButton, l10n.tr('Open'))
        self.open_report.setObjectName('primary')
        self.open_report.setIcon(validator_icon('open', '#A2CCED'))
        l10n.display(self.open_report, 'setAccessibleName', l10n.tr('Open Validator report'))
        self.open_report.clicked.connect(self._open_report)
        self.copy_link = l10n.localized(QPushButton, l10n.tr('Copy link'))
        self.copy_link.setIcon(validator_icon('copy', '#A2CCED'))
        self.copy_link.clicked.connect(self._copy_link)
        link_row.addWidget(self.open_report)
        link_row.addWidget(self.copy_link)
        link_row.addStretch()
        run_layout.addWidget(self.report_actions)
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
        self.run_id = QLineEdit()
        self.run_id.setReadOnly(True)
        l10n.display(self.run_id, 'setAccessibleName', l10n.tr('Public session ID:'))
        self.diagnostics.layout().addWidget(self.run_id)
        self.diagnostics.hide()
        self.diagnostics_toggle.toggled.connect(self.diagnostics.setVisible)
        self.diagnostics_toggle.toggled.connect(self._diagnostics_toggled)
        layout.addWidget(self.diagnostics)
        if reports is not None:
            self._history = ValidatorHistory()
            layout.addWidget(self._history)
            self._history_feedback = l10n.localized(QLabel, l10n.tr('Report history could not be saved.'))
            self._history_feedback.setObjectName('dialogHint')
            self._history_feedback.hide()
            layout.addWidget(self._history_feedback)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
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
        self.report_access = self._plain_label()
        layout.addWidget(self.report_access)
        self.image_events = self._plain_label()
        self.image_events.hide()
        layout.addWidget(self.image_events)
        self.security_audit = self._plain_label()
        self.security_audit.hide()
        layout.addWidget(self.security_audit)
        url_label = l10n.localized(QLabel, l10n.tr('Validator service:'))
        layout.addWidget(url_label)
        stored_url = settings.get('service_url_v3')
        env_url = os.environ.get('BONKSCANNER_VALIDATOR_URL', '')
        saved_url = env_url or (stored_url if isinstance(stored_url, str) else '')
        self.url = QLineEdit(saved_url)
        self.url.setPlaceholderText('https://…')
        url_label.setBuddy(self.url)
        layout.addWidget(self.url)
        self.local_test = l10n.localized(QCheckBox, l10n.tr('Allow a local test receiver'))
        if env_url:
            try:
                allow_loopback = urlsplit(env_url).hostname in ('127.0.0.1', 'localhost', '::1')
            except ValueError:
                allow_loopback = False
        else:
            allow_loopback = isinstance(stored_url, str) and settings.get('allow_loopback_v3') is True
        self.local_test.setChecked(allow_loopback)
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
        if self._save_preferences(service_url_v3=base, allow_loopback_v3=allow_loopback):
            self._show_settings_feedback(l10n.tr('Validator service settings saved.'))

    def _enable(self):
        from infra.scenario_trace import trace
        trace("validator_enable_requested")
        self.refresh()
        base, allow_loopback = self._endpoint()
        if self.controller.enable(base, allow_loopback=allow_loopback, protocol_version='3'):
            trace("validator_enable_accepted")
            self._active_base = base
        self.refresh()

    def _disable(self):
        self.controller.disable(timeout=0)
        self.refresh()

    def _report_link_for_action(self):
        displayed_link = self._current_link
        # A run can end between painting the button and handling the click.
        if displayed_link and self.refresh() and self._current_link == displayed_link:
            return displayed_link
        return ''

    def _open_report(self):
        link = self._report_link_for_action()
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def _copy_link(self):
        link = self._report_link_for_action()
        if link:
            QApplication.clipboard().setText(link)
            self._copied_link = link
            l10n.display(self.copy_feedback, 'setText', l10n.tr('Link copied'))
            self.copy_feedback.show()

    def _poll(self):
        self.refresh(polling=True)

    def stop_polling(self):
        self._timer.stop()

    def _diagnostics_toggled(self, opened):
        if opened:
            self.refresh()

    def refresh(self, *, polling=False):
        visible = self.isVisible() and not self.window().isMinimized()
        diagnostics = not polling or (visible and self.diagnostics_toggle.isChecked())
        get_snapshot = getattr(self.controller, 'try_snapshot', None)
        snapshot = (get_snapshot(diagnostics=diagnostics) if get_snapshot is not None
                    else self.controller.snapshot())
        if snapshot is None:
            return False
        if self._reports is not None:
            self._reports.refresh(snapshot, self._active_base)
        # Recordings and report history keep advancing while the window is minimized.
        if polling and self.window().isMinimized():
            return True
        state = snapshot['state']
        coverage = snapshot['coverage']
        access = snapshot.get('process_access') or {}
        if state == 'observing' and (
            access.get('mode') == 'fallback'
            or any(channel.get('status') in ('partial', 'unknown') for channel in coverage.values())
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
        caption = l10n.tr('Validator · {p0}', p0=short)
        if self.header_button.accessibleName() != caption:
            self.header_button.setAccessibleName(caption)
        tooltip = f'{l10n.tr("Live Validator")} · {detail}'
        if self.header_button.toolTip() != tooltip:
            self.header_button.setToolTip(tooltip)
        if self.header_button.property('tone') != tone:
            self.header_button.setProperty('tone', tone)
            color = {'active': '#75B9E4', 'warning': '#DFB773'}.get(tone, '#5C6675')
            self.header_button.setIcon(validator_icon('dot', color, 10))

        if diagnostics:
            diagnostic_data = (l10n.active_translator().language, coverage, access,
                               snapshot.get('active_run_id'), snapshot.get('process_access_ipc_skipped'),
                               snapshot.get('security_audit'), snapshot.get('last_security_audit'),
                               snapshot.get('security_audit_ipc_skipped'))
            if not polling or diagnostic_data != self._rendered_diagnostics:
                self._refresh_diagnostics(snapshot, coverage, access)
                self._rendered_diagnostics = diagnostic_data

        if not polling or visible:
            self.state.setText(detail)
            self._refresh_delivery(snapshot)
            self.enable.setVisible(not snapshot['enabled'])
            self.enable.setEnabled(not snapshot['busy'])
            self.disable.setVisible(snapshot['enabled'])
            self.disable.setEnabled(snapshot['enabled'])
            for widget in (self.url, self.local_test, self.save_service):
                widget.setEnabled(not snapshot['busy'])

        if self._reports is not None:
            if visible:
                self._history.update_reports(self._reports.recent(self._known_recordings))
                self._history_feedback.setVisible(self._reports.save_failed)
            if self._live_strip is not None:
                current = ((snapshot.get('delivery') or {}).get('runs') or {}).get(snapshot['active_run_id'], {})
                fallback = (
                    l10n.tr('Registering session') if current.get('status') == 'enrolling'
                    else short if snapshot['enabled'] or snapshot['busy'] else None
                )
                self._live_strip.update_report(
                    self._reports.live(), fallback, last=not snapshot['active_run_id'],
                )
            if self._refresh_recording_report is not None:
                self._refresh_recording_report()
        return True

    def _refresh_diagnostics(self, snapshot, coverage, access):
        channel_names = {'processAccess': l10n.tr('Process access'),
                         'environment': l10n.tr('Game environment'),
                         'fileIntegrity': l10n.tr('File integrity')}
        coverage_states = {'active': l10n.tr('Observing'), 'complete': l10n.tr('Complete'),
                           'partial': l10n.tr('Partial coverage'), 'unknown': l10n.tr('Unknown')}
        coverage_text = [
            f'{channel_names.get(name, name)}: {coverage_states.get(value.get("status"), l10n.tr("Unknown"))}'
            for name, value in coverage.items()
        ]
        if access:
            etw_status = {
                'healthy': l10n.tr('Observing'),
                'fallback': l10n.tr('Partial coverage'),
                'stopped': l10n.tr('Off'),
            }
            coverage_text.append(l10n.tr('Local ETW: {p0}', p0=etw_status.get(access.get('mode'), l10n.tr('Unknown'))))
        self.coverage.setText(' · '.join(coverage_text) or l10n.tr('Coverage: unknown'))
        details = []
        origin = access.get('attachedMonotonic')
        if origin is not None:
            for gap in access.get('gaps', ()):
                start = f"{gap['fromMonotonic'] - origin:.1f} s"
                end = gap['toMonotonic']
                if end is None:
                    details.append(l10n.tr('Partial ETW coverage since {p0} after attachment', p0=start))
                else:
                    details.append(l10n.tr('Partial ETW coverage from {p0} to {p1} after attachment',
                                           p0=start, p1=f'{end - origin:.1f} s'))
        run_id = snapshot['active_run_id']
        if run_id and any(row['priority'] == 'review' and row['localRunId'] == run_id
                          for row in access.get('findings', ())):
            details.append(l10n.tr('An unknown process successfully opened MegaBonk and requested write access.'))
        skipped = snapshot.get('process_access_ipc_skipped', 0)
        if skipped:
            details.append(l10n.tr('Local ETW diagnostic updates skipped: {p0}', p0=skipped))
        drops = access.get('queueDrops')
        if isinstance(drops, dict):
            for key, message in (
                ('etwCallback', lambda n: l10n.tr('External Access drops at ETW callback queue: {p0}', p0=n)),
                ('runBinding', lambda n: l10n.tr('External Access drops before run binding: {p0}', p0=n)),
                ('payloadPending', lambda n: l10n.tr('External Access drops before payload: {p0}', p0=n)),
                ('observationCapacity', lambda n: l10n.tr('External Access drops at observation capacity: {p0}', p0=n)),
            ):
                count = drops.get(key)
                if type(count) is int and count >= 0:
                    details.append(message(count))
        self.coverage.setToolTip('\n'.join(details))
        self._refresh_image_events(access)
        self._refresh_security_audit(snapshot)

    def _refresh_image_events(self, access):
        events = access.get('imageEvents')
        self.image_events.setVisible(isinstance(events, dict) and bool(events))
        if not isinstance(events, dict) or not events:
            self.image_events.clear()
            self.image_events.setToolTip('')
            return
        states = {'active': l10n.tr('Observing'), 'partial': l10n.tr('Partial coverage'),
                  'unavailable': l10n.tr('Unavailable'), 'stopped': l10n.tr('Stopped')}
        parts = [str(l10n.tr('Local image history (current or last attachment): {p0}',
                             p0=states.get(events.get('status'), l10n.tr('Unknown'))))]
        for key, label in (('loaded', l10n.tr('Loaded')), ('unloaded', l10n.tr('Unloaded')),
                           ('dropped', l10n.tr('Dropped')), ('decodeErrors', l10n.tr('Decode errors')),
                           ('identityUnknown', l10n.tr('Unknown identity')),
                           ('historyOmitted', l10n.tr('History omitted'))):
            count = events.get(key)
            if type(count) is int and count >= 0:
                parts.append(str(l10n.tr('{p0}: {p1}', p0=label, p1=count)))
        self.image_events.setText(' · '.join(parts))
        details = [str(l10n.tr('Local ETW image events for this process attachment. Dropped events, decode errors or unknown identity indicate incomplete history; omitted history means older retained rows were removed.'))]
        origin = access.get('attachedMonotonic')
        rows = events.get('rows')
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or row.get('kind') not in ('load', 'unload'):
                    continue
                name = row.get('name')
                if not isinstance(name, str) or not name:
                    continue
                name = ''.join(c for c in ntpath.basename(name) if c.isprintable())
                if not name:
                    continue
                kind = l10n.tr('Loaded') if row['kind'] == 'load' else l10n.tr('Unloaded')
                when = row.get('occurredMonotonic')
                if (type(origin) in (int, float) and type(when) in (int, float)
                        and math.isfinite(origin) and math.isfinite(when)):
                    details.append(str(l10n.tr('{p0} s after attachment: {p1} {p2}',
                                               p0=f'{when - origin:.1f}', p1=kind, p2=name)))
                else:
                    details.append(str(l10n.tr('{p0}: {p1}', p0=kind, p1=name)))
        self.image_events.setToolTip('\n'.join(details))

    def _refresh_security_audit(self, snapshot):
        current = snapshot.get('security_audit')
        last = snapshot.get('last_security_audit')
        show_current = isinstance(current, dict) and bool(current) and (
            current.get('status') != 'armed' or not last)
        report = current if show_current else last
        skipped = snapshot.get('security_audit_ipc_skipped', 0)
        self.security_audit.setVisible(bool(report) or bool(skipped))
        if not isinstance(report, dict) or not report:
            self.security_audit.setText(str(l10n.tr('Security 4663 (local): {p0}',
                                                    p0=l10n.tr('Unknown'))) if skipped else '')
            return
        states = {
            'armed': l10n.tr('Armed'), 'collecting': l10n.tr('Collecting'),
            'collected': l10n.tr('Collected'), 'partial': l10n.tr('Partial coverage'),
            'unavailable': l10n.tr('Unavailable'), 'cancelled': l10n.tr('Cancelled'),
        }
        restoration = {
            'verified': l10n.tr('Verified'),
            'preserved_external_change': l10n.tr('External change preserved'),
            'failed': l10n.tr('Failed'), 'pending': l10n.tr('Pending'),
            'not_needed': l10n.tr('Not needed'), 'unknown': l10n.tr('Unknown'),
        }
        status = states.get(report.get('status'), l10n.tr('Unknown'))
        if show_current:
            parts = [str(l10n.tr('Security 4663 (local): {p0}', p0=status))]
        else:
            parts = [str(l10n.tr('Last Security 4663 result (local): {p0}', p0=status))]
        if report.get('status') in ('collected', 'partial'):
            for key, label in (('confirmed', l10n.tr('Confirmed')), ('ambiguous', l10n.tr('Ambiguous'))):
                counts = report.get(key)
                if isinstance(counts, dict):
                    reads, writes = counts.get('readRecords'), counts.get('writeRecords')
                    if type(reads) is int and type(writes) is int:
                        parts.append(str(l10n.tr('{p0}: {p1} read records, {p2} write records',
                                                  p0=label, p1=reads, p2=writes)))
        parts.append(str(l10n.tr('Restoration: {p0}',
                                 p0=restoration.get(report.get('restoration'), l10n.tr('Unknown')))))
        help_text = str(l10n.tr('Security event 4663 records exercised access rights. Counts refer to journal records. Path-only matches are ambiguous. This diagnostic stays local.'))
        issues = list(report.get('issues') or ())
        if skipped and 'audit_update_lost' not in issues:
            issues.append('audit_update_lost')
        if isinstance(issues, list) and issues:
            parts.append(str(l10n.tr('Issues: {p0}', p0=', '.join(str(issue) for issue in issues))))
        self.security_audit.setText('\n'.join(parts))
        self.security_audit.setToolTip(help_text)

    def _refresh_delivery(self, snapshot):
        delivery = snapshot['delivery'] or {}
        runs = delivery.get('runs', {})
        active_id = snapshot.get('active_run_id')
        current = runs.get(active_id, {}) if snapshot['enabled'] else {}
        session_id = current.get('session_id')
        if (not self._active_base or current.get('protocol_version') != '3'
                or not report_available(current) or current.get('finish_requested')
                or current.get('status') not in ('active', 'retrying')):
            session_id = None
        self.run_id.setVisible(bool(session_id))
        if self.run_id.text() != (session_id or ''):
            self.run_id.setText(session_id or '')
        self.report_actions.setVisible(bool(session_id))
        self.report_actions.setEnabled(bool(session_id))
        self._current_link = report_url(self._active_base, session_id, '3')
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
        last_report = next((run for run in reversed(runs.values())
                            if run.get('finish_requested') and report_available(run)), {}) if not active_id else {}
        if not delivery.get('configured'):
            message = l10n.tr('Service not configured; local observation only')
        elif last_report:
            status = last_report.get('status')
            if (status == 'finished' and last_report.get('protocol_version') == '3'
                    and last_report.get('confirmed_run_end_ms') is None):
                status = 'expired'
            if status in ('active', 'enrolling'):
                status = 'finish_pending'
            message = l10n.tr('Last report: {p0}', p0=delivery_states.get(status, l10n.tr('Waiting')))
        else:
            message = l10n.tr('Delivery: {p0}', p0=delivery_states.get(current.get('status'), l10n.tr('Waiting')))
        self.delivery.setText(message)
        report_run = last if last.get('finish_requested') else current
        negotiated = report_run.get('direct_open_negotiated')
        if negotiated is False:
            report_access = l10n.tr('Report process access: snapshots only')
        elif negotiated is True and report_run.get('direct_open_available') is True:
            report_access = l10n.tr('Report process access: ETW negotiated')
        elif negotiated is True:
            report_access = l10n.tr('Report process access: ETW pending or unavailable')
        else:
            report_access = l10n.tr('Report process access: negotiation pending')
        self.report_access.setVisible(bool(report_run) and delivery.get('configured', False))
        self.report_access.setText(report_access)

    def add_to(self, tabs):
        l10n.tab(tabs, self, l10n.tr('Validator'))
        self.header_button.clicked.connect(lambda: tabs.setCurrentWidget(self))

    def create_live_strip(self):
        self._live_strip = ValidatorReportStrip(self._live_report_for_action, copy=True)
        return self._live_strip

    def _live_report_for_action(self):
        return self._reports.live() if self.refresh() else None

    def bind_recordings(self, refresh):
        self._refresh_recording_report = refresh

    def showEvent(self, event):
        super().showEvent(event)
        self._known_recordings = self._recordings()
        self.refresh()
