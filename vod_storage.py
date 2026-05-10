from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any

import config
from player_stats import PlayerStatValue


VOD_FORMAT_VERSION = 1
VODS_DIR = Path(config.application_path) / "vods"
_VOD_METADATA_CACHE: dict[Path, tuple[int, int, VodMetadata]] = {}


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
        interval_seconds: int = 60,
        clock=time.monotonic,
    ) -> None:
        self.vods_dir = vods_dir or VODS_DIR
        self.interval_seconds = max(1, int(interval_seconds))
        self.clock = clock
        self.path: Path | None = None
        self.name = ""
        self.start_time: float | None = None
        self.last_snapshot_time: float | None = None
        self.snapshot_count = 0
        self.is_recording = False
        self._file = None

    def start(self, *, name: str | None = None) -> Path:
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
            },
        )
        return self.path

    def stop(self) -> None:
        self.is_recording = False
        if self._file is not None:
            self._write_record(
                {
                    "type": "summary",
                    "duration_seconds": self.elapsed_seconds(),
                    "snapshot_count": self.snapshot_count,
                },
            )
            self._file.close()
            self._file = None

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
        )
        self._write_record(_snapshot_to_record(snapshot))
        self.last_snapshot_time = now
        self.snapshot_count += 1
        return snapshot

    def _write_record(self, record: dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("VOD recorder file is not open.")
        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        self._file.write("\n")
        self._file.flush()


def list_vods(vods_dir: Path | None = None) -> list[VodMetadata]:
    root = vods_dir or VODS_DIR
    if not root.exists():
        return []

    vods = []
    for path in root.glob("*.jsonl"):
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

    records = list(_iter_records(path))
    if not records or records[0].get("type") != "metadata":
        raise ValueError(f"VOD metadata is missing in {path}")

    records[0]["name"] = new_name
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
    os.replace(temp_path, path)
    clear_vod_metadata_cache()
    return load_vod_metadata(path)


def delete_vod(path: Path) -> None:
    path.unlink(missing_ok=True)
    clear_vod_metadata_cache()


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

    return VodMetadata(
        path=path,
        name=str(metadata_record.get("name") or path.stem),
        created_at=str(metadata_record.get("created_at") or ""),
        interval_seconds=int(metadata_record.get("snapshot_interval_seconds") or 60),
        duration_seconds=duration_seconds,
        snapshot_count=snapshot_count,
    )


def _snapshot_to_record(snapshot: VodSnapshot) -> dict[str, Any]:
    return {
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
    }


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
    )


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique VOD path for {path}")
