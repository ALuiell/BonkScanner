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

Step 21 -- ``VodLibrary``, and why the seam grew a class
=======================================================

The re-exports above stayed thin for six steps. ``VodLibrary`` is the one thing
that is not a re-export, and it is here because of a **measurement**, not a
preference.

The metadata index (``_vod_metadata_index``) was a plain ``MegabonkApp``
attribute read by both the Recordings tab and the Compare Runs tab and written
by one of them. Its refresh completion callback, on the Recordings mixin,
cleared **both** tabs' list signatures and repainted **both** lists, while
``ui/tabs/compare_runs/tab.py`` called back into that same Recordings method to
start the refresh. Two tabs, one cache, a cycle through a shared ``self``.

The measurement that chose this shape (all 30 pieces of tab state, scanned for
production readers outside their own tab module):

* **Every** other name -- ``loaded_vod``, the four ``compare_run_*`` slots, both
  chooser flags, both list signatures, all four generation counters -- has
  **zero** production readers outside its own tab. Their only non-tab mention is
  the single initialising line in ``gui_app.__init__``.
* ``_vod_metadata_index`` and its two refresh guards are the **only** state both
  tabs touch.

So the shared thing is exactly one cache and one refresh cycle, and nothing
else. That is what gets an owner. The two list signatures did *not* move here:
each is read by exactly one tab, and the only reason the other tab wrote it was
to force a repaint after the index changed. Making that a **notification**
instead of a write is what removes the cross-tab edge -- moving both signatures
onto this object would have kept the coupling and merely relocated it, which is
what the roadmap warns the wrong ordering produces.

Notification is two-phase (all subscribers invalidated, *then* all repainted)
because that is what the callback it replaces did: it cleared both signatures
before repainting either. One-phase notification would repaint the Recordings
list while the Compare Runs signature was still stale, which happens to be
harmless today and is exactly the kind of ordering a rewrite silently changes.

Thread marshalling is **injected**, not discovered. The old callback reached for
``self.after`` and ``self._invoker`` off the shared namespace; ``schedule`` is a
constructor argument, so an owner that cannot marshal (a test double, a torn-down
window) is a fact about the caller rather than a ``getattr`` that quietly went
``None``.
"""
from __future__ import annotations

import threading

from infra import vod_storage
from typing import Callable, Sequence

from app import config
from projections.recording_sort import normalize_recording_sort_mode

from infra.vod_storage import (
    delete_vod,
    delete_vods_below_snapshot_count,
    load_cached_vods,
    load_vod,
    minimum_snapshot_count,
    refresh_vod_metadata_index,
    rename_vod,
)

__all__ = [
    "VodLibrary",
    "delete_vod",
    "delete_vods_below_snapshot_count",
    "load_cached_vods",
    "load_vod",
    "minimum_snapshot_count",
    "refresh_vod_metadata_index",
    "recording_library_open",
    "recording_library_width",
    "recording_sort_mode",
    "rename_vod",
    "set_minimum_snapshot_count",
    "set_recording_library_open",
    "set_recording_library_width",
    "set_recording_sort_mode",
]


#: Where the library's sort order is remembered. One key, not two: the
#: Recordings tab and the Compare Runs chooser show the *same* library, and a
#: list that sits third in one and seventh in the other is not flexibility.
RECORDING_SORT_CONFIG_KEY = "RECORDING_SORT_MODE"


def recording_sort_mode() -> str:
    """The saved order, normalised -- an unknown value falls back to newest."""
    return normalize_recording_sort_mode(config.user_config.get(RECORDING_SORT_CONFIG_KEY))


def set_recording_sort_mode(mode: str) -> None:
    config.user_config[RECORDING_SORT_CONFIG_KEY] = normalize_recording_sort_mode(mode)
    config.save_config(config.user_config)


#: Where the Recordings tab remembers its library drawer -- whether it is open,
#: and how wide the user dragged it.
#:
#: Deliberately *not* shared with the Compare Runs chooser the way the sort key
#: above is, and the difference is the point: sort order is a property of the
#: library, so two views of one library must agree on it. Open-ness and width
#: are properties of one tab's layout. Compare Runs keeps its own
#: open-on-demand behaviour and reads neither of these.
RECORDING_LIBRARY_OPEN_CONFIG_KEY = "RECORDINGS_LIBRARY_OPEN"
RECORDING_LIBRARY_WIDTH_CONFIG_KEY = "RECORDINGS_LIBRARY_WIDTH"


def recording_library_open() -> bool:
    """Whether the Recordings library drawer was left open. Closed by default."""
    return bool(config.user_config.get(RECORDING_LIBRARY_OPEN_CONFIG_KEY, False))


def set_recording_library_open(is_open: bool) -> None:
    config.user_config[RECORDING_LIBRARY_OPEN_CONFIG_KEY] = bool(is_open)
    config.save_config(config.user_config)


def recording_library_width() -> int | None:
    """The saved drawer width, or ``None`` for "use the layout's default".

    Not clamped here. The bounds are ``RECORDINGS_LIST_MIN/MAX_WIDTH``, which
    live in ``ui/`` and which ``app/`` may not import; the drawer clamps what
    it reads, which is also where a hand-edited config gets caught.
    """
    try:
        width = int(config.user_config.get(RECORDING_LIBRARY_WIDTH_CONFIG_KEY))
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def set_recording_library_width(width: int) -> None:
    config.user_config[RECORDING_LIBRARY_WIDTH_CONFIG_KEY] = max(0, int(width))
    config.save_config(config.user_config)


def set_minimum_snapshot_count(value: int) -> None:
    """Persist the auto-filter threshold through the recording settings.

    Here rather than in ``infra.vod_storage`` beside its reader, because the
    layering table forbids ``ui/ -> infra/`` and this seam is what the
    Recordings tab is allowed to call. The reader is re-exported above for the
    same reason.
    """
    settings = vod_storage._settings
    if settings is None:
        return
    writer = getattr(settings, "write_minimum_snapshot_count", None)
    if callable(writer):
        writer(max(0, int(value)))


class VodLibrary:
    """The recording-metadata index, its refresh cycle, and who to tell.

    Constructed once, by ``gui_app.MegabonkApp.__init__``. Both tabs receive
    *this object*; neither holds a reference to the other.
    """

    def __init__(
        self,
        *,
        load_cached: Callable[[], Sequence] = load_cached_vods,
        refresh_index: Callable[[], Sequence] = refresh_vod_metadata_index,
        schedule: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._index = tuple(load_cached())
        self._refresh_index = refresh_index
        self._schedule = schedule
        self._refreshing = False
        self._refresh_generation = 0
        self._subscribers: list[tuple[Callable[[], None], Callable[[], None]]] = []
        self._failure_listeners: list[Callable[[BaseException], None]] = []

    @property
    def index(self) -> tuple:
        """The cached metadata, newest known state. Never ``None``."""
        return self._index

    def subscribe(
        self,
        *,
        invalidate: Callable[[], None],
        repaint: Callable[[], None],
        failed: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Register one tab's reaction to the index changing.

        ``invalidate`` drops whatever the tab caches about the old index (its
        list signature); ``repaint`` redraws from the new one. They are separate
        because all subscribers are invalidated before any is repainted -- see
        the module header.
        """
        self._subscribers.append((invalidate, repaint))
        if failed is not None:
            self._failure_listeners.append(failed)

    def ensure_refresh(self) -> None:
        """Start a metadata refresh unless one is already in flight.

        Called from both tabs' list repaints, so it is entered far more often
        than it does anything. The in-flight guard is what makes that cheap --
        and, because the repaint that follows a completed refresh calls straight
        back in here, it is also what stops the cycle from recursing.
        """
        if self._refreshing:
            return
        self._refreshing = True
        self._refresh_generation += 1
        generation = self._refresh_generation

        def work() -> None:
            try:
                vods = self._refresh_index()
                error = None
            except Exception as exc:  # noqa: BLE001 -- reported to the tab
                vods = []
                error = exc

            def apply_result() -> None:
                if generation != self._refresh_generation:
                    return
                self._refreshing = True
                if error is not None:
                    self._refreshing = False
                    self._notify_failed(error)
                    return
                self._index = tuple(vods)
                subscribers = tuple(self._subscribers)
                for invalidate, _ in subscribers:
                    invalidate()
                for _, repaint in subscribers:
                    repaint()
                self._refreshing = False

            self._marshal(apply_result)

        threading.Thread(target=work, name="vod-metadata-index", daemon=True).start()

    def _marshal(self, callback: Callable[[], None]) -> None:
        schedule = self._schedule
        if callable(schedule):
            schedule(callback)
        else:
            callback()

    def _notify_failed(self, error: BaseException) -> None:
        for listener in tuple(self._failure_listeners):
            listener(error)
