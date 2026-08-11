"""Application service and config adapters for Build Progression."""
from __future__ import annotations

from threading import RLock
from typing import Any, Mapping

from core.build_progression import (
    BuildProgressionDefinition,
    BuildProgressionSnapshot,
    BuildRequirement,
    DeadlineKind,
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
        "schema_version": 2,
        "name": definition.name,
        "deadlines_enabled": definition.deadlines_enabled,
        "requirements": [
            {
                "id": row.id,
                "kind": row.kind.value,
                "target": row.target,
                "required": int(row.required) if row.kind is RequirementKind.ITEM else row.required,
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
