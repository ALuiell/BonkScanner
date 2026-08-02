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
import unittest
from pathlib import Path
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from ui.tabs.player_stats.recordings import (
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


if __name__ == "__main__":
    unittest.main()
