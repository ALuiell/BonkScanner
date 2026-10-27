"""Writable paths for scanner minimap diagnostics and offline analysis."""
from __future__ import annotations

import os
from pathlib import Path
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS_ROOT = REPO_ROOT / "runtime" / "diagnostics" / "minimap"


def capture_directory(prefix: str) -> Path:
    destination = DIAGNOSTICS_ROOT / time.strftime(prefix + "-%Y%m%d-%H%M%S")
    destination.mkdir(parents=True)
    return destination


def analysis_directory(capture: Path) -> Path:
    configured_root = os.environ.get("BONKSCANNER_MINIMAP_ANALYSIS_ROOT")
    root = Path(configured_root) if configured_root else DIAGNOSTICS_ROOT / "analysis"
    destination = root / capture.name
    if destination.resolve() == capture.resolve():
        raise ValueError("Analysis output must be separate from the capture archive")
    destination.mkdir(parents=True, exist_ok=True)
    return destination
