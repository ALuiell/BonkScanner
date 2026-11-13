"""Host adapter and early worker dispatch; core tests live in the package repo."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SOURCE = str(Path(__file__).resolve().parents[1])


class ValidatorIntegrationTests(unittest.TestCase):
    def test_adapter_passes_host_version_without_starting_observation(self):
        from app.validator import create_validator_controller
        from app.version import CURRENT_VERSION
        controller = create_validator_controller()
        self.assertIsNotNone(controller)
        self.assertEqual(controller._scanner_version, CURRENT_VERSION)
        self.assertEqual(controller.snapshot()['state'], 'disabled')
        self.assertIsNone(controller._reader)
        self.assertIsNone(controller._sender)

    def test_scanner_adapter_works_without_optional_package(self):
        code = "from app.validator import create_validator_controller; assert create_validator_controller() is None"
        result = subprocess.run([sys.executable, '-I', '-S', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);' + code, SOURCE],
            capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_broken_optional_installation_is_not_silently_ignored(self):
        import builtins
        from app.validator import create_validator_controller
        original = builtins.__import__

        def broken(name, *args, **kwargs):
            if name == 'bonkscanner_validator.controller':
                raise ModuleNotFoundError('broken dependency', name='missing_dependency')
            return original(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=broken):
            with self.assertRaises(ModuleNotFoundError):
                create_validator_controller()

    def test_worker_dispatch_without_optional_package_exits_before_gui(self):
        code = """
import runpy,sys
sys.path.insert(0,sys.argv[1])
sys.argv=['main.py','--validator-worker']
try:runpy.run_path(sys.path[0]+'/main.py',run_name='__main__')
except SystemExit as exc:assert exc.code==4
else:raise AssertionError('worker dispatch continued')
assert not any(name in sys.modules for name in ('gui_app','PySide6','app.config','infra.crash_journal'))
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-c', code, SOURCE],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_early_dispatch_imports_no_profile_gui_crash_or_restart(self):
        code = r'''
import sys,runpy
sys.path.insert(0,sys.argv[1])
sys.argv=['main.py','--validator-worker','--invalid']
try:runpy.run_path(sys.path[0]+'/main.py',run_name='__main__')
except SystemExit:pass
for name in ('infra.crash_journal','infra.data_storage','infra.app_restart','app.config','gui_app','keyboard','PySide6'):
    assert name not in sys.modules,name
print('isolated')
'''
        result = subprocess.run([sys.executable, "-I", "-c", code, SOURCE], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"isolated", result.stdout)

    def test_audit_recovery_dispatch_stays_outside_scanner_runtime(self):
        code = r'''
import os,runpy,sys
from bonkscanner_validator import audit_recovery
sys.path.insert(0,sys.argv[1])
sys.argv=['main.py','--validator-audit-recovery','1','2','3','4']
def recovery(arguments):
    assert arguments == ['1','2','3','4']
    for name in ('infra.crash_journal','infra.data_storage','app.config','gui_app','PySide6'):
        assert name not in sys.modules,name
    return 17
audit_recovery.main=recovery
runpy.run_path(sys.path[0]+'/main.py',run_name='__main__')
'''
        result = subprocess.run([sys.executable, "-c", code, SOURCE],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
