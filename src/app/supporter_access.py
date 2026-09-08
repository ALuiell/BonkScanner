"""Application-owned supporter entitlement state and feature gate."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from infra.supporter_access_cache import (
    delete_access_cache,
    read_access_cache,
    write_access_cache,
)
from infra.supporter_access_client import (
    AccessResponse,
    InvalidAccessKey,
    SupporterAccessClient,
    SupporterAccessError,
    SupporterAccessRateLimited,
    masked_access_key,
    normalize_access_key,
)
from infra.supporter_credentials import (
    delete_supporter_access_key,
    get_supporter_access_key,
    set_supporter_access_key,
)


OFFLINE_GRACE = timedelta(hours=24)
DEFAULT_RECHECK_SECONDS = 15 * 60
_CACHE_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class SupporterAccessState:
    status: str
    active: bool = False
    has_key: bool = False
    features: tuple[str, ...] = ()
    expires_at: datetime | None = None
    next_change_at: datetime | None = None
    checked_at: datetime | None = None
    key_hint: str = ""
    online: bool = False
    checking: bool = False
    message: str = ""


Listener = Callable[[SupporterAccessState], None]


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone")
    return parsed.astimezone(timezone.utc)


class SupporterAccessController:
    """Own one key, one validated snapshot and all network refreshes."""

    def __init__(
        self,
        *,
        client: SupporterAccessClient,
        schedule: Callable[[int, Callable[[], None]], object],
        is_shutting_down: Callable[[], bool],
        thread_registry: set | None = None,
        cache_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
        worker_launcher: Callable[[Callable[[], None]], object] | None = None,
        get_key: Callable[[], str] = get_supporter_access_key,
        set_key: Callable[[str], None] = set_supporter_access_key,
        delete_key: Callable[[], None] = delete_supporter_access_key,
    ):
        self._client = client
        self._schedule = schedule
        self._is_shutting_down = is_shutting_down
        self._thread_registry = thread_registry
        self._cache_path = cache_path
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._worker_launcher = worker_launcher
        self._get_key = get_key
        self._set_key = set_key
        self._delete_key = delete_key
        self._listeners: list[Listener] = []
        self._inflight_lock = threading.Lock()
        self._inflight = False
        self._generation = 0
        try:
            self._key = normalize_access_key(self._get_key())
        except Exception:
            self._key = ""
        self._state = self._initial_state()

    @property
    def state(self) -> SupporterAccessState:
        return self._state

    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def start(self) -> None:
        if not self._key or self._is_shutting_down():
            return
        digest = hashlib.sha256(self._key.encode("ascii")).digest()
        initial_delay_ms = 1500 + int.from_bytes(digest[:2], "big") % 13_500
        self._schedule_check(initial_delay_ms)

    def has_feature(self, feature_code: str) -> bool:
        state = self._state
        now = self._now()
        if not state.active or feature_code not in state.features:
            return False
        if state.expires_at is not None and state.expires_at <= now:
            return False
        if (
            not state.online
            and state.checked_at is not None
            and state.checked_at + OFFLINE_GRACE <= now
        ):
            return False
        return True

    def activate(self, raw_key: str) -> bool:
        try:
            candidate = normalize_access_key(raw_key)
        except InvalidAccessKey as exc:
            self._publish(replace(self._state, checking=False, message=str(exc)))
            return False
        return self._begin_check(candidate, save_candidate=True)

    def check_now(self) -> bool:
        if not self._key:
            self._publish(self._no_key_state())
            return False
        return self._begin_check(self._key, save_candidate=False)

    def remove_key(self) -> None:
        self._generation += 1
        self._key = ""
        try:
            self._delete_key()
        finally:
            delete_access_cache(self._cache_path)
        self._publish(self._no_key_state())

    def _initial_state(self) -> SupporterAccessState:
        if not self._key:
            return self._no_key_state()
        cached = self._state_from_cache(self._key)
        if cached is not None:
            return cached
        return SupporterAccessState(
            status="unchecked",
            has_key=True,
            key_hint=masked_access_key(self._key),
            message="The saved key has not been checked yet.",
        )

    @staticmethod
    def _no_key_state() -> SupporterAccessState:
        return SupporterAccessState(
            status="no_key",
            message="Add a supporter key to unlock assigned premium features.",
        )

    def _state_from_cache(self, raw_key: str) -> SupporterAccessState | None:
        payload = read_access_cache(self._cache_path)
        if not payload or payload.get("schema_version") != _CACHE_SCHEMA:
            return None
        try:
            key_hint = str(payload["key_hint"])
            if key_hint != masked_access_key(raw_key):
                return None
            status = str(payload["status"])
            active = bool(payload["active"])
            features_value = payload["features"]
            if not isinstance(features_value, list) or not all(
                isinstance(value, str) for value in features_value
            ):
                return None
            checked_at = _timestamp(payload["checked_at"])
            expires_at = _timestamp(payload.get("expires_at"))
            next_change_at = _timestamp(payload.get("next_change_at"))
        except (KeyError, TypeError, ValueError):
            return None
        if checked_at is None or checked_at > self._now() + timedelta(minutes=5):
            return None
        safe_active = bool(
            active
            and status.startswith("active_")
            and checked_at + OFFLINE_GRACE > self._now()
            and (expires_at is None or expires_at > self._now())
        )
        stale_status = (
            "expired"
            if active and expires_at is not None and expires_at <= self._now()
            else "offline_unknown"
            if active
            else status
        )
        return SupporterAccessState(
            status="cached_valid" if safe_active else stale_status,
            active=safe_active,
            has_key=True,
            features=tuple(sorted(set(features_value))) if safe_active else (),
            expires_at=expires_at,
            next_change_at=next_change_at,
            checked_at=checked_at,
            key_hint=key_hint,
            online=False,
            message=(
                "Using access verified recently while the service reconnects."
                if safe_active
                else "Showing the last known access state."
            ),
        )

    def _begin_check(self, key: str, *, save_candidate: bool) -> bool:
        if self._is_shutting_down():
            return False
        with self._inflight_lock:
            if self._inflight:
                return False
            self._inflight = True
        self._generation += 1
        generation = self._generation
        previous = self._state
        self._publish(
            replace(
                previous,
                has_key=bool(self._key) or save_candidate,
                checking=True,
                message="Checking supporter access…",
            )
        )

        def worker() -> None:
            try:
                response = self._client.check(key)
                outcome = ("response", response)
            except InvalidAccessKey as exc:
                outcome = ("invalid", exc)
            except SupporterAccessRateLimited as exc:
                outcome = ("rate_limited", exc)
            except SupporterAccessError as exc:
                outcome = ("offline", exc)
            except Exception:
                outcome = (
                    "offline",
                    SupporterAccessError("Supporter access could not be checked."),
                )
            finally:
                with self._inflight_lock:
                    self._inflight = False

            def apply() -> None:
                if self._is_shutting_down() or generation != self._generation:
                    return
                kind, value = outcome
                if kind == "response":
                    self._apply_response(key, value, save_candidate=save_candidate)
                elif kind == "invalid":
                    if save_candidate:
                        # A mistyped replacement must not discard an already
                        # working saved key or its last verified entitlement.
                        self._publish(
                            replace(previous, checking=False, message=str(value))
                        )
                    else:
                        # A real online 401 for the saved key is authoritative.
                        # Never leave rights inherited from an offline cache
                        # active until its grace period happens to elapse.
                        delete_access_cache(self._cache_path)
                        self._publish(
                            SupporterAccessState(
                                status="invalid",
                                active=False,
                                has_key=True,
                                features=(),
                                checked_at=self._now(),
                                key_hint=(
                                    previous.key_hint or masked_access_key(key)
                                ),
                                online=True,
                                checking=False,
                                message=str(value),
                            )
                        )
                        self._schedule_next(DEFAULT_RECHECK_SECONDS)
                elif kind == "rate_limited":
                    self._publish(
                        replace(previous, checking=False, message=str(value))
                    )
                    self._schedule_next(value.retry_after)
                else:
                    self._apply_offline(previous, str(value))

            try:
                self._schedule(0, apply)
            except RuntimeError:
                pass

        try:
            self._launch_worker(worker)
        except Exception:
            self._publish(
                replace(
                    previous,
                    checking=False,
                    message="Supporter access could not start its background check.",
                )
            )
            return False
        return True

    def _apply_response(
        self,
        key: str,
        response: AccessResponse,
        *,
        save_candidate: bool,
    ) -> None:
        if save_candidate:
            try:
                self._set_key(key)
            except Exception:
                self._publish(
                    replace(
                        self._state,
                        active=False,
                        features=(),
                        checking=False,
                        message="The key was valid, but Windows could not store it securely.",
                    )
                )
                return
            self._key = key
        messages = {
            "active_subscription": "Premium subscription is active.",
            "active_supporter": "Supporter privileges are active.",
            "expired": "This access period has expired.",
            "inactive": "The assigned plan is currently inactive.",
            "no_access": "This key has no active access plan.",
            "pending": "This access period has not started yet.",
            "revoked": "This supporter key has been revoked.",
            "suspended": "Supporter access is suspended.",
        }
        state = SupporterAccessState(
            status=response.status,
            active=response.active,
            has_key=True,
            features=response.features if response.active else (),
            expires_at=response.expires_at,
            next_change_at=response.next_change_at,
            checked_at=response.checked_at,
            key_hint=response.key_hint or masked_access_key(key),
            online=True,
            checking=False,
            message=messages.get(response.status, "Supporter access checked."),
        )
        self._write_cache(state)
        self._publish(state)
        recheck = response.cache_seconds
        if response.next_change_at is not None:
            until_change = int((response.next_change_at - self._now()).total_seconds())
            if until_change > 0:
                recheck = min(recheck, max(60, until_change))
        self._schedule_next(recheck)

    def _apply_offline(self, previous: SupporterAccessState, message: str) -> None:
        now = self._now()
        keep_active = bool(
            previous.active
            and previous.checked_at is not None
            and previous.checked_at + OFFLINE_GRACE > now
            and (previous.expires_at is None or previous.expires_at > now)
        )
        state = replace(
            previous,
            status="cached_valid" if keep_active else "offline_unknown",
            active=keep_active,
            features=previous.features if keep_active else (),
            online=False,
            checking=False,
            message=(
                "Using recently verified access; the service is temporarily unavailable."
                if keep_active
                else message
            ),
        )
        self._publish(state)
        self._schedule_next(DEFAULT_RECHECK_SECONDS)

    def _write_cache(self, state: SupporterAccessState) -> None:
        if state.checked_at is None:
            return
        payload = {
            "schema_version": _CACHE_SCHEMA,
            "status": state.status,
            "active": state.active,
            "features": list(state.features),
            "expires_at": _isoformat(state.expires_at),
            "next_change_at": _isoformat(state.next_change_at),
            "checked_at": _isoformat(state.checked_at),
            "key_hint": state.key_hint,
        }
        try:
            write_access_cache(payload, self._cache_path)
        except (OSError, ValueError):
            pass

    def _publish(self, state: SupporterAccessState) -> None:
        self._state = state
        for listener in tuple(self._listeners):
            try:
                listener(state)
            except Exception:
                pass

    def _schedule_next(self, seconds: int) -> None:
        self._schedule_check(max(60_000, int(seconds) * 1000))

    def _schedule_check(self, delay_ms: int) -> None:
        generation = self._generation

        def check_if_current() -> None:
            if generation == self._generation and not self._is_shutting_down():
                self.check_now()

        try:
            self._schedule(int(delay_ms), check_if_current)
        except RuntimeError:
            pass

    def _launch_worker(self, target: Callable[[], None]):
        if self._worker_launcher is not None:
            return self._worker_launcher(target)
        registry = self._thread_registry

        def run() -> None:
            try:
                target()
            finally:
                if isinstance(registry, set):
                    registry.discard(threading.current_thread())

        thread = threading.Thread(target=run, name="BonkSupporterAccess", daemon=True)
        if isinstance(registry, set):
            registry.add(thread)
        try:
            thread.start()
        except Exception:
            if isinstance(registry, set):
                registry.discard(thread)
            with self._inflight_lock:
                self._inflight = False
            raise
        return thread
