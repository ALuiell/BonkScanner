from __future__ import annotations

import re


CURRENT_VERSION = "3.1.3"
_VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_version(value: object) -> tuple[int, int, int, int]:
    """Parse a release or test version into one comparable four-part tuple."""
    if not isinstance(value, str):
        raise ValueError("Version must be a string in X.Y.Z or X.Y.Z.N format.")
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Unsupported version format: {value!r}.")
    major, minor, patch, test_revision = match.groups()
    return int(major), int(minor), int(patch), int(test_revision or 0)
