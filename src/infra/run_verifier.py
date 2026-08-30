"""Verifier telemetry serialization and one-pass recording analysis."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.character_passives import (
    CharacterPassiveEffectKind,
    CharacterPassiveStatus,
)
from core.json_safety import loads_legacy_json
from core.run_verifier import (
    ENVIRONMENT_CAPTURE_INTERVAL_SECONDS,
    ENVIRONMENT_SCHEMA_VERSION,
    MECHANICS_PROFILE_ID,
    TARGET_STAT_IDS,
    VERIFIER_SCHEMA_VERSION,
    VerifierStatFrame,
    VerificationReport,
    analyze_records,
    environment_digest,
    float32_bits,
)
from core.run_summary import item_counts


VERIFIER_CAPTURE_INTERVAL_SECONDS = 2.0
def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _stat_totals(snapshot: Any) -> tuple[dict[str, float], bool]:
    """Return target totals and whether every target value was usable.

    A missing source snapshot or a target row with no finite value is unknown,
    not a zero bonus.  Keeping that distinction here prevents a temporarily
    unavailable Chaos/Shrine reader from turning into a false source mismatch.
    """
    totals = {str(stat_id): 0.0 for stat_id in TARGET_STAT_IDS}
    if snapshot is None:
        return totals, False
    seen: set[int] = set()
    complete = True
    for stat in tuple(getattr(snapshot, "stats", ()) or ()):
        try:
            stat_id = int(getattr(stat, "stat_id", -1))
        except (TypeError, ValueError, OverflowError):
            complete = False
            continue
        value = _finite(getattr(stat, "value", None))
        if stat_id not in TARGET_STAT_IDS:
            continue
        if stat_id in seen or value is None:
            complete = False
            continue
        seen.add(stat_id)
        totals[str(stat_id)] = value
    return totals, complete


def _dice_totals(snapshot: Any) -> tuple[dict[str, float], bool]:
    totals = {str(stat_id): 0.0 for stat_id in TARGET_STAT_IDS}
    if snapshot is None:
        return totals, False
    if str(getattr(snapshot, "passive_name", "")) != "Gamba":
        return totals, True
    seen: set[int] = set()
    complete = True
    for effect in tuple(getattr(snapshot, "effects", ()) or ()):
        if getattr(effect, "kind", None) is not CharacterPassiveEffectKind.PERMANENT_ROLL:
            continue
        try:
            stat_id = int(getattr(effect, "stat_id", -1))
        except (TypeError, ValueError, OverflowError):
            complete = False
            continue
        value = _finite(getattr(effect, "value", None))
        if stat_id not in TARGET_STAT_IDS:
            continue
        if stat_id in seen or value is None:
            complete = False
            continue
        seen.add(stat_id)
        totals[str(stat_id)] = value
    return totals, complete


class VerifierTelemetryWriter:
    """Run-local state for compact checkpoints, deltas and coverage."""

    def __init__(
        self,
        *,
        interval_seconds: float = VERIFIER_CAPTURE_INTERVAL_SECONDS,
        environment_interval_seconds: float = ENVIRONMENT_CAPTURE_INTERVAL_SECONDS,
    ):
        self.interval_seconds = max(0.25, float(interval_seconds))
        self.environment_interval_seconds = max(
            2.0, float(environment_interval_seconds)
        )
        self.reset()

    def reset(self) -> None:
        self.last_checkpoint_elapsed: float | None = None
        self.checkpoint_count = 0
        self.event_count = 0
        self._modifier_ids: dict[int, str] = {}
        self._last_modifiers: dict[str, dict[str, Any]] = {}
        self._last_source_signature: tuple[Any, ...] | None = None
        self._gaps: list[dict[str, Any]] = []
        self._open_gap: dict[str, Any] | None = None
        self.last_environment_elapsed: float | None = None
        self.environment_scan_count = 0
        self.environment_failure_count = 0
        self.environment_change_count = 0
        self._environment_modules: dict[str, dict[str, Any]] | None = None
        self._environment_artifacts: dict[str, dict[str, Any]] | None = None
        self._environment_regions: dict[str, dict[str, Any]] | None = None
        self._environment_initial_digest: str | None = None
        self._environment_last_digest: str | None = None

    def metadata(
        self,
        *,
        scanner_version: str | None,
        game_build_id: str | None,
        run_start_time_seconds: float | None,
    ) -> dict[str, Any]:
        run_start = _finite(run_start_time_seconds)
        return {
            "schema": VERIFIER_SCHEMA_VERSION,
            "mechanics_profile": MECHANICS_PROFILE_ID,
            "scanner_version": scanner_version,
            "game_build_id": game_build_id,
            "capture_interval_seconds": self.interval_seconds,
            "environment_schema": ENVIRONMENT_SCHEMA_VERSION,
            "environment_capture_interval_seconds": self.environment_interval_seconds,
            "target_stat_ids": list(TARGET_STAT_IDS),
            "run_start_time_seconds": run_start,
            "late_start": bool(run_start is not None and run_start > 5.0),
        }

    def should_capture(self, elapsed_seconds: float) -> bool:
        if self.last_checkpoint_elapsed is None:
            return True
        return (
            float(elapsed_seconds) - self.last_checkpoint_elapsed
            >= self.interval_seconds
        )

    def should_capture_environment(self, elapsed_seconds: float) -> bool:
        if self.last_environment_elapsed is None:
            return True
        return (
            float(elapsed_seconds) - self.last_environment_elapsed
            >= self.environment_interval_seconds
        )

    @staticmethod
    def _environment_maps(
        snapshot: dict[str, Any],
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        if int(snapshot.get("schema", -1)) != ENVIRONMENT_SCHEMA_VERSION:
            raise ValueError("Process environment snapshot schema is invalid.")
        raw_modules = snapshot.get("modules")
        raw_artifacts = snapshot.get("artifacts")
        raw_regions = snapshot.get("private_executable_regions")
        if (
            not isinstance(raw_modules, list)
            or not isinstance(raw_artifacts, list)
            or not isinstance(raw_regions, list)
        ):
            raise ValueError("Process environment snapshot lists are invalid.")
        modules: dict[str, dict[str, Any]] = {}
        for raw in raw_modules:
            if not isinstance(raw, dict) or not str(raw.get("id") or ""):
                raise ValueError("Process environment module entry is invalid.")
            entry = dict(raw)
            token = str(entry["id"])
            if token in modules:
                raise ValueError("Process environment module IDs are duplicated.")
            modules[token] = entry
        artifacts: dict[str, dict[str, Any]] = {}
        for raw in raw_artifacts:
            if not isinstance(raw, dict) or not str(raw.get("id") or ""):
                raise ValueError("Process environment artifact entry is invalid.")
            entry = dict(raw)
            token = str(entry["id"])
            if token in artifacts:
                raise ValueError("Process environment artifact IDs are duplicated.")
            artifacts[token] = entry
        regions: dict[str, dict[str, Any]] = {}
        for raw in raw_regions:
            if not isinstance(raw, dict) or not str(raw.get("id") or ""):
                raise ValueError("Process environment region entry is invalid.")
            entry = dict(raw)
            token = str(entry["id"])
            if token in regions:
                raise ValueError("Process environment region IDs are duplicated.")
            regions[token] = entry
        return modules, artifacts, regions

    def environment_record(
        self,
        snapshot: dict[str, Any],
        *,
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        elapsed = max(0.0, float(elapsed_seconds))
        modules, artifacts, regions = self._environment_maps(snapshot)
        digest = environment_digest(
            modules.values(),
            artifacts.values(),
            regions.values(),
        )
        sequence = self.environment_scan_count
        self.environment_scan_count += 1
        self.last_environment_elapsed = elapsed

        if (
            self._environment_modules is None
            or self._environment_artifacts is None
            or self._environment_regions is None
        ):
            self._environment_modules = modules
            self._environment_artifacts = artifacts
            self._environment_regions = regions
            self._environment_initial_digest = digest
            self._environment_last_digest = digest
            return {
                "type": "verification_environment",
                "schema": ENVIRONMENT_SCHEMA_VERSION,
                "sequence": sequence,
                "kind": "initial",
                "elapsed_seconds": elapsed,
                "modules": list(modules.values()),
                "artifacts": list(artifacts.values()),
                "private_executable_regions": list(regions.values()),
                "digest": digest,
                "module_count": len(modules),
                "artifact_count": len(artifacts),
                "private_executable_region_count": len(regions),
            }

        previous_modules = self._environment_modules
        previous_artifacts = self._environment_artifacts
        previous_regions = self._environment_regions
        removed_modules = sorted(set(previous_modules) - set(modules))
        removed_artifacts = sorted(set(previous_artifacts) - set(artifacts))
        removed_regions = sorted(set(previous_regions) - set(regions))
        added_modules = [
            modules[token]
            for token in sorted(set(modules) - set(previous_modules))
        ]
        added_artifacts = [
            artifacts[token]
            for token in sorted(set(artifacts) - set(previous_artifacts))
        ]
        added_regions = [
            regions[token]
            for token in sorted(set(regions) - set(previous_regions))
        ]
        changed_module_ids = sorted(
            token
            for token in set(modules) & set(previous_modules)
            if modules[token] != previous_modules[token]
        )
        changed_artifact_ids = sorted(
            token
            for token in set(artifacts) & set(previous_artifacts)
            if artifacts[token] != previous_artifacts[token]
        )
        changed_region_ids = sorted(
            token
            for token in set(regions) & set(previous_regions)
            if regions[token] != previous_regions[token]
        )
        for token in changed_module_ids:
            removed_modules.append(token)
            added_modules.append(modules[token])
        for token in changed_artifact_ids:
            removed_artifacts.append(token)
            added_artifacts.append(artifacts[token])
        for token in changed_region_ids:
            removed_regions.append(token)
            added_regions.append(regions[token])
        changed = bool(
            added_modules
            or removed_modules
            or added_artifacts
            or removed_artifacts
            or added_regions
            or removed_regions
        )
        if changed:
            self.environment_change_count += 1
        self._environment_modules = modules
        self._environment_artifacts = artifacts
        self._environment_regions = regions
        self._environment_last_digest = digest
        return {
            "type": "verification_environment",
            "schema": ENVIRONMENT_SCHEMA_VERSION,
            "sequence": sequence,
            "kind": "checkpoint",
            "elapsed_seconds": elapsed,
            "modules_added": added_modules,
            "modules_removed": sorted(set(removed_modules)),
            "artifacts_added": added_artifacts,
            "artifacts_removed": sorted(set(removed_artifacts)),
            "regions_added": added_regions,
            "regions_removed": sorted(set(removed_regions)),
            "digest": digest,
            "module_count": len(modules),
            "artifact_count": len(artifacts),
            "private_executable_region_count": len(regions),
        }

    def environment_failure_record(
        self,
        error: BaseException | str,
        *,
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        elapsed = max(0.0, float(elapsed_seconds))
        sequence = self.environment_scan_count
        self.environment_scan_count += 1
        self.environment_failure_count += 1
        self.last_environment_elapsed = elapsed
        # OS and filesystem exceptions often embed an absolute path. The
        # recording only needs to prove that a scan failed; keep diagnostics
        # local rather than leaking a Windows username into a shared JSONL.
        error_type = type(error).__name__ if isinstance(error, BaseException) else None
        reason = (
            f"Process environment scan failed ({error_type})."
            if error_type
            else "Process environment scan failed."
        )
        return {
            "type": "verification_environment",
            "schema": ENVIRONMENT_SCHEMA_VERSION,
            "sequence": sequence,
            "kind": "failure",
            "elapsed_seconds": elapsed,
            "reason": reason,
        }

    def note_failure(self, elapsed_seconds: float, error: BaseException | str) -> dict[str, Any] | None:
        if self._open_gap is not None:
            return None
        self._open_gap = {
            "start_elapsed_seconds": max(0.0, float(elapsed_seconds)),
            "end_elapsed_seconds": None,
            "reason": str(error)[:240],
        }
        self.event_count += 1
        return {
            "type": "verification_event",
            "schema": VERIFIER_SCHEMA_VERSION,
            "event": "telemetry_gap_started",
            "elapsed_seconds": max(0.0, float(elapsed_seconds)),
            "reason": str(error)[:240],
        }

    def _close_gap(self, elapsed_seconds: float) -> dict[str, Any] | None:
        if self._open_gap is None:
            return None
        self._open_gap["end_elapsed_seconds"] = max(0.0, float(elapsed_seconds))
        self._gaps.append(self._open_gap)
        self._open_gap = None
        self.event_count += 1
        return {
            "type": "verification_event",
            "schema": VERIFIER_SCHEMA_VERSION,
            "event": "telemetry_gap_recovered",
            "elapsed_seconds": max(0.0, float(elapsed_seconds)),
        }

    def records_for_checkpoint(
        self,
        frame: VerifierStatFrame,
        *,
        elapsed_seconds: float,
        game_time_seconds: float | None,
        permanent_modifiers: dict[int, tuple[Any, ...]],
        shrine_snapshot: Any,
        chaos_snapshot: Any,
        character_passive_snapshot: Any,
        dice_level: int | None,
        held_items: Iterable[str],
        source_availability: Mapping[str, bool],
    ) -> tuple[dict[str, Any], ...]:
        elapsed = max(0.0, float(elapsed_seconds))
        records: list[dict[str, Any]] = []
        recovered = self._close_gap(elapsed)
        if recovered is not None:
            records.append(recovered)

        modifiers = []
        for stat_id in TARGET_STAT_IDS:
            for modifier in tuple((permanent_modifiers or {}).get(stat_id, ()) or ()):
                pointer = int(getattr(modifier, "object_ptr", 0) or 0)
                token = self._modifier_ids.get(pointer)
                if token is None:
                    token = f"m{len(self._modifier_ids) + 1}"
                    self._modifier_ids[pointer] = token
                value = float(getattr(modifier, "value", 0.0))
                modifiers.append(
                    {
                        "id": token,
                        "stat_id": stat_id,
                        "modify_type": int(getattr(modifier, "modify_type", -1)),
                        "value": value,
                        "value_bits": float32_bits(value),
                    }
                )
        modifiers.sort(key=lambda modifier: (modifier["stat_id"], modifier["id"]))

        shrine_totals, shrine_values_complete = _stat_totals(shrine_snapshot)
        chaos_totals, chaos_values_complete = _stat_totals(chaos_snapshot)
        dice_totals, dice_values_complete = _dice_totals(character_passive_snapshot)
        shrine_available = source_availability.get("shrines") is True
        chaos_available = source_availability.get("chaos_tome") is True
        passive_available = source_availability.get("character_passive") is True
        shrine_complete = bool(
            shrine_available
            and shrine_snapshot is not None
            and shrine_values_complete
            and int(getattr(shrine_snapshot, "pending", 0) or 0) == 0
            and int(getattr(shrine_snapshot, "ambiguous_matches", 0) or 0) == 0
            and int(getattr(shrine_snapshot, "selected", 0) or 0)
            == int(getattr(shrine_snapshot, "charged", 0) or 0)
        )
        chaos_rolls = sum(
            max(0, int(getattr(stat, "rolls", 0) or 0))
            for stat in tuple(getattr(chaos_snapshot, "stats", ()) or ())
        )
        chaos_complete = bool(
            chaos_available
            and (
                # A fresh lookup with no Chaos entry means the tome is not held.
                # The target total is then authoritatively zero.
                chaos_snapshot is None
                or (
                    chaos_values_complete
                    and int(getattr(chaos_snapshot, "ambiguous_rolls", 0) or 0)
                    == 0
                    and chaos_rolls
                    == int(getattr(chaos_snapshot, "level", 0) or 0)
                )
            )
        )
        is_dice = bool(
            character_passive_snapshot is not None
            and str(getattr(character_passive_snapshot, "passive_name", "")) == "Gamba"
        )
        passive_status = getattr(character_passive_snapshot, "status", None)
        identity_complete = bool(
            passive_available
            and character_passive_snapshot is not None
            and passive_status
            in {
                CharacterPassiveStatus.SUPPORTED,
                CharacterPassiveStatus.UNSUPPORTED,
            }
        )
        dice_complete = bool(
            identity_complete
            and dice_values_complete
            and (
                not is_dice
                or (
                    passive_status is CharacterPassiveStatus.SUPPORTED
                    and str(getattr(character_passive_snapshot, "coverage", ""))
                    == "complete"
                    and int(getattr(character_passive_snapshot, "ambiguous", 0) or 0)
                    == 0
                    # ``pending`` is the passives tracker's pool of permanent
                    # modifiers that were *not* assigned to Dice.  It can be
                    # non-zero even at Dice level zero.  Once coverage is
                    # complete and unambiguous, every Dice roll is already
                    # accounted for; leftover candidates must not disable the
                    # legal-source equation that can evaluate them.
                    and dice_level is not None
                    and int(dice_level) >= 0
                )
            )
        )
        item_amounts = item_counts(tuple(held_items or ()))
        old_mask = max(
            0,
            int(item_amounts.get("Old Mask", item_amounts.get("OldMask", 0)) or 0),
        )
        sources = {
            "shrines": {
                "charged": int(getattr(shrine_snapshot, "charged", 0) or 0),
                "selected": int(getattr(shrine_snapshot, "selected", 0) or 0),
                "pending": int(getattr(shrine_snapshot, "pending", 0) or 0),
                "ambiguous": int(
                    getattr(shrine_snapshot, "ambiguous_matches", 0) or 0
                ),
                "totals": shrine_totals,
            },
            "dice": {
                "level": max(0, int(dice_level or 0)) if is_dice else 0,
                "coverage": str(
                    getattr(character_passive_snapshot, "coverage", "not_dice")
                    if is_dice else "not_dice"
                ),
                "ambiguous": int(
                    getattr(character_passive_snapshot, "ambiguous", 0) or 0
                ) if is_dice else 0,
                "pending": int(
                    getattr(character_passive_snapshot, "pending", 0) or 0
                ) if is_dice else 0,
                "totals": dice_totals,
            },
            "chaos": {
                "level": int(getattr(chaos_snapshot, "level", 0) or 0),
                "ambiguous": int(
                    getattr(chaos_snapshot, "ambiguous_rolls", 0) or 0
                ),
                "totals": chaos_totals,
            },
            "items": {"old_mask": old_mask},
        }
        source_complete = shrine_complete and chaos_complete and dice_complete

        stat_records: dict[str, Any] = {}
        for stat in frame.stats:
            values = {
                "final": stat.final_value,
                "raw": stat.raw_value,
                "base": stat.base_value,
                "additive": stat.additive_value,
                "multiplicative": stat.multiplicative_value,
            }
            stat_records[str(stat.stat_id)] = {
                **values,
                **{f"{key}_bits": float32_bits(value) for key, value in values.items()},
                "has_modifications": bool(stat.has_modifications),
            }

        current_modifiers = {modifier["id"]: modifier for modifier in modifiers}
        added = [
            modifier
            for token, modifier in current_modifiers.items()
            if token not in self._last_modifiers
        ]
        changed = [
            modifier
            for token, modifier in current_modifiers.items()
            if token in self._last_modifiers
            and modifier != self._last_modifiers[token]
        ]
        removed = sorted(set(self._last_modifiers) - set(current_modifiers))
        source_signature = (
            tuple(
                (source, json.dumps(value, sort_keys=True, separators=(",", ":")))
                for source, value in sorted(sources.items())
            ),
            source_complete,
        )
        source_changed = (
            self._last_source_signature is not None
            and source_signature != self._last_source_signature
        )
        if added or changed or removed or source_changed:
            self.event_count += 1
            records.append(
                {
                    "type": "verification_event",
                    "schema": VERIFIER_SCHEMA_VERSION,
                    "event": "target_state_changed",
                    "elapsed_seconds": elapsed,
                    "modifier_changes": {
                        "added": added,
                        "changed": changed,
                        "removed": removed,
                    },
                    "source_state_changed": source_changed,
                }
            )
        self._last_modifiers = current_modifiers
        self._last_source_signature = source_signature

        modifier_summary: dict[str, Any] = {}
        for stat_id in TARGET_STAT_IDS:
            stat_modifiers = [
                modifier for modifier in modifiers if modifier["stat_id"] == stat_id
            ]
            addition_sum = math.fsum(
                modifier["value"]
                for modifier in stat_modifiers
                if modifier["modify_type"] == 0
            )
            modifier_summary[str(stat_id)] = {
                "count": len(stat_modifiers),
                "addition_sum": addition_sum,
                "addition_sum_bits": float32_bits(addition_sum),
                "unsupported_count": sum(
                    modifier["modify_type"] != 0 for modifier in stat_modifiers
                ),
            }

        checkpoint = {
            "type": "verification_checkpoint",
            "schema": VERIFIER_SCHEMA_VERSION,
            "sequence": self.checkpoint_count,
            "elapsed_seconds": elapsed,
            "game_time_seconds": _finite(game_time_seconds),
            "stable": bool(frame.stable),
            "stats": stat_records,
            "modifier_summary": modifier_summary,
            "sources": sources,
            "coverage": {
                "source_attribution_complete": source_complete,
                "shrines_complete": shrine_complete,
                "dice_complete": dice_complete,
                "chaos_complete": chaos_complete,
            },
        }
        records.append(checkpoint)
        self.checkpoint_count += 1
        self.last_checkpoint_elapsed = elapsed
        return tuple(records)

    def coverage_record(self, *, elapsed_seconds: float) -> dict[str, Any]:
        if self._open_gap is not None:
            self._open_gap["end_elapsed_seconds"] = None
            self._gaps.append(self._open_gap)
            self._open_gap = None
        return {
            "type": "verification_coverage",
            "schema": VERIFIER_SCHEMA_VERSION,
            "checkpoint_count": self.checkpoint_count,
            "event_count": self.event_count,
            "duration_seconds": max(0.0, float(elapsed_seconds)),
            "gaps": list(self._gaps),
            "environment": {
                "schema": ENVIRONMENT_SCHEMA_VERSION,
                "scan_count": self.environment_scan_count,
                "failure_count": self.environment_failure_count,
                "change_count": self.environment_change_count,
                "initial_digest": self._environment_initial_digest,
                "final_digest": self._environment_last_digest,
                "final_module_count": (
                    len(self._environment_modules)
                    if self._environment_modules is not None
                    else None
                ),
                "final_artifact_count": (
                    len(self._environment_artifacts)
                    if self._environment_artifacts is not None
                    else None
                ),
                "final_private_executable_region_count": (
                    len(self._environment_regions)
                    if self._environment_regions is not None
                    else None
                ),
            },
        }


def _iter_verifier_records(path: Path):
    """Stream JSONL and tolerate only an incomplete process-exit tail."""
    pending: bytes | None = None
    with Path(path).open("rb") as file:
        for line in file:
            if not line.strip():
                continue
            if pending is not None:
                record = loads_legacy_json(pending)
                if not isinstance(record, dict):
                    raise ValueError("Every recording JSONL entry must be an object.")
                yield record
            pending = line
    if pending is None:
        return
    try:
        record = loads_legacy_json(pending)
    except (UnicodeDecodeError, json.JSONDecodeError):
        if pending.endswith((b"\n", b"\r")):
            raise
        return
    if not isinstance(record, dict):
        raise ValueError("Every recording JSONL entry must be an object.")
    yield record


def verify_vod(path: Path | str) -> VerificationReport:
    return analyze_records(_iter_verifier_records(Path(path)))
