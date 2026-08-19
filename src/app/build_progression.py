"""Application service and config adapters for Build Progression."""
from __future__ import annotations

from copy import deepcopy
import math
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4
from dataclasses import dataclass

from core.build_progression import (
    BuildProgressionDefinition,
    BuildProgressionSnapshot,
    BuildRequirement,
    DeadlineKind,
    PROGRESS_TARGETS,
    RequirementDeadline,
    RequirementKind,
    evaluate_build_progression,
)


def definition_from_config(value: Mapping[str, Any] | None) -> BuildProgressionDefinition:
    value = value or {}
    requirements = []
    for order, raw in enumerate(value.get("requirements") or ()):
        try:
            requirements.append(
                BuildRequirement(
                    id=str(raw["id"]),
                    kind=RequirementKind(str(raw["kind"])),
                    target=str(raw["target"]),
                    required=float(raw["required"]),
                    deadline=RequirementDeadline(
                        kind=DeadlineKind(str((raw.get("deadline") or {}).get("kind") or "none")),
                        stage=(raw.get("deadline") or {}).get("stage"),
                        seconds=(raw.get("deadline") or {}).get("seconds"),
                    ),
                    order=int(raw.get("order", order)),
                    max_required=float(raw["max_required"]) if raw.get("max_required") is not None else None,
                    cap_tracking=bool(raw.get("cap_tracking", False)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return BuildProgressionDefinition(
        name=str(value.get("name") or "Build Progression"),
        deadlines_enabled=bool(value.get("deadlines_enabled", True)),
        requirements=tuple(requirements),
    )


def definition_to_config(definition: BuildProgressionDefinition) -> dict[str, Any]:
    requirements = []
    for index, row in enumerate(definition.requirements):
        entry = {
            "id": row.id,
            "kind": row.kind.value,
            "target": row.target,
            "required": (
                int(row.required)
                if row.kind in {RequirementKind.ITEM, RequirementKind.PROGRESS}
                else row.required
            ),
            "deadline": {
                "kind": row.deadline.kind.value,
                "stage": row.deadline.stage,
                "seconds": row.deadline.seconds,
            },
            "order": index,
        }
        if row.max_required is not None:
            entry["max_required"] = int(row.max_required) if row.kind is RequirementKind.ITEM else row.max_required
        if row.cap_tracking:
            entry["cap_tracking"] = True
        requirements.append(entry)
    return {
        "name": definition.name,
        "deadlines_enabled": definition.deadlines_enabled,
        "requirements": requirements,
    }


def active_build_from_config(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    library = value or {}
    active_id = str(library.get("active_build_id") or "")
    for build in library.get("builds") or ():
        if isinstance(build, Mapping) and str(build.get("id") or "") == active_id:
            return dict(build)
    return None


def active_definition_from_config(
    value: Mapping[str, Any] | None,
) -> BuildProgressionDefinition:
    return definition_from_config(active_build_from_config(value))


def unique_build_name(name: str, existing_names) -> str:
    base = str(name or "Build Progression").strip() or "Build Progression"
    used = {str(existing).strip().casefold() for existing in existing_names}
    candidate = base
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def clone_build_config(build: Mapping[str, Any], existing_names=()) -> dict[str, Any]:
    from app import config

    copy = deepcopy(dict(build))
    copy["id"] = uuid4().hex
    copy["name"] = unique_build_name(str(copy.get("name") or "Build Progression"), existing_names)
    return config.normalize_build_definition_config(copy, regenerate_ids=True)


def build_export_payload(build: Mapping[str, Any]) -> dict[str, Any]:
    portable_requirements = []
    for raw in build.get("requirements") or ():
        deadline = raw.get("deadline") if isinstance(raw.get("deadline"), Mapping) else {}
        portable = {
            "kind": str(raw.get("kind") or ""),
            "target": str(raw.get("target") or ""),
            "required": raw.get("required"),
            "deadline": {
                "kind": str(deadline.get("kind") or "none"),
                "stage": deadline.get("stage"),
                "seconds": deadline.get("seconds"),
            },
        }
        if raw.get("max_required") is not None:
            portable["max_required"] = raw["max_required"]
        if raw.get("cap_tracking"):
            portable["cap_tracking"] = True
        portable_requirements.append(portable)
    return {
        "format": "bonkscanner-build",
        "version": 1,
        "build": {
            "name": str(build.get("name") or "Build Progression"),
            "deadlines_enabled": bool(build.get("deadlines_enabled", True)),
            "requirements": portable_requirements,
        },
    }


def _validate_portable_requirement(raw: Any) -> None:
    from app import config

    if not isinstance(raw, Mapping):
        raise ValueError("Every requirement must be a JSON object.")
    kind = str(raw.get("kind") or "").strip().lower()
    target = str(raw.get("target") or "").strip()
    if kind not in {"item", "stat", "progress"} or not target:
        raise ValueError("A requirement has an invalid type or target.")
    if kind == "stat" and target not in config.ALL_STAT_LABELS:
        raise ValueError(f"Unknown player stat: {target}")
    if kind == "progress" and target not in PROGRESS_TARGETS:
        raise ValueError(f"Unknown run progress target: {target}")
    try:
        required = float(raw.get("required"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid required value for {target}.") from exc
    if not math.isfinite(required) or required <= 0:
        raise ValueError(f"Invalid required value for {target}.")
    if kind in {"item", "progress"} and not required.is_integer():
        raise ValueError(f"{target} requires a whole number.")

    deadline = raw.get("deadline")
    if not isinstance(deadline, Mapping):
        raise ValueError(f"Invalid deadline for {target}.")
    deadline_kind = str(deadline.get("kind") or "none").lower()
    if deadline_kind not in {"none", "stage_start", "stage_overtime"}:
        raise ValueError(f"Invalid deadline for {target}.")
    if deadline_kind == "stage_start" and deadline.get("stage") not in {2, 3}:
        raise ValueError(f"Invalid tier deadline for {target}.")
    if deadline_kind == "stage_overtime":
        if deadline.get("stage") not in {1, 2, 3, 4}:
            raise ValueError(f"Invalid tier deadline for {target}.")
        try:
            seconds = float(deadline.get("seconds"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid overtime value for {target}.") from exc
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"Invalid overtime value for {target}.")


def build_from_export_payload(payload: Any, existing_names=()) -> dict[str, Any]:
    from app import config

    if not isinstance(payload, Mapping):
        raise ValueError("This file does not contain a BonkScanner build.")
    if payload.get("format") != "bonkscanner-build":
        raise ValueError("This file is not a BonkScanner build export.")
    if payload.get("version") != 1:
        raise ValueError("This build export version is not supported.")
    raw_build = payload.get("build")
    if not isinstance(raw_build, Mapping):
        raise ValueError("The exported build is missing.")
    name = str(raw_build.get("name") or "").strip()
    if not name:
        raise ValueError("The exported build has no name.")
    if not isinstance(raw_build.get("deadlines_enabled", True), bool):
        raise ValueError("The exported deadline setting is invalid.")
    requirements = raw_build.get("requirements")
    if not isinstance(requirements, list):
        raise ValueError("The exported requirements list is invalid.")
    seen: set[tuple[str, str]] = set()
    for raw in requirements:
        _validate_portable_requirement(raw)
        key = (
            str(raw.get("kind")).strip().lower(),
            str(raw.get("target")).strip(),
        )
        if key in seen:
            raise ValueError(f"Duplicate requirement: {key[1]}")
        seen.add(key)

    build = dict(raw_build)
    build["id"] = uuid4().hex
    build["name"] = unique_build_name(name, existing_names)
    return config.normalize_build_definition_config(build, regenerate_ids=True)


@dataclass
class _CapState:
    last_item_count: int = 0
    captured_size: float | None = None
    calculated_cap: int | None = None


class BuildProgressionService:
    """Own per-run transition state; delegate all rules to the core evaluator."""

    def __init__(self, tracker, definition: BuildProgressionDefinition | None = None) -> None:
        self._tracker = tracker
        self._definition = definition or BuildProgressionDefinition()
        self._run_id: str | None = None
        self._satisfied_at: dict[str, float] = {}
        self._completion_time_seconds: float | None = None
        self._min_satisfied_at: dict[str, float] = {}
        self._late: dict[str, bool] = {}
        self._cap_states: dict[str, _CapState] = {}
        self._lock = RLock()

    @property
    def definition(self) -> BuildProgressionDefinition:
        with self._lock:
            return self._definition

    def replace_definition(self, definition: BuildProgressionDefinition) -> None:
        with self._lock:
            old_signatures = {
                req.id: self._requirement_signature(req)
                for req in self._definition.requirements
            }
            self._definition = definition
            new_signatures = {
                req.id: self._requirement_signature(req)
                for req in definition.requirements
            }
            requirement_ids = set(new_signatures)
            kept_ids = {
                req_id
                for req_id in requirement_ids
                if req_id in old_signatures
                and old_signatures[req_id] == new_signatures[req_id]
            }

            definition_changed = (
                requirement_ids != set(old_signatures)
                or any(
                    old_signatures[req_id] != new_signatures[req_id]
                    for req_id in requirement_ids & set(old_signatures)
                )
            )

            if definition_changed:
                self._completion_time_seconds = None

            self._satisfied_at = {
                req_id: timestamp
                for req_id, timestamp in self._satisfied_at.items()
                if req_id in kept_ids
            }
            self._min_satisfied_at = {
                req_id: timestamp
                for req_id, timestamp in self._min_satisfied_at.items()
                if req_id in kept_ids
            }
            self._late = {
                req_id: late
                for req_id, late in self._late.items()
                if req_id in kept_ids
            }
            self._cap_states = {
                req_id: state
                for req_id, state in self._cap_states.items()
                if req_id in kept_ids
            }

    @staticmethod
    def _requirement_signature(requirement: BuildRequirement) -> tuple:
        return (
            requirement.kind,
            requirement.target,
            requirement.required,
            requirement.max_required,
            requirement.deadline,
            requirement.cap_tracking,
        )

    def has_cap_demand(self) -> bool:
        """True if the active build has any cap-tracked requirements."""
        return any(
            req.cap_tracking for req in self._definition.requirements
        )

    def _resolve_caps(
        self, runtime: Any,
    ) -> dict[str, int | None]:
        """Resolve dynamic cap targets.  Captures Size on item-count change."""
        from core.build_progression import calculate_radius_cap, count_items
        items = runtime.fast_items
        if items is None:
            latest = runtime.latest_snapshot
            if latest is not None and latest.items_available:
                items = latest.items
        item_counts = count_items(items) if items is not None else {}
        effective: dict[str, int | None] = {}
        for req in self._definition.requirements:
            if not req.cap_tracking:
                continue
            current = int(item_counts.get(req.target, 0))
            state = self._cap_states.get(req.id, _CapState())
            if current < 1:
                state = _CapState()
            elif current != state.last_item_count or state.calculated_cap is None:
                size = getattr(runtime, "size", None)
                if size is not None and size > 0:
                    cap = calculate_radius_cap(size)
                    state = _CapState(current, size, cap)
                else:
                    state = _CapState(current, None, None)
            else:
                state = _CapState(
                    current, state.captured_size, state.calculated_cap,
                )
            self._cap_states[req.id] = state
            effective[req.id] = state.calculated_cap
        return effective

    def snapshot(self) -> BuildProgressionSnapshot:
        runtime = self._tracker.runtime_snapshot()
        with self._lock:
            if runtime.run_id != self._run_id:
                self._run_id = runtime.run_id
                self._satisfied_at = {}
                self._completion_time_seconds = None
                self._min_satisfied_at = {}
                self._late = {}
                self._cap_states = {}
            caps = self._resolve_caps(runtime)
            evaluated = evaluate_build_progression(
                self._definition,
                runtime,
                previous_satisfied_at=self._satisfied_at,
                previous_completion_time_seconds=self._completion_time_seconds,
                previous_min_satisfied_at=self._min_satisfied_at,
                previous_late=self._late,
                effective_caps=caps,
            )
            self._satisfied_at = dict(evaluated.satisfied_at)
            self._completion_time_seconds = evaluated.completion_time_seconds
            self._min_satisfied_at = dict(evaluated.min_satisfied_at)
            self._late = dict(evaluated.late)
            return evaluated.snapshot
