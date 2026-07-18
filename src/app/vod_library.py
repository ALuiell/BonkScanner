"""Access to the stored-recordings library, for the UI.

The layering table forbids ``ui/ -> infra/``: the UI must not decide how a
recording is stored or where. ``ui/tabs/compare_runs/`` needs to load a VOD the
user picked, so the dependency goes through here instead of reaching into
``infra/vod_storage`` directly.

Thin on purpose. This is the seam, not a place for logic -- every name here is a
re-export, and adding a decision to one of them is how a seam turns into a
second implementation.

**Library management, not capture.** Loading, renaming, deleting and reindexing
recordings the user already has is this module's scope. Deciding *when* to start
or stop recording is the capture lifecycle, which belongs to ``app/vod_capture.py``
-- keep the two apart, or the UI ends up driving capture through here.

Step 14 widened this from read-only to the four management calls the Recordings
tab makes. It was originally scoped to reading because ``ui/tabs/compare_runs/``
only reads; the Recordings tab renames and deletes as well, and routing those
back through ``infra`` would have reintroduced exactly the edge this exists to
prevent.
"""
from __future__ import annotations

from infra.vod_storage import (
    delete_vod,
    delete_vods_below_snapshot_count,
    load_vod,
    refresh_vod_metadata_index,
    rename_vod,
)

__all__ = [
    "delete_vod",
    "delete_vods_below_snapshot_count",
    "load_vod",
    "refresh_vod_metadata_index",
    "rename_vod",
]
