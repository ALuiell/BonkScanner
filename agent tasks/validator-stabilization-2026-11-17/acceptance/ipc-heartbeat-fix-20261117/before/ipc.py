"""Local, bounded, authenticated-process transport for the validator worker.

No network listeners, impersonation, executable paths or memory operations are
accepted over this protocol. One application frame is outstanding per direction.
"""
from __future__ import annotations

import json
import math
import struct
import time
import uuid

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 240 * 1024
PIPE_BUFFER_BYTES = 4096
KINDS = frozenset({"hello", "ready", "start", "stop", "ping", "ack", "event"})
PIPE_CLIENT_RIGHTS = 0x12019B  # specific read/write; excludes FILE_CREATE_PIPE_INSTANCE


class ProtocolError(ValueError):
    pass


def canonical_uuid(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ProtocolError("invalid instance UUID")
    return value


def pipe_path(instance: str) -> str:
    return r"\\.\pipe\BonkScanner.Validator." + canonical_uuid(instance)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ProtocolError("duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ProtocolError("non-finite JSON number")


def _validate_tree(value, depth=0):
    if depth > 32:
        raise ProtocolError("JSON nesting exceeds limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError("non-finite JSON number")
    if isinstance(value, dict):
        for child in value.values():
            _validate_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_tree(child, depth + 1)


class FrameCodec:
    def __init__(self, worker_id: str):
        self.worker_id = canonical_uuid(worker_id)
        self.sent = 0
        self.received = 0

    def encode(self, kind: str, data: dict | None = None) -> bytes:
        if not isinstance(kind, str) or kind not in KINDS or (data is not None and not isinstance(data, dict)):
            raise ProtocolError("invalid frame type")
        frame = {"v": PROTOCOL_VERSION, "worker": self.worker_id,
                 "seq": self.sent + 1, "kind": kind, "data": data or {}}
        try:
            _validate_tree(frame)
            body = json.dumps(frame, ensure_ascii=True, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProtocolError("invalid JSON payload") from exc
        if len(body) > MAX_FRAME_BYTES:
            raise ProtocolError("frame exceeds transport budget")
        self.sent += 1
        return struct.pack("!I", len(body)) + body

    def decode(self, body: bytes) -> dict:
        if not 0 < len(body) <= MAX_FRAME_BYTES:
            raise ProtocolError("invalid frame size")
        try:
            frame = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs,
                               parse_constant=_invalid_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ProtocolError("invalid JSON frame") from exc
        if not isinstance(frame, dict) or set(frame) != {"v", "worker", "seq", "kind", "data"}:
            raise ProtocolError("invalid envelope")
        _validate_tree(frame)
        if (type(frame["v"]) is not int or frame["v"] != PROTOCOL_VERSION
                or frame["worker"] != self.worker_id
                or type(frame["seq"]) is not int or frame["seq"] != self.received + 1
                or not isinstance(frame["kind"], str) or frame["kind"] not in KINDS
                or not isinstance(frame["data"], dict)):
            raise ProtocolError("stale or invalid envelope")
        self.received += 1
        return frame


def _native():
    import pywintypes
    import win32event
    import win32file
    import win32pipe
    return pywintypes, win32event, win32file, win32pipe


def _cancel(handle):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.CancelIoEx.restype = wintypes.BOOL
    if not kernel.CancelIoEx(int(handle), None) and ctypes.get_last_error() != 1168:
        raise ctypes.WinError(ctypes.get_last_error())


class Pipe:
    """Overlapped byte pipe. Timeouts cancel and drain pending operations.

    A timeout during a frame is terminal: callers must close the pipe rather
    than treating a partially consumed frame as an idle connection.
    """
    def __init__(self, handle, *, server=False):
        self.handle = handle
        self.server = server

    @classmethod
    def create(cls, instance: str):
        import win32api
        import win32con
        import win32security
        pywintypes, _, _, pipe = _native()
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.ConvertSidToStringSid(
                win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        finally:
            token.Close()
        # Protected DACL, no inherited/Everyone/Authenticated Users entries.
        descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f"D:P(A;;0x{PIPE_CLIENT_RIGHTS:x};;;{sid})"
            f"(A;;0x{PIPE_CLIENT_RIGHTS:x};;;BA)(A;;0x{PIPE_CLIENT_RIGHTS:x};;;SY)", 1)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        attributes.bInheritHandle = False
        handle = pipe.CreateNamedPipe(pipe_path(instance),
            0x00000003 | 0x00080000 | 0x40000000,  # duplex, first instance, overlapped
            0x00000008,  # byte mode, PIPE_REJECT_REMOTE_CLIENTS
            1, PIPE_BUFFER_BYTES, PIPE_BUFFER_BYTES, 0, attributes)
        return cls(handle, server=True)

    @classmethod
    def connect(cls, instance: str, timeout=10.0):
        _, _, file, pipe = _native()
        pipe.WaitNamedPipe(pipe_path(instance), max(1, int(timeout * 1000)))
        return cls(file.CreateFile(pipe_path(instance), PIPE_CLIENT_RIGHTS, 0, None,
                                   3, 0x40000000, None))

    def _operation(self, operation, timeout: float, cancel_event=None):
        pywintypes, event, file, _ = _native()
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = event.CreateEvent(None, True, False, None)
        pending = False
        try:
            try:
                result = operation(overlapped)
                # ConnectNamedPipe reports ERROR_PIPE_CONNECTED as a return
                # code in pywin32, without an outstanding OVERLAPPED request.
                if result == 535:
                    return 0, result
                pending = True
            except pywintypes.error as exc:
                if exc.winerror == 535:  # client connected before ConnectNamedPipe
                    return 0
                if exc.winerror != 997:
                    raise
                result = None
                pending = True
            deadline = time.monotonic() + timeout
            cancelled = False
            while True:
                remaining = deadline - time.monotonic()
                wait = event.WaitForSingleObject(overlapped.hEvent,
                    max(1, int(min(remaining, .05) * 1000)))
                if wait == event.WAIT_OBJECT_0:
                    break
                cancelled = bool(cancel_event and cancel_event())
                if cancelled or time.monotonic() >= deadline:
                    break
            if wait != event.WAIT_OBJECT_0:
                _cancel(self.handle)
                try:
                    file.GetOverlappedResult(self.handle, overlapped, True)
                except pywintypes.error:
                    pass
                pending = False
                if cancelled:
                    raise InterruptedError("validator pipe operation cancelled")
                raise TimeoutError("validator pipe operation timed out")
            count = file.GetOverlappedResult(self.handle, overlapped, False)
            pending = False
            return count, result
        finally:
            if pending:
                try:
                    _cancel(self.handle)
                    file.GetOverlappedResult(self.handle, overlapped, True)
                except Exception:
                    pass
            overlapped.hEvent.Close()

    def accept(self, timeout=15.0, cancel_event=None):
        _, _, _, pipe = _native()
        self._operation(lambda ov: pipe.ConnectNamedPipe(self.handle, ov), timeout, cancel_event)

    def peer_pid(self) -> int:
        # pywin32 versions differ in exposing these functions.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        function = (kernel.GetNamedPipeClientProcessId if self.server
                    else kernel.GetNamedPipeServerProcessId)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        function.restype = wintypes.BOOL
        pid = wintypes.ULONG()
        if not function(int(self.handle), ctypes.byref(pid)):
            raise ctypes.WinError(ctypes.get_last_error())
        return pid.value

    def send(self, codec: FrameCodec, kind: str, data=None, timeout=2.0):
        _, _, file, _ = _native()
        frame = codec.encode(kind, data)
        deadline = time.monotonic() + timeout
        offset = 0
        while offset < len(frame):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("validator frame write timed out")
            # A large WriteFile can grow the named pipe's nonpaged buffer quota
            # beyond its requested size. Keep each native write within 4KiB.
            count, _ = self._operation(lambda ov: file.WriteFile(
                self.handle, frame[offset:offset + PIPE_BUFFER_BYTES], ov), remaining)
            if not count:
                raise EOFError("validator pipe closed")
            offset += count

    def receive(self, codec: FrameCodec, timeout=2.0):
        _, _, file, _ = _native()
        deadline = time.monotonic() + timeout

        def read_exact(size):
            chunks = bytearray()
            while len(chunks) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("validator frame read timed out")
                buffer = file.AllocateReadBuffer(min(PIPE_BUFFER_BYTES, size - len(chunks)))
                count, _ = self._operation(lambda ov: file.ReadFile(self.handle, buffer, ov), remaining)
                if not count:
                    raise EOFError("validator pipe closed")
                chunks.extend(buffer[:count])
            return bytes(chunks)

        length = struct.unpack("!I", read_exact(4))[0]
        if not 0 < length <= MAX_FRAME_BYTES:
            raise ProtocolError("invalid frame length")
        return codec.decode(read_exact(length))

    def available(self) -> bool:
        _, _, _, pipe = _native()
        return bool(pipe.PeekNamedPipe(self.handle, 0)[1])

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            handle.Close()

    def cancel(self):
        if self.handle is not None:
            try:
                _cancel(self.handle)
            except OSError:
                pass
