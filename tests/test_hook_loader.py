from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hook_loader import HookLoadError, HookLoadResult, NativeHookLoader


class FakeNativeHookLoader(NativeHookLoader):
    def __init__(self, *, dll_path: Path, pid: int | None = 1234) -> None:
        self.process_name = "Megabonk.exe"
        self.dll_path = dll_path
        self._injected_pids: set[int] = set()
        self.pid = pid
        self.injected: list[int] = []

    def _find_process_id(self) -> int | None:
        return self.pid

    def _inject_into_pid(self, pid: int) -> None:
        self.injected.append(pid)


class FailingNativeHookLoader(FakeNativeHookLoader):
    def _inject_into_pid(self, pid: int) -> None:
        del pid
        raise HookLoadError("boom")


class NativeHookLoaderTests(unittest.TestCase):
    def test_resolve_default_dll_path_uses_base_path(self) -> None:
        base = Path("C:/BonkScanner")

        path = NativeHookLoader.resolve_dll_path(base_path=base)

        self.assertEqual(path, (base / NativeHookLoader.DEFAULT_RELATIVE_DLL).resolve())

    def test_inject_once_skips_pid_that_was_already_injected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dll_path = Path(temp_dir) / "BonkHook.dll"
            dll_path.write_bytes(b"placeholder")
            loader = FakeNativeHookLoader(dll_path=dll_path)

            first = loader.inject_once()
            second = loader.inject_once()

        self.assertEqual(first, HookLoadResult(pid=1234, dll_path=dll_path, initialized=True))
        self.assertTrue(second.skipped)
        self.assertEqual(loader.injected, [1234])

    def test_try_inject_once_logs_winapi_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dll_path = Path(temp_dir) / "BonkHook.dll"
            dll_path.write_bytes(b"placeholder")
            loader = FailingNativeHookLoader(dll_path=dll_path)
            messages: list[str] = []

            result = loader.try_inject_once(messages.append)

        self.assertIsNone(result)
        self.assertEqual(messages, ["boom"])


if __name__ == "__main__":
    unittest.main()
