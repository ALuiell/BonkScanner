from __future__ import annotations

import re


CURRENT_VERSION = "3.0.1"
_VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)$")


def parse_version(value: object) -> tuple[int, int, int]:
    """Parse the release format BonkScanner publishes, or reject it clearly."""
    if not isinstance(value, str):
        raise ValueError("Version must be a string in X.Y.Z format.")
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Unsupported version format: {value!r}.")
    return tuple(int(part) for part in match.groups())
