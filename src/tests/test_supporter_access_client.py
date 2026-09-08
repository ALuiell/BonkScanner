from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from infra.supporter_access_client import (
    InvalidAccessKey,
    SupporterAccessClient,
    SupporterAccessError,
    SupporterAccessRateLimited,
    masked_access_key,
)


RAW_KEY = "BSK_AAAAAAAA_BBBBBBBB_CCCCCCCC_DDDDDDDD"


class SupporterAccessClientTests(unittest.TestCase):
    def response(self, payload, *, status=200, headers=None):
        response = Mock()
        response.status_code = status
        response.content = json.dumps(payload).encode("utf-8")
        response.headers = headers or {}
        return response

    def test_active_response_is_validated_and_minimized(self):
        payload = {
            "schema_version": 1,
            "active": True,
            "status": "active_subscription",
            "features": ["native_hook", "native_hook"],
            "expires_at": "2026-10-01T10:00:00Z",
            "next_change_at": "2026-10-01T10:00:00Z",
            "checked_at": "2026-09-08T10:00:00Z",
            "cache_seconds": 900,
            "key_hint": masked_access_key(RAW_KEY),
        }
        client = SupporterAccessClient("http://127.0.0.1:8000", client_version="3.1")

        with patch("requests.post", return_value=self.response(payload)) as post:
            result = client.check(RAW_KEY.lower())

        self.assertTrue(result.active)
        self.assertEqual(result.features, ("native_hook",))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], f"Bearer {RAW_KEY}")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_invalid_key_and_rate_limit_are_distinct(self):
        client = SupporterAccessClient("https://example.com", client_version="3.1")
        invalid = {
            "schema_version": 1,
            "active": False,
            "status": "invalid",
            "features": [],
        }
        with patch("requests.post", return_value=self.response(invalid, status=401)):
            with self.assertRaises(InvalidAccessKey):
                client.check(RAW_KEY)

        with patch(
            "requests.post",
            return_value=self.response({}, status=429, headers={"Retry-After": "75"}),
        ):
            with self.assertRaises(SupporterAccessRateLimited) as raised:
                client.check(RAW_KEY)
        self.assertEqual(raised.exception.retry_after, 75)

    def test_only_https_or_local_development_http_is_accepted(self):
        with self.assertRaises(SupporterAccessError):
            SupporterAccessClient("http://example.com", client_version="3.1")
        SupporterAccessClient("http://localhost:8000", client_version="3.1")

    def test_malformed_contract_is_rejected(self):
        client = SupporterAccessClient("https://example.com", client_version="3.1")
        payload = {
            "schema_version": 1,
            "active": True,
            "status": "active_subscription",
            "features": ["Not A Slug"],
            "checked_at": "2026-09-08T10:00:00Z",
            "cache_seconds": 900,
            "key_hint": "",
        }
        with patch("requests.post", return_value=self.response(payload)):
            with self.assertRaises(SupporterAccessError):
                client.check(RAW_KEY)


if __name__ == "__main__":
    unittest.main()
