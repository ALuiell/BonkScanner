"""Data-loss regressions and a real second-process read-only session."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import src  # noqa: F401
from app.config_repository import ConfigRepository
from infra import data_storage as storage


class ProfilePersistenceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        context = storage.StorageContext("source", self.root, self.root, None, None)
        self.lock = storage._ProcessFileLock(self.root / storage.DATA_LOCK_NAME)
        self.assertTrue(self.lock.acquire())
        self.addCleanup(self.lock.release)
        for name, value in (("_context", context), ("_active_lock", self.lock)):
            patched = patch.object(storage, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def write_profile(self):
        original = b'{"TOTAL_REROLLS":123,"TEMPLATES":[{"id":1,"name":"CUSTOM","sm_total":17}],"ACTIVE_TEMPLATES":["CUSTOM"]}'
        self.path.write_bytes(original)
        return original

    def test_uninitialized_and_failed_load_cannot_replace_a_profile(self):
        for raw in (b'{"preserve":true}', b'{broken', b'[]'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                repository = ConfigRepository(self.path)
                self.assertFalse(repository.commit({}).success)
                loaded = repository.load()
                if raw != b'{"preserve":true}':
                    self.assertTrue(loaded.error)
                    self.assertFalse(repository.commit({}).success)
                self.assertEqual(self.path.read_bytes(), raw)

    def test_one_read_failure_does_not_authorize_a_later_write(self):
        original = self.write_profile()
        repository = ConfigRepository(self.path)
        with patch.object(Path, "read_bytes", side_effect=PermissionError("temporary denial")):
            self.assertTrue(repository.load().error)
        self.assertFalse(repository.commit({}).success)
        self.assertEqual(self.path.read_bytes(), original)

    def test_stat_failure_is_a_load_error_and_preserves_the_file(self):
        original = self.write_profile()
        repository = ConfigRepository(self.path)
        with patch.object(Path, "is_file", side_effect=PermissionError("temporary denial")):
            self.assertTrue(repository.load().error)
        self.assertFalse(repository.commit({}).success)
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_config_with_a_backup_is_not_treated_as_a_new_profile(self):
        backup = self.root / "config.json.bak"
        original = b'{"TOTAL_REROLLS":123}'
        backup.write_bytes(original)
        repository = ConfigRepository(self.path)
        self.assertTrue(repository.load().error)
        self.assertFalse(repository.commit({}).success)
        self.assertFalse(self.path.exists())
        self.assertEqual(backup.read_bytes(), original)

    def test_profile_migration_keeps_the_single_backup(self):
        original = self.write_profile()
        backup = self.root / "config.json.bak"
        backup.write_bytes(original)
        sources = dict((relative, path) for path, relative in storage._migration_sources(self.root))
        self.assertEqual(sources[Path("config.json.bak")], backup)

    def test_utf8_bom_is_read_without_losing_settings(self):
        original = self.write_profile()
        self.path.write_bytes(b'\xef\xbb\xbf' + original)
        repository = ConfigRepository(self.path)
        loaded = repository.load()
        self.assertFalse(loaded.error)
        self.assertEqual(loaded.snapshot["TOTAL_REROLLS"], 123)
        self.assertTrue(repository.commit(loaded.snapshot).success)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8-sig")), loaded.snapshot)

    def test_stale_snapshot_cannot_replace_a_newer_file(self):
        self.write_profile()
        first, second = ConfigRepository(self.path), ConfigRepository(self.path)
        first.load()
        second.load()
        self.assertTrue(first.update(lambda cfg: cfg.update(TOTAL_REROLLS=124)).success)
        latest = self.path.read_bytes()
        result = second.update(lambda cfg: cfg.update(HOTKEY="f7"))
        self.assertFalse(result.success)
        self.assertEqual(self.path.read_bytes(), latest)

    def test_successful_load_is_insufficient_without_profile_ownership(self):
        original = self.write_profile()
        repository = ConfigRepository(self.path)
        repository.load()
        with patch.object(storage, "_active_lock", None):
            self.assertFalse(repository.commit({}).success)
        self.assertEqual(self.path.read_bytes(), original)

    def test_a_helper_cannot_write_another_selected_or_busy_profile(self):
        original = self.write_profile()
        repository = ConfigRepository(self.path)
        repository.load()
        with patch.object(storage, "_context", None):
            self.assertFalse(repository.commit({}).success)
        self.assertEqual(self.path.read_bytes(), original)

    def test_read_only_credentials_are_temporary_without_touching_the_vault(self):
        from infra import supporter_credentials as supporter, twitch_credentials as twitch
        storage.mark_profile_read_only(storage.PROFILE_IN_USE)
        for module, field, setter, getter, remover in (
            (supporter, "_session_key", supporter.set_supporter_access_key,
             supporter.get_supporter_access_key, supporter.delete_supporter_access_key),
            (twitch, "_session_token", twitch.set_twitch_oauth_token,
             twitch.get_twitch_oauth_token, twitch.delete_twitch_oauth_token),
        ):
            with patch.object(module, field, None), patch.object(module, "_set_windows_credential", side_effect=AssertionError("vault write")), patch.object(module, "_delete_windows_credential", side_effect=AssertionError("vault delete")):
                setter("temporary")
                self.assertEqual(getter(), "temporary")
                remover()
                self.assertEqual(getter(), "")

    def test_simultaneous_storage_bootstrap_uses_a_read_only_context(self):
        original = self.write_profile()
        state_lock = storage._ProcessFileLock(self.root / storage.STATE_LOCK_NAME)
        self.assertTrue(state_lock.acquire())
        try:
            selected = storage._load_selected_context(self.root / "installation", self.root, "other")
            self.assertTrue(selected.read_only)
            self.assertEqual(selected.data_dir, self.root)
            self.assertEqual(self.path.read_bytes(), original)
        finally:
            state_lock.release()

    def test_backup_is_one_reused_file_and_noop_saves_do_not_rewrite(self):
        self.write_profile()
        repository = ConfigRepository(self.path)
        repository.load()
        for count in range(124, 129):
            before = self.path.read_bytes()
            self.assertTrue(repository.update(lambda cfg: cfg.update(TOTAL_REROLLS=count)).success)
            self.assertEqual((self.root / "config.json.bak").read_bytes(), before)
        stamp = self.path.stat().st_mtime_ns
        self.assertTrue(repository.commit(repository.snapshot()).success)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)
        self.assertEqual(sorted(p.name for p in self.root.glob("config.json.*")), ["config.json.bak"])

    def test_bootstrap_keeps_bad_or_temporarily_unreadable_files(self):
        self.lock.release()
        script = r'''
import sys
from pathlib import Path
from unittest.mock import patch
from infra import data_storage as storage
root=Path(sys.argv[1]); target=root/'config.json'
with patch.object(storage,'is_frozen_build',return_value=True), patch.object(storage,'installation_directory',return_value=root/'installation'), patch.object(storage,'recommended_data_directory',return_value=root):
    storage.initialize_storage()
from app import config
original=target.read_bytes()
original_read=Path.read_bytes
failed=False
def once(path):
    global failed
    if path==target and not failed:
        failed=True
        raise PermissionError('temporary read failure')
    return original_read(path)
if sys.argv[2]=='denial':
    with patch.object(Path,'read_bytes',once): result=config.initialize_config()
else:
    result=config.initialize_config()
assert result.error
assert config.profile_read_only_reason()
assert storage.storage_context().read_only
assert config.update_config(lambda cfg: cfg.update(HOTKEY='f12')).success
assert target.read_bytes()==original
assert not (root/'config.json.bak').exists()
storage.release_storage_lock()
'''
        for mode, raw in (("json", b'{broken'), ("root", b'[]'), ("denial", b'{"TOTAL_REROLLS":123}')):
            with self.subTest(mode=mode):
                self.path.write_bytes(raw)
                result = subprocess.run([sys.executable, "-c", script, str(self.root), mode],
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.path.read_bytes(), raw)

    def test_second_process_reads_but_cannot_mutate_and_never_promotes_itself(self):
        original = self.write_profile()
        (self.root / storage.STATE_LOCK_NAME).write_bytes(b'0')
        (self.root / "merchant_history.jsonl").write_bytes(b'{incomplete')
        (self.root / "supporter_access_cache.json").write_text('{"preserved":true}')
        def snapshot():
            return {p.name: None if p.name.endswith('.lock') else p.read_bytes()
                    for p in self.root.iterdir() if p.is_file()}
        before = snapshot()
        script = r'''
import sys
from pathlib import Path
from unittest.mock import patch
from infra import data_storage as storage
root = Path(sys.argv[1])
with patch.object(storage, 'is_frozen_build', return_value=True), patch.object(storage, 'installation_directory', return_value=root / 'installation'), patch.object(storage, 'recommended_data_directory', return_value=root):
    context = storage.initialize_storage()
assert context.read_only
from app import config
result = config.initialize_config()
assert not result.error and config.ACTIVE_TEMPLATES == ['CUSTOM']
assert config.update_config(lambda cfg: cfg.update(HOTKEY='f12')).success
assert config.user_config['HOTKEY'] == 'f12'
from app.settings import ConfigRecordingSettings
settings = ConfigRecordingSettings()
settings.read_metadata_index()
settings.write_metadata_index({'version':1,'records':[]})
from infra.merchant_history_store import MerchantHistoryStore
from infra.roll_history_store import RollHistoryStore
merchant, rolls = MerchantHistoryStore(), RollHistoryStore()
assert not merchant.writable and not rolls.writable
merchant.close(); rolls.close()
from infra.supporter_access_cache import write_access_cache, delete_access_cache
write_access_cache({'changed':True}); delete_access_cache()
from infra.vod_storage import VodRecorder, delete_vod
for action in (lambda: VodRecorder().start(), lambda: delete_vod(root/'merchant_history.jsonl')):
    try: action()
    except PermissionError: pass
    else: raise AssertionError('Reader mutated profile')
assert not storage.request_migration(root/'elsewhere').success
assert not storage.cancel_migration().success
assert not storage.remove_legacy_data().success
with patch.object(config,'update_game_reset_time',side_effect=AssertionError('game config write')):
    assert config.save_settings_with_game_reset({'RESET_HOLD_DURATION':0.1},0.01,sync_game=True).success
print('READER_READY',flush=True)
sys.stdin.readline()
assert storage.initialize_storage().read_only
assert config.update_config(lambda cfg: cfg.update(HOTKEY='f11')).success
print('STILL_READ_ONLY',flush=True)
'''
        process = subprocess.Popen([sys.executable, "-u", "-c", script, str(self.root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "READER_READY")
            self.lock.release()
            output, error = process.communicate("continue\n", timeout=25)
            self.assertEqual(process.returncode, 0, error)
            self.assertIn("STILL_READ_ONLY", output)
            self.assertEqual(snapshot(), before)
            self.assertEqual(self.path.read_bytes(), original)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
