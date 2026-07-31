"""The library sort, as a decision that needs no widgets.

Both surfaces that show the recording library -- the Recordings tab and the
Compare Runs chooser -- run this one function, so the order they show cannot
drift apart. The cases here are what "one function" is worth: they pin the four
orders, the tie-break that keeps a refresh from shuffling, and the fallback
that stops a hand-edited config from breaking the list.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections.recording_sort import (
    RECORDING_SORT_DEFAULT,
    RECORDING_SORT_LONGEST,
    RECORDING_SORT_NEWEST,
    RECORDING_SORT_OLDEST,
    RECORDING_SORT_SNAPSHOTS,
    normalize_recording_sort_mode,
    sort_recordings,
)


def vod(name, created_at, duration_seconds, snapshot_count):
    return SimpleNamespace(
        name=name,
        created_at=created_at,
        duration_seconds=duration_seconds,
        snapshot_count=snapshot_count,
    )


#: Deliberately not in any of the four orders, so every case has to do work.
LIBRARY = (
    vod("middle", "2026-07-14T20:58:58", 9467, 713),
    vod("newest", "2026-07-18T16:33:12", 1964, 141),
    vod("oldest", "2026-07-02T04:12:00", 4200, 900),
)


def names(vods):
    return [vod.name for vod in vods]


class SortOrderTests(unittest.TestCase):
    def test_newest_first_is_the_default(self) -> None:
        self.assertEqual(RECORDING_SORT_NEWEST, RECORDING_SORT_DEFAULT)
        self.assertEqual(
            ["newest", "middle", "oldest"],
            names(sort_recordings(LIBRARY, RECORDING_SORT_DEFAULT)),
        )

    def test_oldest_first_reverses_it(self) -> None:
        self.assertEqual(
            ["oldest", "middle", "newest"],
            names(sort_recordings(LIBRARY, RECORDING_SORT_OLDEST)),
        )

    def test_longest_first_sorts_by_duration_not_by_date(self) -> None:
        self.assertEqual(
            ["middle", "oldest", "newest"],
            names(sort_recordings(LIBRARY, RECORDING_SORT_LONGEST)),
        )

    def test_most_snapshots_first_is_not_the_same_order_as_longest(self) -> None:
        """They correlate, but the interval can differ between recordings."""
        self.assertEqual(
            ["oldest", "middle", "newest"],
            names(sort_recordings(LIBRARY, RECORDING_SORT_SNAPSHOTS)),
        )

    def test_ties_break_on_the_name_so_a_refresh_does_not_shuffle(self) -> None:
        same_second = (
            vod("zulu", "2026-07-14T20:58:58", 100, 10),
            vod("alpha", "2026-07-14T20:58:58", 100, 10),
        )

        for mode in (RECORDING_SORT_OLDEST, RECORDING_SORT_LONGEST, RECORDING_SORT_SNAPSHOTS):
            with self.subTest(mode=mode):
                self.assertEqual(["alpha", "zulu"], names(sort_recordings(same_second, mode)))

    def test_the_source_sequence_is_not_mutated(self) -> None:
        library = list(LIBRARY)

        sort_recordings(library, RECORDING_SORT_OLDEST)

        self.assertEqual(names(LIBRARY), names(library))


class ModeFallbackTests(unittest.TestCase):
    def test_an_unknown_mode_falls_back_instead_of_raising(self) -> None:
        """This reads a config file; a stale or hand-edited value must not
        stop the library from painting."""
        for value in ("nonsense", "", None, 7):
            with self.subTest(value=value):
                self.assertEqual(RECORDING_SORT_DEFAULT, normalize_recording_sort_mode(value))
                self.assertEqual(
                    names(sort_recordings(LIBRARY, RECORDING_SORT_DEFAULT)),
                    names(sort_recordings(LIBRARY, value)),
                )

    def test_an_empty_library_is_not_an_error(self) -> None:
        self.assertEqual([], sort_recordings((), RECORDING_SORT_LONGEST))
        self.assertEqual([], sort_recordings(None, RECORDING_SORT_LONGEST))


class LabelParityTests(unittest.TestCase):
    def test_every_mode_has_a_label_and_every_label_a_mode(self) -> None:
        """A mode with no label is unreachable; a label with no mode crashes."""
        from projections.recording_sort import RECORDING_SORT_MODES
        from ui.styles import RECORDING_SORT_LABELS

        self.assertEqual(set(RECORDING_SORT_MODES), set(RECORDING_SORT_LABELS))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
