r"""Real BonkScanner process smoke/stress checks through the Windows API.

This is intentionally a manual test instead of a ``test_*.py`` unit test.  It
maps a real Qt window on the desktop, starts the production runtime owners and
checks the *process* exit code, so it must not run as part of the ordinary test
suite.

Run from the repository root with::

    .venv\Scripts\python.exe src\tests\manual_winapi_app_stress.py --cycles 5

Every child gets an isolated config, temporary directory and crash-journal log
directory.  The harness never reads or writes the user's repository config.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


if os.name == "nt":
    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    _USER32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _USER32.EnumWindows.restype = wintypes.BOOL
    _USER32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _USER32.IsWindowVisible.argtypes = [wintypes.HWND]
    _USER32.IsWindowVisible.restype = wintypes.BOOL
    _USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _USER32.GetWindowTextLengthW.restype = ctypes.c_int
    _USER32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    _USER32.GetWindowTextW.restype = ctypes.c_int
    _USER32.IsHungAppWindow.argtypes = [wintypes.HWND]
    _USER32.IsHungAppWindow.restype = wintypes.BOOL
    _USER32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _USER32.SendMessageTimeoutW.restype = wintypes.LPARAM
    _USER32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _USER32.PostMessageW.restype = wintypes.BOOL
    _USER32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.ShowWindow.restype = wintypes.BOOL
    _USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _USER32.GetWindowRect.restype = wintypes.BOOL
    _USER32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _USER32.SetWindowPos.restype = wintypes.BOOL


_WM_NULL = 0x0000
_WM_CLOSE = 0x0010
_SMTO_BLOCK = 0x0001
_SMTO_ABORTIFHUNG = 0x0002
_SW_MAXIMIZE = 3
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


@dataclass(frozen=True)
class EventRecord:
    record_id: int
    event_id: int
    provider: str
    created_utc: str
    data: dict[str, str]

    def relevant_to(self, executable_name: str) -> bool:
        executable = executable_name.casefold()
        values = {key: value.casefold() for key, value in self.data.items()}
        if self.provider.casefold() == "application error":
            return values.get("AppName", "") == executable
        if self.provider.casefold() == "application hang":
            return values.get("AppName", "") == executable
        if self.provider.casefold() == "windows error reporting":
            return (
                values.get("EventName", "") in {"appcrash", "apphangb1", "apphangxproc"}
                and values.get("P1", "") == executable
            )
        return False


@dataclass
class CycleResult:
    cycle: int
    scenario: str
    pid: int | None = None
    hwnd: int | None = None
    window_title: str = ""
    window_found_seconds: float | None = None
    responsive_checks: int = 0
    exit_code: int | None = None
    exit_seconds: float | None = None
    pending_journals: list[str] = field(default_factory=list)
    crash_logs: list[str] = field(default_factory=list)
    runtime_exercise: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            not self.errors
            and self.exit_code == 0
            and not self.pending_journals
            and not self.crash_logs
        )


@dataclass
class StressReport:
    started_utc: str
    artifact_dir: str
    python_executable: str
    baseline_event_record_id: int
    cycles: list[CycleResult] = field(default_factory=list)
    new_relevant_events: list[EventRecord] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.cycles) and all(cycle.passed for cycle in self.cycles) and not self.new_relevant_events


def _window_text(hwnd: int) -> str:
    length = int(_USER32.GetWindowTextLengthW(hwnd))
    buffer = ctypes.create_unicode_buffer(length + 1)
    _USER32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _visible_windows() -> list[tuple[int, int, str]]:
    windows: list[tuple[int, int, str]] = []

    @_WNDENUMPROC
    def visit(hwnd, _extra):
        owner_pid = wintypes.DWORD()
        _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if _USER32.IsWindowVisible(hwnd):
            windows.append((int(hwnd), int(owner_pid.value), _window_text(hwnd)))
        return True

    if not _USER32.EnumWindows(visit, 0):
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)
    return windows


def _wait_for_window(
    process: subprocess.Popen,
    token: str,
    timeout: float,
) -> tuple[int, int, str, float]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"process exited before its window appeared (exit code {return_code})")
        for hwnd, owner_pid, title in _visible_windows():
            if token in title:
                return hwnd, owner_pid, title, time.monotonic() - started
        time.sleep(0.05)
    matching = [entry for entry in _visible_windows() if token in entry[2]]
    raise TimeoutError(f"window was not found within {timeout:.1f}s; matching={matching!r}")


def _assert_responsive(hwnd: int, timeout_ms: int = 2000) -> None:
    if _USER32.IsHungAppWindow(hwnd):
        raise TimeoutError("IsHungAppWindow reported an unresponsive window")
    result = ctypes.c_size_t()
    completed = _USER32.SendMessageTimeoutW(
        hwnd,
        _WM_NULL,
        0,
        0,
        _SMTO_BLOCK | _SMTO_ABORTIFHUNG,
        timeout_ms,
        ctypes.byref(result),
    )
    if not completed:
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)
        raise TimeoutError(f"WM_NULL was not processed within {timeout_ms} ms")


def _send_win32_scan_code_key(vk_code: int, hold_seconds: float) -> None:
    """Send one physical-scan-code style key hold for live input diagnosis."""

    if os.name != "nt":
        raise OSError("Win32 scan-code input requires Windows")

    pointer_int = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("virtual_key", wintypes.WORD),
            ("scan_code", wintypes.WORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra_info", pointer_int),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouse_data", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra_info", pointer_int),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("message", wintypes.DWORD),
            ("param_low", wintypes.WORD),
            ("param_high", wintypes.WORD),
        ]

    class InputPayload(ctypes.Union):
        _fields_ = [
            ("mouse", MouseInput),
            ("keyboard", KeyboardInput),
            ("hardware", HardwareInput),
        ]

    class Input(ctypes.Structure):
        _anonymous_ = ("payload",)
        _fields_ = [("input_type", wintypes.DWORD), ("payload", InputPayload)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT

    scan_code = int(user32.MapVirtualKeyW(int(vk_code), 0))
    if not scan_code:
        raise ctypes.WinError(ctypes.get_last_error())

    def send(flags: int) -> None:
        event = Input(
            input_type=1,
            payload=InputPayload(
                keyboard=KeyboardInput(
                    virtual_key=0,
                    scan_code=scan_code,
                    flags=flags,
                    time=0,
                    extra_info=0,
                )
            ),
        )
        if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    send(0x0008)  # KEYEVENTF_SCANCODE
    try:
        time.sleep(max(0.0, float(hold_seconds)))
    finally:
        send(0x0008 | 0x0002)  # KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP


def _exercise_window(hwnd: int, *, settle_seconds: float) -> int:
    checks = 0
    _assert_responsive(hwnd)
    checks += 1
    if settle_seconds > 0:
        time.sleep(settle_seconds)
        _assert_responsive(hwnd)
        checks += 1

    rect = wintypes.RECT()
    if not _USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    original_width = max(480, rect.right - rect.left)
    original_height = max(360, rect.bottom - rect.top)

    for state in (_SW_MINIMIZE, _SW_RESTORE, _SW_MAXIMIZE, _SW_RESTORE):
        _USER32.ShowWindow(hwnd, state)
        time.sleep(0.15)
        _assert_responsive(hwnd)
        checks += 1

    resized_width = max(640, original_width - 120)
    resized_height = max(480, original_height - 80)
    for width, height in (
        (resized_width, resized_height),
        (original_width, original_height),
    ):
        if not _USER32.SetWindowPos(
            hwnd,
            0,
            rect.left,
            rect.top,
            width,
            height,
            _SWP_NOZORDER | _SWP_NOACTIVATE,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.15)
        _assert_responsive(hwnd)
        checks += 1
    return checks


def _decode_command_output(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "mbcs"):
        try:
            return payload.decode(encoding)
        except UnicodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _read_crash_events(limit: int = 300) -> list[EventRecord]:
    query = "*[System[(EventID=1000 or EventID=1001 or EventID=1002)]]"
    completed = subprocess.run(
        [
            "wevtutil.exe",
            "qe",
            "Application",
            f"/q:{query}",
            "/rd:true",
            f"/c:{int(limit)}",
            "/f:RenderedXml",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = _decode_command_output(completed.stderr).strip()
        raise RuntimeError(f"wevtutil failed with code {completed.returncode}: {detail}")
    payload = _decode_command_output(completed.stdout).strip()
    if not payload:
        return []
    root = ET.fromstring(f"<Events>{payload}</Events>")
    records: list[EventRecord] = []
    for event in root:
        system = event.find(f"{_EVENT_NS}System")
        event_data = event.find(f"{_EVENT_NS}EventData")
        if system is None:
            continue
        provider_element = system.find(f"{_EVENT_NS}Provider")
        event_id_element = system.find(f"{_EVENT_NS}EventID")
        record_id_element = system.find(f"{_EVENT_NS}EventRecordID")
        time_element = system.find(f"{_EVENT_NS}TimeCreated")
        if event_id_element is None or record_id_element is None:
            continue
        data: dict[str, str] = {}
        if event_data is not None:
            for element in event_data.findall(f"{_EVENT_NS}Data"):
                data[str(element.attrib.get("Name", ""))] = str(element.text or "")
        records.append(
            EventRecord(
                record_id=int(record_id_element.text or 0),
                event_id=int(event_id_element.text or 0),
                provider=str(provider_element.attrib.get("Name", "") if provider_element is not None else ""),
                created_utc=str(time_element.attrib.get("SystemTime", "") if time_element is not None else ""),
                data=data,
            )
        )
    return records


def _write_text(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8", errors="replace")


def _terminate_test_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3.0)
        return
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def _run_cycle(
    *,
    cycle: int,
    scenario: str,
    artifact_dir: Path,
    python_executable: Path,
    startup_timeout: float,
    exit_timeout: float,
    settle_seconds: float,
    enable_network_startup: bool,
) -> CycleResult:
    cycle_dir = artifact_dir / f"cycle-{cycle:02d}-{scenario}"
    temp_dir = cycle_dir / "temp"
    crash_dir = cycle_dir / "crash_logs"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    crash_dir.mkdir(parents=True, exist_ok=True)
    token = f"BonkScanner WinAPI Stress {uuid.uuid4().hex[:10]}"
    result = CycleResult(cycle=cycle, scenario=scenario)

    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment.update(
        {
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "BONKSCANNER_CRASH_LOG_DIR": str(crash_dir),
        }
    )
    command = [
        str(python_executable),
        str(Path(__file__).resolve()),
        "--child",
        "--title-token",
        token,
        "--config-dir",
        str(cycle_dir / "config"),
    ]
    if enable_network_startup:
        command.append("--enable-network-startup")
    if scenario == "live-runtime":
        command.extend(("--exercise-runtime", "--force-reroll-profile"))
    process_started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(_repository_root()),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result.pid = process.pid
    try:
        hwnd, owner_pid, title, found_seconds = _wait_for_window(
            process,
            token,
            startup_timeout,
        )
        result.pid = owner_pid
        result.hwnd = hwnd
        result.window_title = title
        result.window_found_seconds = round(found_seconds, 3)
        if scenario == "immediate-close":
            _assert_responsive(hwnd)
            result.responsive_checks = 1
        elif scenario == "live-runtime":
            runtime_result_path = cycle_dir / "runtime-exercise.json"
            runtime_deadline = time.monotonic() + startup_timeout
            while time.monotonic() < runtime_deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "child exited before the live runtime exercise completed"
                    )
                _assert_responsive(hwnd)
                result.responsive_checks += 1
                if runtime_result_path.exists():
                    result.runtime_exercise = json.loads(
                        runtime_result_path.read_text(encoding="utf-8")
                    )
                    break
                time.sleep(0.2)
            else:
                raise TimeoutError("live runtime exercise did not report completion")
            if not bool(result.runtime_exercise.get("passed")):
                result.errors.append(
                    f"live runtime exercise failed: {result.runtime_exercise!r}"
                )
        else:
            result.responsive_checks = _exercise_window(
                hwnd,
                settle_seconds=settle_seconds,
            )
        close_started = time.monotonic()
        if not _USER32.PostMessageW(hwnd, _WM_CLOSE, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result.exit_code = process.wait(timeout=exit_timeout)
            result.exit_seconds = round(time.monotonic() - close_started, 3)
        except subprocess.TimeoutExpired:
            result.errors.append(f"process did not exit within {exit_timeout:.1f}s after WM_CLOSE")
    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if process.poll() is None:
            _terminate_test_process(process)
        if result.exit_code is None:
            result.exit_code = process.returncode
        stdout, stderr = process.communicate(timeout=1.0)
        _write_text(cycle_dir / "stdout.log", stdout)
        _write_text(cycle_dir / "stderr.log", stderr)

    overlay_port = result.runtime_exercise.get("overlay_port")
    if isinstance(overlay_port, int) and overlay_port > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", overlay_port)) == 0:
                result.errors.append(
                    f"overlay port {overlay_port} remained open after process exit"
                )

    if result.exit_code != 0:
        result.errors.append(f"process exit code was {result.exit_code}, expected 0")
    result.pending_journals = sorted(
        str(path.relative_to(cycle_dir)) for path in temp_dir.rglob("pending-*.log")
    )
    result.crash_logs = sorted(
        str(path.relative_to(cycle_dir)) for path in crash_dir.glob("crash-*.log")
    )
    if result.pending_journals:
        result.errors.append(f"unclean pending journals: {result.pending_journals!r}")
    if result.crash_logs:
        result.errors.append(f"crash journals were promoted: {result.crash_logs!r}")
    _write_text(cycle_dir / "result.json", json.dumps(asdict(result), indent=2))
    elapsed = time.monotonic() - process_started
    status = "PASS" if result.passed else "FAIL"
    print(
        f"[{status}] cycle={cycle} scenario={scenario} pid={result.pid} "
        f"exit={result.exit_code} checks={result.responsive_checks} elapsed={elapsed:.2f}s",
        flush=True,
    )
    return result


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _seed_child_config(
    config_dir: Path,
    *,
    config_source: Path | None = None,
    force_reroll_profile: bool = False,
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    repository_root = _repository_root()
    sys.path.insert(0, str(repository_root / "src"))

    from app.config_repository import ConfigRepository
    from core.json_safety import load_legacy_json

    seed: dict = {}
    if config_source is not None:
        with config_source.open("r", encoding="utf-8") as stream:
            loaded = load_legacy_json(stream)
        if not isinstance(loaded, dict):
            raise ValueError(f"config source must contain a JSON object: {config_source}")
        seed = deepcopy(loaded)

    overlay = deepcopy(seed.get("OVERLAY")) if isinstance(seed.get("OVERLAY"), dict) else {}
    overlay.update({"enabled": False, "auto_start": False})
    in_game_overlay = (
        deepcopy(seed.get("IN_GAME_OVERLAY"))
        if isinstance(seed.get("IN_GAME_OVERLAY"), dict)
        else {}
    )
    in_game_overlay.update({"enabled": False, "auto_start": False})
    twitch_bot = (
        deepcopy(seed.get("TWITCH_BOT"))
        if isinstance(seed.get("TWITCH_BOT"), dict)
        else {}
    )
    twitch_bot["auto_connect"] = False
    if config_source is None:
        twitch_bot["username"] = ""

    seed.update({
        "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED": True,
        "AUTO_REROLL_SETUP_GUIDE_VERSION": 2,
        "AUTO_START_RECORDING": False,
        "SKIP_REROLL_WARNING": True,
        "SHOW_OBS_REMINDER_ON_START_SCANNER": False,
        "OVERLAY": overlay,
        "IN_GAME_OVERLAY": in_game_overlay,
        "TWITCH_BOT": twitch_bot,
    })
    if force_reroll_profile:
        impossible_name = "WINAPI LIVE FORCED REROLL"
        seed.update(
            {
                "EVALUATION_MODE": "templates",
                "TEMPLATES": [
                    {
                        "id": 999_999,
                        "name": impossible_name,
                        "color": "MAGENTA",
                        "desc": "Live harness: deliberately impossible profile",
                        "sm_total": 10_000,
                        "micro": 10_000,
                        "boss": 10_000,
                    }
                ],
                "ACTIVE_TEMPLATES": [impossible_name],
            }
        )
    repository = ConfigRepository(config_dir / "config.json")
    saved = repository.commit(seed)
    if not saved.success:
        raise OSError(saved.reason)

    from app import config

    config.initialize_config(repository)
    # Config-backed runtime caches must follow the isolated repository, not the
    # source checkout's application_path compatibility constant.  Existing VOD
    # files remain read-only inputs if an interactive test opens their tabs.
    config.application_path = str(config_dir)
    config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED = True
    config.AUTO_START_RECORDING = False
    config.OVERLAY["enabled"] = False
    config.OVERLAY["auto_start"] = False
    config.IN_GAME_OVERLAY["enabled"] = False
    config.IN_GAME_OVERLAY["auto_start"] = False
    if config_source is None:
        config.TWITCH_BOT["username"] = ""
    config.TWITCH_BOT["auto_connect"] = False
    config.user_config.update(
        {
            "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED": True,
            "AUTO_REROLL_SETUP_GUIDE_VERSION": config.AUTO_REROLL_SETUP_GUIDE_VERSION,
            "AUTO_START_RECORDING": False,
            "SKIP_REROLL_WARNING": True,
            "OVERLAY": deepcopy(config.OVERLAY),
            "IN_GAME_OVERLAY": deepcopy(config.IN_GAME_OVERLAY),
            "TWITCH_BOT": deepcopy(config.TWITCH_BOT),
        }
    )
    persisted = config.save_config(config.user_config)
    if not persisted.success:
        raise OSError(persisted.reason)


def _schedule_runtime_exercise(app, config_dir: Path) -> None:
    """Drive production runtime owners without GUI automation.

    The child starts the scanner, OBS server and in-game overlay on the Qt
    thread.  The parent observes only Win32 responsiveness and closes the real
    top-level window with ``WM_CLOSE`` once this marker proves the resources are
    active.  Production shutdown must then stop all three owners cleanly.
    """

    result_path = config_dir.parent / "runtime-exercise.json"
    started_at = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        overlay_port = int(reservation.getsockname()[1])

    state: dict[str, object] = {
        "passed": False,
        "overlay_port": overlay_port,
        "errors": [],
    }

    def record_error(exc: BaseException) -> None:
        errors = state.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(f"{type(exc).__name__}: {exc}")

    def publish() -> None:
        state["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
        _write_text(result_path, json.dumps(state, indent=2))

    def observe_until_ready() -> None:
        try:
            scanner = app._scanner
            worker = scanner.scanner_thread
            overlay = app._overlay
            in_game = app._in_game_overlay
            in_game_window = in_game.in_game_overlay_window
            attached_pid = app._run_control.attached_game_process_id()
            state.update(
                {
                    "attached_game_pid": attached_pid,
                    "scanner_worker_alive": bool(worker is not None and worker.is_alive()),
                    "scanner_ready": bool(scanner.is_ready_to_start),
                    "obs_server_running": bool(overlay.overlay_server.is_running),
                    "in_game_overlay_created": bool(in_game_window is not None),
                    "in_game_overlay_timer_active": bool(
                        in_game.overlay_fast_timer.isActive()
                    ),
                    "in_game_overlay_visible": bool(
                        in_game_window is not None and in_game_window.isVisible()
                    ),
                }
            )
            ready = bool(
                attached_pid
                and state["scanner_worker_alive"]
                and state["scanner_ready"]
                and state["obs_server_running"]
                and state["in_game_overlay_created"]
                and state["in_game_overlay_timer_active"]
            )
            if ready:
                state["passed"] = True
                publish()
                return
            if time.monotonic() - started_at >= 6.0:
                state.setdefault("errors", []).append("runtime owners did not become ready")
                publish()
                return
        except BaseException as exc:
            record_error(exc)
            publish()
            return
        app.after(100, observe_until_ready)

    def start_runtime_owners() -> None:
        try:
            from app import config

            overlay = app._overlay
            if overlay.overlay_port_entry is not None:
                overlay.overlay_port_entry.setText(str(overlay_port))
            state["obs_start_returned"] = bool(overlay.start_overlay_server())

            in_game = app._in_game_overlay
            in_game._init_in_game_overlay()
            config.IN_GAME_OVERLAY["enabled"] = True
            config.user_config["IN_GAME_OVERLAY"] = deepcopy(config.IN_GAME_OVERLAY)
            state["game_focus_requested"] = bool(
                app._run_control.bring_game_window_to_front(config.PROCESS_NAME)
            )
            in_game.start_in_game_overlay()

            app._scanner.toggle_main_loop()
        except BaseException as exc:
            record_error(exc)
            publish()
            return
        observe_until_ready()

    app.after(250, start_runtime_owners)


def _child_main(args: argparse.Namespace) -> int:
    # Only stdlib modules have been imported before the journal is installed.
    repository_root = _repository_root()
    sys.path.insert(0, str(repository_root / "src"))
    from infra.crash_journal import install_crash_journal, log_runtime_event, mark_clean_exit

    install_crash_journal()
    event_loop_failed = False
    app = None
    clean_shutdown = False
    try:
        _seed_child_config(
            Path(args.config_dir),
            config_source=Path(args.config_source) if args.config_source else None,
            force_reroll_profile=bool(args.force_reroll_profile),
        )
        import keyboard
        from gui_app import MegabonkApp

        log_runtime_event("winapi_stress.application.constructing")
        app = MegabonkApp(terminate_process=lambda code: os._exit(int(code)))
        app.setWindowTitle(args.title_token)
        if not args.enable_network_startup:
            app.deferred_update_check = lambda: None
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        app.start()
        if args.exercise_runtime:
            _schedule_runtime_exercise(app, Path(args.config_dir))
        log_runtime_event("winapi_stress.application.mainloop_enter")
        app.mainloop()
    except BaseException:
        event_loop_failed = True
        raise
    finally:
        if app is not None:
            clean_shutdown = app.on_closing() is not False
    log_runtime_event(
        "winapi_stress.application.mainloop_return",
        clean_shutdown=clean_shutdown,
    )
    if not event_loop_failed and clean_shutdown:
        mark_clean_exit()
        return 0
    return 1


def _parent_main(args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("This manual stress test requires Windows.", file=sys.stderr)
        return 2
    repository_root = _repository_root()
    python_executable = Path(args.python or sys.executable).resolve()
    artifact_dir = repository_root / (
        f".tmp_winapi_app_stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    artifact_dir.mkdir(parents=True, exist_ok=False)

    baseline_events = _read_crash_events()
    baseline_record_id = max((record.record_id for record in baseline_events), default=0)
    report = StressReport(
        started_utc=datetime.now(timezone.utc).isoformat(),
        artifact_dir=str(artifact_dir),
        python_executable=str(python_executable),
        baseline_event_record_id=baseline_record_id,
    )
    print(f"Artifacts: {artifact_dir}", flush=True)
    print(f"WER baseline EventRecordID: {baseline_record_id}", flush=True)

    for cycle in range(1, args.cycles + 1):
        if args.live_runtime and cycle == args.cycles:
            scenario = "live-runtime"
        else:
            scenario = "immediate-close" if cycle == 1 else "window-lifecycle"
        report.cycles.append(
            _run_cycle(
                cycle=cycle,
                scenario=scenario,
                artifact_dir=artifact_dir,
                python_executable=python_executable,
                startup_timeout=args.startup_timeout,
                exit_timeout=args.exit_timeout,
                settle_seconds=args.settle_seconds,
                enable_network_startup=args.enable_network_startup,
            )
        )

    # WER can be written shortly after the faulting process has disappeared.
    time.sleep(args.wer_settle_seconds)
    executable_name = python_executable.name
    report.new_relevant_events = [
        record
        for record in _read_crash_events()
        if record.record_id > baseline_record_id and record.relevant_to(executable_name)
    ]
    report_path = artifact_dir / "report.json"
    _write_text(report_path, json.dumps(asdict(report), indent=2))
    print(
        f"New relevant Application Error/WER events: {len(report.new_relevant_events)}",
        flush=True,
    )
    print(f"Report: {report_path}", flush=True)
    print("RESULT: PASS" if report.passed else "RESULT: FAIL", flush=True)
    return 0 if report.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--exit-timeout", type=float, default=20.0)
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    parser.add_argument("--wer-settle-seconds", type=float, default=3.0)
    parser.add_argument("--python", default="")
    parser.add_argument("--enable-network-startup", action="store_true")
    parser.add_argument(
        "--live-runtime",
        action="store_true",
        help="exercise scanner and overlay owners against the running game",
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--title-token", default="", help=argparse.SUPPRESS)
    parser.add_argument("--config-dir", default="", help=argparse.SUPPRESS)
    parser.add_argument("--config-source", default="", help=argparse.SUPPRESS)
    parser.add_argument("--force-reroll-profile", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--exercise-runtime", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.child:
        return _child_main(args)
    if args.cycles < 1:
        raise SystemExit("--cycles must be at least 1")
    return _parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
