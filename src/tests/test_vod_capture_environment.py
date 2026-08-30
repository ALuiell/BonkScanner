from __future__ import annotations

from types import SimpleNamespace
import unittest

import src  # noqa: F401 -- path bootstrap

from core.run_verifier import ENVIRONMENT_SCHEMA_VERSION
from tests.support.vod_capture import build_vod_capture


class _EnvironmentRecorder:
    def __init__(self) -> None:
        self.is_recording = False
        self.prepared = None
        self.captured = []
        self.failures = []
        self.stop_calls = 0

    def prepare_verification_context(self, **kwargs) -> None:
        self.prepared = kwargs

    def start(self, **_kwargs):
        self.is_recording = True
        return SimpleNamespace(name="environment.jsonl")

    def should_capture_environment(self) -> bool:
        return True

    def capture_environment(self, snapshot) -> None:
        self.captured.append(snapshot)

    def note_environment_failure(self, error) -> None:
        self.failures.append(str(error))

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_recording = False


class VodCaptureEnvironmentTests(unittest.TestCase):
    def test_start_periodic_and_final_scans_use_the_environment_lane(self) -> None:
        recorder = _EnvironmentRecorder()
        snapshots = iter(
            [
                {"schema": ENVIRONMENT_SCHEMA_VERSION, "digest": "initial"},
                {"schema": ENVIRONMENT_SCHEMA_VERSION, "digest": "periodic"},
                {"schema": ENVIRONMENT_SCHEMA_VERSION, "digest": "final"},
            ]
        )
        service, _world = build_vod_capture(
            recorder=recorder,
            read_game_build_id=lambda: "pe-6980d323-036fa000",
            read_process_environment=lambda: next(snapshots),
        )

        service.start_recording(seed=123, run_time_seconds=0.25)
        service._capture_process_environment()
        service.stop_recording(
            refresh_live_stats=False,
            finalize_snapshot=False,
        )

        self.assertEqual(recorder.prepared["game_build_id"], "pe-6980d323-036fa000")
        self.assertEqual(recorder.prepared["environment_snapshot"]["digest"], "initial")
        self.assertEqual(
            [snapshot["digest"] for snapshot in recorder.captured],
            ["periodic", "final"],
        )
        self.assertEqual(recorder.failures, [])
        self.assertEqual(recorder.stop_calls, 1)

    def test_scan_failure_is_recorded_without_stopping_the_run(self) -> None:
        recorder = _EnvironmentRecorder()
        calls = 0

        def read_environment():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "schema": ENVIRONMENT_SCHEMA_VERSION,
                    "digest": "initial",
                }
            raise RuntimeError("module scan failed")

        service, _world = build_vod_capture(
            recorder=recorder,
            read_process_environment=read_environment,
        )
        service.start_recording(seed=123)

        service._capture_process_environment()

        self.assertTrue(recorder.is_recording)
        self.assertEqual(recorder.failures, ["module scan failed"])


if __name__ == "__main__":
    unittest.main()
