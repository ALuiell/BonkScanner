"""Translate persisted tracked-item configuration into tracker rules.

This adapter lives at the top level because the persisted configuration is an
``app`` concern while ``TrackedItemRule`` still belongs to the top-level live
run tracker.  Keeping it separate prevents either the OBS overlay or session
statistics from becoming the accidental owner of the shared rule shape.
"""

from __future__ import annotations

from typing import Any

from core.tracker.live_run import TrackedItemRule


def tracked_item_rules_from_config(
    rule_config: dict[str, Any],
) -> tuple[TrackedItemRule, ...]:
    rules: list[TrackedItemRule] = []
    for raw_rule in rule_config.get("tracked_items") or ():
        if not isinstance(raw_rule, dict):
            continue
        item_names = tuple(
            str(name)
            for name in raw_rule.get("item_names") or ()
            if str(name).strip()
        )
        if not item_names:
            continue
        rules.append(
            TrackedItemRule(
                id=str(raw_rule.get("id") or "_".join(item_names).lower()),
                label=str(raw_rule.get("label") or ", ".join(item_names)),
                item_names=item_names,
                mode=str(raw_rule.get("mode") or "all_run"),
                before_stage=_coerce_optional_int(raw_rule.get("before_stage")),
                before_seconds=_coerce_optional_float(raw_rule.get("before_seconds")),
                max_copies=_coerce_optional_int(raw_rule.get("max_copies")),
            )
        )
    return tuple(rules)


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
