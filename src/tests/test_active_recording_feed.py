from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import src  # noqa: F401 -- repository path bootstrap

from app.active_recording_feed import (
    DISCARDED,
    FINALIZE_FAILED,
    FINALIZED,
    RECORDING,
    ActiveRecordingFeed,
)
from app.vod_library import VodLibrary
from infra.vod_storage import VodMetadata, VodSnapshot
from tests.support.player_stats import build_recordings_tab
from ui.tabs.player_stats import recordings as recordings_module


def _metadata(path: Path, count: int = 0) -> VodMetadata:
    return VodMetadata(
        path=path,
        name="Live run",
        created_at="2026-09-17T12:00:00",
        interval_seconds=10,
        duration_seconds=count * 10,
        snapshot_count=count,
        character_id=7,
        character_name="CL4NK",
    )


def _snapshot(index: int) -> VodSnapshot:
    return VodSnapshot(index * 10, float(index), {}, game_time_seconds=index * 10.0)


class ActiveRecordingFeedTests(unittest.TestCase):
    def test_start_append_finalize_keeps_snapshot_identity_and_monotonic_revision(self):
        feed = ActiveRecordingFeed()
        path = Path("live.jsonl")
        events = []
        token = feed.subscribe(events.append, lambda callback: callback())
        first = _snapshot(1)
        second = _snapshot(2)

        started = feed.start(_metadata(path))
        appended_one = feed.append(_metadata(path, 1), first)
        appended_two = feed.append(_metadata(path, 2), second)
        finalized = feed.finalize(_metadata(path, 2))
        feed.unsubscribe(token)

        self.assertEqual(RECORDING, started.status)
        self.assertEqual(FINALIZED, finalized.status)
        self.assertEqual(
            sorted(state.revision for state in events),
            [state.revision for state in events],
        )
        self.assertIs(first, appended_two.snapshots[0])
        self.assertIs(second, appended_two.snapshots[1])
        self.assertEqual(2, finalized.metadata.snapshot_count)
        self.assertIsNone(feed.active_state)

    def test_discard_and_finalize_failure_publish_terminal_state(self):
        feed = ActiveRecordingFeed()
        path = Path("live.jsonl")
        feed.start(_metadata(path))
        discarded = feed.discard("deleted_short")
        self.assertEqual(DISCARDED, discarded.status)
        self.assertEqual("deleted_short", discarded.detail)

        feed.start(_metadata(path))
        failed = feed.fail_finalize(OSError("disk full"))
        self.assertEqual(FINALIZE_FAILED, failed.status)
        self.assertIn("disk full", failed.detail)
        self.assertEqual((), failed.snapshots)

    def test_new_run_releases_finalized_snapshots_but_retains_failed_finalize(self):
        feed = ActiveRecordingFeed()
        first = Path("first.jsonl")
        second = Path("second.jsonl")
        feed.start(_metadata(first))
        feed.append(_metadata(first, 1), _snapshot(1))
        feed.finalize(_metadata(first, 1))
        feed.start(_metadata(second))
        self.assertIsNone(feed.state_for(first))

        feed.fail_finalize("disk full")
        feed.start(_metadata(first))
        self.assertEqual(FINALIZE_FAILED, feed.state_for(second).status)

    def test_finalize_failed_path_remains_protected_in_library(self):
        feed = ActiveRecordingFeed()
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=tuple,
            active_recording_feed=feed,
        )
        path = Path("failed.jsonl")
        feed.start(_metadata(path))
        feed.fail_finalize("disk full")
        self.assertTrue(library.is_active_path(path))
        self.assertFalse(library.is_live_path(path))

    def test_library_append_repaints_without_metadata_refresh_or_invalidation(self):
        feed = ActiveRecordingFeed()
        refreshes = []
        invalidations = []
        live_repaints = []
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=lambda: refreshes.append(True) or (),
            active_recording_feed=feed,
        )
        library.subscribe(
            invalidate=lambda: invalidations.append(True),
            repaint=lambda: None,
            live_repaint=lambda: live_repaints.append(True),
        )
        path = Path(tempfile.gettempdir()) / "bonkscanner-live-test.jsonl"

        feed.start(_metadata(path))
        feed.append(_metadata(path, 1), _snapshot(1))

        self.assertEqual([], refreshes)
        self.assertEqual([], invalidations)
        self.assertEqual(2, len(live_repaints))
        self.assertEqual(1, library.index[0].snapshot_count)
        self.assertTrue(library.is_active_path(path))


class RecordingsLiveFeedTests(unittest.TestCase):
    def test_active_run_opens_from_memory_and_manual_scrub_keeps_index_on_sync(self):
        feed = ActiveRecordingFeed()
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=tuple,
            active_recording_feed=feed,
        )
        tab = build_recordings_tab(
            vod_library=library,
            active_recording_feed=feed,
        )
        tab.refresh_loaded_vod_ui = MagicMock()
        tab.refresh_vods_list = MagicMock()
        path = Path(tempfile.gettempdir()) / "bonkscanner-live-ui.jsonl"
        feed.start(_metadata(path))
        feed.append(_metadata(path, 1), _snapshot(1))
        feed.append(_metadata(path, 2), _snapshot(2))

        with patch.object(
            recordings_module,
            "load_vod",
            side_effect=AssertionError("active run must not read JSONL"),
        ) as disk_load:
            tab.load_selected_vod(path)

        disk_load.assert_not_called()
        self.assertEqual(1, tab._snapshot_index)
        self.assertTrue(tab._live_follow)

        # A manual historical selection disables only Follow Live.
        tab.on_scrub_index_changed(1)
        self.assertFalse(tab._live_follow)
        self.assertTrue(tab._live_auto_sync)

        tab._live_auto_sync = False
        feed.append(_metadata(path, 3), _snapshot(3))
        self.assertEqual(2, len(tab._loaded_vod.snapshots))
        self.assertIsNotNone(tab._live_pending_state)

        tab._on_live_sync_clicked()
        self.assertEqual(3, len(tab._loaded_vod.snapshots))
        self.assertEqual(1, tab._snapshot_index)

    def test_queued_feed_event_is_ignored_after_tab_destruction(self):
        feed = ActiveRecordingFeed()
        scheduled = []
        tab = build_recordings_tab(
            active_recording_feed=feed,
            schedule=scheduled.append,
        )
        path = Path(tempfile.gettempdir()) / "bonkscanner-destroyed-live-ui.jsonl"
        feed.start(_metadata(path))
        self.assertEqual(1, len(scheduled))

        tab._on_tab_destroyed()
        scheduled.pop()()

        self.assertTrue(tab._disposed)
        self.assertIsNone(tab._loading_path)


if __name__ == "__main__":
    unittest.main()
