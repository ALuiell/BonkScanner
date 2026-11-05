"""Protect personal libraries while constructing editable diagnostic fixtures."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workspace_diagnostics"))
import workspace_paths as paths


@pytest.fixture
def fixture_library(tmp_path, monkeypatch):
    library = tmp_path / "personal-library"
    library.mkdir()
    recording = library / "run.jsonl"
    payload = b'{"type":"metadata"}\n{"type":"snapshot","kills":123}\n'
    recording.write_bytes(payload)
    code = tmp_path / "code"
    code.mkdir()
    (code / "recording_fixtures.json").write_text(json.dumps({"files": [{
        "name": recording.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]}), encoding="utf-8")
    monkeypatch.setattr(paths, "CODE_ROOT", code)
    monkeypatch.setenv("BONKSCANNER_DIAGNOSTIC_RECORDINGS_SOURCE", str(library))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unused-profile"))
    monkeypatch.setenv("OneDrive", str(tmp_path / "unused-cloud"))
    output = tmp_path / "diagnostic-output"
    monkeypatch.setenv("BONKSCANNER_DIAGNOSTIC_OUTPUT_ROOT", str(output))
    return library, recording, payload, output


def test_editable_fixture_cannot_modify_original(fixture_library):
    _, original, payload, output = fixture_library
    destination = paths.stage_recording_fixtures(output / "session" / "recordings")
    copied = destination / original.name
    assert copied.read_bytes() == payload
    copied.write_text("edited by diagnostic UI", encoding="utf-8")
    assert original.read_bytes() == payload
    with pytest.raises(FileExistsError):
        paths.stage_recording_fixtures(destination)
    assert copied.read_text(encoding="utf-8") == "edited by diagnostic UI"


def test_reject_source_library_even_if_it_is_configured_as_output(fixture_library, monkeypatch):
    library, original, payload, _ = fixture_library
    monkeypatch.setenv("BONKSCANNER_DIAGNOSTIC_OUTPUT_ROOT", str(library))
    destination = library / "nested-output"
    with pytest.raises(ValueError):
        paths.stage_recording_fixtures(destination)
    assert not destination.exists()
    assert original.read_bytes() == payload


def test_changed_source_is_not_silently_used(fixture_library):
    _, original, payload, output = fixture_library
    original.write_bytes(payload.replace(b"123", b"999"))
    destination = output / "session"
    with pytest.raises(FileNotFoundError):
        paths.stage_recording_fixtures(destination)
    assert not destination.exists()


def test_output_traversal_does_not_create_external_directory(tmp_path, monkeypatch):
    output = tmp_path / "output"
    monkeypatch.setenv("BONKSCANNER_DIAGNOSTIC_OUTPUT_ROOT", str(output))
    with pytest.raises(ValueError):
        paths.output_directory("../outside")
    assert not (tmp_path / "outside").exists()
