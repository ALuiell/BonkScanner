"""Strict JSON output and compatible input for persisted/public boundaries."""

from __future__ import annotations

import json
from math import isfinite
from typing import Any, TextIO


def normalize_json_data(value: Any) -> Any:
    """Replace non-finite floats recursively without inventing a numeric value."""
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: normalize_json_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json_data(item) for item in value]
    return value


def dumps_strict_json(value: Any, **kwargs: Any) -> str:
    """Serialize standard JSON only; unavailable numbers become ``null``."""
    kwargs["allow_nan"] = False
    return json.dumps(normalize_json_data(value), **kwargs)


def _parse_finite_float(value: str) -> float:
    converted = float(value)
    if not isfinite(converted):
        raise ValueError(f"JSON number is outside the finite float range: {value}")
    return converted


def _parse_legacy_float(value: str) -> float | None:
    converted = float(value)
    return converted if isfinite(converted) else None


def _reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


def loads_strict_json(payload: str | bytes) -> Any:
    """Parse external JSON while rejecting NaN, Infinity and float overflow."""
    return json.loads(
        payload,
        parse_constant=_reject_non_finite_constant,
        parse_float=_parse_finite_float,
    )


def loads_legacy_json(payload: str | bytes) -> Any:
    """Read older Python-written JSON, treating non-finite numbers as unknown."""
    return json.loads(
        payload,
        parse_constant=lambda _constant: None,
        parse_float=_parse_legacy_float,
    )


def load_legacy_json(file: TextIO) -> Any:
    return json.load(
        file,
        parse_constant=lambda _constant: None,
        parse_float=_parse_legacy_float,
    )
