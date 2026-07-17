"""Read access to stored recordings, for the UI.

The layering table forbids ``ui/ -> infra/``: the UI must not decide how a
recording is stored or where. ``ui/tabs/compare_runs/`` needs to load a VOD the
user picked, so the dependency goes through here instead of reaching into
``infra/vod_storage`` directly.

Thin on purpose. This is the seam, not a place for logic -- when
``AppCoordinator`` lands (step 11) it owns VOD orchestration, and the recording
*lifecycle* is ``app/vod_capture.py``'s job, not this module's. Reading a
recording someone already chose is all that belongs here.

Only the tabs actually living under ``ui/`` route through this. The ``gui_*.py``
files still import ``infra.vod_storage`` directly; they are top-level, so they
are not formally ``ui/`` yet, and step 14 has to move them behind this seam when
it packages them.
"""
from __future__ import annotations

from infra.vod_storage import load_vod

__all__ = ["load_vod"]
