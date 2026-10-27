"""Paths and isolated recording fixtures for retained scanner diagnostics."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_ROOT = Path(__file__).resolve().parent
LOCAL_ARCHIVE = REPO_ROOT / "ui_assets" / "archive" / "scratch_20261027"


def output_directory(relative: str = "") -> Path:
    configured = os.environ.get("BONKSCANNER_DIAGNOSTIC_OUTPUT_ROOT")
    root = Path(configured).resolve() if configured else REPO_ROOT / "runtime/diagnostics/workspace"
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Diagnostic output must stay inside its output root")
    result = root / relative_path
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Diagnostic output escapes its output root")
    result.mkdir(parents=True, exist_ok=True)
    return result


def output_path(relative: str) -> Path:
    path = Path(relative)
    return output_directory(path.parent.as_posix()) / path.name


def session_directory(label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns())
    return output_directory(label + "/" + stamp)


def local_asset_path(relative: str) -> Path:
    path = LOCAL_ARCHIVE / relative
    if not path.resolve().is_relative_to(LOCAL_ARCHIVE.resolve()):
        raise ValueError("Local asset escapes its archive")
    return path


def stage_recording_fixtures(destination: Path) -> Path:
    """Copy verified runs into an empty diagnostic directory before showing UI.

    Source libraries are read only. A UI probe must never receive their paths.
    """
    destination = Path(destination).resolve()
    allowed = output_directory().resolve()
    if not destination.is_relative_to(allowed) or destination == allowed:
        raise ValueError("Fixtures must be inside a diagnostic output subdirectory")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Use a fresh fixture directory for every UI session")
    local_data = os.environ.get("LOCALAPPDATA")
    onedrive = Path(os.environ.get("OneDrive", str(Path.home() / "OneDrive")))
    sources = ([Path(local_data) / "BonkScanner/stats_recordings"] if local_data else [])
    sources.append(onedrive / "Desktop/BS_adv/stats_recordings")
    override = os.environ.get("BONKSCANNER_DIAGNOSTIC_RECORDINGS_SOURCE")
    if override:
        sources.insert(0, Path(override))
    manifest = json.loads((CODE_ROOT / "recording_fixtures.json").read_text(encoding="utf-8"))
    selected = []
    for record in manifest["files"]:
        name = record["name"]
        if Path(name).name != name:
            raise ValueError("Fixture names must be plain filenames")
        matched = None
        for source in sources:
            candidate = source / name
            if candidate.is_file() and candidate.stat().st_size == record["bytes"]:
                with candidate.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest == record["sha256"]:
                    matched = candidate
                    break
        if matched is None:
            raise FileNotFoundError("Verified local recording fixture unavailable: " + name)
        if destination.is_relative_to(matched.parent.resolve()):
            raise ValueError("Fixture output must be separate from the source library")
        selected.append((matched, record))
    destination.mkdir(parents=True, exist_ok=True)
    for source, record in selected:
        target = destination / record["name"]
        shutil.copy2(source, target)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise RuntimeError("Recording changed while making a fixture copy")
    return destination
