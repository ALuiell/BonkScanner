from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any

import config
from player_stats import (
    ChaosTomeSnapshot,
    ChaosTomeStatSnapshot,
    DamageSourceSnapshot,
    PlayerStatFormat,
    PlayerStatValue,
    TomeSnapshot,
    WeaponSnapshot,
    WeaponStatFormat,
    WeaponStatValue,
)


VOD_FORMAT_VERSION = 5
RECORDINGS_DIR = Path(config.application_path) / "stats_recordings"
LEGACY_VODS_DIR = Path(config.application_path) / "vods"
_VOD_METADATA_CACHE: dict[Path, tuple[int, int, VodMetadata]] = {}
SNAPSHOT_FLUSH_EVERY = 3


@dataclass(frozen=True)
class VodStatValue:
    value: float | None
    display_value: str


@dataclass(frozen=True)
class VodSnapshot:
    elapsed_seconds: int
    captured_at: float
    stats: dict[str, VodStatValue]
    items: tuple[str, ...] = ()
    weapons: tuple[WeaponSnapshot, ...] = ()
    tomes: tuple[TomeSnapshot, ...] = ()
    chaos_tome: ChaosTomeSnapshot | None = None
    banishes: tuple[str, ...] = ()
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    mob_kills: int | None = None
    kps_at_capture: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
    stage_time_seconds: float | None = None
    chests_opened: int | None = None
    chests_total: int | None = None
    paid_chests: int | None = None
    key_procs: int | None = None
    free_chests: int | None = None
    keys_count: int | None = None
    expected_key_procs: float | None = None
    chests_opened_by_stage: dict[int, int] | None = None
    chests_total_by_stage: dict[int, int] | None = None

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


class VodRecorder:
    def __init__(
        self,
        *,
        vods_dir: Path | None = None,
        interval_seconds: int = 30,
        clock=time.monotonic,
    ) -> None:
        self.vods_dir = vods_dir or RECORDINGS_DIR
        self.interval_seconds = max(1, int(interval_seconds))
        self.clock = clock
        self.path: Path | None = None
        self.name = ""
        self.start_time: float | None = None
        self.last_snapshot_time: float | None = None
        self.snapshot_count = 0
        self.is_recording = False
        self._file = None

    def start(self, *, name: str | None = None, seed: int | None = None) -> Path:
        self.vods_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now().replace(microsecond=0)
        file_stem = created_at.strftime("%Y-%m-%d_%H-%M-%S")
        self.path = _unique_path(self.vods_dir / f"{file_stem}.jsonl")
        self.name = name or f"Run {created_at.strftime('%Y-%m-%d %H:%M:%S')}"
        self.start_time = self.clock()
        self.last_snapshot_time = None
        self.snapshot_count = 0
        self.is_recording = True
        self._file = self.path.open("w", encoding="utf-8")
        self._write_record(
            {
                "type": "metadata",
                "version": VOD_FORMAT_VERSION,
                "name": self.name,
                "created_at": created_at.isoformat(),
                "snapshot_interval_seconds": self.interval_seconds,
                "run_seed": seed,
            },
            flush=True,
        )
        return self.path

    def stop(self) -> str:
        self.is_recording = False
        status = "kept"
        if self._file is not None:
            self._write_record(
                {
                    "type": "summary",
                    "duration_seconds": self.elapsed_seconds(),
                    "snapshot_count": self.snapshot_count,
                },
                flush=True,
            )
            self._file.flush()
            self._file.close()
            self._file = None
        if self.path is not None and self.snapshot_count == 0:
            self.path.unlink(missing_ok=True)
            clear_vod_metadata_cache()
            status = "deleted_empty"
        return status

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self.is_recording = False

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
        chests_per_minute: float | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        kps_at_capture: int | None = None,
        player_level: int | None = None,
        map_seed: int | None = None,
        stage_ptr: int = 0,
        stage_time_seconds: float | None = None,
        chests_opened: int | None = None,
        chests_total: int | None = None,
        paid_chests: int | None = None,
        key_procs: int | None = None,
        free_chests: int | None = None,
        keys_count: int | None = None,
        expected_key_procs: float | None = None,
        chests_opened_by_stage: dict[int, int] | None = None,
        chests_total_by_stage: dict[int, int] | None = None,
    ) -> VodSnapshot:
        if not self.is_recording or self._file is None:
            raise RuntimeError("VOD recorder is not active.")

        now = self.clock()
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
            banishes=tuple(banishes),
            damage_sources=tuple(damage_sources),
            chests_per_minute=chests_per_minute,
            game_time_seconds=game_time_seconds,
            mob_kills=mob_kills,
            kps_at_capture=kps_at_capture,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_time_seconds=stage_time_seconds,
            chests_opened=chests_opened,
            chests_total=chests_total,
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
        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
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

    for record in _iter_records(path):
        record_type = record.get("type")
        if record_type == "metadata":
            metadata_record = record
        elif record_type == "summary":
            summary_record = record
        elif record_type == "snapshot":
            snapshots.append(_record_to_snapshot(record))

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
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
    os.replace(temp_path, target_path)
    if target_path != path:
        path.unlink(missing_ok=True)
    clear_vod_metadata_cache()
    return load_vod_metadata(target_path)


def delete_vod(path: Path) -> None:
    path.unlink(missing_ok=True)
    clear_vod_metadata_cache()


def delete_vods_below_snapshot_count(min_snapshot_count: int, vods_dir: Path | None = None) -> int:
    threshold = max(0, int(min_snapshot_count))
    removed = 0
    for metadata in list_vods(vods_dir):
        if metadata.snapshot_count < threshold:
            delete_vod(metadata.path)
            removed += 1
    return removed


def _iter_records(path: Path):
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                yield json.loads(line)


def _read_first_record(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                return json.loads(line)
    return {}


def _read_last_record(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        position = file.tell()
        if position == 0:
            return {}

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
        return {}

    return json.loads(bytes(reversed(buffer)).decode("utf-8"))


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
        duration_seconds = int(summary_record.get("duration_seconds", duration_seconds))

    raw_run_seed = metadata_record.get("run_seed")
    try:
        run_seed = int(raw_run_seed) if raw_run_seed is not None else None
    except (TypeError, ValueError):
        run_seed = None

    return VodMetadata(
        path=path,
        name=str(metadata_record.get("name") or path.stem),
        created_at=str(metadata_record.get("created_at") or ""),
        interval_seconds=int(metadata_record.get("snapshot_interval_seconds") or 30),
        duration_seconds=duration_seconds,
        snapshot_count=snapshot_count,
        run_seed=run_seed,
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
    if snapshot.player_level is not None:
        record["player_level"] = snapshot.player_level
    if snapshot.map_seed is not None:
        record["map_seed"] = snapshot.map_seed
    if snapshot.stage_ptr:
        record["stage_ptr"] = snapshot.stage_ptr
    if snapshot.stage_time_seconds is not None:
        record["stage_time_seconds"] = snapshot.stage_time_seconds
    if snapshot.chests_opened is not None:
        record["chests_opened"] = snapshot.chests_opened
    if snapshot.chests_total is not None:
        record["chests_total"] = snapshot.chests_total
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
    return record


def _record_to_snapshot(record: dict[str, Any]) -> VodSnapshot:
    raw_stats = record.get("stats") or {}
    return VodSnapshot(
        elapsed_seconds=int(record.get("elapsed_seconds") or 0),
        captured_at=float(record.get("captured_at") or 0.0),
        stats={
            str(label): VodStatValue(
                value=value.get("value"),
                display_value=str(value.get("display") or "--"),
            )
            for label, value in raw_stats.items()
            if isinstance(value, dict)
        },
        items=tuple(str(item) for item in record.get("items") or ()),
        weapons=tuple(_record_to_weapon(weapon) for weapon in record.get("weapons") or ()),
        tomes=tuple(_record_to_tome(tome) for tome in record.get("tomes") or ()),
        chaos_tome=_record_to_chaos_tome(record.get("chaos_tome")),
        banishes=tuple(str(item) for item in record.get("banishes") or ()),
        damage_sources=tuple(_record_to_damage_source(item) for item in record.get("damage_sources") or ()),
        chests_per_minute=_coerce_optional_float(record.get("chests_per_minute")),
        game_time_seconds=_coerce_optional_float(
            record.get("game_time_seconds", record.get("in_game_elapsed_seconds"))
        ),
        mob_kills=_coerce_optional_int(record.get("mob_kills", record.get("mobs_alive"))),
        kps_at_capture=_coerce_optional_int(record.get("kps_at_capture")),
        player_level=_coerce_optional_int(record.get("player_level")),
        map_seed=_coerce_optional_int(record.get("map_seed", record.get("run_seed"))),
        stage_ptr=_coerce_int(record.get("stage_ptr")),
        stage_time_seconds=_coerce_optional_float(record.get("stage_time_seconds")),
        chests_opened=_coerce_optional_int(record.get("chests_opened")),
        chests_total=_coerce_optional_int(record.get("chests_total")),
        paid_chests=_coerce_optional_int(record.get("paid_chests")),
        key_procs=_coerce_optional_int(record.get("key_procs")),
        free_chests=_coerce_optional_int(record.get("free_chests")),
        keys_count=_coerce_optional_int(record.get("keys_count")),
        expected_key_procs=_coerce_optional_float(record.get("expected_key_procs")),
        chests_opened_by_stage=_coerce_int_dict(record.get("chests_opened_by_stage")),
        chests_total_by_stage=_coerce_int_dict(record.get("chests_total_by_stage")),
    )


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _record_to_weapon(record: Any) -> WeaponSnapshot:
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
        name=str(record.get("name") or "Unknown Weapon"),
        level=max(_coerce_int(record.get("level"), default=0), 0),
        upgrade_stat_ids=upgrade_stat_ids,
        upgraded_stats=_record_to_weapon_stats(raw_upgraded_stats),
        full_stats=_record_to_weapon_stats(raw_full_stats),
    )


def _record_to_tome(record: Any) -> TomeSnapshot:
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
        name=str(record.get("name") or "Unknown Tome"),
        level=max(_coerce_int(record.get("level"), default=0), 0),
        stat_id=_coerce_optional_int(record.get("stat_id")),
        stat_label=str(record.get("stat_label") or "Unknown"),
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


def _record_to_damage_source(record: Any) -> DamageSourceSnapshot:
    if not isinstance(record, dict):
        return DamageSourceSnapshot(source_key="Unknown", source_name="Unknown", damage=0.0, added_at_time=None)
    return DamageSourceSnapshot(
        source_key=str(record.get("source_key") or "Unknown"),
        source_name=str(record.get("source_name") or record.get("source_key") or "Unknown"),
        damage=max(0.0, float(record.get("damage") or 0.0)),
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
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
