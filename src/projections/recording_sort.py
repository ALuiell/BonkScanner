"""Recording-library sort modes, and the ordering each one means.

Same shape as `projections/item_sort.py`: a small vocabulary plus the pure
function that applies it, so the decision is testable without Qt and so the two
surfaces that show the library -- the Recordings tab and the Compare Runs
chooser -- cannot drift apart. They already share `RecordingLibraryRow`; a
recording that sits third in one list and seventh in the other would be the
same library wearing two faces.

Direction is folded into the mode rather than split into a separate toggle, the
way `ITEM_SORT_RARITY_ASC`/`_DESC` already are. Four named orders read as four
answers to "what am I looking for"; a key plus a direction is two controls and
eight states for the sake of two orders nobody asks for.

`created_at` is an ISO timestamp string, so it sorts lexicographically -- which
is what `list_vods` has always relied on for its newest-first default.
"""

from __future__ import annotations

RECORDING_SORT_NEWEST = "newest"
RECORDING_SORT_OLDEST = "oldest"
RECORDING_SORT_LONGEST = "longest"
RECORDING_SORT_SNAPSHOTS = "snapshots"

#: The default, and the order `list_vods` returns unsorted-by-us.
RECORDING_SORT_DEFAULT = RECORDING_SORT_NEWEST

RECORDING_SORT_MODES = (
    RECORDING_SORT_NEWEST,
    RECORDING_SORT_OLDEST,
    RECORDING_SORT_LONGEST,
    RECORDING_SORT_SNAPSHOTS,
)


def _created_at(vod) -> str:
    return str(getattr(vod, "created_at", "") or "")


def _name_key(vod) -> str:
    return str(getattr(vod, "name", "") or "").casefold()


def normalize_recording_sort_mode(mode) -> str:
    """An unknown or missing mode falls back to the default rather than raising.

    This reads a saved config value, and a config file edited by hand -- or
    written by an older build -- must not stop the library from painting.
    """
    text = str(mode or "")
    return text if text in RECORDING_SORT_MODES else RECORDING_SORT_DEFAULT


def sort_recordings(vods, mode) -> list:
    """The library in the order `mode` asks for, newest first by default.

    Every order breaks ties on the name, so a list of recordings that share a
    duration -- or a batch saved in the same second -- has a stable order
    instead of one that shuffles between refreshes.
    """
    vods = list(vods or ())
    mode = normalize_recording_sort_mode(mode)
    if mode == RECORDING_SORT_OLDEST:
        return sorted(vods, key=lambda vod: (_created_at(vod), _name_key(vod)))
    if mode == RECORDING_SORT_LONGEST:
        return sorted(
            vods,
            key=lambda vod: (-int(getattr(vod, "duration_seconds", 0) or 0), _name_key(vod)),
        )
    if mode == RECORDING_SORT_SNAPSHOTS:
        return sorted(
            vods,
            key=lambda vod: (-int(getattr(vod, "snapshot_count", 0) or 0), _name_key(vod)),
        )
    return sorted(vods, key=lambda vod: (_created_at(vod), _name_key(vod)), reverse=True)
