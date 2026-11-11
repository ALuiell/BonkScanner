import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QWidget

from app import config
from ui.validator import SETTINGS_KEY, ValidatorTab


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

    def test_header_opens_tab_and_default_startup_is_off(self):
        tab = self.tab()
        tabs = QTabWidget()
        self.addCleanup(tabs.deleteLater)
        tabs.addTab(QWidget(), 'Recordings')
        tab.add_to(tabs)
        self.assertEqual(tabs.currentIndex(), 0)
        self.button.click()
        self.assertIs(tabs.currentWidget(), tab)
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
