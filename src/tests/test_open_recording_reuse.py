"""Open panes may share disk snapshots, without retaining closed/stale runs."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

import src  # noqa: F401
from app.latest_wins_loader import LoadCancelled
from app.prepared_recording import load_and_prepare_recording
from app.vod_library import VodLibrary
from infra.vod_storage import load_vod, UnsupportedVodVersionError


class OpenRecordingReuseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'run.jsonl'
        self.library = VodLibrary(load_cached=tuple, refresh_index=tuple)
        self.write('First')

    def write(self, name, *, path=None, version=12):
        (path or self.path).write_text(json.dumps({
            'type': 'metadata', 'version': version, 'name': name,
            'created_at': '2026-10-25T12:00:00',
        }) + '\n' + json.dumps({
            'type': 'snapshot', 'elapsed_seconds': 10, 'captured_at': 10, 'stats': {},
        }) + '\n', encoding='utf-8')

    def test_open_panes_share_the_same_snapshots_and_keep_their_projections(self):
        with patch('app.vod_library.load_vod', wraps=load_vod) as read:
            a = load_and_prepare_recording(self.path, series_keys=('kills',),
                                          load_recording=self.library.load_recording)
            b = load_and_prepare_recording(self.path, series_keys=('luck',),
                                          load_recording=self.library.load_recording)
        self.assertEqual(read.call_count, 1)
        self.assertIs(a.vod, b.vod)
        self.assertEqual(a.series_signature, ('kills',))
        self.assertEqual(b.series_signature, ('luck',))
        self.assertIsNot(a.scrubber_model, b.scrubber_model)

    def test_closed_runs_are_not_retained(self):
        loaded = self.library.load_recording(self.path)
        reference = weakref.ref(loaded)
        del loaded
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(len(self.library._open_recordings), 0)

    def test_changed_file_is_read_again_even_while_old_pane_remains_open(self):
        old = self.library.load_recording(self.path)
        self.write('Changed recording')
        new = self.library.load_recording(self.path)
        self.assertIsNot(old, new)
        self.assertEqual(new.metadata.name, 'Changed recording')

    def test_replaced_file_with_same_size_and_timestamp_is_read_again(self):
        old = self.library.load_recording(self.path)
        signature = self.path.stat()
        replacement = self.path.with_name('replacement.jsonl')
        self.write('Other', path=replacement)
        os.utime(replacement, ns=(signature.st_atime_ns, signature.st_mtime_ns))
        self.assertEqual(replacement.stat().st_size, signature.st_size)
        os.replace(replacement, self.path)
        new = self.library.load_recording(self.path)
        self.assertIsNot(old, new)
        self.assertEqual(new.metadata.name, 'Other')

    def test_deleted_file_is_not_returned_from_open_pane(self):
        old = self.library.load_recording(self.path)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.library.load_recording(self.path)
        self.assertEqual(old.metadata.name, 'First')

    def test_version_gate_is_rechecked_after_file_changes(self):
        old = self.library.load_recording(self.path)
        self.write('Future version', version=999)
        with self.assertRaises(UnsupportedVodVersionError):
            self.library.load_recording(self.path)
        self.assertEqual(old.metadata.name, 'First')

    def test_file_changed_during_read_is_not_cached(self):
        def changing_read(path, **kwargs):
            loaded = load_vod(path, **kwargs)
            self.write('Changed during read')
            return loaded
        with patch('app.vod_library.load_vod', side_effect=changing_read):
            old = self.library.load_recording(self.path)
        new = self.library.load_recording(self.path)
        self.assertIsNot(old, new)
        self.assertEqual(new.metadata.name, 'Changed during read')

    def test_cache_hit_still_honors_cancellation(self):
        old = self.library.load_recording(self.path)
        with self.assertRaises(LoadCancelled):
            self.library.load_recording(self.path, cancelled=lambda: True)
        checks = iter((False, True))
        with self.assertRaises(LoadCancelled):
            self.library.load_recording(self.path, cancelled=lambda: next(checks))
        self.assertIs(self.library.load_recording(self.path), old)

    def test_failure_does_not_poison_the_next_request(self):
        with patch('app.vod_library.load_vod', side_effect=ValueError('broken')):
            with self.assertRaisesRegex(ValueError, 'broken'):
                self.library.load_recording(self.path)
        self.assertEqual(self.library.load_recording(self.path).metadata.name, 'First')

    def test_two_cold_requests_do_not_hold_cache_lock_during_parsing(self):
        entered = threading.Barrier(2)
        cancelled = threading.Event()
        results, errors = [], []
        def worker(cancel=None):
            try: results.append(self.library.load_recording(self.path, cancelled=cancel))
            except Exception as exc: errors.append(exc)
        # One request cancelling must not cancel or block the other lane.
        def cancelled_read(path, **kwargs):
            entered.wait(timeout=3)
            if kwargs.get('cancelled') is not None:
                cancelled.set()
            return load_vod(path)
        with patch('app.vod_library.load_vod', side_effect=cancelled_read):
            workers = [threading.Thread(target=worker, args=(cancelled.is_set,)),
                       threading.Thread(target=worker)]
            for thread in workers: thread.start()
            for thread in workers: thread.join(timeout=4)
        self.assertFalse(any(thread.is_alive() for thread in workers))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LoadCancelled)
