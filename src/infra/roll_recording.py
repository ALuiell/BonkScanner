"""Bounded, read-only header/tail access for recorded Roll Analytics.

Never call load_vod here: a recording can contain hours of unrelated snapshots
and power-up samples. Only the header and at most 4 MiB of the tail are read;
no more than four cumulative snapshots are considered, independently per source.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from core.roll_analysis_view import (
    RecordedRollSource, finite_time, recorded_source_from_snapshot,
    valid_recorded_counter_block,
)
from core.roll_analytics import ROLL_SOURCES
from infra.vod_storage import (
    VodFormatError, _loads_record, _normalize_vod_record,
    _record_to_chaos_tome, _record_to_character_passive, _vod_version,
)

HEADER_LIMIT = 64 * 1024
TAIL_LIMIT = 4 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
SNAPSHOT_LIMIT = 4


@dataclass(frozen=True, slots=True)
class RecordedRolls:
    path: Path
    name: str
    version: int
    signature: tuple[int, int]
    sources: tuple[RecordedRollSource, ...]
    snapshots_examined: int
    bytes_read: int
    finalized: bool
    incomplete_tail: bool = False
    created_at: str = ""

    def for_source(self, source: str) -> RecordedRollSource:
        return next(value for value in self.sources if value.source == source)


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _reverse_lines(file, start: int, size: int, meter: list[int], cancelled):
    """Yield complete lines newest first without a byte-at-a-time seek loop."""
    position, carry, read = size, b"", 0
    first = True
    terminated = None
    while position > start and read < TAIL_LIMIT:
        if cancelled is not None and cancelled():
            raise InterruptedError("Recording load cancelled")
        count = min(CHUNK_SIZE, position - start, TAIL_LIMIT - read)
        position -= count
        file.seek(position)
        chunk = file.read(count)
        read += len(chunk)
        meter[0] += len(chunk)
        if len(chunk) != count:
            raise OSError("Recording changed while it was being read; reopen it.")
        if terminated is None:
            terminated = chunk.endswith((b"\n", b"\r"))
        pieces = (chunk + carry).split(b"\n")
        carry = pieces[0]
        for line in reversed(pieces[1:]):
            line = line.rstrip(b"\r")
            if not line.strip():
                continue
            yield line, first and not terminated
            first = False
        if position == start and carry.strip():
            yield carry.rstrip(b"\r"), first and not terminated
            return
    # `carry` may start in the middle of an older record at the byte budget.
    # Do not parse it or fall back to an unbounded scan.


def read_recorded_rolls(path: Path, *, cancelled: Callable[[], bool] | None = None) -> RecordedRolls:
    path = Path(path).resolve()
    found: dict[str, RecordedRollSource] = {}
    examined = 0
    finalized = False
    incomplete_tail = False
    newer_time = None
    source_character = None
    with path.open("rb") as file:
        before = os.fstat(file.fileno())
        signature = (before.st_size, before.st_mtime_ns)
        header = file.readline(HEADER_LIMIT + 1)
        if len(header) > HEADER_LIMIT:
            raise VodFormatError("Recording metadata exceeds the supported size.")
        metadata = _loads_record(header.removeprefix(b"\xef\xbb\xbf"))
        if not isinstance(metadata, dict) or metadata.get("type") != "metadata":
            raise VodFormatError("Recording metadata is missing.")
        version = _vod_version(metadata)  # Preserve the normal version safety gate.
        name = str(metadata.get("name") or path.stem)
        start = file.tell()
        meter = [len(header)]
        for raw, may_be_incomplete in _reverse_lines(file, start, before.st_size, meter, cancelled):
            try:
                record = _loads_record(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                if may_be_incomplete:
                    incomplete_tail = True
                    continue
                raise VodFormatError("Corrupt JSON in the recording tail.") from None
            if not isinstance(record, dict):
                raise VodFormatError("Invalid recording tail record.")
            kind = record.get("type")
            if kind == "summary":
                if not finalized:
                    name = str(record.get("name") or name)
                finalized = True
                continue
            if kind != "snapshot":
                continue
            record = _normalize_vod_record(record, version)
            time = finite_time(record.get("game_time_seconds", record.get("in_game_elapsed_seconds")))
            # Do not recover from the preceding run if an abnormal file includes a reset.
            if examined and time is not None and newer_time is not None and time > newer_time + 0.1:
                break
            raw_passive = record.get("character_passive")
            character = raw_passive.get("character_id") if isinstance(raw_passive, dict) else None
            if source_character is not None and character is not None and character != source_character:
                break
            if character is not None:
                source_character = character
            if time is not None:
                newer_time = time
            examined += 1
            chaos_raw = record.get("chaos_tome")
            chaos = (_record_to_chaos_tome(chaos_raw)
                     if valid_recorded_counter_block(chaos_raw, "chaos") else None)
            passive = (_record_to_character_passive(raw_passive)
                       if valid_recorded_counter_block(raw_passive, "dice") else None)
            frame = SimpleNamespace(
                chaos_tome=chaos, character_passive=passive,
                game_time_seconds=time, elapsed_seconds=record.get("elapsed_seconds"),
            )
            for source in ROLL_SOURCES:
                if source in found:
                    continue
                result = recorded_source_from_snapshot(frame, source, older=examined > 1)
                if result.analytics is not None:
                    found[source] = result
            if len(found) == len(ROLL_SOURCES) or examined >= SNAPSHOT_LIMIT:
                break
        after = os.fstat(file.fileno())
        if signature != (after.st_size, after.st_mtime_ns):
            raise OSError("Recording changed while it was being read; reopen it.")
    if file_signature(path) != signature:
        raise OSError("Recording changed while it was being read; reopen it.")
    missing_reason = ("No snapshot found within the bounded tail read."
                      if not examined else "No confirmed counters in the last four snapshots.")
    return RecordedRolls(
        path, name, version, signature,
        tuple(found.get(source, RecordedRollSource(source, reason=missing_reason)) for source in ROLL_SOURCES),
        examined, meter[0], finalized, incomplete_tail, str(metadata.get("created_at") or ""),
    )
