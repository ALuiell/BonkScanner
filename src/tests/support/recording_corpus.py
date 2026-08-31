"""Reusable recording scenarios, mutations, and corpus inspection for tests.

The real recording libraries are evidence, not fixtures: tests must never edit
them or depend on a developer-specific path.  This module provides two layers:

* :class:`RecordedRunFixture` writes small, valid JSONL files through the real
  ``VodRecorder`` and verifier telemetry writer.
* :class:`RecordingDocument` applies deliberate JSONL mutations without
  teaching each test how the file format is laid out.

``scan_recording_libraries`` is intentionally read-only.  It inventories a
local corpus by schema shape and digest so research can use large recordings
without copying names, paths, or full payloads into the repository.  The
mechanics layer builds evidence-labelled source progressions and a compressed
checkpoint timeline on top of the same production serializers.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping, Sequence

from core.character_passives import (
    CharacterPassiveEffectKind,
    CharacterPassiveEffectSnapshot,
    CharacterPassiveSnapshot,
    CharacterPassiveStatus,
)
from core.json_safety import dumps_strict_json, loads_legacy_json
from core.run_verifier import (
    ENVIRONMENT_SCHEMA_VERSION,
    MECHANICS_PROFILE_ID,
    SUPPORTED_GAME_BUILD_IDS,
    TARGET_STAT_IDS,
    TARGET_STAT_LABELS,
    VerifierStatComponents,
    VerifierStatFrame,
    VerificationStatus,
    close_float32,
    float32,
    float32_bits,
    environment_digest,
    reconstruct_stat,
)
from core.stats.types import (
    PLAYER_STAT_SPEC_BY_LABEL,
    ChaosTomeSnapshot,
    ChaosTomeStatSnapshot,
    ChargeShrineSnapshot,
    ChargeShrineStatSnapshot,
    PlayerStatFormat,
    PlayerStatValue,
)
from infra.vod_storage import VodRecorder


JsonPathPart = str | int


@dataclass(frozen=True)
class RecordingParseIssue:
    """A privacy-safe structural problem found while scanning one JSONL file."""

    line_number: int
    kind: str


@dataclass(frozen=True)
class RecordingInventory:
    """Schema fingerprint for one recording; payload values stay on disk."""

    path: Path
    size_bytes: int
    sha256: str
    line_count: int
    parsed_record_count: int
    record_counts: tuple[tuple[str, int], ...]
    metadata_versions: tuple[int, ...]
    verification_profiles: tuple[str, ...]
    verifier_schemas: tuple[int, ...]
    snapshot_fields: tuple[str, ...]
    first_record_type: str | None
    last_record_type: str | None
    finalized: bool
    issues: tuple[RecordingParseIssue, ...] = ()

    def count(self, record_type: str) -> int:
        return dict(self.record_counts).get(str(record_type), 0)


@dataclass(frozen=True)
class ReferenceRecording:
    """One generated corpus file and the verifier outcome it represents."""

    key: str
    path: Path
    expected_status: VerificationStatus | None
    expected_exception: type[BaseException] | None = None
    description: str = ""


@dataclass(frozen=True)
class SnapshotAlignmentIssue:
    """One playback stat that matches no nearby stable verifier checkpoint."""

    snapshot_index: int
    stat_id: int
    snapshot_elapsed_seconds: float
    nearest_checkpoint_elapsed_seconds: float
    observed: float
    nearest_expected: float
    transitioning_neighborhood: bool


@dataclass(frozen=True)
class SnapshotAlignmentReport:
    snapshot_count: int
    checkpoint_count: int
    compared_value_count: int
    snapshots_without_nearby_checkpoint: int
    issues: tuple[SnapshotAlignmentIssue, ...] = ()


@dataclass(frozen=True)
class RecordingDocument:
    """Parsed JSONL records plus an optional deliberately incomplete tail."""

    records: tuple[dict[str, Any], ...]
    trailing_fragment: bytes = b""

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> "RecordingDocument":
        return cls(tuple(deepcopy(dict(record)) for record in records))

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        tolerate_incomplete_tail: bool = True,
    ) -> "RecordingDocument":
        payload = Path(path).read_bytes()
        records: list[dict[str, Any]] = []
        trailing_fragment = b""
        lines = payload.splitlines(keepends=True)
        for index, raw_line in enumerate(lines):
            if not raw_line.strip():
                continue
            try:
                record = loads_legacy_json(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                is_final_fragment = (
                    index == len(lines) - 1
                    and not raw_line.endswith((b"\n", b"\r"))
                )
                if tolerate_incomplete_tail and is_final_fragment:
                    trailing_fragment = bytes(raw_line)
                    break
                raise
            if not isinstance(record, dict):
                raise ValueError("Every recording JSONL entry must be an object.")
            records.append(record)
        return cls(tuple(records), trailing_fragment)

    @property
    def record_types(self) -> tuple[str, ...]:
        return tuple(str(record.get("type") or "") for record in self.records)

    def records_of_type(self, record_type: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            record for record in self.records if record.get("type") == record_type
        )

    def to_bytes(self) -> bytes:
        body = b"".join(
            (dumps_strict_json(record) + "\n").encode("utf-8")
            for record in self.records
        )
        return body + bytes(self.trailing_fragment)

    def write(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.to_bytes())
        return destination

    def with_field(
        self,
        record_type: str,
        field_path: Sequence[JsonPathPart],
        value: Any,
        *,
        occurrence: int = 0,
    ) -> "RecordingDocument":
        records = deepcopy(list(self.records))
        index = _record_index(records, record_type, occurrence)
        target: Any = records[index]
        if not field_path:
            raise ValueError("field_path must not be empty")
        for part in field_path[:-1]:
            target = target[part]
        target[field_path[-1]] = deepcopy(value)
        return RecordingDocument(tuple(records), self.trailing_fragment)

    def mutate_record(
        self,
        record_type: str,
        mutate: Callable[[dict[str, Any]], None],
        *,
        occurrence: int = 0,
    ) -> "RecordingDocument":
        records = deepcopy(list(self.records))
        mutate(records[_record_index(records, record_type, occurrence)])
        return RecordingDocument(tuple(records), self.trailing_fragment)

    def without(self, record_type: str, *, occurrence: int = 0) -> "RecordingDocument":
        records = deepcopy(list(self.records))
        del records[_record_index(records, record_type, occurrence)]
        return RecordingDocument(tuple(records), self.trailing_fragment)

    def duplicated(
        self,
        record_type: str,
        *,
        occurrence: int = 0,
    ) -> "RecordingDocument":
        records = deepcopy(list(self.records))
        index = _record_index(records, record_type, occurrence)
        records.insert(index + 1, deepcopy(records[index]))
        return RecordingDocument(tuple(records), self.trailing_fragment)

    def swapped(self, first_index: int, second_index: int) -> "RecordingDocument":
        records = deepcopy(list(self.records))
        records[first_index], records[second_index] = (
            records[second_index],
            records[first_index],
        )
        return RecordingDocument(tuple(records), self.trailing_fragment)

    def with_trailing_fragment(self, fragment: bytes | str) -> "RecordingDocument":
        encoded = fragment.encode("utf-8") if isinstance(fragment, str) else bytes(fragment)
        return RecordingDocument(deepcopy(self.records), encoded)

    def truncated_bytes(self, byte_count: int = 1) -> bytes:
        payload = self.to_bytes()
        count = int(byte_count)
        if count <= 0 or count >= len(payload):
            raise ValueError("byte_count must remove part, but not all, of the document")
        return payload[:-count]


def _record_index(
    records: Sequence[Mapping[str, Any]],
    record_type: str,
    occurrence: int,
) -> int:
    matches = [
        index for index, record in enumerate(records) if record.get("type") == record_type
    ]
    if not matches:
        raise LookupError(f"Recording has no {record_type!r} record")
    try:
        return matches[occurrence]
    except IndexError as exc:
        raise LookupError(
            f"Recording has {len(matches)} {record_type!r} record(s), not occurrence {occurrence}"
        ) from exc


def inspect_recording(path: Path | str) -> RecordingInventory:
    """Read one file once and return a value-only schema fingerprint."""

    source = Path(path)
    stat_before = source.stat()
    payload = source.read_bytes()
    stat_after = source.stat()
    issues: list[RecordingParseIssue] = []
    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
    ):
        issues.append(RecordingParseIssue(0, "changed_while_scanning"))

    record_counts: Counter[str] = Counter()
    metadata_versions: set[int] = set()
    verification_profiles: set[str] = set()
    verifier_schemas: set[int] = set()
    snapshot_fields: set[str] = set()
    parsed_types: list[str] = []
    lines = payload.splitlines(keepends=True)

    for index, raw_line in enumerate(lines):
        line_number = index + 1
        if not raw_line.strip():
            continue
        try:
            record = loads_legacy_json(raw_line)
        except Exception:
            is_incomplete_tail = (
                index == len(lines) - 1
                and not raw_line.endswith((b"\n", b"\r"))
            )
            issues.append(
                RecordingParseIssue(
                    line_number,
                    "incomplete_tail" if is_incomplete_tail else "malformed_json",
                )
            )
            continue
        if not isinstance(record, dict):
            issues.append(RecordingParseIssue(line_number, "non_object_record"))
            continue

        record_type = str(record.get("type") or "missing")
        parsed_types.append(record_type)
        record_counts[record_type] += 1
        if record_type == "metadata":
            version = record.get("version")
            if isinstance(version, int) and not isinstance(version, bool):
                metadata_versions.add(version)
            verification = record.get("verification")
            if isinstance(verification, dict):
                profile = verification.get("mechanics_profile")
                if isinstance(profile, str) and profile:
                    verification_profiles.add(profile)
                schema = verification.get("schema")
                if isinstance(schema, int) and not isinstance(schema, bool):
                    verifier_schemas.add(schema)
        elif record_type == "snapshot":
            snapshot_fields.update(str(key) for key in record)
        elif record_type.startswith("verification_"):
            schema = record.get("schema")
            if isinstance(schema, int) and not isinstance(schema, bool):
                verifier_schemas.add(schema)

    finalized = bool(
        parsed_types
        and parsed_types[-1] == "summary"
        and not issues
    )
    return RecordingInventory(
        path=source,
        size_bytes=len(payload),
        sha256=sha256(payload).hexdigest(),
        line_count=len(lines),
        parsed_record_count=len(parsed_types),
        record_counts=tuple(sorted(record_counts.items())),
        metadata_versions=tuple(sorted(metadata_versions)),
        verification_profiles=tuple(sorted(verification_profiles)),
        verifier_schemas=tuple(sorted(verifier_schemas)),
        snapshot_fields=tuple(sorted(snapshot_fields)),
        first_record_type=parsed_types[0] if parsed_types else None,
        last_record_type=parsed_types[-1] if parsed_types else None,
        finalized=finalized,
        issues=tuple(issues),
    )


def scan_recording_libraries(
    libraries: Iterable[Path | str],
) -> tuple[RecordingInventory, ...]:
    """Inventory JSONL files from each library without changing or copying them."""

    paths: dict[Path, Path] = {}
    for library in libraries:
        root = Path(library)
        if not root.is_dir():
            continue
        for path in root.glob("*.jsonl"):
            paths.setdefault(path.resolve(), path)
    return tuple(inspect_recording(paths[key]) for key in sorted(paths, key=str))


def summarize_inventory(entries: Iterable[RecordingInventory]) -> dict[str, Any]:
    """Aggregate inventory facts into a stable JSON-serializable summary."""

    materialized = tuple(entries)
    versions: Counter[int] = Counter()
    profiles: Counter[str] = Counter()
    record_types: Counter[str] = Counter()
    issue_kinds: Counter[str] = Counter()
    for entry in materialized:
        versions.update(entry.metadata_versions)
        profiles.update(entry.verification_profiles)
        record_types.update(dict(entry.record_counts))
        issue_kinds.update(issue.kind for issue in entry.issues)
    digest_counts = Counter(entry.sha256 for entry in materialized)
    return {
        "file_count": len(materialized),
        "total_bytes": sum(entry.size_bytes for entry in materialized),
        "unique_payloads": len(digest_counts),
        "duplicate_files": sum(count - 1 for count in digest_counts.values()),
        "finalized_files": sum(entry.finalized for entry in materialized),
        "files_with_issues": sum(bool(entry.issues) for entry in materialized),
        "metadata_versions": dict(sorted(versions.items())),
        "verification_profiles": dict(sorted(profiles.items())),
        "record_types": dict(sorted(record_types.items())),
        "issue_kinds": dict(sorted(issue_kinds.items())),
    }


def audit_snapshot_alignment(
    path: Path | str,
    *,
    window_seconds: float = 3.0,
) -> SnapshotAlignmentReport:
    """Compare playback target stats with any nearby stable verifier sample.

    This is a corpus diagnostic rather than a verifier verdict.  Accepting any
    matching sample in the small window avoids blaming a legitimate stat
    transition merely because the normal snapshot and 2-second checkpoint were
    captured on opposite sides of the game's write.
    """

    window = float(window_seconds)
    if not math.isfinite(window) or window < 0.0:
        raise ValueError("window_seconds must be finite and non-negative")
    document = RecordingDocument.load(path)
    snapshots = document.records_of_type("snapshot")
    checkpoints = tuple(
        checkpoint
        for checkpoint in document.records_of_type("verification_checkpoint")
        if checkpoint.get("stable") is True
        and isinstance(checkpoint.get("stats"), dict)
        and _finite_number(checkpoint.get("elapsed_seconds")) is not None
    )
    issues: list[SnapshotAlignmentIssue] = []
    compared = 0
    snapshots_without_checkpoint = 0
    for snapshot_index, snapshot in enumerate(snapshots):
        snapshot_elapsed = _finite_number(snapshot.get("elapsed_seconds"))
        stats = snapshot.get("stats")
        if snapshot_elapsed is None or not isinstance(stats, dict):
            continue
        nearby = tuple(
            checkpoint
            for checkpoint in checkpoints
            if abs(float(checkpoint["elapsed_seconds"]) - snapshot_elapsed) <= window
        )
        if not nearby:
            snapshots_without_checkpoint += 1
            continue
        for stat_id, label in TARGET_STAT_LABELS.items():
            snapshot_stat = stats.get(label)
            observed = (
                _finite_number(snapshot_stat.get("value"))
                if isinstance(snapshot_stat, dict)
                else None
            )
            if observed is None:
                continue
            candidates: list[tuple[float, float]] = []
            for checkpoint in nearby:
                checkpoint_stat = checkpoint["stats"].get(
                    str(stat_id), checkpoint["stats"].get(stat_id)
                )
                expected = (
                    _finite_number(checkpoint_stat.get("final"))
                    if isinstance(checkpoint_stat, dict)
                    else None
                )
                if expected is not None:
                    candidates.append(
                        (float(checkpoint["elapsed_seconds"]), expected)
                    )
            if not candidates:
                continue
            compared += 1
            if any(close_float32(observed, expected) for _, expected in candidates):
                continue
            nearest_elapsed, nearest_expected = min(
                candidates,
                key=lambda candidate: abs(candidate[0] - snapshot_elapsed),
            )
            issues.append(
                SnapshotAlignmentIssue(
                    snapshot_index=snapshot_index,
                    stat_id=stat_id,
                    snapshot_elapsed_seconds=snapshot_elapsed,
                    nearest_checkpoint_elapsed_seconds=nearest_elapsed,
                    observed=observed,
                    nearest_expected=nearest_expected,
                    transitioning_neighborhood=(
                        len({float32_bits(expected) for _, expected in candidates}) > 1
                    ),
                )
            )
    return SnapshotAlignmentReport(
        snapshot_count=len(snapshots),
        checkpoint_count=len(checkpoints),
        compared_value_count=compared,
        snapshots_without_nearby_checkpoint=snapshots_without_checkpoint,
        issues=tuple(issues),
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        # Recording telemetry is float32. A finite JSON number can still be
        # too large for the schema and must not crash the optional diagnostic.
        float32_bits(number)
    except (OverflowError, ValueError):
        return None
    return number


# Mechanics timeline diagnostics


def build_mechanics_timeline(path: Path | str) -> dict[str, Any]:
    """Return compressed source/component transitions and the first bad frame."""

    document = RecordingDocument.load(path)
    checkpoints = document.records_of_type("verification_checkpoint")
    metadata = document.records_of_type("metadata")
    verification = metadata[0].get("verification") if metadata else None
    recording_profile = (
        verification.get("mechanics_profile")
        if isinstance(verification, dict)
        and isinstance(verification.get("mechanics_profile"), str)
        else None
    )
    profile_matches = (
        recording_profile == MECHANICS_PROFILE_ID
        if recording_profile is not None
        else None
    )
    unavailable_reason = None
    if not checkpoints:
        unavailable_reason = "The recording has no verifier checkpoints."
    elif profile_matches is not True:
        unavailable_reason = "The recording mechanics profile is unavailable or unsupported."
    if unavailable_reason is not None:
        return {
            "file": Path(path).name,
            "available": False,
            "unavailable_reason": unavailable_reason,
            "mechanics_profile": recording_profile,
            "analyzer_profile": MECHANICS_PROFILE_ID,
            "profile_matches_analyzer": profile_matches,
            "checkpoint_count": len(checkpoints),
            "stable_checkpoint_count": 0,
            "limitation_checkpoint_count": len(checkpoints),
            "event_count": 0,
            "issue_event_count": 0,
            "observation_checkpoint_count": 0,
            "pending_observation_checkpoint_count": 0,
            "first_issue": None,
            "events": [],
        }
    events: list[dict[str, Any]] = []
    previous_state: dict[str, Any] | None = None
    first_issue: dict[str, Any] | None = None
    pending_reconcilable: set[str] = set()
    stable_count = 0
    limitation_count = 0
    observation_count = 0
    pending_observation_count = 0
    for checkpoint_index, checkpoint in enumerate(checkpoints):
        stable = checkpoint.get("stable") is True
        if stable:
            stable_count += 1
        coverage = checkpoint.get("coverage")
        source_complete = (
            coverage.get("source_attribution_complete")
            if isinstance(coverage, dict)
            and isinstance(coverage.get("source_attribution_complete"), bool)
            else None
        )
        issues: list[str] = []
        sources = checkpoint.get("sources")
        items = sources.get("items") if isinstance(sources, dict) else None
        old_mask = _timeline_integer(
            items.get("old_mask") if isinstance(items, dict) else None
        )
        if stable and old_mask is None:
            issues.append("old_mask_invalid")
        effective_mask = old_mask if old_mask is not None else 0
        stats: list[dict[str, Any]] = []
        state_stats: dict[str, Any] = {}
        raw_stats = checkpoint.get("stats")
        for stat_id in TARGET_STAT_IDS:
            entry = (
                raw_stats.get(str(stat_id), raw_stats.get(stat_id))
                if isinstance(raw_stats, dict)
                else None
            )
            stat_state, stat_issues = _timeline_stat_state(
                checkpoint,
                entry,
                stat_id=stat_id,
                old_mask=effective_mask,
                source_complete=source_complete,
                strong=stable,
            )
            stats.append(stat_state)
            issues.extend(stat_issues)
            state_stats[str(stat_id)] = {
                "final_bits": stat_state["final_bits"],
                "base_bits": stat_state["base_bits"],
                "additive_bits": stat_state["additive_bits"],
                "multiplicative_bits": stat_state["multiplicative_bits"],
                "modifier_addition_sum_bits": stat_state[
                    "modifier_addition_sum_bits"
                ],
                "unsupported_modifier_count": stat_state[
                    "unsupported_modifier_count"
                ],
                "sources": {
                    source: _bits_or_none(stat_state["sources"][source])
                    for source in ("shrines", "dice", "chaos")
                },
            }
        observed_issues = set(issues)
        reconcilable = {
            issue
            for issue in observed_issues
            if issue.endswith(("_old_mask_base", "_modifier_sum", "_source_sum"))
        }
        immediate = observed_issues - reconcilable
        confirmed_issues = immediate | (reconcilable & pending_reconcilable)
        pending_only = reconcilable - pending_reconcilable
        if observed_issues:
            observation_count += 1
        if pending_only:
            pending_observation_count += 1
        if stable:
            pending_reconcilable = reconcilable
        else:
            pending_reconcilable.clear()
        issue_list = sorted(confirmed_issues)
        observation_list = sorted(observed_issues)
        state = {
            "stable": stable,
            "source_complete": source_complete,
            "old_mask": old_mask,
            "stats": state_stats,
            "observations": tuple(observation_list),
            "issues": tuple(issue_list),
        }
        changes = _timeline_changes(previous_state, state)
        if previous_state is None or changes:
            event = {
                "checkpoint_index": checkpoint_index,
                "sequence": _timeline_integer(checkpoint.get("sequence")),
                "elapsed_seconds": _finite_number(checkpoint.get("elapsed_seconds")),
                "game_time_seconds": _finite_number(
                    checkpoint.get("game_time_seconds")
                ),
                "stable": stable,
                "source_attribution_complete": source_complete,
                "old_mask": old_mask,
                "changes": changes,
                "stats": stats,
                "observations": observation_list,
                "issues": issue_list,
            }
            events.append(event)
            if issue_list and first_issue is None:
                first_issue = {
                    "checkpoint_index": checkpoint_index,
                    "sequence": event["sequence"],
                    "elapsed_seconds": event["elapsed_seconds"],
                    "issues": list(issue_list),
                }
        if not stable or source_complete is not True:
            limitation_count += 1
        previous_state = state
    return {
        "file": Path(path).name,
        "available": True,
        "unavailable_reason": None,
        "mechanics_profile": recording_profile,
        "analyzer_profile": MECHANICS_PROFILE_ID,
        "profile_matches_analyzer": profile_matches,
        "checkpoint_count": len(checkpoints),
        "stable_checkpoint_count": stable_count,
        "limitation_checkpoint_count": limitation_count,
        "event_count": len(events),
        "issue_event_count": sum(bool(event["issues"]) for event in events),
        "observation_checkpoint_count": observation_count,
        "pending_observation_checkpoint_count": pending_observation_count,
        "first_issue": first_issue,
        "events": events,
    }


def _timeline_stat_state(
    checkpoint: Mapping[str, Any],
    entry: Any,
    *,
    stat_id: int,
    old_mask: int,
    source_complete: bool | None,
    strong: bool,
) -> tuple[dict[str, Any], list[str]]:
    label = TARGET_STAT_LABELS[stat_id]
    issues: list[str] = []
    if not isinstance(entry, dict):
        return (
            {
                "stat_id": stat_id,
                "label": label,
                "final": None,
                "final_bits": None,
                "raw": None,
                "raw_bits": None,
                "base": None,
                "base_bits": None,
                "additive": None,
                "additive_bits": None,
                "multiplicative": None,
                "multiplicative_bits": None,
                "modifier_addition_sum": None,
                "modifier_addition_sum_bits": None,
                "unsupported_modifier_count": None,
                "sources": {"shrines": None, "dice": None, "chaos": None},
                "expected_base": None,
                "expected_additive": None,
                "expected_final": None,
                "checks": {
                    "recorded_bits": False,
                    "component_equation": None,
                    "final_raw": None,
                    "old_mask_base": None,
                    "modifier_recorded_bits": None,
                    "modifier_sum": None,
                    "source_sum": None,
                    "supported_modifier_types": None,
                    "supported_multiplier": None,
                },
            },
            [f"stat_{stat_id}_missing"] if strong else [],
        )

    values: dict[str, float | None] = {}
    recorded_bits_match = True
    for field_name in ("final", "raw", "base", "additive", "multiplicative"):
        value = _finite_number(entry.get(field_name))
        bits = entry.get(f"{field_name}_bits")
        values[field_name] = value
        if (
            value is None
            or not isinstance(bits, str)
            or float32_bits(value) != bits.casefold()
        ):
            recorded_bits_match = False
    final = values["final"]
    raw = values["raw"]
    base = values["base"]
    additive = values["additive"]
    multiplicative = values["multiplicative"]
    component_match: bool | None = None
    final_raw_match: bool | None = None
    if all(
        value is not None
        for value in (final, raw, base, additive, multiplicative)
    ):
        assert final is not None and raw is not None and base is not None
        assert additive is not None and multiplicative is not None
        try:
            component_expected = reconstruct_stat(base, additive, multiplicative)
        except (OverflowError, ValueError, struct.error):
            component_expected = None
        component_match = bool(
            component_expected is not None
            and float32_bits(raw) == float32_bits(component_expected)
        )
        final_raw_match = float32_bits(final) == float32_bits(raw)

    expected_base = 1.0 + (0.15 * old_mask if stat_id == 39 else 0.0)
    base_match = (
        close_float32(base, expected_base, source_sum=True)
        if base is not None
        else None
    )
    multiplier_match = (
        close_float32(multiplicative, 1.0)
        if multiplicative is not None
        else None
    )
    (
        modifier_sum,
        modifier_bits_match,
        unsupported_modifier_count,
    ) = _timeline_modifier_summary(checkpoint, stat_id)
    modifier_match = (
        close_float32(additive - 1.0, modifier_sum, source_sum=True)
        if additive is not None and modifier_sum is not None
        else None
    )
    supported_modifier_types = (
        unsupported_modifier_count == 0
        if unsupported_modifier_count is not None
        else None
    )
    source_values = {
        source: _timeline_source_total(checkpoint, source, stat_id)
        for source in ("shrines", "dice", "chaos")
    }
    expected_additive: float | None = None
    expected_final: float | None = None
    source_match: bool | None = None
    if source_complete is True and all(
        value is not None for value in source_values.values()
    ):
        expected_additive = 1.0 + math.fsum(
            value for value in source_values.values() if value is not None
        )
        source_match = (
            close_float32(additive, expected_additive, source_sum=True)
            if additive is not None
            else False
        )
        try:
            expected_final = reconstruct_stat(expected_base, expected_additive, 1.0)
        except (OverflowError, ValueError, struct.error):
            expected_final = None

    checks = {
        "recorded_bits": recorded_bits_match,
        "component_equation": component_match,
        "final_raw": final_raw_match,
        "old_mask_base": base_match,
        "modifier_recorded_bits": modifier_bits_match,
        "modifier_sum": modifier_match,
        "source_sum": source_match,
        "supported_modifier_types": supported_modifier_types,
        "supported_multiplier": multiplier_match,
    }
    if strong:
        for check, matches in checks.items():
            if matches is False:
                issues.append(f"stat_{stat_id}_{check}")
        if source_complete is True and source_match is None:
            issues.append(f"stat_{stat_id}_source_values_missing")
    return (
        {
            "stat_id": stat_id,
            "label": label,
            "final": final,
            "final_bits": _bits_or_none(final),
            "raw": raw,
            "raw_bits": _bits_or_none(raw),
            "base": base,
            "base_bits": _bits_or_none(base),
            "additive": additive,
            "additive_bits": _bits_or_none(additive),
            "multiplicative": multiplicative,
            "multiplicative_bits": _bits_or_none(multiplicative),
            "modifier_addition_sum": modifier_sum,
            "modifier_addition_sum_bits": _bits_or_none(modifier_sum),
            "unsupported_modifier_count": unsupported_modifier_count,
            "sources": source_values,
            "expected_base": expected_base,
            "expected_additive": expected_additive,
            "expected_final": expected_final,
            "checks": checks,
        },
        issues,
    )


def _timeline_source_total(
    checkpoint: Mapping[str, Any], source: str, stat_id: int
) -> float | None:
    sources = checkpoint.get("sources")
    source_record = sources.get(source) if isinstance(sources, dict) else None
    totals = source_record.get("totals") if isinstance(source_record, dict) else None
    value = (
        totals.get(str(stat_id), totals.get(stat_id))
        if isinstance(totals, dict)
        else None
    )
    return _finite_number(value)


def _timeline_modifier_summary(
    checkpoint: Mapping[str, Any], stat_id: int
) -> tuple[float | None, bool | None, int | None]:
    summaries = checkpoint.get("modifier_summary")
    summary = (
        summaries.get(str(stat_id), summaries.get(stat_id))
        if isinstance(summaries, dict)
        else None
    )
    if isinstance(summary, dict):
        value = _finite_number(summary.get("addition_sum"))
        bits = summary.get("addition_sum_bits")
        bits_match = bool(
            value is not None
            and isinstance(bits, str)
            and float32_bits(value) == bits.casefold()
        )
        return value, bits_match, _timeline_integer(summary.get("unsupported_count"))

    modifiers = checkpoint.get("modifiers")
    if isinstance(modifiers, list):
        values: list[float] = []
        unsupported = 0
        for modifier in modifiers:
            if not isinstance(modifier, dict):
                continue
            if _timeline_integer(modifier.get("stat_id")) != stat_id:
                continue
            value = _finite_number(modifier.get("value"))
            modify_type = _timeline_integer(modifier.get("modify_type"))
            if value is None or modify_type is None:
                return None, False, None
            if modify_type == 0:
                values.append(value)
            else:
                unsupported += 1
        return math.fsum(values), True, unsupported
    return None, False, None


def _timeline_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _bits_or_none(value: float | None) -> str | None:
    return float32_bits(value) if value is not None else None


def _timeline_changes(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> list[str]:
    if previous is None:
        return ["initial"]
    changes = []
    for field_name in ("stable", "source_complete", "old_mask"):
        if previous.get(field_name) != current.get(field_name):
            changes.append(field_name)
    previous_stats = previous.get("stats")
    current_stats = current.get("stats")
    if not isinstance(previous_stats, dict) or not isinstance(current_stats, dict):
        return [*changes, "stats"]
    for stat_id in TARGET_STAT_IDS:
        key = str(stat_id)
        old_stat = previous_stats.get(key, {})
        new_stat = current_stats.get(key, {})
        for field_name in (
            "final_bits",
            "base_bits",
            "additive_bits",
            "multiplicative_bits",
            "modifier_addition_sum_bits",
            "unsupported_modifier_count",
        ):
            if old_stat.get(field_name) != new_stat.get(field_name):
                changes.append(f"stat_{stat_id}_{field_name.removesuffix('_bits')}")
        old_sources = old_stat.get("sources", {})
        new_sources = new_stat.get("sources", {})
        for source in ("shrines", "dice", "chaos"):
            if old_sources.get(source) != new_sources.get(source):
                changes.append(f"stat_{stat_id}_{source}")
    if previous.get("issues") != current.get("issues"):
        changes.append("issues")
    if previous.get("observations") != current.get("observations"):
        changes.append("observations")
    return changes


class ManualClock:
    """Monotonic clock controlled by a scenario instead of wall time."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> float:
        amount = float(seconds)
        if amount < 0:
            raise ValueError("A monotonic fixture clock cannot move backwards")
        self.value += amount
        return self.value


# Legal-source fixtures and mechanics scenarios


@dataclass(frozen=True)
class TargetStatSources:
    """Known legal sources for the three verifier target stats."""

    shrines: Mapping[int, float] = field(default_factory=dict)
    shrine_rolls: Mapping[int, int] = field(default_factory=dict)
    dice: Mapping[int, float] = field(default_factory=dict)
    dice_rolls: Mapping[int, int] = field(default_factory=dict)
    chaos: Mapping[int, float] = field(default_factory=dict)
    chaos_rolls: Mapping[int, int] = field(default_factory=dict)
    old_mask: int = 0
    shrine_charged: int | None = None
    dice_level: int | None = None
    chaos_level: int | None = None

    def __post_init__(self) -> None:
        for source_name, values in (
            ("shrines", self.shrines),
            ("dice", self.dice),
            ("chaos", self.chaos),
        ):
            for stat_id, value in values.items():
                if (
                    isinstance(stat_id, bool)
                    or not isinstance(stat_id, int)
                    or stat_id not in TARGET_STAT_IDS
                ):
                    raise ValueError(f"{source_name} contains non-target stat {stat_id}")
                number = _finite_number(value)
                if number is None:
                    raise ValueError(
                        f"{source_name} values must be finite float32 numbers"
                    )
                if number < 0.0:
                    raise ValueError(f"{source_name} bonuses must be non-negative")
        for source_name, counts in (
            ("shrine_rolls", self.shrine_rolls),
            ("dice_rolls", self.dice_rolls),
            ("chaos_rolls", self.chaos_rolls),
        ):
            for stat_id, count in counts.items():
                if (
                    isinstance(stat_id, bool)
                    or not isinstance(stat_id, int)
                    or stat_id not in TARGET_STAT_IDS
                ):
                    raise ValueError(f"{source_name} contains non-target stat {stat_id}")
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or count < 0
                ):
                    raise ValueError(f"{source_name} counts must be non-negative integers")
        for source_name, values, counts in (
            ("shrines", self.shrines, self.shrine_rolls),
            ("dice", self.dice, self.dice_rolls),
            ("chaos", self.chaos, self.chaos_rolls),
        ):
            for stat_id in set(values) | set(counts):
                value = float(values.get(stat_id, 0.0))
                count = int(counts.get(stat_id, 1 if value != 0.0 else 0))
                if (value == 0.0) != (count == 0):
                    raise ValueError(
                        f"{source_name} value and roll count disagree for stat {stat_id}"
                    )
        if (
            isinstance(self.old_mask, bool)
            or not isinstance(self.old_mask, int)
            or self.old_mask < 0
        ):
            raise ValueError("old_mask must be a non-negative integer")
        for source_name, total, values, counts in (
            (
                "shrine_charged",
                self.shrine_charged,
                self.shrines,
                self.shrine_rolls,
            ),
            ("dice_level", self.dice_level, self.dice, self.dice_rolls),
            ("chaos_level", self.chaos_level, self.chaos, self.chaos_rolls),
        ):
            if total is None:
                continue
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise ValueError(f"{source_name} must be a non-negative integer")
            effective_target_rolls = sum(
                int(counts.get(stat_id, 1 if float(value) != 0.0 else 0))
                for stat_id, value in values.items()
            )
            if total < effective_target_rolls:
                raise ValueError(
                    f"{source_name} cannot be smaller than its target roll count"
                )


@dataclass(frozen=True)
class MechanicsObservedStat:
    """Exact float32 component state retained from a live capture."""

    final: float
    raw: float
    base: float
    additive: float
    multiplicative: float = 1.0
    has_modifications: bool = False

    def __post_init__(self) -> None:
        values = (
            self.final,
            self.raw,
            self.base,
            self.additive,
            self.multiplicative,
        )
        if any(_finite_number(value) is None for value in values):
            raise ValueError("Observed mechanics components must be finite float32")
        reconstructed = reconstruct_stat(
            self.base,
            self.additive,
            self.multiplicative,
        )
        if (
            float32_bits(self.raw) != float32_bits(reconstructed)
            or float32_bits(self.final) != float32_bits(self.raw)
        ):
            raise ValueError("Observed mechanics components must reconstruct exactly")

    def component(self, stat_id: int) -> VerifierStatComponents:
        return VerifierStatComponents(
            stat_id=stat_id,
            final_value=float32(self.final),
            raw_value=float32(self.raw),
            has_modifications=bool(self.has_modifications),
            base_value=float32(self.base),
            additive_value=float32(self.additive),
            multiplicative_value=float32(self.multiplicative),
        )


@dataclass(frozen=True)
class MechanicsScenarioStep:
    """One source transition with an explicit evidence boundary."""

    key: str
    description: str
    sources: TargetStatSources
    evidence: str
    advance_seconds: float = 2.0
    observed_stats: Mapping[int, MechanicsObservedStat] = field(default_factory=dict)


@dataclass(frozen=True)
class MechanicsScenario:
    """A deterministic progression for one part of the verifier equation."""

    key: str
    description: str
    evidence: str
    steps: tuple[MechanicsScenarioStep, ...]


@dataclass(frozen=True)
class MechanicsReferenceRecording:
    scenario: MechanicsScenario
    path: Path
    expected_status: VerificationStatus
    sha256: str


@dataclass(frozen=True)
class MechanicsCorpusBuild:
    manifest_path: Path
    recordings: tuple[MechanicsReferenceRecording, ...]


MECHANICS_SCENARIOS = (
    MechanicsScenario(
        key="shrine_pdc_confirmed",
        description="The confirmed one-roll +6% Powerup Drop Chance shrine transition.",
        evidence="live_confirmed",
        steps=(
            MechanicsScenarioStep(
                "baseline",
                "No earned target-stat sources.",
                TargetStatSources(shrine_charged=0),
                "live_confirmed",
            ),
            MechanicsScenarioStep(
                "pdc_plus_6_percent",
                "One charged shrine contributes the captured PDC Addition value.",
                TargetStatSources(
                    shrines={41: 0.0599999987},
                    shrine_rolls={41: 1},
                    shrine_charged=1,
                ),
                "live_confirmed",
            ),
        ),
    ),
    MechanicsScenario(
        key="dice_esi_confirmed",
        description="The isolated Dice/Gamba Elite Spawn Increase transition.",
        evidence="live_confirmed",
        steps=(
            MechanicsScenarioStep(
                "dice_level_zero",
                "Dice/Gamba is identified before target-stat rolls are earned.",
                TargetStatSources(dice_level=0),
                "synthetic_identity_baseline",
            ),
            MechanicsScenarioStep(
                "dice_esi_roll",
                "One captured Dice/Gamba roll contributes ESI Addition.",
                TargetStatSources(
                    dice={39: 0.1100107357},
                    dice_rolls={39: 1},
                    dice_level=1,
                ),
                "live_confirmed",
            ),
        ),
    ),
    MechanicsScenario(
        key="old_mask_linear_stacking",
        description="Old Mask changes the ESI Flat/base component linearly.",
        evidence="native_and_live_confirmed",
        steps=(
            MechanicsScenarioStep(
                "no_mask",
                "ESI starts at built-in base 1.0.",
                TargetStatSources(),
                "live_confirmed",
            ),
            MechanicsScenarioStep(
                "one_mask",
                "One mask produces base factor 1.15.",
                TargetStatSources(old_mask=1),
                "native_confirmed_synthetic_transition",
            ),
            MechanicsScenarioStep(
                "two_masks",
                "Two masks produce base factor 1.30, not 1.15 squared.",
                TargetStatSources(old_mask=2),
                "native_confirmed_synthetic_transition",
            ),
            MechanicsScenarioStep(
                "two_masks_with_dice_esi",
                "The Flat factor multiplies the captured Dice Addition component.",
                TargetStatSources(
                    dice={39: 0.1100107357},
                    dice_rolls={39: 1},
                    dice_level=1,
                    old_mask=2,
                ),
                "confirmed_inputs_synthetic_combination",
            ),
        ),
    ),
    MechanicsScenario(
        key="chaos_target_rolls",
        description="A reduced replay of the captured Chaos target-stat contribution.",
        evidence="derived_from_live_stress_capture",
        steps=(
            MechanicsScenarioStep(
                "baseline",
                "No Chaos levels have been earned.",
                TargetStatSources(chaos_level=0),
                "synthetic_baseline",
            ),
            MechanicsScenarioStep(
                "chaos_level_101",
                "Ten target rolls plus 91 non-target rolls reproduce the captured totals.",
                TargetStatSources(
                    chaos={
                        39: 0.679999992251396,
                        40: 1.83000002801418,
                        41: 0.297000005841255,
                    },
                    chaos_rolls={39: 2, 40: 6, 41: 2},
                    chaos_level=101,
                ),
                "live_confirmed_aggregate",
            ),
        ),
    ),
    MechanicsScenario(
        key="mixed_live_stress",
        description="Reduced target-stat replay of the paired five-mask stress capture.",
        evidence="derived_from_live_paired_capture",
        steps=(
            MechanicsScenarioStep(
                "clean_start",
                "All three target stats are at baseline.",
                TargetStatSources(shrine_charged=0, dice_level=0, chaos_level=0),
                "live_confirmed",
            ),
            MechanicsScenarioStep(
                "large_stack",
                "Captured Shrine, Dice, Chaos and five-mask totals are applied together.",
                TargetStatSources(
                    shrines={39: 0.525000035762787},
                    shrine_rolls={39: 1},
                    shrine_charged=13,
                    dice={
                        39: 0.436670791357756,
                        40: 0.425056639593095,
                        41: 0.115880756173283,
                    },
                    dice_rolls={39: 12, 40: 27, 41: 14},
                    dice_level=497,
                    chaos={
                        39: 0.679999992251396,
                        40: 1.83000002801418,
                        41: 0.297000005841255,
                    },
                    chaos_rolls={39: 2, 40: 6, 41: 2},
                    chaos_level=101,
                    old_mask=5,
                ),
                "live_confirmed_aggregate",
                observed_stats={
                    39: MechanicsObservedStat(
                        final=4.622924327850342,
                        raw=4.622924327850342,
                        base=1.75,
                        additive=2.6416709423065186,
                    ),
                    40: MechanicsObservedStat(
                        final=3.255056858062744,
                        raw=3.255056858062744,
                        base=1.0,
                        additive=3.255056858062744,
                    ),
                    41: MechanicsObservedStat(
                        final=1.412880778312683,
                        raw=1.412880778312683,
                        base=1.0,
                        additive=1.412880778312683,
                    ),
                },
            ),
        ),
    ),
)

MECHANICS_FIXTURE_CREATED_AT = "2000-01-01T00:00:00"


def clean_environment_snapshot() -> dict[str, Any]:
    modules = [
        {
            "id": "a" * 24,
            "name": "Megabonk.exe",
            "location": "game",
            "size": 1234,
            "sha256": None,
            "classification": "game",
        }
    ]
    artifacts: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    return {
        "schema": ENVIRONMENT_SCHEMA_VERSION,
        "modules": modules,
        "artifacts": artifacts,
        "private_executable_regions": regions,
        "digest": environment_digest(modules, artifacts, regions),
    }


def modded_environment_snapshot() -> dict[str, Any]:
    """Small synthetic Doorstop/BepInEx baseline; no machine paths or addresses."""

    modules = [
        {
            "id": "a" * 24,
            "name": "Megabonk.exe",
            "location": "game",
            "size": 1234,
            "sha256": None,
            "classification": "game",
        },
        {
            "id": "b" * 24,
            "name": "BepInEx.Core.dll",
            "location": "other",
            "size": 4321,
            "sha256": None,
            "classification": "mod_loader",
        },
    ]
    artifacts = [
        {
            "id": "c" * 24,
            "path": "winhttp.dll",
            "kind": "proxy_loader",
            "size": 2048,
            "sha256": "d" * 64,
        }
    ]
    regions: list[dict[str, Any]] = []
    return {
        "schema": ENVIRONMENT_SCHEMA_VERSION,
        "modules": modules,
        "artifacts": artifacts,
        "private_executable_regions": regions,
        "digest": environment_digest(modules, artifacts, regions),
    }


class RecordedRunFixture:
    """A valid recording written through production serializers and clocks."""

    def __init__(
        self,
        directory: Path | str,
        *,
        name: str = "Recording fixture",
        game_build_id: str | None = None,
        environment_snapshot: dict[str, Any] | None = None,
        character_id: int = 0,
        character_name: str = "Fixture",
    ) -> None:
        self.clock = ManualClock()
        self.recorder = VodRecorder(
            vods_dir=Path(directory),
            interval_seconds=10,
            clock=self.clock,
        )
        build = game_build_id or sorted(SUPPORTED_GAME_BUILD_IDS)[0]
        self.path = self.recorder.start(
            name=name,
            character_id=character_id,
            character_name=character_name,
            scanner_version="fixture",
            game_build_id=build,
            run_start_time_seconds=0.0,
            environment_snapshot=(
                clean_environment_snapshot()
                if environment_snapshot is None
                else environment_snapshot
            ),
        )
        self._stopped = False

    def __enter__(self) -> "RecordedRunFixture":
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        if exc_type is None:
            self.finish()
        else:
            self.close()

    def advance(self, seconds: float) -> float:
        return self.clock.advance(seconds)

    def capture_snapshot(
        self,
        stats: Mapping[str, float | None] | None = None,
        *,
        items: Iterable[str] = (),
        chaos_tome: ChaosTomeSnapshot | None = None,
        shrines: ChargeShrineSnapshot | None = None,
        character_passive: CharacterPassiveSnapshot | None = None,
        game_time_seconds: float | None = None,
        player_level: int | None = None,
        mob_kills: int | None = None,
    ):
        values = {
            label: PlayerStatValue(PLAYER_STAT_SPEC_BY_LABEL[label], value)
            for label, value in (stats or {}).items()
        }
        return self.recorder.capture(
            values,
            tuple(items),
            chaos_tome=chaos_tome,
            shrines=shrines,
            character_passive=character_passive,
            game_time_seconds=(
                self.clock.value if game_time_seconds is None else game_time_seconds
            ),
            player_level=player_level,
            mob_kills=mob_kills,
        )

    def capture_target_stats(
        self,
        sources: TargetStatSources,
        *,
        game_time_seconds: float | None = None,
        stable: bool = True,
        source_availability: Mapping[str, bool] | None = None,
        observed_stats: Mapping[int, MechanicsObservedStat] | None = None,
    ) -> VerifierStatFrame:
        shrine_values = _target_values(sources.shrines)
        dice_values = _target_values(sources.dice)
        chaos_values = _target_values(sources.chaos)
        shrine_rolls = _source_roll_counts(shrine_values, sources.shrine_rolls)
        dice_rolls = _source_roll_counts(dice_values, sources.dice_rolls)
        chaos_rolls = _source_roll_counts(chaos_values, sources.chaos_rolls)
        shrine_charged = _resolved_source_count(
            sources.shrine_charged, shrine_rolls
        )
        dice_level = _resolved_source_count(sources.dice_level, dice_rolls)
        chaos_level = _resolved_source_count(sources.chaos_level, chaos_rolls)
        is_dice = sources.dice_level is not None or any(dice_values.values())
        totals = {
            stat_id: shrine_values[stat_id]
            + dice_values[stat_id]
            + chaos_values[stat_id]
            for stat_id in TARGET_STAT_IDS
        }
        overrides = dict(observed_stats or {})
        invalid_overrides = set(overrides) - set(TARGET_STAT_IDS)
        if invalid_overrides or any(
            not isinstance(value, MechanicsObservedStat)
            for value in overrides.values()
        ):
            raise ValueError("Observed stat overrides must contain target stat components")
        frame = VerifierStatFrame(
            stats=tuple(
                (
                    overrides[stat_id].component(stat_id)
                    if stat_id in overrides
                    else _target_stat_component(
                        stat_id,
                        total=totals[stat_id],
                        old_mask=int(sources.old_mask),
                    )
                )
                for stat_id in TARGET_STAT_IDS
            ),
            stable=bool(stable),
        )
        modifiers = _target_modifiers(
            shrine_values,
            dice_values,
            chaos_values,
            shrine_rolls,
            dice_rolls,
            chaos_rolls,
        )
        shrine_snapshot = _shrine_snapshot(
            shrine_values,
            shrine_rolls,
            charged=shrine_charged,
        )
        chaos_snapshot = _chaos_snapshot(
            chaos_values,
            chaos_rolls,
            level=chaos_level,
        )
        passive = _dice_passive_snapshot(
            dice_values,
            dice_rolls,
            level=dice_level if is_dice else None,
        )
        held_items = (
            (f"Old Mask x{int(sources.old_mask)}",)
            if int(sources.old_mask) > 0
            else ()
        )
        availability = {
            "shrines": True,
            "chaos_tome": True,
            "character_passive": True,
        }
        if source_availability is not None:
            unknown_sources = set(source_availability) - set(availability)
            if unknown_sources:
                raise ValueError(
                    "Unknown verifier source availability: "
                    + ", ".join(sorted(map(str, unknown_sources)))
                )
            if any(
                not isinstance(value, bool)
                for value in source_availability.values()
            ):
                raise ValueError("Verifier source availability values must be booleans")
            availability.update(source_availability)
        self.recorder.capture_verification(
            frame,
            game_time_seconds=(
                self.clock.value if game_time_seconds is None else game_time_seconds
            ),
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine_snapshot,
            chaos_snapshot=chaos_snapshot,
            character_passive_snapshot=passive,
            dice_level=dice_level if is_dice else None,
            held_items=held_items,
            source_availability=availability,
        )
        return frame

    def capture_state(
        self,
        sources: TargetStatSources,
        *,
        game_time_seconds: float | None = None,
        stable: bool = True,
        source_availability: Mapping[str, bool] | None = None,
        observed_stats: Mapping[int, MechanicsObservedStat] | None = None,
        extra_stats: Mapping[str, float | None] | None = None,
        player_level: int | None = None,
        mob_kills: int | None = None,
    ) -> VerifierStatFrame:
        """Capture matching verifier telemetry and a normal playback snapshot."""

        additions = dict(extra_stats or {})
        overlap = set(additions) & set(TARGET_STAT_LABELS.values())
        if overlap:
            raise ValueError(
                "extra_stats cannot replace verifier target stats: "
                + ", ".join(sorted(overlap))
            )
        frame = self.capture_target_stats(
            sources,
            game_time_seconds=game_time_seconds,
            stable=stable,
            source_availability=source_availability,
            observed_stats=observed_stats,
        )
        shrine_values = _target_values(sources.shrines)
        dice_values = _target_values(sources.dice)
        chaos_values = _target_values(sources.chaos)
        shrine_rolls = _source_roll_counts(shrine_values, sources.shrine_rolls)
        dice_rolls = _source_roll_counts(dice_values, sources.dice_rolls)
        chaos_rolls = _source_roll_counts(chaos_values, sources.chaos_rolls)
        shrine_charged = _resolved_source_count(
            sources.shrine_charged, shrine_rolls
        )
        dice_level = _resolved_source_count(sources.dice_level, dice_rolls)
        chaos_level = _resolved_source_count(sources.chaos_level, chaos_rolls)
        is_dice = sources.dice_level is not None or any(dice_values.values())
        stats = {
            TARGET_STAT_LABELS[component.stat_id]: component.final_value
            for component in frame.stats
        }
        stats.update(additions)
        self.capture_snapshot(
            stats,
            items=(
                (f"Old Mask x{int(sources.old_mask)}",)
                if int(sources.old_mask) > 0
                else ()
            ),
            chaos_tome=_chaos_snapshot(
                chaos_values,
                chaos_rolls,
                level=chaos_level,
            ),
            shrines=_shrine_snapshot(
                shrine_values,
                shrine_rolls,
                charged=shrine_charged,
            ),
            character_passive=_dice_passive_snapshot(
                dice_values,
                dice_rolls,
                level=dice_level if is_dice else None,
            ),
            game_time_seconds=game_time_seconds,
            player_level=player_level,
            mob_kills=mob_kills,
        )
        return frame

    def capture_environment(self, snapshot: Mapping[str, Any]) -> None:
        self.recorder.capture_environment(deepcopy(dict(snapshot)))

    def note_environment_failure(self, error: BaseException | str) -> None:
        self.recorder.note_environment_failure(error)

    def note_verification_failure(self, error: BaseException | str) -> None:
        self.recorder.note_verification_failure(error)

    def finish(self) -> str:
        if self._stopped:
            return "kept"
        status = self.recorder.stop()
        self._stopped = True
        return status

    def close(self) -> None:
        if not self._stopped:
            self.recorder.close()
            self._stopped = True

    def document(self) -> RecordingDocument:
        if not self._stopped:
            raise RuntimeError("Finish the fixture before loading its document")
        return RecordingDocument.load(self.path)


def build_reference_corpus(
    directory: Path | str,
) -> tuple[ReferenceRecording, ...]:
    """Build a small reusable clean/modded/adversarial recording corpus.

    The corpus is generated through :class:`VodRecorder`, then only the
    explicitly adversarial variants are edited as JSONL documents.  Existing
    destination files are never overwritten.
    """

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    destination_names = (
        "clean_mixed_sources.jsonl",
        "modded_environment.jsonl",
        "interrupted_telemetry.jsonl",
        "tampered_final_value.jsonl",
        "duplicate_metadata.jsonl",
        "summary_not_last.jsonl",
        "incomplete_tail.jsonl",
        "malformed_tail.jsonl",
    )
    for name in destination_names:
        destination = root / name
        if destination.exists():
            raise FileExistsError(destination)

    clean_fixture = RecordedRunFixture(root, name="Clean mixed-source fixture")
    try:
        clean_fixture.advance(1.0)
        clean_fixture.capture_state(TargetStatSources(), player_level=1, mob_kills=0)
        clean_fixture.advance(2.0)
        clean_fixture.capture_state(
            TargetStatSources(shrines={39: 0.15, 41: 0.06}),
            player_level=2,
            mob_kills=3,
        )
        clean_fixture.advance(2.0)
        clean_fixture.capture_state(
            TargetStatSources(
                shrines={39: 0.15, 41: 0.06},
                chaos={40: 0.20},
            ),
            player_level=3,
            mob_kills=7,
        )
        clean_fixture.advance(2.0)
        clean_fixture.capture_state(
            TargetStatSources(
                shrines={39: 0.15, 41: 0.06},
                dice={41: 0.05},
                chaos={40: 0.20},
                old_mask=2,
            ),
            player_level=4,
            mob_kills=10,
        )
        clean_fixture.finish()
        clean_document = clean_fixture.document()
    except Exception:
        clean_fixture.close()
        clean_fixture.path.unlink(missing_ok=True)
        raise
    clean_path = _write_new_document(
        clean_document,
        root / "clean_mixed_sources.jsonl",
    )
    clean_fixture.path.unlink(missing_ok=True)

    modded_fixture = RecordedRunFixture(
        root,
        name="Modded environment fixture",
        environment_snapshot=modded_environment_snapshot(),
    )
    try:
        modded_fixture.advance(1.0)
        modded_fixture.capture_state(TargetStatSources())
        modded_fixture.finish()
        modded_document = modded_fixture.document()
    except Exception:
        modded_fixture.close()
        modded_fixture.path.unlink(missing_ok=True)
        raise
    modded_path = _write_new_document(
        modded_document,
        root / "modded_environment.jsonl",
    )
    modded_fixture.path.unlink(missing_ok=True)

    interrupted_fixture = RecordedRunFixture(
        root,
        name="Recovered telemetry-gap fixture",
    )
    try:
        interrupted_fixture.advance(1.0)
        interrupted_fixture.capture_state(TargetStatSources())
        interrupted_fixture.advance(1.0)
        interrupted_fixture.note_verification_failure("synthetic read failure")
        interrupted_fixture.advance(3.0)
        interrupted_fixture.capture_state(TargetStatSources())
        interrupted_fixture.finish()
        interrupted_document = interrupted_fixture.document()
    except Exception:
        interrupted_fixture.close()
        interrupted_fixture.path.unlink(missing_ok=True)
        raise
    interrupted_path = _write_new_document(
        interrupted_document,
        root / "interrupted_telemetry.jsonl",
    )
    interrupted_fixture.path.unlink(missing_ok=True)

    tampered = clean_document.with_field(
        "verification_checkpoint",
        ("stats", "40", "final"),
        99.0,
        occurrence=-1,
    )
    duplicate_metadata = clean_document.duplicated("metadata")
    summary_not_last = clean_document.swapped(
        len(clean_document.records) - 1,
        len(clean_document.records) - 2,
    )
    incomplete_tail = clean_document.with_trailing_fragment('{"type":"snapshot"')
    malformed_tail = clean_document.with_trailing_fragment("{broken}\n")

    return (
        ReferenceRecording(
            "clean_mixed_sources",
            clean_path,
            VerificationStatus.CONSISTENT,
            description="Legal Shrine, Chaos, Dice, and Old Mask transitions.",
        ),
        ReferenceRecording(
            "modded_environment",
            modded_path,
            VerificationStatus.REVIEW_REQUIRED,
            description="Valid stats with explicit BepInEx/Doorstop indicators.",
        ),
        ReferenceRecording(
            "interrupted_telemetry",
            interrupted_path,
            VerificationStatus.INTERRUPTED,
            description="A recorded telemetry gap that later recovered.",
        ),
        ReferenceRecording(
            "tampered_final_value",
            _write_new_document(tampered, root / "tampered_final_value.jsonl"),
            VerificationStatus.INCONSISTENT,
            description="One final stat value no longer matches its components.",
        ),
        ReferenceRecording(
            "duplicate_metadata",
            _write_new_document(duplicate_metadata, root / "duplicate_metadata.jsonl"),
            VerificationStatus.INCONSISTENT,
            description="The recording metadata record was duplicated.",
        ),
        ReferenceRecording(
            "summary_not_last",
            _write_new_document(summary_not_last, root / "summary_not_last.jsonl"),
            VerificationStatus.INTERRUPTED,
            description="A valid summary exists but is not the final record.",
        ),
        ReferenceRecording(
            "incomplete_tail",
            _write_new_document(incomplete_tail, root / "incomplete_tail.jsonl"),
            VerificationStatus.CONSISTENT,
            description="An incomplete process-exit tail is ignored safely.",
        ),
        ReferenceRecording(
            "malformed_tail",
            _write_new_document(malformed_tail, root / "malformed_tail.jsonl"),
            None,
            expected_exception=json.JSONDecodeError,
            description="A complete malformed JSON line must be rejected.",
        ),
    )


# Mechanics corpus and manifest


def build_mechanics_corpus(
    directory: Path | str,
    scenarios: Iterable[MechanicsScenario] = MECHANICS_SCENARIOS,
) -> MechanicsCorpusBuild:
    """Build named source-equation progressions plus a machine-readable manifest."""

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    selected = tuple(scenarios)
    keys = [scenario.key for scenario in selected]
    if not selected:
        raise ValueError("At least one mechanics scenario is required")
    if len(keys) != len(set(keys)):
        raise ValueError("Mechanics scenario keys must be unique")
    for scenario in selected:
        if not _safe_fixture_key(scenario.key) or not scenario.steps:
            raise ValueError("Every mechanics scenario needs a key and steps")
        for step in scenario.steps:
            if not _safe_fixture_key(step.key) or not math.isfinite(
                step.advance_seconds
            ):
                raise ValueError("Every mechanics step needs a key and finite delay")
            if step.advance_seconds <= 0.0:
                raise ValueError("Mechanics step delays must be positive")

    manifest_path = root / "mechanics_manifest.json"
    destinations = tuple(root / f"{key}.jsonl" for key in keys)
    for destination in (*destinations, manifest_path):
        if destination.exists():
            raise FileExistsError(destination)

    references: list[MechanicsReferenceRecording] = []
    manifest_scenarios: list[dict[str, Any]] = []
    for scenario, destination in zip(selected, destinations):
        fixture = RecordedRunFixture(root, name=f"Mechanics: {scenario.key}")
        step_records: list[dict[str, Any]] = []
        try:
            for index, step in enumerate(scenario.steps):
                fixture.advance(step.advance_seconds)
                frame = fixture.capture_state(
                    step.sources,
                    observed_stats=step.observed_stats,
                    player_level=index + 1,
                    mob_kills=index,
                )
                step_records.append(
                    _mechanics_manifest_step(
                        step,
                        elapsed_seconds=fixture.clock.value,
                        frame=frame,
                    )
                )
            fixture.finish()
            document = fixture.document().with_field(
                "metadata",
                ("created_at",),
                MECHANICS_FIXTURE_CREATED_AT,
            )
        except Exception:
            fixture.close()
            fixture.path.unlink(missing_ok=True)
            raise
        path = _write_new_document(document, destination)
        fixture.path.unlink(missing_ok=True)
        digest = sha256(path.read_bytes()).hexdigest()
        reference = MechanicsReferenceRecording(
            scenario=scenario,
            path=path,
            expected_status=VerificationStatus.CONSISTENT,
            sha256=digest,
        )
        references.append(reference)
        manifest_scenarios.append(
            {
                "key": scenario.key,
                "description": scenario.description,
                "evidence": scenario.evidence,
                "recording": path.name,
                "sha256": digest,
                "expected_status": reference.expected_status.value,
                "steps": step_records,
            }
        )

    manifest = {
        "schema": 1,
        "mechanics_profile": MECHANICS_PROFILE_ID,
        "normalized_created_at": MECHANICS_FIXTURE_CREATED_AT,
        "target_stats": {
            str(stat_id): TARGET_STAT_LABELS[stat_id]
            for stat_id in TARGET_STAT_IDS
        },
        "source_equations": {
            "39": "(1 + 0.15 * old_mask) * (1 + shrines + dice + chaos)",
            "40": "1 + shrines + dice + chaos",
            "41": "1 + shrines + dice + chaos",
        },
        "scenarios": manifest_scenarios,
    }
    _write_new_bytes(
        manifest_path,
        (
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return MechanicsCorpusBuild(manifest_path, tuple(references))


def _safe_fixture_key(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value.isascii()
        and value == value.casefold()
        and all(character.isalnum() or character == "_" for character in value)
    )


def _mechanics_manifest_step(
    step: MechanicsScenarioStep,
    *,
    elapsed_seconds: float,
    frame: VerifierStatFrame,
) -> dict[str, Any]:
    sources = step.sources
    shrine_values = _target_values(sources.shrines)
    dice_values = _target_values(sources.dice)
    chaos_values = _target_values(sources.chaos)
    shrine_rolls = _source_roll_counts(shrine_values, sources.shrine_rolls)
    dice_rolls = _source_roll_counts(dice_values, sources.dice_rolls)
    chaos_rolls = _source_roll_counts(chaos_values, sources.chaos_rolls)
    return {
        "key": step.key,
        "description": step.description,
        "evidence": step.evidence,
        "elapsed_seconds": elapsed_seconds,
        "sources": {
            "shrines": _string_keyed_numbers(shrine_values),
            "shrine_rolls": _string_keyed_numbers(shrine_rolls),
            "shrine_charged": _resolved_source_count(
                sources.shrine_charged,
                shrine_rolls,
            ),
            "dice": _string_keyed_numbers(dice_values),
            "dice_rolls": _string_keyed_numbers(dice_rolls),
            "dice_level": _resolved_source_count(sources.dice_level, dice_rolls),
            "chaos": _string_keyed_numbers(chaos_values),
            "chaos_rolls": _string_keyed_numbers(chaos_rolls),
            "chaos_level": _resolved_source_count(
                sources.chaos_level,
                chaos_rolls,
            ),
            "old_mask": sources.old_mask,
        },
        "expected_stats": {
            str(component.stat_id): {
                "final": component.final_value,
                "final_bits": float32_bits(component.final_value),
                "raw": component.raw_value,
                "raw_bits": float32_bits(component.raw_value),
                "base": component.base_value,
                "base_bits": float32_bits(component.base_value),
                "additive": component.additive_value,
                "additive_bits": float32_bits(component.additive_value),
                "multiplicative": component.multiplicative_value,
                "multiplicative_bits": float32_bits(
                    component.multiplicative_value
                ),
            }
            for component in frame.stats
        },
    }


def _string_keyed_numbers(values: Mapping[int, float | int]) -> dict[str, float | int]:
    return {str(key): value for key, value in sorted(values.items())}


def _write_new_document(document: RecordingDocument, path: Path) -> Path:
    # Exclusive creation keeps the corpus builder's no-overwrite guarantee true
    # even if another process creates the destination after the preflight pass.
    return _write_new_bytes(path, document.to_bytes())


def _write_new_bytes(path: Path, payload: bytes) -> Path:
    with path.open("xb") as output:
        output.write(payload)
    return path


def _target_values(values: Mapping[int, float]) -> dict[int, float]:
    return {stat_id: float(values.get(stat_id, 0.0)) for stat_id in TARGET_STAT_IDS}


def _source_roll_counts(
    values: Mapping[int, float],
    counts: Mapping[int, int],
) -> dict[int, int]:
    return {
        stat_id: int(counts.get(stat_id, 1 if value != 0.0 else 0))
        for stat_id, value in values.items()
    }


def _resolved_source_count(explicit: int | None, rolls: Mapping[int, int]) -> int:
    return sum(rolls.values()) if explicit is None else int(explicit)


def _shrine_snapshot(
    values: Mapping[int, float],
    rolls: Mapping[int, int],
    *,
    charged: int,
) -> ChargeShrineSnapshot:
    target_rolls = sum(rolls.values())
    other_rolls = max(0, int(charged) - target_rolls)
    stats = tuple(
        ChargeShrineStatSnapshot(
            stat_id=stat_id,
            label=f"Target {stat_id}",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=rolls[stat_id],
        )
        for stat_id, value in values.items()
        if value != 0.0
    )
    if other_rolls:
        stats += (
            ChargeShrineStatSnapshot(
                stat_id=0,
                label="Other shrine rewards",
                value=0.0,
                value_format=PlayerStatFormat.MULTIPLIER,
                rolls=other_rolls,
            ),
        )
    return ChargeShrineSnapshot(
        charged=int(charged),
        selected=int(charged),
        stats=stats,
    )


def _chaos_snapshot(
    values: Mapping[int, float],
    rolls: Mapping[int, int],
    *,
    level: int,
) -> ChaosTomeSnapshot:
    target_rolls = sum(rolls.values())
    other_rolls = max(0, int(level) - target_rolls)
    stats = tuple(
        ChaosTomeStatSnapshot(
            stat_id=stat_id,
            label=f"Target {stat_id}",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=rolls[stat_id],
        )
        for stat_id, value in values.items()
        if value != 0.0
    )
    if other_rolls:
        stats += (
            ChaosTomeStatSnapshot(
                stat_id=0,
                label="Other Chaos rolls",
                value=0.0,
                value_format=PlayerStatFormat.MULTIPLIER,
                rolls=other_rolls,
            ),
        )
    return ChaosTomeSnapshot(
        level=int(level),
        stats=stats,
    )


def _target_stat_component(
    stat_id: int,
    *,
    total: float,
    old_mask: int,
) -> VerifierStatComponents:
    base = float32(1.0 + (0.15 * old_mask if stat_id == 39 else 0.0))
    additive = float32(1.0 + float(total))
    multiplicative = float32(1.0)
    final = reconstruct_stat(base, additive, multiplicative)
    return VerifierStatComponents(
        stat_id=stat_id,
        final_value=final,
        raw_value=final,
        has_modifications=bool(total),
        base_value=base,
        additive_value=additive,
        multiplicative_value=multiplicative,
    )


def _target_modifiers(
    shrine_values: Mapping[int, float],
    dice_values: Mapping[int, float],
    chaos_values: Mapping[int, float],
    shrine_rolls: Mapping[int, int],
    dice_rolls: Mapping[int, int],
    chaos_rolls: Mapping[int, int],
) -> dict[int, tuple[Any, ...]]:
    by_stat: dict[int, list[Any]] = {stat_id: [] for stat_id in TARGET_STAT_IDS}
    for source_index, (values, counts) in enumerate(
        (
            (shrine_values, shrine_rolls),
            (dice_values, dice_rolls),
            (chaos_values, chaos_rolls),
        ),
        start=1,
    ):
        for stat_id, value in values.items():
            if value == 0.0:
                continue
            count = max(1, int(counts[stat_id]))
            per_roll = float(value) / count
            for roll_index in range(count):
                roll_value = (
                    float(value) - per_roll * (count - 1)
                    if roll_index == count - 1
                    else per_roll
                )
                by_stat[stat_id].append(
                    SimpleNamespace(
                        object_ptr=(
                            0xA00000
                            + source_index * 0x10000
                            + stat_id * 0x100
                            + roll_index
                        ),
                        stat_id=stat_id,
                        modify_type=0,
                        value=roll_value,
                    )
                )
    return {stat_id: tuple(modifiers) for stat_id, modifiers in by_stat.items()}


def _dice_passive_snapshot(
    dice_values: Mapping[int, float],
    dice_rolls: Mapping[int, int],
    *,
    level: int | None,
) -> CharacterPassiveSnapshot:
    is_dice = level is not None or any(value != 0.0 for value in dice_values.values())
    resolved_level = sum(dice_rolls.values()) if level is None else int(level)
    other_rolls = max(0, resolved_level - sum(dice_rolls.values()))
    effects = tuple(
        CharacterPassiveEffectSnapshot(
            key=f"target_{stat_id}",
            label=f"Target {stat_id}",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
            kind=CharacterPassiveEffectKind.PERMANENT_ROLL,
            stat_id=stat_id,
            count=dice_rolls[stat_id],
        )
        for stat_id, value in dice_values.items()
        if value != 0.0
    )
    if is_dice and other_rolls:
        effects += (
            CharacterPassiveEffectSnapshot(
                key="other_rolls",
                label="Other Dice rolls",
                value=0.0,
                value_format=PlayerStatFormat.MULTIPLIER,
                kind=CharacterPassiveEffectKind.PERMANENT_ROLL,
                stat_id=0,
                count=other_rolls,
            ),
        )
    return CharacterPassiveSnapshot(
        character_id=18 if is_dice else 0,
        character_name="Dice" if is_dice else "Fixture",
        passive_id=15 if is_dice else 0,
        passive_name="Gamba" if is_dice else "Not Gamba",
        runtime_class="PassiveAbilityGamba" if is_dice else "FixturePassive",
        level=resolved_level if is_dice else 0,
        status=CharacterPassiveStatus.SUPPORTED,
        effects=effects,
        coverage="complete",
        ambiguous=0,
        pending=0,
    )
