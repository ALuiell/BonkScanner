"""Where the application is installed.

This is not a setting -- nothing chooses it and nothing persists it. It is a fact
about the running process, which is why it belongs here rather than in
`app/config`, where it used to be the reason `infra/vod_storage.py` had to import
`app`.

Keeping it in `config.py` was also a live bug. Both values were derived from
`config.py`'s own `__file__`, so moving that file moved the application's data
directory with it: step 10b's `src/config.py` -> `src/app/config.py` silently
repointed `config.json` and `stats_recordings/` from the repository root into
`src/`, for source runs only (the frozen branch reads `sys.executable`, so no exe
build could reveal it). Anchoring here, one directory below `src/`, restores the
original values -- and pins them, because these functions have no reason to move
again.
"""
from __future__ import annotations

import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_path() -> str:
    """The `src/` directory, or the exe's directory in a frozen build."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _SRC_DIR


def application_path() -> str:
    """The directory holding `config.json` and `stats_recordings/`."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(_SRC_DIR)
