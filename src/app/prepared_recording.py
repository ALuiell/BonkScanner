"""Background preparation of every immutable projection needed by a VOD UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Callable

from app.latest_wins_loader import LoadCancelled
from app.vod_library import load_vod
from core.run_summary import build_stage_summary
from infra.vod_storage import LoadedVod
from projections.scrubber import ScrubberModel, build_model
from core.powerup_history import POWERUPS_SERIES
from projections.powerup_history import PowerupProjection
from projections.timeline_axis import (
    SnapshotTimeIndex,
    TimelineAxisProjection,
    build_axis_projection,
)


@dataclass(frozen=True)
class PreparedRecording:
    vod: LoadedVod
    scrubber_model: ScrubberModel
    axis_projection: TimelineAxisProjection
    stage_summary: tuple
    time_index: SnapshotTimeIndex
    revision: int | None
    series_signature: tuple[str, ...]
    cap_signature: tuple[str, ...]
    powerups: PowerupProjection | None = None


def live_preparation_matches(request, state, series_keys, cap_keys) -> bool:
    """Fast effect ticks must not cancel preparation of the same stat data."""
    if request is None:
        return False
    previous, keys, caps = request
    return (previous.path == state.path and previous.status == state.status
            and previous.snapshots is state.snapshots
            and keys == series_keys and caps == cap_keys)


def merge_live_powerup_revision(prepared: PreparedRecording, state) -> PreparedRecording:
    """Install newer metadata/effect history while reusing numerical projections."""
    return replace(prepared, vod=state.loaded_vod, revision=state.revision,
                   powerups=PowerupProjection(state.powerup_history, previous=prepared.powerups))


def prepare_loaded_recording(
    vod: LoadedVod,
    *,
    series_keys=(),
    cap_keys=(),
    revision: int | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> PreparedRecording:
    keys = tuple(dict.fromkeys(series_keys))
    caps = tuple(dict.fromkeys(cap_keys))
    _check_cancelled(cancelled)
    if progress is not None:
        progress({"phase": "Preparing timeline", "fraction": None})
    model = build_model(vod.snapshots, series_keys=tuple(k for k in keys if k != POWERUPS_SERIES))
    _check_cancelled(cancelled)
    projection = build_axis_projection(vod.snapshots)
    stages = tuple(build_stage_summary(vod.snapshots))
    time_index = SnapshotTimeIndex.build(vod.snapshots)
    _check_cancelled(cancelled)
    if progress is not None:
        progress({"phase": "Rendering", "fraction": 1.0})
    return PreparedRecording(
        vod=vod,
        scrubber_model=model,
        axis_projection=projection,
        stage_summary=stages,
        time_index=time_index,
        revision=revision,
        series_signature=keys,
        cap_signature=caps,
        powerups=PowerupProjection(getattr(vod, "powerup_history", None)),
    )


def load_and_prepare_recording(
    path: Path,
    *,
    series_keys=(),
    cap_keys=(),
    revision: int | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> PreparedRecording:
    last_update = 0.0

    def on_bytes(done: int, total: int) -> None:
        nonlocal last_update
        now = time.monotonic()
        if done < total and now - last_update < 0.1:
            return
        last_update = now
        if progress is not None:
            progress(
                {
                    "phase": "Reading recording",
                    "fraction": done / max(total, 1),
                    "bytes": done,
                    "total": total,
                }
            )

    if progress is not None:
        progress({"phase": "Reading recording", "fraction": 0.0})
    vod = load_vod(path, cancelled=cancelled, progress=on_bytes)
    return prepare_loaded_recording(
        vod,
        series_keys=series_keys,
        cap_keys=cap_keys,
        revision=revision,
        cancelled=cancelled,
        progress=progress,
    )


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise LoadCancelled()


def replace_prepared_metadata(
    prepared: PreparedRecording | None,
    vod: LoadedVod,
    metadata,
) -> tuple[PreparedRecording | None, LoadedVod]:
    """Replace rename metadata without reparsing or rebuilding snapshot data."""
    renamed_vod = LoadedVod(metadata=metadata, snapshots=vod.snapshots,
                           powerup_history=getattr(vod, "powerup_history", None))
    if prepared is None:
        return None, renamed_vod
    return replace(prepared, vod=renamed_vod), renamed_vod
