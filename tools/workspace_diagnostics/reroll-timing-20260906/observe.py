"""Passive restart timing: read-only process handle, no input injection."""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
import datetime as dt
import json
from pathlib import Path
import statistics as S
import struct
import sys
import time
from collections import deque

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from infra.memory.game_data_client import GameDataClient as G
import os

K = C.WinDLL("kernel32", use_last_error=True)
U = C.WinDLL("user32", use_last_error=True)
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.CloseHandle.restype = W.BOOL
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.ReadProcessMemory.restype = W.BOOL
K.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
K.GetProcessTimes.restype = W.BOOL
K.GetSystemTimes.argtypes = [C.POINTER(W.FILETIME)] * 3
K.GetSystemTimes.restype = W.BOOL
K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
U.GetAsyncKeyState.argtypes = [C.c_int]
U.GetAsyncKeyState.restype = C.c_short
U.GetForegroundWindow.restype = W.HWND
U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype = W.DWORD

class Module(C.Structure):
    _fields_ = [("size", W.DWORD), ("id", W.DWORD), ("pid", W.DWORD),
                ("global_usage", W.DWORD), ("process_usage", W.DWORD),
                ("base", C.c_void_p), ("bytes", W.DWORD), ("module", W.HMODULE),
                ("name", W.WCHAR * 256), ("path", W.WCHAR * 260)]

K.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(Module)]
K.Module32FirstW.restype = W.BOOL
K.Module32NextW.argtypes = [W.HANDLE, C.POINTER(Module)]
K.Module32NextW.restype = W.BOOL

class Reader:
    def __init__(self, pid):
        self.handle = K.OpenProcess(0x0010 | 0x1000, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        snap = K.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
        if snap == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            item = Module()
            item.size = C.sizeof(Module)
            ok = K.Module32FirstW(snap, C.byref(item))
            self.base = None
            while ok:
                if item.name.lower() == "gameassembly.dll":
                    self.base = item.base
                    break
                ok = K.Module32NextW(snap, C.byref(item))
            if self.base is None:
                raise RuntimeError("GameAssembly.dll not found")
        finally:
            K.CloseHandle(snap)

    def read(self, address, size):
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not K.ReadProcessMemory(self.handle, address, buf, size, C.byref(got)) or got.value != size:
            raise OSError(C.get_last_error(), f"Read failed at {address:#x}, {size} bytes")
        return buf.raw

    def ptr(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def static(self, offset):
        return self.ptr(self.ptr(self.base + offset) + G.CLASS_STATIC_FIELDS_OFFSET)

def quantile(values, q):
    return sorted(values)[min(len(values)-1, int((len(values)-1)*q))] if values else None

def filetime_seconds(value):
    return ((value.dwHighDateTime << 32) | value.dwLowDateTime) / 10_000_000

class CpuSampler:
    def __init__(self, pids):
        self.handles = {name: K.OpenProcess(0x1000, False, pid) for name, pid in pids.items()}
        self.previous = {}
        self.previous_system = None
        self.last_time = time.perf_counter()
        self.sample()

    def sample(self):
        now = time.perf_counter()
        elapsed = max(.000001, now-self.last_time)
        values = {}
        for name, handle in self.handles.items():
            create, exit_time, kernel, user = (W.FILETIME() for _ in range(4))
            if K.GetProcessTimes(handle, C.byref(create), C.byref(exit_time), C.byref(kernel), C.byref(user)):
                total = filetime_seconds(kernel) + filetime_seconds(user)
                values[name] = round((total-self.previous.get(name, total))/elapsed*100, 2)
                self.previous[name] = total
        idle, kernel, user = (W.FILETIME() for _ in range(3))
        if K.GetSystemTimes(C.byref(idle), C.byref(kernel), C.byref(user)):
            current = (filetime_seconds(idle), filetime_seconds(kernel)+filetime_seconds(user))
            if self.previous_system:
                idle_delta, total_delta = (a-b for a,b in zip(current, self.previous_system))
                values["system"] = round((1-idle_delta/max(.000001,total_delta))*100, 2)
            self.previous_system = current
        self.last_time = now
        return values

    def close(self):
        for handle in self.handles.values():
            if handle:
                K.CloseHandle(handle)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--scanner-pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--interval", type=float, default=.005)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = (args.output / "events.jsonl").open("x", encoding="utf-8", buffering=65536)
    cycles_file = (args.output / "cycles.jsonl").open("x", encoding="utf-8", buffering=65536)
    reader = Reader(args.pid)
    generation = reader.static(G.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET)
    controller = reader.static(G.MAP_CONTROLLER_TYPE_INFO_OFFSET)
    activity = reader.static(G.TYPE_INFO_OFFSET)
    mytime = reader.static(G.MY_TIME_TYPE_INFO_OFFSET)
    started = time.perf_counter()
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    cpu_sampler = CpuSampler({"game": args.pid, "scanner": args.scanner_pid, "observer": os.getpid()})
    metadata = {"utc_start": stamp, "game_pid": args.pid, "scanner_pid": args.scanner_pid,
                "interval_s": args.interval, "process_access": "VM_READ|QUERY_LIMITED_INFORMATION",
                "config_reset_hold": json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("RESET_HOLD_DURATION"),
                "precision_note": "Polling timestamps, not scanner internal spans. Stats sampled independently. No input sent."}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    def emit(kind, **data):
        raw.write(json.dumps({"kind": kind, "t": round(time.perf_counter()-started, 6), **data}, separators=(",", ":")) + "\n")
    emit("start", **metadata)
    print(json.dumps({"status": "observing", "utc_start": stamp, "output": str(args.output)}), flush=True)
    previous_key = False
    previous_signature = None
    previous_stats = None
    stats_since = None
    last_stats_sample = -1.0
    last_loop = 0.0
    last_report = 0.0
    last_cpu = 0.0
    cycle = None
    cycles = []
    seed_events = []
    gaps, costs = deque(maxlen=20000), deque(maxlen=20000)
    errors = 0
    last_error = None
    cpu = {}
    recent_intervals = deque(maxlen=50)
    total_samples = 0
    last_seed = None
    try:
        while (now := time.perf_counter()-started) < args.seconds:
            if (args.output / "STOP").exists():
                break
            tick_start = time.perf_counter()
            gaps.append((now-last_loop)*1000)
            last_loop = now
            total_samples += 1
            try:
                r = bool(U.GetAsyncKeyState(0x52) & 0x8000)
                fg_pid = W.DWORD()
                U.GetWindowThreadProcessId(U.GetForegroundWindow(), C.byref(fg_pid))
                focused = fg_pid.value == args.pid
                g = reader.read(generation, 0x30)
                m = reader.read(controller, 0x38)
                timer = struct.unpack_from("<f", reader.read(mytime, 0x24), 0x20)[0]
                generating = bool(g[0x10])
                resetting = bool(m[0x21])
                seed = struct.unpack_from("<i", g, 0x2c)[0]
                map_ptr, stage_ptr = struct.unpack_from("<QQ", m, 0x10)
                lifecycle_ready = bool(map_ptr and stage_ptr and not generating and not resetting)
                dictionary = reader.ptr(activity)
                header = reader.read(dictionary, 0x30) if dictionary else bytes(0x30)
                entries = struct.unpack_from("<Q", header, 0x18)[0]
                count = struct.unpack_from("<i", header, 0x20)[0]
                version = struct.unpack_from("<i", header, 0x2c)[0]
                revision = (dictionary, entries, count, version)
                signature = (r, focused, generating, resetting, seed, map_ptr, stage_ptr, revision)
                if signature != previous_signature:
                    emit("state", r=r, focused=focused, generating=generating, resetting=resetting,
                         seed=seed, map_ptr=map_ptr, stage_ptr=stage_ptr, revision=revision, timer=timer)
                    previous_signature = signature
                if last_seed is not None and seed != last_seed:
                    seed_events.append(now)
                    emit("seed_change", old=last_seed, new=seed)
                last_seed = seed
                if r and not previous_key and focused:
                    if cycle:
                        cycle["cycle_ms"] = round((now-cycle["start"])*1000, 3)
                        cycle["end_seed"] = seed
                        cycle["seed_changed"] = seed != cycle["start_seed"]
                        baseline = S.median(recent_intervals) if len(recent_intervals) >= 10 else None
                        cycle["baseline_ms"] = round(baseline, 3) if baseline else None
                        cycle["fast"] = bool(baseline and cycle["cycle_ms"] < baseline*.75)
                        if cycle["cycle_ms"] < 3000:
                            recent_intervals.append(cycle["cycle_ms"])
                        cycles.append(cycle)
                        cycles_file.write(json.dumps(cycle, separators=(",", ":")) + "\n")
                        if cycle["fast"]:
                            print(json.dumps({"status": "fast_cycle", **cycle}), flush=True)
                    cycle = {"n": len(cycles)+1, "start": now, "start_seed": seed,
                             "hold_ms": None, "reset_start_ms": None, "generation_start_ms": None,
                             "generation_end_ms": None, "ready_ms": None, "stable_ms": None,
                             "unfocused_samples": 0}
                    previous_stats = None
                    stats_since = None
                if cycle:
                    elapsed = round((now-cycle["start"])*1000, 3)
                    if previous_key and not r and cycle["hold_ms"] is None:
                        cycle["hold_ms"] = elapsed
                    if resetting and cycle["reset_start_ms"] is None:
                        cycle["reset_start_ms"] = elapsed
                    if generating and cycle["generation_start_ms"] is None:
                        cycle["generation_start_ms"] = elapsed
                    if not generating and cycle["generation_start_ms"] is not None and cycle["generation_end_ms"] is None:
                        cycle["generation_end_ms"] = elapsed
                    changed = seed != cycle["start_seed"]
                    if changed and lifecycle_ready and cycle["ready_ms"] is None:
                        cycle["ready_ms"] = elapsed
                    if not focused:
                        cycle["unfocused_samples"] += 1
                    if changed and lifecycle_ready and now-last_stats_sample >= .010:
                        last_stats_sample = now
                        if not 0 < count <= 64 or not entries:
                            raise ValueError(f"Unexpected stats dictionary count={count}")
                        block = reader.read(entries+0x20, count*0x18)
                        values = []
                        for index in range(count):
                            key, value = struct.unpack_from("<QQ", block, index*0x18+8)
                            if key and value:
                                maximum, current = struct.unpack("<ii", reader.read(value+0x10, 8))
                                values.append((key, value, maximum, current))
                        after = reader.read(dictionary, 0x30)
                        if (struct.unpack_from("<Q", after, 0x18)[0], struct.unpack_from("<i", after, 0x20)[0], struct.unpack_from("<i", after, 0x2c)[0]) != (entries, count, version):
                            previous_stats = None
                            stats_since = None
                        else:
                            stats = (revision, tuple(values))
                            if stats != previous_stats:
                                previous_stats = stats
                                stats_since = now
                                emit("stats_change", cycle=cycle["n"], revision=revision, values=values)
                            elif stats_since is not None and now-stats_since >= .025 and cycle["stable_ms"] is None:
                                cycle["stable_ms"] = elapsed
                    elif not lifecycle_ready:
                        previous_stats = None
                        stats_since = None
                previous_key = r
                last_error = None
            except (OSError, ValueError, struct.error) as exc:
                errors += 1
                previous_stats = None
                stats_since = None
                if str(exc) != last_error:
                    emit("read_error", error=str(exc))
                    last_error = str(exc)
            if now-last_cpu >= 1:
                last_cpu = now
                cpu = cpu_sampler.sample()
                emit("cpu", percentages=cpu)
            costs.append((time.perf_counter()-tick_start)*1000)
            if now-last_report >= 10:
                last_report = now
                valid = [c for c in cycles if c["cycle_ms"] < 3000 and c["unfocused_samples"] == 0]
                recent = valid[-20:]
                summary = {"status": "observing", "elapsed_s": round(now, 1), "cycles": len(cycles),
                           "seed_changes": len(seed_events), "valid_cycles": len(valid), "errors": errors,
                           "recent_cycle_median_ms": round(S.median(c["cycle_ms"] for c in recent), 2) if recent else None,
                           "recent_hold_median_ms": round(S.median(c["hold_ms"] for c in recent if c["hold_ms"] is not None), 2) if any(c["hold_ms"] is not None for c in recent) else None,
                           "fast_cycles": sum(c["fast"] for c in valid), "sample_gap_p95_ms": round(quantile(gaps,.95), 3),
                           "read_cost_p95_ms": round(quantile(costs,.95), 3), "cpu_percent_one_core": cpu}
                (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                print(json.dumps(summary), flush=True)
                raw.flush()
                cycles_file.flush()
            time.sleep(max(0, args.interval-(time.perf_counter()-tick_start)))
    finally:
        emit("stop", cycles=len(cycles), seed_changes=len(seed_events), samples=total_samples, errors=errors)
        raw.close()
        cycles_file.close()
        K.CloseHandle(reader.handle)
        cpu_sampler.close()
        print(json.dumps({"status": "finished", "cycles": len(cycles), "seed_changes": len(seed_events), "errors": errors}), flush=True)

if __name__ == "__main__":
    main()
