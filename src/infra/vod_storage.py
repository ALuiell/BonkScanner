from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from math import isfinite
import os
from pathlib import Path
import threading
import time
from typing import Any

from infra import paths

from core.character_passives import (
    CharacterPassiveEffectKind,
    CharacterPassiveEffectSnapshot,
    CharacterPassiveSnapshot,
    CharacterPassiveStatus,
)
from core.settings import (
    DEFAULT_MINIMUM_SNAPSHOT_COUNT,
    MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
    RecordingSettings,
)
from core.json_safety import dumps_strict_json, loads_legacy_json
from core.stats.formats import PlayerStatFormat, WeaponStatFormat
from core.stats.types import ChaosTomeSnapshot, ChaosTomeStatSnapshot, ChargeShrineSnapshot, ChargeShrineStatSnapshot, DamageSourceSnapshot, PlayerStatValue, TomeSnapshot, WeaponSnapshot, WeaponStatValue
from core.run_verifier import VerifierStatFrame
from infra.run_verifier import VerifierTelemetryWriter


# 11 adds hidden run-verifier checkpoints while keeping summary as the last line.
# 12 adds process-environment snapshots and deltas for the verifier.
# 13 adds privacy-safe private executable memory-region evidence.
# 10 lets the final summary publish the completed automatic name and kill count.
# 9 added character identity metadata and the generic character-passive frame.
# Older recordings omit newer fields and keep their original metadata name.
VOD_FORMAT_VERSION = 13
RECORDINGS_DIR = Path(paths.application_path()) / "stats_recordings"
LEGACY_VODS_DIR = Path(paths.application_path()) / "vods"
_VOD_METADATA_CACHE: dict[Path, tuple[int, int, VodMetadata]] = {}
_VOD_METADATA_INDEX_CONFIG_KEY = "_VOD_METADATA_INDEX"
_VOD_INDEX_LOCK = threading.RLock()

# Injected by app/ at startup. None means "no persistent index": the metadata
# is still correct, it is just recomputed from disk instead of cached, which is
# what the tests exercise.
_settings: RecordingSettings | None = None


def use_settings(settings: RecordingSettings | None) -> None:
    global _settings
    _settings = settings
SNAPSHOT_FLUSH_EVERY = 3


def format_recording_kill_count(value: int) -> str:
    """Return the compact whole-number count used in automatic VOD names."""
    count = max(0, int(value))
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        return f"{count // 1_000}K"
    return f"{count // 1_000_000}M"


def _automatic_vod_name(
    prefix: str,
    created_at: datetime,
    mob_kills: int | None = None,
) -> str:
    parts = [prefix]
    if mob_kills is not None:
        parts.append(format_recording_kill_count(mob_kills))
    parts.append(created_at.strftime("%Y-%m-%d %H:%M:%S"))
    return " ".join(parts)


# `slots=True` on the two types below, and it is not a style choice: these are
# the only objects in the application that exist in five figures. Opening one
# recording of 855 snapshots creates 855 `VodSnapshot` and 25,650
# `VodStatValue` -- one per stat per snapshot -- and a dataclass without slots
# carries a per-instance `__dict__`, which for `VodStatValue` is 296 of its 344
# bytes. Measured on the real library, the pair is worth about 9 MB of the
# ~26 MB that browsing recordings adds to the process.
#
# Neither is subclassed, pickled, or given an attribute it was not declared
# with, which is the whole list of things slots would break.
@dataclass(frozen=True, slots=True)
class VodStatValue:
    value: float | None
    display_value: str


@dataclass(frozen=True, slots=True)
class VodSnapshot:
    elapsed_seconds: int
    captured_at: float
    stats: dict[str, VodStatValue]
    items: tuple[str, ...] = ()
    weapons: tuple[WeaponSnapshot, ...] = ()
    tomes: tuple[TomeSnapshot, ...] = ()
    chaos_tome: ChaosTomeSnapshot | None = None
    shrines: ChargeShrineSnapshot | None = None
    character_passive: CharacterPassiveSnapshot | None = None
    banishes: tuple[str, ...] = ()
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    mob_kills: int | None = None
    kps_at_capture: int | None = None
    minute_avg_kps_at_capture: int | None = None
    five_minute_avg_kps_at_capture: int | None = None
    run_avg_kps_at_capture: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
    stage_index: int | None = None
    stage_time_seconds: float | None = None
    chests_opened: int | None = None
    chests_total: int | None = None
    pots_total: int | None = None
    paid_chests: int | None = None
    key_procs: int | None = None
    free_chests: int | None = None
    keys_count: int | None = None
    expected_key_procs: float | None = None
    chests_opened_by_stage: dict[int, int] | None = None
    chests_total_by_stage: dict[int, int] | None = None
    # Per-tier actual and expected, keyed by our internal rarity names. `None`
    # is "not recorded" -- an older file, or a run the tracker could not
    # measure -- and is deliberately *not* an empty dict or a zeroed one: a
    # comparison that read absence as zero would report "no items of this tier"
    # where the truth is "we do not know".
    loot_actual: dict[str, int] | None = None
    loot_expected: dict[str, float] | None = None

    @property
    def time_label(self) -> str:
        minutes, seconds = divmod(max(self.elapsed_seconds, 0), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class VodMetadata:
    path: Path
    name: str
    created_at: str
    interval_seconds: int
    duration_seconds: int
    snapshot_count: int
    run_seed: int | None = None
    character_id: int | None = None
    character_name: str | None = None

    @property
    def created_label(self) -> str:
        try:
            value = datetime.fromisoformat(self.created_at)
        except ValueError:
            return self.created_at
        return value.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class LoadedVod:
    metadata: VodMetadata
    snapshots: tuple[VodSnapshot, ...]


@dataclass(frozen=True)
class VodCleanupResult:
    removed: int = 0
    skipped_active: int = 0
    skipped_locked: int = 0


def _metadata_to_index_record(metadata: VodMetadata, *, mtime_ns: int, size: int) -> dict[str, Any]:
    return {
        "path": str(metadata.path),
        "mtime_ns": int(mtime_ns),
        "size": int(size),
        "metadata": {
            "name": metadata.name,
            "created_at": metadata.created_at,
            "interval_seconds": metadata.interval_seconds,
            "duration_seconds": metadata.duration_seconds,
            "snapshot_count": metadata.snapshot_count,
            "run_seed": metadata.run_seed,
            "character_id": metadata.character_id,
            "character_name": metadata.character_name,
        },
    }


def _metadata_from_index_record(record: dict[str, Any]) -> tuple[Path, int, int, VodMetadata]:
    path = Path(str(record["path"])).resolve()
    raw = record["metadata"]
    metadata = VodMetadata(
        path=path,
        name=str(raw.get("name") or path.stem),
        created_at=str(raw.get("created_at") or ""),
        interval_seconds=int(raw.get("interval_seconds") or 0),
        duration_seconds=int(raw.get("duration_seconds") or 0),
        snapshot_count=int(raw.get("snapshot_count") or 0),
        run_seed=raw.get("run_seed"),
        character_id=_coerce_optional_int(raw.get("character_id")),
        character_name=(
            str(raw.get("character_name")) if raw.get("character_name") else None
        ),
    )
    return path, int(record.get("mtime_ns") or 0), int(record.get("size") or 0), metadata


def minimum_snapshot_count() -> int:
    """Shortest run the recorder keeps, in snapshots.

    Falls back to the default when there is no settings store, which is what a
    test or a bare `VodRecorder` has: the alternative -- keeping everything --
    would silently disable the discard rule in exactly the configuration that
    is hardest to notice it in.
    """
    if _settings is None:
        return DEFAULT_MINIMUM_SNAPSHOT_COUNT
    reader = getattr(_settings, "read_minimum_snapshot_count", None)
    if not callable(reader):
        return DEFAULT_MINIMUM_SNAPSHOT_COUNT
    try:
        return max(0, int(reader()))
    except (TypeError, ValueError):
        return DEFAULT_MINIMUM_SNAPSHOT_COUNT


def _load_index_records() -> list[dict[str, Any]]:
    if _settings is None:
        return []
    payload = _settings.read_metadata_index()
    if not isinstance(payload, dict):
        return []
    records = payload.get("records", [])
    return records if isinstance(records, list) else []


def load_cached_vods() -> list[VodMetadata]:
    """Return the last valid metadata index without scanning recording payloads."""
    with _VOD_INDEX_LOCK:
        result = []
        for record in _load_index_records():
            try:
                path, _mtime_ns, _size, metadata = _metadata_from_index_record(record)
            except (TypeError, ValueError, KeyError):
                continue
            if path.exists():
                result.append(metadata)
        return sorted(result, key=lambda vod: vod.created_at, reverse=True)


def refresh_vod_metadata_index() -> list[VodMetadata]:
    """Refresh changed metadata entries and persist the lightweight VOD index."""
    roots = [RECORDINGS_DIR, LEGACY_VODS_DIR]
    with _VOD_INDEX_LOCK:
        previous: dict[Path, tuple[int, int, VodMetadata]] = {}
        for record in _load_index_records():
            try:
                path, mtime_ns, size, metadata = _metadata_from_index_record(record)
                previous[path] = (mtime_ns, size, metadata)
            except (TypeError, ValueError, KeyError):
                continue

        current: dict[Path, tuple[int, int, VodMetadata]] = {}
        for root in roots:
            if root is None or not root.exists():
                continue
            for path in root.glob("*.jsonl"):
                resolved_path = path.resolve()
                if resolved_path in current:
                    continue
                try:
                    stat = path.stat()
                    cached = previous.get(resolved_path)
                    if cached is not None and cached[:2] == (stat.st_mtime_ns, stat.st_size):
                        current[resolved_path] = cached
                        continue
                    metadata = load_vod_metadata(path)
                    current[resolved_path] = (stat.st_mtime_ns, stat.st_size, metadata)
                except (OSError, ValueError, json.JSONDecodeError):
                    if resolved_path in previous:
                        current[resolved_path] = previous[resolved_path]

        records = [
            _metadata_to_index_record(metadata, mtime_ns=mtime_ns, size=size)
            for mtime_ns, size, metadata in current.values()
        ]
        if _settings is not None:
            _settings.write_metadata_index({"version": 1, "records": records})
        return sorted((entry[2] for entry in current.values()), key=lambda vod: vod.created_at, reverse=True)


class VodRecorder:
    def __init__(
        self,
        *,
        vods_dir: Path | None = None,
        interval_seconds: int = 30,
        clock=time.monotonic,
    ) -> None:
        self.vods_dir = vods_dir or RECORDINGS_DIR
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.path: Path | None = None
        self.name = ""
        self.start_time: float | None = None
        self.last_snapshot_time: float | None = None
        self.snapshot_count = 0
        self.is_recording = False
        self._file = None
        self._uses_automatic_name = True
        self._automatic_name_prefix = "Run"
        self._created_at: datetime | None = None
        self._max_mob_kills: int | None = None
        self._verifier = VerifierTelemetryWriter()
        self._pending_verification_context: tuple[
            str | None,
            str | None,
            float | None,
            dict[str, Any] | None,
            str | None,
        ] = (None, None, None, None, None)

    def prepare_verification_context(
        self,
        *,
        scanner_version: str | None,
        game_build_id: str | None,
        run_start_time_seconds: float | None,
        environment_snapshot: dict[str, Any] | None = None,
        environment_error: str | None = None,
    ) -> None:
        """Supply start-only metadata without widening capture's recorder port."""
        self._pending_verification_context = (
            scanner_version,
            game_build_id,
            run_start_time_seconds,
            environment_snapshot,
            environment_error,
        )

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    @interval_seconds.setter
    def interval_seconds(self, value: int) -> None:
        self._interval_seconds = max(
            MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
            int(value),
        )

    def start(
        self,
        *,
        name: str | None = None,
        seed: int | None = None,
        character_id: int | None = None,
        character_name: str | None = None,
        scanner_version: str | None = None,
        game_build_id: str | None = None,
        run_start_time_seconds: float | None = None,
        environment_snapshot: dict[str, Any] | None = None,
        environment_error: str | None = None,
    ) -> Path:
        if self.is_recording or self._file is not None:
            raise RuntimeError("VOD recorder is already active.")
        (
            pending_scanner,
            pending_build,
            pending_run_start,
            pending_environment,
            pending_environment_error,
        ) = (
            self._pending_verification_context
        )
        if scanner_version is None:
            scanner_version = pending_scanner
        if game_build_id is None:
            game_build_id = pending_build
        if run_start_time_seconds is None:
            run_start_time_seconds = pending_run_start
        if environment_snapshot is None:
            environment_snapshot = pending_environment
        if environment_error is None:
            environment_error = pending_environment_error
        self._pending_verification_context = (None, None, None, None, None)
        self.vods_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now().replace(microsecond=0)
        file_stem = created_at.strftime("%Y-%m-%d_%H-%M-%S")
        self.path = _unique_path(self.vods_dir / f"{file_stem}.jsonl")
        default_prefix = str(character_name).strip() if character_name else "Run"
        self._uses_automatic_name = not bool(name)
        self._automatic_name_prefix = default_prefix
        self._created_at = created_at
        self._max_mob_kills = None
        self.name = name or _automatic_vod_name(default_prefix, created_at)
        self.start_time = self.clock()
        self.last_snapshot_time = None
        self.snapshot_count = 0
        self._verifier.reset()
        self.is_recording = False
        try:
            self._file = self.path.open("w", encoding="utf-8")
            self._write_record(
                {
                    "type": "metadata",
                    "version": VOD_FORMAT_VERSION,
                    "name": self.name,
                    "created_at": created_at.isoformat(),
                    "snapshot_interval_seconds": self.interval_seconds,
                    "run_seed": seed,
                    "character_id": character_id,
                    "character_name": character_name,
                    "verification": self._verifier.metadata(
                        scanner_version=scanner_version,
                        game_build_id=game_build_id,
                        run_start_time_seconds=run_start_time_seconds,
                    ),
                },
                flush=True,
            )
            if environment_snapshot is not None:
                try:
                    environment_record = self._verifier.environment_record(
                        environment_snapshot,
                        elapsed_seconds=0.0,
                    )
                except Exception as exc:
                    environment_record = self._verifier.environment_failure_record(
                        exc,
                        elapsed_seconds=0.0,
                    )
            else:
                environment_record = self._verifier.environment_failure_record(
                    environment_error
                    or "Initial process environment snapshot is unavailable.",
                    elapsed_seconds=0.0,
                )
            self._write_record(environment_record, flush=True)
        except Exception:
            opened_file, self._file = self._file, None
            if opened_file is not None:
                try:
                    opened_file.close()
                except Exception:
                    pass
            failed_path, self.path = self.path, None
            if failed_path is not None:
                try:
                    failed_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.name = ""
            self.start_time = None
            self.last_snapshot_time = None
            self.snapshot_count = 0
            self._created_at = None
            self._max_mob_kills = None
            self._verifier.reset()
            raise
        self.is_recording = True
        return self.path

    def stop(self) -> str:
        self.is_recording = False
        status = "kept"
        if self._file is not None:
            stop_error = None
            try:
                if (
                    self._uses_automatic_name
                    and self._created_at is not None
                    and self._max_mob_kills is not None
                ):
                    self.name = _automatic_vod_name(
                        self._automatic_name_prefix,
                        self._created_at,
                        self._max_mob_kills,
                    )
                try:
                    self._write_record(
                        self._verifier.coverage_record(
                            elapsed_seconds=self._verification_elapsed_seconds()
                        ),
                        flush=False,
                    )
                except Exception as exc:
                    # The recording summary and close still have to run.  The
                    # caller receives this error after the file is retired.
                    stop_error = exc
                self._write_record(
                    {
                        "type": "summary",
                        "name": self.name,
                        "duration_seconds": self.elapsed_seconds(),
                        "snapshot_count": self.snapshot_count,
                        "mob_kills": self._max_mob_kills,
                    },
                    flush=True,
                )
                self._file.flush()
            except Exception as exc:
                stop_error = stop_error or exc
            finally:
                opened_file, self._file = self._file, None
                try:
                    opened_file.close()
                except Exception as exc:
                    stop_error = stop_error or exc
            if stop_error is not None:
                raise stop_error
        threshold = minimum_snapshot_count()
        if self.path is not None and self.snapshot_count < threshold:
            self.path.unlink(missing_ok=True)
            clear_vod_metadata_cache()
            # Two statuses rather than one, because the caller logs them and
            # "we threw away a run you played" deserves different words from
            # "the file was empty". `deleted_empty` keeps its exact old meaning
            # so the existing log line and its test stay true.
            status = "deleted_empty" if self.snapshot_count == 0 else "deleted_short"
        return status

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self.is_recording = False
        self._verifier.reset()

    def elapsed_seconds(self) -> int:
        if self.start_time is None:
            return 0
        return max(0, int(self.clock() - self.start_time))

    def elapsed_label(self) -> str:
        minutes, seconds = divmod(self.elapsed_seconds(), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def should_capture(self) -> bool:
        if not self.is_recording:
            return False
        if self.last_snapshot_time is None:
            return True
        return self.clock() - self.last_snapshot_time >= self.interval_seconds

    def _verification_elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        return max(0.0, float(self.clock() - self.start_time))

    def should_capture_verification(self) -> bool:
        return bool(
            self.is_recording
            and self._file is not None
            and self._verifier.should_capture(self._verification_elapsed_seconds())
        )

    def should_capture_environment(self) -> bool:
        return bool(
            self.is_recording
            and self._file is not None
            and self._verifier.should_capture_environment(
                self._verification_elapsed_seconds()
            )
        )

    def capture_environment(self, snapshot: dict[str, Any]) -> None:
        if not self.is_recording or self._file is None:
            raise RuntimeError("VOD recorder is not active.")
        record = self._verifier.environment_record(
            snapshot,
            elapsed_seconds=self._verification_elapsed_seconds(),
        )
        self._write_record(record, flush=True)

    def note_environment_failure(self, error: BaseException | str) -> None:
        if not self.is_recording or self._file is None:
            return
        record = self._verifier.environment_failure_record(
            error,
            elapsed_seconds=self._verification_elapsed_seconds(),
        )
        self._write_record(record, flush=True)

    def capture_verification(
        self,
        frame: VerifierStatFrame,
        *,
        game_time_seconds: float | None,
        permanent_modifiers: dict[int, tuple[Any, ...]],
        shrine_snapshot: Any,
        chaos_snapshot: Any,
        character_passive_snapshot: Any,
        dice_level: int | None,
        held_items: tuple[str, ...],
        source_availability: dict[str, bool],
    ) -> None:
        if not self.is_recording or self._file is None:
            raise RuntimeError("VOD recorder is not active.")
        records = self._verifier.records_for_checkpoint(
            frame,
            elapsed_seconds=self._verification_elapsed_seconds(),
            game_time_seconds=game_time_seconds,
            permanent_modifiers=permanent_modifiers,
            shrine_snapshot=shrine_snapshot,
            chaos_snapshot=chaos_snapshot,
            character_passive_snapshot=character_passive_snapshot,
            dice_level=dice_level,
            held_items=held_items,
            source_availability=source_availability,
        )
        for record in records:
            self._write_record(record, flush=False)
        if records:
            self._file.flush()

    def note_verification_failure(self, error: BaseException | str) -> None:
        if not self.is_recording or self._file is None:
            return
        record = self._verifier.note_failure(
            self._verification_elapsed_seconds(), error
        )
        if record is not None:
            self._write_record(record, flush=True)

    def capture(
        self,
        stats: dict[str, PlayerStatValue],
        items: tuple[str, ...] = (),
        weapons: tuple[WeaponSnapshot, ...] = (),
        tomes: tuple[TomeSnapshot, ...] = (),
        banishes: tuple[str, ...] = (),
        damage_sources: tuple[DamageSourceSnapshot, ...] = (),
        *,
        chaos_tome: ChaosTomeSnapshot | None = None,
        shrines: ChargeShrineSnapshot | None = None,
        character_passive: CharacterPassiveSnapshot | None = None,
        chests_per_minute: float | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        kps_at_capture: int | None = None,
        minute_avg_kps_at_capture: int | None = None,
        five_minute_avg_kps_at_capture: int | None = None,
        run_avg_kps_at_capture: int | None = None,
        player_level: int | None = None,
        map_seed: int | None = None,
        stage_ptr: int = 0,
        stage_index: int | None = None,
        stage_time_seconds: float | None = None,
        chests_opened: int | None = None,
        chests_total: int | None = None,
        pots_total: int | None = None,
        paid_chests: int | None = None,
        key_procs: int | None = None,
        free_chests: int | None = None,
        keys_count: int | None = None,
        expected_key_procs: float | None = None,
        chests_opened_by_stage: dict[int, int] | None = None,
        chests_total_by_stage: dict[int, int] | None = None,
        loot_actual: dict[str, int] | None = None,
        loot_expected: dict[str, float] | None = None,
    ) -> VodSnapshot:
        if not self.is_recording or self._file is None:
            raise RuntimeError("VOD recorder is not active.")

        now = self.clock()
        if mob_kills is not None:
            current_mob_kills = max(0, int(mob_kills))
            if (
                self._max_mob_kills is None
                or current_mob_kills > self._max_mob_kills
            ):
                self._max_mob_kills = current_mob_kills
        snapshot = VodSnapshot(
            elapsed_seconds=self.elapsed_seconds(),
            captured_at=now,
            stats={
                label: VodStatValue(value=stat.value, display_value=stat.display_value)
                for label, stat in stats.items()
            },
            items=tuple(items),
            weapons=tuple(weapons),
            tomes=tuple(tomes),
            chaos_tome=chaos_tome,
            shrines=shrines,
            character_passive=character_passive,
            banishes=tuple(banishes),
            damage_sources=tuple(damage_sources),
            chests_per_minute=chests_per_minute,
            game_time_seconds=game_time_seconds,
            mob_kills=mob_kills,
            kps_at_capture=kps_at_capture,
            minute_avg_kps_at_capture=minute_avg_kps_at_capture,
            five_minute_avg_kps_at_capture=five_minute_avg_kps_at_capture,
            run_avg_kps_at_capture=run_avg_kps_at_capture,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            stage_time_seconds=stage_time_seconds,
            chests_opened=chests_opened,
            chests_total=chests_total,
            pots_total=pots_total,
            paid_chests=paid_chests,
            key_procs=key_procs,
            free_chests=free_chests,
            keys_count=keys_count,
            expected_key_procs=expected_key_procs,
            chests_opened_by_stage=(
                dict(chests_opened_by_stage) if chests_opened_by_stage is not None else None
            ),
            chests_total_by_stage=(
                dict(chests_total_by_stage) if chests_total_by_stage is not None else None
            ),
            loot_actual=dict(loot_actual) if loot_actual is not None else None,
            loot_expected=dict(loot_expected) if loot_expected is not None else None,
        )
        self.snapshot_count += 1
        self._write_record(
            _snapshot_to_record(snapshot),
            flush=(self.snapshot_count % SNAPSHOT_FLUSH_EVERY == 0),
        )
        self.last_snapshot_time = now
        return snapshot

    def _write_record(self, record: dict[str, Any], *, flush: bool = False) -> None:
        if self._file is None:
            raise RuntimeError("VOD recorder file is not open.")
        self._file.write(_dumps_record(record))
        self._file.write("\n")
        if flush:
            self._file.flush()


def list_vods(vods_dir: Path | None = None) -> list[VodMetadata]:
    roots = [vods_dir] if vods_dir is not None else [RECORDINGS_DIR, LEGACY_VODS_DIR]

    vods = []
    seen_paths: set[Path] = set()
    for root in roots:
        if root is None or not root.exists():
            continue

        for path in root.glob("*.jsonl"):
            resolved_path = path.resolve()
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            try:
                vods.append(load_vod_metadata(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return sorted(vods, key=lambda vod: vod.created_at, reverse=True)


def clear_vod_metadata_cache() -> None:
    _VOD_METADATA_CACHE.clear()


def load_vod(path: Path) -> LoadedVod:
    metadata_record: dict[str, Any] | None = None
    summary_record: dict[str, Any] | None = None
    snapshots: list[VodSnapshot] = []
    # One string pool for the whole file, dropped when this returns -- the
    # strings it shares are then held by the snapshots that use them, not by it.
    # See `_record_to_snapshot`, which is where the sharing happens.
    pool: dict[str, str] = {}

    for record in _iter_records(path):
        record_type = record.get("type")
        if record_type == "metadata":
            metadata_record = record
        elif record_type == "summary":
            summary_record = record
        elif record_type == "snapshot":
            snapshots.append(_record_to_snapshot(record, pool))

    if metadata_record is None:
        raise ValueError(f"VOD metadata is missing in {path}")

    metadata = _metadata_from_records(path, metadata_record, summary_record, snapshots)
    return LoadedVod(metadata=metadata, snapshots=tuple(snapshots))


def load_vod_metadata(path: Path) -> VodMetadata:
    stat = path.stat()
    resolved_path = path.resolve()
    cached = _VOD_METADATA_CACHE.get(resolved_path)
    if cached is not None:
        cached_mtime_ns, cached_size, cached_metadata = cached
        if cached_mtime_ns == stat.st_mtime_ns and cached_size == stat.st_size:
            return cached_metadata

    first_record = _read_first_record(path)
    last_record = _read_last_record(path)
    if (
        first_record.get("type") == "metadata"
        and last_record.get("type") == "summary"
        and "snapshot_count" in last_record
    ):
        metadata = _metadata_from_records(
            path,
            first_record,
            last_record,
            snapshot_count=int(last_record.get("snapshot_count") or 0),
        )
        _VOD_METADATA_CACHE[resolved_path] = (stat.st_mtime_ns, stat.st_size, metadata)
        return metadata

    metadata_record: dict[str, Any] | None = None
    summary_record: dict[str, Any] | None = None
    last_snapshot_elapsed_seconds = 0
    snapshot_count = 0

    for record in _iter_records(path):
        record_type = record.get("type")
        if record_type == "metadata":
            metadata_record = record
        elif record_type == "summary":
            summary_record = record
        elif record_type == "snapshot":
            snapshot_count += 1
            last_snapshot_elapsed_seconds = int(record.get("elapsed_seconds") or 0)

    if metadata_record is None:
        raise ValueError(f"VOD metadata is missing in {path}")

    metadata = _metadata_from_records(
        path,
        metadata_record,
        summary_record,
        snapshot_count=snapshot_count,
        last_snapshot_elapsed_seconds=last_snapshot_elapsed_seconds,
    )
    _VOD_METADATA_CACHE[resolved_path] = (stat.st_mtime_ns, stat.st_size, metadata)
    return metadata


def rename_vod(path: Path, new_name: str) -> VodMetadata:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("VOD name cannot be empty.")

    target_path = _renamed_vod_path(path, new_name)
    records = list(_iter_records(path))
    if not records or records[0].get("type") != "metadata":
        raise ValueError(f"VOD metadata is missing in {path}")

    records[0]["name"] = new_name
    for record in records:
        if record.get("type") == "summary":
            record["name"] = new_name
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(_dumps_record(record))
            file.write("\n")
    os.replace(temp_path, target_path)
    if target_path != path:
        path.unlink(missing_ok=True)
    clear_vod_metadata_cache()
    return load_vod_metadata(target_path)


def delete_vod(path: Path) -> None:
    path.unlink(missing_ok=True)
    clear_vod_metadata_cache()


def delete_vods_below_snapshot_count(
    min_snapshot_count: int,
    vods_dir: Path | None = None,
    *,
    excluded_paths: set[Path] | None = None,
) -> VodCleanupResult:
    threshold = max(0, int(min_snapshot_count))
    excluded_resolved_paths = {
        path.resolve() for path in (excluded_paths or set())
    }
    removed = 0
    skipped_active = 0
    skipped_locked = 0
    for metadata in list_vods(vods_dir):
        if metadata.snapshot_count >= threshold:
            continue
        if metadata.path.resolve() in excluded_resolved_paths:
            skipped_active += 1
            continue
        try:
            delete_vod(metadata.path)
        except PermissionError:
            skipped_locked += 1
            continue
        except OSError:
            # A file can become locked or disappear after list_vods() returns.
            # Keep cleaning the remaining short recordings in either case.
            skipped_locked += 1
            continue
        removed += 1
    return VodCleanupResult(
        removed=removed,
        skipped_active=skipped_active,
        skipped_locked=skipped_locked,
    )


def _dumps_record(record: dict[str, Any]) -> str:
    return dumps_strict_json(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _loads_record(payload: str | bytes) -> dict[str, Any]:
    # Older Python-written recordings may contain these non-standard tokens.
    # They are unreadable measurements, not zeroes; new recordings use null.
    record = loads_legacy_json(payload)
    if not isinstance(record, dict):
        raise ValueError("Every VOD JSONL entry must be an object.")
    return record


def _iter_records(path: Path):
    """Yield records, tolerating only an incomplete final write.

    A process can exit between writing a JSON object and its terminating
    newline. A malformed complete line, or one followed by another record, is
    real corruption and must still fail loudly.
    """
    pending_line: bytes | None = None
    with path.open("rb") as file:
        for line in file:
            if not line.strip():
                continue
            if pending_line is not None:
                yield _loads_record(pending_line)
            pending_line = line

    if pending_line is None:
        return
    try:
        yield _loads_record(pending_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        if pending_line.endswith((b"\n", b"\r")):
            raise


def _read_first_record(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        for line in file:
            line = line.strip()
            if line:
                return _loads_record(line)
    return {}


def _read_last_record(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        position = file.tell()
        if position == 0:
            return {}

        file.seek(position - 1)
        may_skip_incomplete_tail = file.read(1) not in (b"\n", b"\r")

        while position > 0:
            buffer = bytearray()
            while position > 0:
                position -= 1
                file.seek(position)
                char = file.read(1)
                if char == b"\n" and buffer:
                    break
                if char not in (b"\n", b"\r"):
                    buffer.extend(char)
            if not buffer:
                continue
            try:
                return _loads_record(bytes(reversed(buffer)))
            except (UnicodeDecodeError, json.JSONDecodeError):
                if not may_skip_incomplete_tail:
                    raise
                may_skip_incomplete_tail = False

    return {}


def _metadata_from_records(
    path: Path,
    metadata_record: dict[str, Any],
    summary_record: dict[str, Any] | None,
    snapshots: list[VodSnapshot] | None = None,
    *,
    snapshot_count: int | None = None,
    last_snapshot_elapsed_seconds: int = 0,
) -> VodMetadata:
    snapshots = snapshots or []
    if snapshot_count is None:
        snapshot_count = len(snapshots)

    duration_seconds = last_snapshot_elapsed_seconds
    if snapshots:
        duration_seconds = snapshots[-1].elapsed_seconds
    if summary_record is not None:
        duration_seconds = _coerce_int(
            summary_record.get("duration_seconds"), default=duration_seconds
        )

    raw_run_seed = metadata_record.get("run_seed")
    try:
        run_seed = int(raw_run_seed) if raw_run_seed is not None else None
    except (TypeError, ValueError):
        run_seed = None

    summary_name = summary_record.get("name") if summary_record is not None else None
    return VodMetadata(
        path=path,
        name=str(summary_name or metadata_record.get("name") or path.stem),
        created_at=str(metadata_record.get("created_at") or ""),
        interval_seconds=int(metadata_record.get("snapshot_interval_seconds") or 30),
        duration_seconds=duration_seconds,
        snapshot_count=snapshot_count,
        run_seed=run_seed,
        character_id=_coerce_optional_int(metadata_record.get("character_id")),
        character_name=(
            str(metadata_record.get("character_name"))
            if metadata_record.get("character_name")
            else None
        ),
    )


def _snapshot_to_record(snapshot: VodSnapshot) -> dict[str, Any]:
    record = {
        "type": "snapshot",
        "elapsed_seconds": snapshot.elapsed_seconds,
        "captured_at": snapshot.captured_at,
        "stats": {
            label: {
                "value": stat.value,
                "display": stat.display_value,
            }
            for label, stat in snapshot.stats.items()
        },
        "items": list(snapshot.items),
        "weapons": [_weapon_to_record(weapon) for weapon in snapshot.weapons],
        "tomes": [_tome_to_record(tome) for tome in snapshot.tomes],
        "chaos_tome": _chaos_tome_to_record(snapshot.chaos_tome),
        "shrines": _charge_shrines_to_record(snapshot.shrines),
        "character_passive": _character_passive_to_record(
            snapshot.character_passive
        ),
        "banishes": list(snapshot.banishes),
        "damage_sources": [_damage_source_to_record(source) for source in snapshot.damage_sources],
        "chests_per_minute": snapshot.chests_per_minute,
    }
    if snapshot.game_time_seconds is not None:
        record["game_time_seconds"] = snapshot.game_time_seconds
    if snapshot.mob_kills is not None:
        record["mob_kills"] = snapshot.mob_kills
    if snapshot.kps_at_capture is not None:
        record["kps_at_capture"] = snapshot.kps_at_capture
    if snapshot.minute_avg_kps_at_capture is not None:
        record["minute_avg_kps_at_capture"] = snapshot.minute_avg_kps_at_capture
    if snapshot.five_minute_avg_kps_at_capture is not None:
        record["five_minute_avg_kps_at_capture"] = snapshot.five_minute_avg_kps_at_capture
    if snapshot.run_avg_kps_at_capture is not None:
        record["run_avg_kps_at_capture"] = snapshot.run_avg_kps_at_capture
    if snapshot.player_level is not None:
        record["player_level"] = snapshot.player_level
    if snapshot.map_seed is not None:
        record["map_seed"] = snapshot.map_seed
    if snapshot.stage_ptr:
        record["stage_ptr"] = snapshot.stage_ptr
    if snapshot.stage_index is not None:
        record["stage_index"] = snapshot.stage_index
    if snapshot.stage_time_seconds is not None:
        record["stage_time_seconds"] = snapshot.stage_time_seconds
    if snapshot.chests_opened is not None:
        record["chests_opened"] = snapshot.chests_opened
    if snapshot.chests_total is not None:
        record["chests_total"] = snapshot.chests_total
    if snapshot.pots_total is not None:
        record["pots_total"] = snapshot.pots_total
    if snapshot.paid_chests is not None:
        record["paid_chests"] = snapshot.paid_chests
    if snapshot.key_procs is not None:
        record["key_procs"] = snapshot.key_procs
    if snapshot.free_chests is not None:
        record["free_chests"] = snapshot.free_chests
    if snapshot.keys_count is not None:
        record["keys_count"] = snapshot.keys_count
    if snapshot.expected_key_procs is not None:
        record["expected_key_procs"] = snapshot.expected_key_procs
    if snapshot.chests_opened_by_stage is not None:
        record["chests_opened_by_stage"] = snapshot.chests_opened_by_stage
    if snapshot.chests_total_by_stage is not None:
        record["chests_total_by_stage"] = snapshot.chests_total_by_stage
    if snapshot.loot_actual is not None:
        record["loot_actual"] = snapshot.loot_actual
    if snapshot.loot_expected is not None:
        record["loot_expected"] = snapshot.loot_expected
    return record


def _shared_display(value: Any, share) -> str:
    """A stat's display text, shared with every other snapshot that shows it."""
    if type(value) is str:
        return share(value, value)
    return str(value) if value else "--"


def _shared_name(value: Any, share) -> str:
    """An item or banish name, shared across the snapshots that carry it."""
    if type(value) is str:
        return share(value, value)
    return str(value)


def _record_to_snapshot(record: dict[str, Any], pool: dict[str, str] | None = None) -> VodSnapshot:
    """One snapshot record as a `VodSnapshot`, sharing strings through `pool`.

    A recording is one JSON object per line, so the decoder runs once per line
    and throws its key memo away in between: a file of 713 snapshots ends up
    holding 713 separate copies of every stat name, and 21,390 separate copies
    of the handful of display strings those stats cycle through. The vocabulary
    is a few hundred strings stored tens of thousands of times.

    `pool` is the caller's, one per load and dropped with it -- see `load_vod`.
    Not `sys.intern`, which is process-wide and permanent, and these include
    run-specific text. Sharing only here rather than through a decoder hook is
    deliberate: a hook runs for every key in the file and cost 260ms a load,
    where three dict lookups per stat cost almost nothing for the same 5 MB.

    `None` keeps the old behaviour for the callers that read a single record and
    have no load to pool across.
    """
    raw_stats = record.get("stats") or {}
    if pool is None:
        pool = {}
    share = pool.setdefault
    return VodSnapshot(
        elapsed_seconds=int(record.get("elapsed_seconds") or 0),
        captured_at=float(record.get("captured_at") or 0.0),
        stats={
            share(label, label) if type(label) is str else str(label): VodStatValue(
                value=value.get("value"),
                display_value=_shared_display(value.get("display"), share),
            )
            for label, value in raw_stats.items()
            if isinstance(value, dict)
        },
        items=tuple(_shared_name(item, share) for item in record.get("items") or ()),
        weapons=tuple(_record_to_weapon(weapon, share) for weapon in record.get("weapons") or ()),
        tomes=tuple(_record_to_tome(tome, share) for tome in record.get("tomes") or ()),
        chaos_tome=_record_to_chaos_tome(record.get("chaos_tome")),
        shrines=_record_to_charge_shrines(record.get("shrines"), share),
        character_passive=_record_to_character_passive(
            record.get("character_passive"), share
        ),
        banishes=tuple(_shared_name(item, share) for item in record.get("banishes") or ()),
        damage_sources=tuple(_record_to_damage_source(item, share) for item in record.get("damage_sources") or ()),
        chests_per_minute=_coerce_optional_float(record.get("chests_per_minute")),
        game_time_seconds=_coerce_optional_float(
            record.get("game_time_seconds", record.get("in_game_elapsed_seconds"))
        ),
        mob_kills=_coerce_optional_int(record.get("mob_kills", record.get("mobs_alive"))),
        kps_at_capture=_coerce_optional_int(record.get("kps_at_capture")),
        minute_avg_kps_at_capture=_coerce_optional_int(record.get("minute_avg_kps_at_capture")),
        five_minute_avg_kps_at_capture=_coerce_optional_int(record.get("five_minute_avg_kps_at_capture")),
        run_avg_kps_at_capture=_coerce_optional_int(record.get("run_avg_kps_at_capture")),
        player_level=_coerce_optional_int(record.get("player_level")),
        map_seed=_coerce_optional_int(record.get("map_seed", record.get("run_seed"))),
        stage_ptr=_coerce_int(record.get("stage_ptr")),
        stage_index=_coerce_optional_int(record.get("stage_index")),
        stage_time_seconds=_coerce_optional_float(record.get("stage_time_seconds")),
        chests_opened=_coerce_optional_int(record.get("chests_opened")),
        chests_total=_coerce_optional_int(record.get("chests_total")),
        pots_total=_coerce_optional_int(record.get("pots_total")),
        paid_chests=_coerce_optional_int(record.get("paid_chests")),
        key_procs=_coerce_optional_int(record.get("key_procs")),
        free_chests=_coerce_optional_int(record.get("free_chests")),
        keys_count=_coerce_optional_int(record.get("keys_count")),
        expected_key_procs=_coerce_optional_float(record.get("expected_key_procs")),
        chests_opened_by_stage=_coerce_int_dict(record.get("chests_opened_by_stage")),
        chests_total_by_stage=_coerce_int_dict(record.get("chests_total_by_stage")),
        loot_actual=_coerce_rarity_int_dict(record.get("loot_actual")),
        loot_expected=_coerce_rarity_float_dict(record.get("loot_expected")),
    )


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_rarity_int_dict(value: Any) -> dict[str, int] | None:
    """Tier -> count, or ``None`` when the key was absent.

    Absence must survive as ``None`` all the way to the comparison. Returning
    ``{}`` here would look like a recorded run that gained nothing.
    """
    if not isinstance(value, dict):
        return None
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result


def _coerce_rarity_float_dict(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, float] = {}
    for key, item in value.items():
        converted = _coerce_optional_float(item)
        if converted is not None:
            result[str(key)] = converted
    return result


def _coerce_int_dict(value: Any) -> dict[int, int] | None:
    if not isinstance(value, dict):
        return None
    result: dict[int, int] = {}
    for key, item in value.items():
        try:
            result[int(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result


def _weapon_to_record(weapon: WeaponSnapshot) -> dict[str, Any]:
    return {
        "id": weapon.weapon_id,
        "name": weapon.name,
        "level": weapon.level,
        "upgrade_stat_ids": list(weapon.upgrade_stat_ids),
        "upgraded_stats": {
            str(stat_id): _weapon_stat_value_to_record(value)
            for stat_id, value in weapon.upgraded_stats.items()
        },
        "full_stats": {
            str(stat_id): _weapon_stat_value_to_record(value)
            for stat_id, value in weapon.full_stats.items()
        },
    }


def _tome_to_record(tome: TomeSnapshot) -> dict[str, Any]:
    return {
        "id": tome.tome_id,
        "name": tome.name,
        "level": tome.level,
        "stat_id": tome.stat_id,
        "stat_label": tome.stat_label,
        "value": tome.value,
        "display": tome.display_value,
        "value_format": tome.value_format.value,
    }


def _chaos_tome_to_record(chaos_tome: ChaosTomeSnapshot | None) -> dict[str, Any] | None:
    if chaos_tome is None:
        return None
    return {
        "level": chaos_tome.level,
        "ambiguous_rolls": chaos_tome.ambiguous_rolls,
        "stats": [
            {
                "stat_id": stat.stat_id,
                "label": stat.label,
                "value": stat.value,
                "display": stat.display_delta,
                "value_format": stat.value_format.value,
                "rolls": stat.rolls,
            }
            for stat in chaos_tome.stats
        ],
    }


def _charge_shrines_to_record(shrines: ChargeShrineSnapshot | None) -> dict[str, Any] | None:
    if shrines is None:
        return None

    def stat_record(stat: ChargeShrineStatSnapshot) -> dict[str, Any]:
        return {
            "stat_id": stat.stat_id,
            "label": stat.label,
            "value": stat.value,
            "value_format": stat.value_format.value,
            "rolls": stat.rolls,
            "rarity_counts": [[rarity, count] for rarity, count in stat.rarity_counts],
        }

    return {
        "charged": shrines.charged,
        "selected": shrines.selected,
        "pending": shrines.pending,
        "stats": [stat_record(stat) for stat in shrines.stats],
        "ambiguous_matches": shrines.ambiguous_matches,
    }


def _character_passive_to_record(
    passive: CharacterPassiveSnapshot | None,
) -> dict[str, Any] | None:
    if passive is None:
        return None
    return {
        "character_id": passive.character_id,
        "character_name": passive.character_name,
        "passive_id": passive.passive_id,
        "passive_name": passive.passive_name,
        "runtime_class": passive.runtime_class,
        "level": passive.level,
        "status": passive.status.value,
        "coverage": passive.coverage,
        "ambiguous": passive.ambiguous,
        "pending": passive.pending,
        "effects": [
            {
                "key": effect.key,
                "label": effect.label,
                "value": effect.value,
                "value_format": effect.value_format.value,
                "kind": effect.kind.value,
                "stat_id": effect.stat_id,
                "count": effect.count,
            }
            for effect in passive.effects
        ],
    }


def _damage_source_to_record(source: DamageSourceSnapshot) -> dict[str, Any]:
    return {
        "source_key": source.source_key,
        "source_name": source.source_name,
        "damage": source.damage,
        "added_at_time": source.added_at_time,
    }


def _weapon_stat_value_to_record(value: WeaponStatValue) -> dict[str, Any]:
    return {
        "label": value.label,
        "value": value.value,
        "display": value.display_value,
        "value_format": value.value_format.value,
    }


def _record_to_weapon(record: Any, share=None) -> WeaponSnapshot:
    share = share or (lambda value, _default: value)
    if not isinstance(record, dict):
        return WeaponSnapshot(weapon_id=-1, name="Unknown Weapon", level=0, upgrade_stat_ids=(), upgraded_stats={}, full_stats={})

    raw_upgraded_stats = record.get("upgraded_stats") or {}
    raw_full_stats = record.get("full_stats") or {}
    upgrade_stat_ids = tuple(
        int(stat_id)
        for stat_id in record.get("upgrade_stat_ids") or ()
        if _is_int_like(stat_id)
    )
    return WeaponSnapshot(
        weapon_id=_coerce_int(record.get("id"), default=-1),
        name=_shared_name(record.get("name") or "Unknown Weapon", share),
        level=max(_coerce_int(record.get("level"), default=0), 0),
        upgrade_stat_ids=upgrade_stat_ids,
        upgraded_stats=_record_to_weapon_stats(raw_upgraded_stats),
        full_stats=_record_to_weapon_stats(raw_full_stats),
    )


def _record_to_tome(record: Any, share=None) -> TomeSnapshot:
    share = share or (lambda value, _default: value)
    if not isinstance(record, dict):
        return TomeSnapshot(
            tome_id=-1,
            name="Unknown Tome",
            level=0,
            stat_id=None,
            stat_label="Unknown",
            value=None,
            value_format=PlayerStatFormat.FLAT,
        )

    value_format_name = str(record.get("value_format") or PlayerStatFormat.FLAT.value)
    try:
        value_format = PlayerStatFormat(value_format_name)
    except ValueError:
        value_format = PlayerStatFormat.FLAT
    return TomeSnapshot(
        tome_id=_coerce_int(record.get("id"), default=-1),
        name=_shared_name(record.get("name") or "Unknown Tome", share),
        level=max(_coerce_int(record.get("level"), default=0), 0),
        stat_id=_coerce_optional_int(record.get("stat_id")),
        stat_label=_shared_name(record.get("stat_label") or "Unknown", share),
        value=_coerce_optional_float(record.get("value")),
        value_format=value_format,
    )


def _record_to_chaos_tome(record: Any) -> ChaosTomeSnapshot | None:
    if not isinstance(record, dict):
        return None
    stats = []
    for raw_stat in record.get("stats") or ():
        if not isinstance(raw_stat, dict):
            continue
        value_format_name = str(raw_stat.get("value_format") or PlayerStatFormat.FLAT.value)
        try:
            value_format = PlayerStatFormat(value_format_name)
        except ValueError:
            value_format = PlayerStatFormat.FLAT
        stats.append(
            ChaosTomeStatSnapshot(
                stat_id=_coerce_int(raw_stat.get("stat_id"), default=-1),
                label=str(raw_stat.get("label") or f"Stat {raw_stat.get('stat_id', '?')}"),
                value=_coerce_optional_float(raw_stat.get("value")),
                value_format=value_format,
                rolls=max(_coerce_int(raw_stat.get("rolls"), default=0), 0),
            )
        )
    return ChaosTomeSnapshot(
        level=max(_coerce_int(record.get("level"), default=0), 0),
        stats=tuple(stats),
        ambiguous_rolls=max(_coerce_int(record.get("ambiguous_rolls"), default=0), 0),
    )


def _record_to_charge_shrines(record: Any, share=None) -> ChargeShrineSnapshot | None:
    if not isinstance(record, dict):
        return None
    share = share or (lambda value, _default: value)

    def read_stats(raw_stats: Any) -> tuple[ChargeShrineStatSnapshot, ...]:
        decoded = []
        for raw_stat in raw_stats or ():
            if not isinstance(raw_stat, dict):
                continue
            value_format_name = str(
                raw_stat.get("value_format") or PlayerStatFormat.FLAT.value
            )
            try:
                value_format = PlayerStatFormat(value_format_name)
            except ValueError:
                value_format = PlayerStatFormat.FLAT
            rarities = []
            for pair in raw_stat.get("rarity_counts") or ():
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                count = max(0, _coerce_int(pair[1], default=0))
                if count:
                    rarities.append((_shared_name(pair[0], share), count))
            stat_id = _coerce_int(raw_stat.get("stat_id"), default=-1)
            decoded.append(
                ChargeShrineStatSnapshot(
                    stat_id=stat_id,
                    label=_shared_name(
                        raw_stat.get("label") or f"Stat {stat_id}", share
                    ),
                    value=_coerce_optional_float(raw_stat.get("value")),
                    value_format=value_format,
                    rolls=max(0, _coerce_int(raw_stat.get("rolls"), default=0)),
                    rarity_counts=tuple(rarities),
                )
            )
        return tuple(decoded)

    raw_stats = record.get("stats")
    if raw_stats is None:
        raw_stats = record.get("run_stats")
    return ChargeShrineSnapshot(
        charged=max(
            0,
            _coerce_int(
                record.get("charged", record.get("run_charged")), default=0
            ),
        ),
        selected=max(
            0,
            _coerce_int(
                record.get("selected", record.get("run_selected")), default=0
            ),
        ),
        pending=max(
            0,
            _coerce_int(
                record.get("pending", record.get("run_pending")), default=0
            ),
        ),
        stats=read_stats(raw_stats),
        ambiguous_matches=max(
            0, _coerce_int(record.get("ambiguous_matches"), default=0)
        ),
    )


def _record_to_character_passive(record: Any, share=None) -> CharacterPassiveSnapshot | None:
    if not isinstance(record, dict):
        return None
    share = share or (lambda value, _default: value)
    try:
        status = CharacterPassiveStatus(
            str(record.get("status") or CharacterPassiveStatus.UNAVAILABLE.value)
        )
    except ValueError:
        status = CharacterPassiveStatus.UNKNOWN

    effects = []
    for raw_effect in record.get("effects") or ():
        if not isinstance(raw_effect, dict):
            continue
        try:
            value_format = PlayerStatFormat(
                str(raw_effect.get("value_format") or PlayerStatFormat.FLAT.value)
            )
        except ValueError:
            value_format = PlayerStatFormat.FLAT
        try:
            kind = CharacterPassiveEffectKind(
                str(
                    raw_effect.get("kind")
                    or CharacterPassiveEffectKind.PERMANENT_LEVEL.value
                )
            )
        except ValueError:
            kind = CharacterPassiveEffectKind.COUNTER
        effects.append(
            CharacterPassiveEffectSnapshot(
                key=_shared_name(raw_effect.get("key") or "effect", share),
                label=_shared_name(
                    raw_effect.get("label") or "Passive bonus", share
                ),
                value=_coerce_optional_float(raw_effect.get("value")),
                value_format=value_format,
                kind=kind,
                stat_id=_coerce_optional_int(raw_effect.get("stat_id")),
                count=_coerce_optional_int(raw_effect.get("count")),
            )
        )

    return CharacterPassiveSnapshot(
        character_id=_coerce_int(record.get("character_id"), default=-1),
        character_name=_shared_name(
            record.get("character_name") or "Unknown Character", share
        ),
        passive_id=_coerce_int(record.get("passive_id"), default=-1),
        passive_name=_shared_name(
            record.get("passive_name") or "Unknown Passive", share
        ),
        runtime_class=_shared_name(record.get("runtime_class") or "", share),
        level=max(0, _coerce_int(record.get("level"), default=0)),
        status=status,
        effects=tuple(effects),
        coverage=_shared_name(record.get("coverage") or "identity_only", share),
        ambiguous=max(0, _coerce_int(record.get("ambiguous"), default=0)),
        pending=max(0, _coerce_int(record.get("pending"), default=0)),
    )


def _record_to_damage_source(record: Any, share=None) -> DamageSourceSnapshot:
    share = share or (lambda value, _default: value)
    if not isinstance(record, dict):
        return DamageSourceSnapshot(source_key="Unknown", source_name="Unknown", damage=0.0, added_at_time=None)
    return DamageSourceSnapshot(
        source_key=_shared_name(record.get("source_key") or "Unknown", share),
        source_name=_shared_name(record.get("source_name") or record.get("source_key") or "Unknown", share),
        damage=_coerce_optional_float(record.get("damage")),
        added_at_time=_coerce_optional_float(record.get("added_at_time")),
    )


def _record_to_weapon_stats(raw_stats: Any) -> dict[int, WeaponStatValue]:
    if not isinstance(raw_stats, dict):
        return {}

    stats: dict[int, WeaponStatValue] = {}
    for raw_stat_id, raw_value in raw_stats.items():
        if not _is_int_like(raw_stat_id) or not isinstance(raw_value, dict):
            continue
        stat_id = int(raw_stat_id)
        value_format_name = str(raw_value.get("value_format") or WeaponStatFormat.FLAT.value)
        try:
            value_format = WeaponStatFormat(value_format_name)
        except ValueError:
            value_format = WeaponStatFormat.FLAT
        stats[stat_id] = WeaponStatValue(
            stat_id=stat_id,
            label=str(raw_value.get("label") or f"Stat {stat_id}"),
            value=_coerce_optional_float(raw_value.get("value")),
            value_format=value_format,
        )
    return stats


def _coerce_optional_float(value: Any) -> float | None:
    try:
        converted = float(value) if value is not None else None
    except (OverflowError, TypeError, ValueError):
        return None
    return converted if converted is not None and isfinite(converted) else None


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_int_like(value: Any) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique VOD path for {path}")


def _renamed_vod_path(path: Path, new_name: str) -> Path:
    safe_stem = _sanitize_vod_filename(new_name)
    candidate = path.with_name(f"{safe_stem}{path.suffix}")
    if candidate == path:
        return path
    return _unique_path(candidate)


def _sanitize_vod_filename(value: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    safe = "".join("_" if char in invalid_chars else char for char in value)
    safe = " ".join(safe.split()).strip(" .")
    return safe or "recording"
