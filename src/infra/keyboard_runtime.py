"""Exception-safe serialization of BonkScanner's own keyboard sends."""
from __future__ import annotations

import threading
from contextlib import contextmanager

from core.run_control import RunControlError

_SEND_LOCK = threading.RLock()


@contextmanager
def keyboard_send_scope(keyboard_module):
    """Do not take ownership of another sender's already-active replay flag."""
    with _SEND_LOCK:
        listener = getattr(keyboard_module, "_listener", None)
        if listener is not None and listener.is_replaying:
            raise RunControlError("Keyboard input is busy. Try again after the current operation finishes.")
        yield


def keyboard_operation(keyboard_module, operation: str, hotkey: str) -> None:
    # keyboard 0.13.5 send() does not reset is_replaying in a finally block.
    with keyboard_send_scope(keyboard_module):
        listener = getattr(keyboard_module, "_listener", None)
        try:
            getattr(keyboard_module, operation)(hotkey)
        finally:
            if listener is not None:
                listener.is_replaying = False
