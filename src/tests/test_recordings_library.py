"""What the recordings library decides, separately from how it draws it.

The panel's three questions -- which recordings a search shows, how many the
auto-filter threshold would remove, and how much disk the library uses -- are
free functions precisely so they can be answered here without Qt. Building the
tab inside the suite's own process is what `test_recordings_layout.py` runs in
a **subprocess** for: the widget tree outlives the test and takes the
interpreter down later, which surfaces as a segfault in an unrelated file
rather than as a failure. The rendered panel is asserted on over there.

The one that is easy to get wrong and invisible by eye: the footer describes
the *library*, not the filtered view. A three-letter search must not turn
"28 recordings" into "3".
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app.vod_library import VodLibrary
from app.shutdown import ShutdownDeadline
from ui.tabs.player_stats.recordings import (
    RecordingsTab,
    _format_bytes,
    filter_recordings,
    library_size_bytes,
    short_recording_count,
)


def _vod(name: str, *, snapshots: int = 100, path: Path | None = None):
    return SimpleNamespace(
        name=name,
        snapshot_count=snapshots,
        duration_seconds=600,
        path=path if path is not None else Path("nowhere") / f"{name}.jsonl",
    )


VODS = (
    _vod("950k", snapshots=713),
    _vod("970k", snapshots=744),
    _vod("Run 2026-07-29 00:18", snapshots=6),
)


class SearchTests(unittest.TestCase):
    def test_an_empty_query_shows_everything(self) -> None:
        self.assertEqual(len(filter_recordings(VODS, "")), 3)
        self.assertEqual(len(filter_recordings(VODS, "   ")), 3)

    def test_a_query_matches_a_substring_of_the_name(self) -> None:
        self.assertEqual([vod.name for vod in filter_recordings(VODS, "k")], ["950k", "970k"])

    def test_matching_ignores_case(self) -> None:
        self.assertEqual([vod.name for vod in filter_recordings(VODS, "RUN")], ["Run 2026-07-29 00:18"])

    def test_no_match_is_an_empty_list_not_everything(self) -> None:
        self.assertEqual(filter_recordings(VODS, "nothing matches"), [])


class ShortRecordingCountTests(unittest.TestCase):
    def test_counts_what_the_threshold_would_remove(self) -> None:
        self.assertEqual(short_recording_count(VODS, 100), 1)
        self.assertEqual(short_recording_count(VODS, 720), 2)

    def test_the_threshold_is_the_shortest_run_kept(self) -> None:
        """Same boundary the recorder uses: `< threshold`, not `<=`."""
        self.assertEqual(short_recording_count((_vod("a", snapshots=6),), 6), 0)
        self.assertEqual(short_recording_count((_vod("a", snapshots=6),), 7), 1)

    def test_a_threshold_of_zero_removes_nothing(self) -> None:
        self.assertEqual(short_recording_count(VODS, 0), 0)

    def test_a_negative_threshold_cannot_select_recordings(self) -> None:
        self.assertEqual(short_recording_count(VODS, -10), 0)


class _FakeTextWidget:
    def __init__(self) -> None:
        self.value = ""
        self.enabled = None

    def setText(self, value: str) -> None:
        self.value = value

    def setEnabled(self, value: bool) -> None:
        self.enabled = bool(value)


class CleanupButtonStateTests(unittest.TestCase):
    def test_cleanup_stays_available_when_the_current_threshold_matches_nothing(self) -> None:
        button = _FakeTextWidget()
        tab = SimpleNamespace(
            _library_summary_label=_FakeTextWidget(),
            _cleanup_btn=button,
            _refresh_recordings_chooser=lambda: None,
        )

        RecordingsTab._refresh_library_footer(tab, VODS)

        self.assertEqual(button.value, "Recording cleanup")
        self.assertTrue(button.enabled)

    def test_cleanup_is_disabled_only_for_an_empty_library(self) -> None:
        button = _FakeTextWidget()
        tab = SimpleNamespace(
            _library_summary_label=_FakeTextWidget(),
            _cleanup_btn=button,
            _refresh_recordings_chooser=lambda: None,
        )

        RecordingsTab._refresh_library_footer(tab, ())

        self.assertFalse(button.enabled)


class LibrarySizeTests(unittest.TestCase):
    def test_sums_the_files_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.jsonl").write_text("x" * 100, encoding="utf-8")
            (root / "b.jsonl").write_text("x" * 50, encoding="utf-8")
            vods = (_vod("a", path=root / "a.jsonl"), _vod("b", path=root / "b.jsonl"))

            self.assertEqual(library_size_bytes(vods), 150)

    def test_a_missing_file_is_skipped_rather_than_raising(self) -> None:
        """The index can name a file a moment after something deleted it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.jsonl").write_text("x" * 100, encoding="utf-8")
            vods = (_vod("a", path=root / "a.jsonl"), _vod("gone", path=root / "gone.jsonl"))

            self.assertEqual(library_size_bytes(vods), 100)


class FormatBytesTests(unittest.TestCase):
    def test_scales_to_a_readable_unit(self) -> None:
        self.assertEqual(_format_bytes(512), "512 B")
        self.assertEqual(_format_bytes(2048), "2 KB")
        self.assertEqual(_format_bytes(5 * 1024 * 1024), "5.0 MB")

    def test_zero_and_negative_do_not_produce_nonsense(self) -> None:
        self.assertEqual(_format_bytes(0), "0 B")
        self.assertEqual(_format_bytes(-1), "0 B")


class VodLibraryLifecycleTests(unittest.TestCase):
    def test_shutdown_joins_with_deadline_and_drops_the_ui_callback(self) -> None:
        started = threading.Event()
        release = threading.Event()
        scheduled = []

        def refresh():
            started.set()
            release.wait(2.0)
            return (_vod("late"),)

        library = VodLibrary(
            load_cached=tuple,
            refresh_index=refresh,
            schedule=scheduled.append,
        )
        self.addCleanup(release.set)
        library.ensure_refresh()
        self.assertTrue(started.wait(1.0))

        pending = library.shutdown(ShutdownDeadline.after(0.0))
        release.set()
        finished = library.shutdown(ShutdownDeadline.after(1.0))

        self.assertEqual(pending, ("vod-metadata-index",))
        self.assertEqual(finished, ())
        self.assertEqual(scheduled, [])

    @staticmethod
    def _run_threads_inline():
        class ImmediateThread:
            def __init__(self, *, target, **_kwargs) -> None:
                self.target = target

            def start(self) -> None:
                self.target()

        return patch("app.vod_library.threading.Thread", ImmediateThread)

    def test_one_broken_subscriber_does_not_latch_or_starve_the_others(self) -> None:
        scheduled = []
        calls = []
        failures = []
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=lambda: (_vod("fresh"),),
            schedule=scheduled.append,
        )
        library.subscribe(
            invalidate=lambda: (_ for _ in ()).throw(RuntimeError("disposed tab")),
            repaint=lambda: calls.append("broken repaint still attempted"),
            failed=lambda error: failures.append(str(error)),
        )
        library.subscribe(
            invalidate=lambda: calls.append("good invalidate"),
            repaint=lambda: calls.append("good repaint"),
        )

        with self._run_threads_inline():
            library.ensure_refresh()
        scheduled.pop(0)()

        self.assertEqual(["fresh"], [vod.name for vod in library.index])
        self.assertEqual(
            ["good invalidate", "broken repaint still attempted", "good repaint"],
            calls,
        )
        self.assertEqual(["disposed tab"], failures)
        self.assertFalse(library._refreshing)

        # The failed callback did not permanently disable later refreshes.
        with self._run_threads_inline():
            library.ensure_refresh()
        self.assertEqual(1, len(scheduled))

    def test_failure_listener_exceptions_are_contained(self) -> None:
        scheduled = []
        observed = []
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=lambda: (_ for _ in ()).throw(OSError("index failed")),
            schedule=scheduled.append,
        )
        library.subscribe(
            invalidate=lambda: None,
            repaint=lambda: None,
            failed=lambda _error: (_ for _ in ()).throw(RuntimeError("dead label")),
        )
        library.subscribe(
            invalidate=lambda: None,
            repaint=lambda: None,
            failed=lambda error: observed.append(str(error)),
        )

        with self._run_threads_inline():
            library.ensure_refresh()
        scheduled.pop(0)()

        self.assertEqual(["index failed"], observed)
        self.assertFalse(library._refreshing)

    def test_thread_start_failure_restores_refresh_guard(self) -> None:
        failures = []
        library = VodLibrary(load_cached=tuple, refresh_index=tuple)
        library.subscribe(
            invalidate=lambda: None,
            repaint=lambda: None,
            failed=lambda error: failures.append(str(error)),
        )

        with patch(
            "app.vod_library.threading.Thread",
            side_effect=RuntimeError("thread unavailable"),
        ):
            library.ensure_refresh()

        self.assertEqual(["thread unavailable"], failures)
        self.assertFalse(library._refreshing)

    def test_dropped_ui_schedule_restores_refresh_guard(self) -> None:
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=lambda: (_vod("fresh"),),
            schedule=lambda _callback: False,
        )

        with self._run_threads_inline():
            library.ensure_refresh()

        self.assertFalse(library._refreshing)
        self.assertEqual([], list(library.index))

    def test_raising_ui_schedule_restores_refresh_guard(self) -> None:
        library = VodLibrary(
            load_cached=tuple,
            refresh_index=lambda: (_vod("fresh"),),
            schedule=lambda _callback: (_ for _ in ()).throw(
                RuntimeError("invoker deleted")
            ),
        )

        with self._run_threads_inline():
            library.ensure_refresh()

        self.assertFalse(library._refreshing)


class RecordingPreferenceTests(unittest.TestCase):
    def test_preference_write_failure_is_contained_at_the_qt_boundary(self) -> None:
        messages = []
        tab = SimpleNamespace(
            _log=lambda message, **kwargs: messages.append((message, kwargs))
        )

        saved = RecordingsTab._save_recording_preference(
            tab,
            "recording sort order",
            lambda: (_ for _ in ()).throw(OSError("disk full")),
        )

        self.assertFalse(saved)
        self.assertEqual(1, len(messages))
        self.assertIn("disk full", messages[0][0])
        self.assertEqual("warning", messages[0][1]["tag"])

    def test_unsuccessful_config_result_is_reported(self) -> None:
        from app import config

        messages = []
        tab = SimpleNamespace(
            _log=lambda message, **kwargs: messages.append((message, kwargs))
        )

        saved = RecordingsTab._save_recording_preference(
            tab,
            "recording sort order",
            lambda: config.ConfigSaveResult(False, "verification failed"),
        )

        self.assertFalse(saved)
        self.assertIn("verification failed", messages[0][0])


if __name__ == "__main__":
    unittest.main()
