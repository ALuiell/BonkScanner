import src

import unittest
from unittest.mock import MagicMock, patch

import twitch_auth


class TwitchAuthTests(unittest.TestCase):
    def test_validate_token_parses_valid_response(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "login": "BonkBot",
            "user_id": "123",
            "expires_in": "3600",
        }

        with patch.object(twitch_auth.requests, "get", return_value=response) as request:
            result = twitch_auth.validate_twitch_access_token("token")

        self.assertTrue(result.valid)
        self.assertEqual(result.login, "bonkbot")
        self.assertEqual(result.user_id, "123")
        self.assertEqual(result.expires_in, 3600)
        request.assert_called_once()

    def test_validate_token_treats_malformed_json_as_transient_error(self) -> None:
        response = MagicMock(status_code=200)
        response.json.side_effect = ValueError("invalid json")

        with patch.object(twitch_auth.requests, "get", return_value=response):
            result = twitch_auth.validate_twitch_access_token("token")

        self.assertFalse(result.valid)
        self.assertTrue(result.transient_error)
        self.assertIn("Invalid Twitch validation response", result.error_message)

    def test_validate_token_rejects_incomplete_success_response(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"login": "bonkbot"}

        with patch.object(twitch_auth.requests, "get", return_value=response):
            result = twitch_auth.validate_twitch_access_token("token")

        self.assertFalse(result.valid)
        self.assertTrue(result.transient_error)

    def test_validate_token_marks_request_errors_transient(self) -> None:
        with patch.object(
            twitch_auth.requests,
            "get",
            side_effect=twitch_auth.requests.RequestException("offline"),
        ):
            result = twitch_auth.validate_twitch_access_token("token")

        self.assertFalse(result.valid)
        self.assertTrue(result.transient_error)

    def test_revoke_accepts_already_invalid_token(self) -> None:
        response = MagicMock(status_code=400)

        with patch.object(twitch_auth.requests, "post", return_value=response) as request:
            revoked, message = twitch_auth.revoke_twitch_access_token("token")

        self.assertTrue(revoked)
        self.assertEqual(message, "Token already invalid.")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
