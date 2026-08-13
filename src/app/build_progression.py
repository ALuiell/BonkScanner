"""Application service and config adapters for Build Progression."""
from __future__ import annotations

from copy import deepcopy
import math
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

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
    return {
        "name": definition.name,
        "deadlines_enabled": definition.deadlines_enabled,
        "requirements": [
            {
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
            for index, row in enumerate(definition.requirements)
        ],
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
        portable_requirements.append(
            {
                "kind": str(raw.get("kind") or ""),
                "target": str(raw.get("target") or ""),
                "required": raw.get("required"),
                "deadline": {
                    "kind": str(deadline.get("kind") or "none"),
                    "stage": deadline.get("stage"),
                    "seconds": deadline.get("seconds"),
                },
            }
        )
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


class BuildProgressionService:
    """Own per-run transition state; delegate all rules to the core evaluator."""

    def __init__(self, tracker, definition: BuildProgressionDefinition | None = None) -> None:
        self._tracker = tracker
        self._definition = definition or BuildProgressionDefinition()
        self._run_id: str | None = None
        self._satisfied_at: dict[str, float] = {}
        self._completion_time_seconds: float | None = None
        self._lock = RLock()

    @property
    def definition(self) -> BuildProgressionDefinition:
        with self._lock:
            return self._definition

    def replace_definition(self, definition: BuildProgressionDefinition) -> None:
        with self._lock:
            self._definition = definition
            self._satisfied_at = {}
            self._completion_time_seconds = None

    def snapshot(self) -> BuildProgressionSnapshot:
        runtime = self._tracker.runtime_snapshot()
        with self._lock:
            if runtime.run_id != self._run_id:
                self._run_id = runtime.run_id
                self._satisfied_at = {}
                self._completion_time_seconds = None
            evaluated = evaluate_build_progression(
                self._definition,
                runtime,
                previous_satisfied_at=self._satisfied_at,
                previous_completion_time_seconds=self._completion_time_seconds,
            )
            self._satisfied_at = dict(evaluated.satisfied_at)
            self._completion_time_seconds = evaluated.completion_time_seconds
            return evaluated.snapshot
