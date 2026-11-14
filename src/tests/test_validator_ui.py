import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QWidget

from app import config
from app.validator_reports import ValidatorReport
from ui.validator import SETTINGS_KEY, ValidatorTab
from ui.validator_reports import ValidatorHistory, ValidatorReportStrip


class Controller:
    def __init__(self):
        self.value = {'state': 'disabled', 'error': None, 'enabled': False,
                      'busy': False, 'coverage': {}, 'delivery': None, 'active_run_id': None}
        self.starts = []
        self.stop_options = None

    def snapshot(self):
        return self.value

    def enable(self, url, **options):
        self.starts.append((url, options))
        return True

    def disable(self, **options):
        self.stop_options = options


class ValidatorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = Controller()
        self.settings = {}
        self.save_success = True
        self.enterContext(patch.object(config, 'user_config', self.settings))
        self.enterContext(patch.object(config, 'update_config', self.save))
        self.enterContext(patch.object(config, 'profile_read_only_reason', return_value=''))
        self.enterContext(patch.dict(os.environ, {'BONKSCANNER_VALIDATOR_URL': ''}))

    def save(self, mutate):
        if self.save_success:
            mutate(self.settings)
        return SimpleNamespace(success=self.save_success)

    def tab(self):
        self.button = QPushButton()
        tab = ValidatorTab(self.controller, self.button)
        self.addCleanup(self.button.deleteLater)
        self.addCleanup(tab.deleteLater)
        return tab

    def test_history_hides_short_and_legacy_interrupted_reports_by_default(self):
        history = ValidatorHistory()
        self.addCleanup(history.deleteLater)
        legacy = ValidatorReport('https://validator.example/legacy', '2026-11-11T18:42:00Z', 'interrupted')
        short = ValidatorReport('https://validator.example/short', '2026-11-11T18:42:00Z', 'interrupted',
                                short_attempt=True)
        long = ValidatorReport('https://validator.example/long', '2026-11-11T18:42:00Z', 'interrupted',
                               short_attempt=False)
        history.update_reports((legacy, short))
        self.assertEqual(history._rows, {})
        self.assertTrue(history._empty.isHidden())
        history.update_reports((legacy, short, long))
        self.assertEqual(set(history._rows), {long.url})
        self.assertFalse(history.show_all.isHidden())
        history.show_all.click()
        self.assertEqual(set(history._rows), {legacy.url, short.url, long.url})
        history.show_all.click()
        self.assertEqual(set(history._rows), {long.url})
        history.update_reports((long,))
        self.assertTrue(history.show_all.isHidden())

    def test_header_opens_tab_and_default_startup_is_off(self):
        tab = self.tab()
        tabs = QTabWidget()
        self.addCleanup(tabs.deleteLater)
        tabs.addTab(QWidget(), 'Recordings')
        tab.add_to(tabs)
        self.assertEqual(tabs.currentIndex(), 0)
        self.button.click()
        self.assertIs(tabs.currentWidget(), tab)
        self.assertEqual(self.button.text(), 'VAL')
        self.assertEqual(self.button.accessibleName(), 'Validator · Off')
        self.assertIn('local observation', tab.delivery.text())
        self.assertFalse(tab.copy_link.isEnabled())
        tab.start_if_configured()
        self.assertEqual(self.controller.starts, [])

    def test_header_distinguishes_waiting_from_active_observation(self):
        tab = self.tab()
        self.controller.value.update(state='waiting_game', enabled=True, busy=True)
        tab.refresh()
        self.assertEqual(self.button.accessibleName(), 'Validator · Waiting for run')
        self.assertEqual(self.button.property('tone'), 'pending')

        self.controller.value['state'] = 'observing'
        tab.refresh()
        self.assertEqual(self.button.property('tone'), 'active')

        self.controller.value['coverage'] = {'processAccess': {'status': 'partial'}}
        tab.refresh()
        self.assertEqual(self.button.accessibleName(), 'Validator · Limited')
        self.assertEqual(self.button.property('tone'), 'warning')

    def test_etw_coverage_and_write_priority_are_scoped_to_the_current_run(self):
        tab = self.tab()
        self.controller.value.update(state='observing', enabled=True, active_run_id='second',
                                     process_access={'mode': 'fallback', 'attachedMonotonic': 5,
                                         'gaps': [{'fromMonotonic': 6, 'toMonotonic': None}],
                                         'findings': [{'priority': 'review', 'localRunId': 'first'},
                                                      {'priority': 'review', 'localRunId': None}]})
        tab.refresh()
        self.assertEqual(self.button.property('tone'), 'warning')
        self.assertIn('Local ETW: Partial coverage', tab.coverage.text())
        self.assertIn('since 1.0 s', tab.coverage.toolTip())
        self.assertNotIn('requested write access', tab.coverage.toolTip())
        self.controller.value['process_access']['findings'].append(
            {'priority': 'review', 'localRunId': 'second'})
        tab.refresh()
        self.assertIn('requested write access', tab.coverage.toolTip())

    def test_local_image_history_shows_counts_gaps_and_attachment_relative_rows(self):
        tab = self.tab()
        self.assertTrue(tab.image_events.isHidden())
        self.controller.value.update(state='observing', enabled=True, process_access={
            'mode': 'healthy', 'attachedMonotonic': 10.0,
            'imageEvents': {'status': 'partial', 'loaded': 4, 'unloaded': 2,
                            'dropped': 3, 'decodeErrors': 1, 'identityUnknown': 2,
                            'historyOmitted': 5,
                            'rows': [{'kind': 'load', 'name': 'example.dll', 'occurredMonotonic': 11.5},
                                     {'kind': 'unload', 'name': 'C:\\private\\old.dll', 'occurredMonotonic': 12.0}]}})
        tab.refresh()
        self.assertFalse(tab.image_events.isHidden())
        self.assertIn('Local image history', tab.image_events.text())
        self.assertIn('Partial coverage', tab.image_events.text())
        for text in ('Loaded: 4', 'Unloaded: 2', 'Dropped: 3', 'Decode errors: 1',
                     'Unknown identity: 2', 'History omitted: 5'):
            self.assertIn(text, tab.image_events.text())
        self.assertIn('1.5 s after attachment: Loaded example.dll', tab.image_events.toolTip())
        self.assertIn('2.0 s after attachment: Unloaded old.dll', tab.image_events.toolTip())
        self.assertNotIn('private', tab.image_events.toolTip())
        self.assertEqual(self.button.property('tone'), 'active')
        self.controller.value['process_access']['imageEvents'] = {'status': 'stopped'}
        tab.refresh()
        self.assertIn('Stopped', tab.image_events.text())
        self.assertNotIn('Loaded: 0', tab.image_events.text())
        self.assertNotIn('example.dll', tab.image_events.toolTip())
        del self.controller.value['process_access']['imageEvents']
        tab.refresh()
        self.assertTrue(tab.image_events.isHidden())

    def test_autostart_persists_and_relaunches_once_with_saved_endpoint(self):
        tab = self.tab()
        tab.url.setText(' http://127.0.0.1:8765/ ')
        tab.local_test.setChecked(True)
        tab.save_service.click()
        tab.autostart.setChecked(True)
        self.assertEqual(self.controller.starts, [])
        self.assertEqual(self.settings[SETTINGS_KEY], {
            'autostart': True, 'service_url': 'http://127.0.0.1:8765', 'allow_loopback': True,
        })
        next_tab = self.tab()
        next_tab.start_if_configured()
        self.controller.value['error'] = 'observer_not_started'
        next_tab.start_if_configured()
        self.assertEqual(self.controller.starts, [('http://127.0.0.1:8765', {'allow_loopback': True})])
        next_tab.refresh()
        self.assertIn('permission was not granted', next_tab.state.text())
        self.assertTrue(next_tab.enable.isEnabled())
        next_tab._disable()
        self.assertTrue(self.settings[SETTINGS_KEY]['autostart'])
        self.assertEqual(self.controller.stop_options, {'timeout': 0})

    def test_autostart_setting_rolls_back_on_write_failure(self):
        tab = self.tab()
        self.save_success = False
        tab.autostart.setChecked(True)
        self.assertFalse(tab.autostart.isChecked())
        self.assertNotIn(SETTINGS_KEY, self.settings)
        self.assertIn('Could not save', tab.settings_feedback.text())

    def test_read_only_profile_does_not_report_autostart_as_saved(self):
        tab = self.tab()
        config.profile_read_only_reason.return_value = 'Read-only profile'
        tab.autostart.setChecked(True)
        self.assertFalse(tab.autostart.isChecked())
        self.assertNotIn(SETTINGS_KEY, self.settings)

    def test_service_settings_require_explicit_loopback_consent(self):
        tab = self.tab()
        tab.url.setText('http://127.0.0.1:8765')
        tab.save_service.click()
        self.assertNotIn(SETTINGS_KEY, self.settings)
        self.assertIn('Invalid service address', tab.settings_feedback.text())

    def test_copy_uses_only_current_registered_session_and_rechecks_on_click(self):
        tab = self.tab()
        tab.url.setText('https://validator.example/base/')
        tab._enable()
        runs = {
            'current': {'session_id': 'current-id', 'status': 'active', 'finish_requested': False},
            'old': {'session_id': 'old-id', 'status': 'retrying', 'finish_requested': True},
        }
        self.controller.value.update(state='observing', enabled=True, busy=True, active_run_id='current',
                                     delivery={'configured': True, 'runs': runs})
        runs['current']['local_report_available'] = False
        tab.refresh()
        self.assertEqual(tab.run_id.text(), '')
        self.assertFalse(tab.copy_link.isEnabled())
        self.assertEqual(self.button.accessibleName(), 'Validator · Observing')
        runs['current']['local_report_available'] = True
        tab.refresh()
        self.assertEqual(tab.run_id.text(), 'current-id')
        self.assertTrue(tab.copy_link.isEnabled())
        self.assertFalse(tab.url.isEnabled())
        self.assertTrue(tab.disable.isEnabled())
        self.assertEqual(self.button.accessibleName(), 'Validator · Observing')
        with patch('ui.validator.QApplication.clipboard') as clipboard:
            tab.copy_link.click()
            clipboard.return_value.setText.assert_called_once_with(
                'https://validator.example/base/v2/sessions/current-id'
            )
            clipboard.reset_mock()
            runs['next'] = {'status': 'enrolling'}
            self.controller.value['active_run_id'] = 'next'
            tab.copy_link.click()
            clipboard.assert_not_called()
        self.assertEqual(tab.run_id.text(), '')
        self.assertFalse(tab.copy_link.isEnabled())
        self.assertIn('Registering session', tab.delivery.text())

    def test_completed_run_delivery_remains_visible_without_copy_action(self):
        tab = self.tab()
        self.controller.value['delivery'] = {'configured': True, 'runs': {'ended': {
            'session_id': 'old-id', 'status': 'finish_unconfirmed', 'finish_requested': True,
        }}}
        tab.refresh()
        self.assertIn('Last report', tab.delivery.text())
        self.assertIn('unconfirmed', tab.delivery.text())
        self.assertFalse(tab.copy_link.isEnabled())

    def test_report_process_access_separates_negotiation_from_local_etw(self):
        tab = self.tab()
        run = {'status': 'enrolling', 'direct_open_negotiated': None,
               'direct_open_available': False}
        self.controller.value.update(state='observing', enabled=True, active_run_id='run',
                                     process_access={'mode': 'healthy'},
                                     delivery={'configured': True, 'runs': {'run': run}})
        tab.refresh()
        self.assertIn('negotiation pending', tab.report_access.text())
        self.assertIn('Local ETW: Observing', tab.coverage.text())
        run['direct_open_negotiated'] = False
        tab.refresh()
        self.assertIn('snapshots only', tab.report_access.text())
        run['direct_open_negotiated'] = True
        tab.refresh()
        self.assertIn('pending or unavailable', tab.report_access.text())
        run['direct_open_available'] = True
        tab.refresh()
        self.assertIn('ETW negotiated', tab.report_access.text())
        run.update(status='finished', session_id='closed', finish_requested=True, direct_open_available=False)
        self.controller.value.update(enabled=False, active_run_id=None)
        tab.refresh()
        self.assertIn('Last report', tab.delivery.text())
        self.assertIn('pending or unavailable', tab.report_access.text())

    def test_security_audit_current_and_completed_results_are_local_and_distinct(self):
        tab = self.tab()
        self.assertTrue(tab.security_audit.isHidden())
        completed = {'status': 'partial', 'restoration': 'verified',
                     'confirmed': {'readRecords': 2, 'writeRecords': 1},
                     'ambiguous': {'readRecords': 3, 'writeRecords': 0},
                     'issues': ['journal_gap']}
        self.controller.value.update(last_security_audit=completed,
                                     security_audit={'status': 'collecting', 'restoration': 'pending'})
        tab.refresh()
        self.assertIn('Collecting', tab.security_audit.text())
        self.assertNotIn('2 read records', tab.security_audit.text())
        self.controller.value['security_audit'] = None
        tab.refresh()
        self.assertFalse(tab.security_audit.isHidden())
        self.assertIn('Last Security 4663 result (local)', tab.security_audit.text())
        self.assertIn('Partial coverage', tab.security_audit.text())
        self.assertIn('Confirmed: 2 read records, 1 write records', tab.security_audit.text())
        self.assertIn('Ambiguous: 3 read records, 0 write records', tab.security_audit.text())
        self.assertIn('Restoration: Verified', tab.security_audit.text())
        self.assertIn('exercised access rights', tab.security_audit.toolTip())
        self.assertIn('Path-only matches are ambiguous', tab.security_audit.toolTip())
        self.assertIn('stays local', tab.security_audit.toolTip())
        self.assertIn('journal_gap', tab.security_audit.text())
        self.controller.value['security_audit'] = {'status': 'armed', 'restoration': 'pending'}
        tab.refresh()
        self.assertIn('Last Security 4663 result (local)', tab.security_audit.text())

    def test_security_audit_unknown_and_missing_fields_do_not_imply_zero_counts(self):
        tab = self.tab()
        self.controller.value['security_audit'] = {'status': 'unavailable',
                                                    'restoration': 'failed',
                                                    'confirmed': {}}
        tab.refresh()
        self.assertIn('Unavailable', tab.security_audit.text())
        self.assertIn('Restoration: Failed', tab.security_audit.text())
        self.assertNotIn('read records', tab.security_audit.text())

    def test_recording_report_action_rechecks_the_selected_recording(self):
        shown = ValidatorReport('https://validator.example/v2/sessions/shown', '2026-11-11T18:42:00Z', 'finished')
        selection = [shown]
        strip = ValidatorReportStrip(lambda: selection[0])
        self.addCleanup(strip.deleteLater)
        strip.update_report(shown)
        with patch('ui.validator_reports.QDesktopServices.openUrl') as open_url:
            selection[0] = None
            strip.action.click()
            open_url.assert_not_called()
            selection[0] = shown
            strip.action.click()
            self.assertEqual(open_url.call_args.args[0].toString(), shown.url)
