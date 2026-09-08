"""Strict HTTP client for the small BonkScanner supporter-access API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from core.supporter_service import ACCESS_CHECK_PATH, ACCESS_KEY_PATTERN


_KEY_RE = re.compile(ACCESS_KEY_PATTERN)
_FEATURE_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
_KNOWN_STATUSES = {
    "active_subscription",
    "active_supporter",
    "expired",
    "inactive",
    "invalid",
    "missing_key",
    "no_access",
    "pending",
    "revoked",
    "suspended",
}
_MAX_RESPONSE_BYTES = 64 * 1024


class SupporterAccessError(RuntimeError):
    """A safe error that never includes the submitted access key."""


class InvalidAccessKey(SupporterAccessError):
    pass


class SupporterAccessRateLimited(SupporterAccessError):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__("Too many failed checks. Try again later.")


@dataclass(frozen=True, slots=True)
class AccessResponse:
    active: bool
    status: str
    features: tuple[str, ...]
    expires_at: datetime | None
    next_change_at: datetime | None
    checked_at: datetime
    cache_seconds: int
    key_hint: str


def normalize_access_key(raw_key: str) -> str:
    normalized = str(raw_key or "").strip().upper()
    if not _KEY_RE.fullmatch(normalized):
        raise InvalidAccessKey("Enter the complete BSK_ supporter key.")
    return normalized


def masked_access_key(raw_key: str) -> str:
    normalized = normalize_access_key(raw_key)
    return f"{normalized[:12]}••••{normalized[-4:]}"


def _parse_timestamp(value, *, required: bool = False) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SupporterAccessError("The access service returned an invalid timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SupporterAccessError(
            "The access service returned an invalid timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise SupporterAccessError("The access service returned a timestamp without a timezone.")
    return parsed.astimezone(timezone.utc)


def _validated_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    local_http = parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise SupporterAccessError("The supporter service must use HTTPS.")
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SupporterAccessError("The supporter service URL is invalid.")
    if parsed.path not in {"", "/"}:
        raise SupporterAccessError("The supporter service URL must point to its root.")
    return value


class SupporterAccessClient:
    def __init__(self, base_url: str, *, client_version: str):
        self._base_url = _validated_base_url(base_url)
        self._client_version = str(client_version or "")[:64]

    def check(self, raw_key: str) -> AccessResponse:
        import requests

        key = normalize_access_key(raw_key)
        try:
            response = requests.post(
                self._base_url + ACCESS_CHECK_PATH,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {key}",
                    "User-Agent": f"BonkScanner/{self._client_version or 'source'}",
                },
                json={"client_version": self._client_version},
                timeout=(4, 8),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SupporterAccessError("The supporter service could not be reached.") from exc

        if response.status_code == 429:
            try:
                retry_after = int(response.headers.get("Retry-After", "60"))
            except ValueError:
                retry_after = 60
            raise SupporterAccessRateLimited(retry_after)
        if response.status_code not in {200, 400, 401, 403}:
            raise SupporterAccessError(
                f"The supporter service returned HTTP {response.status_code}."
            )
        content = response.content
        if len(content) > _MAX_RESPONSE_BYTES:
            raise SupporterAccessError("The supporter service response was too large.")
        try:
            payload = json.loads(content)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupporterAccessError("The supporter service returned invalid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise SupporterAccessError("The supporter service response version is unsupported.")

        active = payload.get("active")
        status = payload.get("status")
        raw_features = payload.get("features")
        if not isinstance(active, bool) or status not in _KNOWN_STATUSES:
            raise SupporterAccessError("The supporter service returned an invalid access state.")
        if status in {"invalid", "missing_key"}:
            raise InvalidAccessKey("This supporter key was not recognized.")
        if not isinstance(raw_features, list) or len(raw_features) > 256:
            raise SupporterAccessError("The supporter service returned an invalid feature list.")
        features = []
        for feature in raw_features:
            if not isinstance(feature, str) or not _FEATURE_RE.fullmatch(feature):
                raise SupporterAccessError(
                    "The supporter service returned an invalid feature code."
                )
            features.append(feature)
        if active != status.startswith("active_"):
            raise SupporterAccessError("The supporter service returned a conflicting access state.")

        key_hint = payload.get("key_hint", "")
        if not isinstance(key_hint, str) or len(key_hint) > 32:
            raise SupporterAccessError("The supporter service returned an invalid key hint.")
        try:
            cache_seconds = int(payload.get("cache_seconds", 0))
        except (TypeError, ValueError) as exc:
            raise SupporterAccessError(
                "The supporter service returned an invalid cache interval."
            ) from exc
        cache_seconds = min(3600, max(60, cache_seconds))

        checked_at = _parse_timestamp(payload.get("checked_at"), required=True)
        assert checked_at is not None
        return AccessResponse(
            active=active,
            status=status,
            features=tuple(sorted(set(features))) if active else (),
            expires_at=_parse_timestamp(payload.get("expires_at")),
            next_change_at=_parse_timestamp(payload.get("next_change_at")),
            checked_at=checked_at,
            cache_seconds=cache_seconds,
            key_hint=key_hint,
        )
