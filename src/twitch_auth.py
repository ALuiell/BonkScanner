import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from dataclasses import dataclass
# `requests` is imported inside the three functions that call it, not here. It
# is the heaviest import in the application -- 14.7 MB and 346ms, measured --
# and every one of its uses is a network call the user has to ask for. At module
# scope it sat on the startup path, through `gui_twitch`.
import webbrowser
import secrets
from PySide6.QtCore import QThread, Signal

# Replace with the actual Twitch Application Client ID from the Developer Console.
# The app must have http://localhost:17846/auth/twitch/callback as a registered Redirect URI.
TWITCH_CLIENT_ID = "4tvblbz0dp1v9pgufiz3oaqg8vxphl"
OAUTH_PORT = 17846
REDIRECT_URI = f"http://localhost:{OAUTH_PORT}/auth/twitch/callback"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TWITCH_REVOKE_URL = "https://id.twitch.tv/oauth2/revoke"


@dataclass(slots=True)
class TwitchTokenValidationResult:
    valid: bool
    login: str = ""
    user_id: str = ""
    expires_in: int | None = None
    error_message: str = ""
    transient_error: bool = False


def validate_twitch_access_token(access_token: str, timeout: float = 5.0) -> TwitchTokenValidationResult:
    if not access_token:
        return TwitchTokenValidationResult(valid=False, error_message="Missing token.")

    import requests

    try:
        resp = requests.get(
            TWITCH_VALIDATE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return TwitchTokenValidationResult(
            valid=False,
            error_message=f"Token validation failed: {exc}",
            transient_error=True,
        )

    if resp.status_code == 200:
        try:
            data = resp.json()
        except (TypeError, ValueError) as exc:
            return TwitchTokenValidationResult(
                valid=False,
                error_message=f"Invalid Twitch validation response: {exc}",
                transient_error=True,
            )

        if not isinstance(data, dict):
            return TwitchTokenValidationResult(
                valid=False,
                error_message="Invalid Twitch validation response format.",
                transient_error=True,
            )

        login = str(data.get("login") or "").strip().lower()
        user_id = str(data.get("user_id") or "").strip()
        if not login or not user_id:
            return TwitchTokenValidationResult(
                valid=False,
                error_message="Incomplete Twitch validation response.",
                transient_error=True,
            )

        expires_in = data.get("expires_in")
        if isinstance(expires_in, bool):
            expires_in = None
        elif expires_in is not None:
            try:
                expires_in = int(expires_in)
            except (TypeError, ValueError):
                expires_in = None

        return TwitchTokenValidationResult(
            valid=True,
            login=login,
            user_id=user_id,
            expires_in=expires_in,
        )

    if resp.status_code == 401:
        return TwitchTokenValidationResult(valid=False, error_message="Token is no longer valid.")

    return TwitchTokenValidationResult(
        valid=False,
        error_message=f"Unexpected Twitch validation response: {resp.status_code}",
        transient_error=True,
    )


def revoke_twitch_access_token(access_token: str, timeout: float = 5.0) -> tuple[bool, str]:
    if not access_token:
        return True, ""

    import requests

    try:
        resp = requests.post(
            TWITCH_REVOKE_URL,
            data={"client_id": TWITCH_CLIENT_ID, "token": access_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, str(exc)

    if resp.status_code == 200:
        return True, ""
    if resp.status_code == 400:
        return True, "Token already invalid."
    return False, f"Twitch revoke failed with status {resp.status_code}."


AUTH_HTML = """
<!DOCTYPE html>
<html>
<head><title>Twitch Auth</title></head>
<body>
    <h2>Authorizing with Twitch...</h2>
    <p>Please wait...</p>
    <script>
        // The token is in the hash fragment, e.g. #access_token=...&scope=...
        const hash = window.location.hash.substring(1);
        const params = new URLSearchParams(hash);
        const accessToken = params.get('access_token');
        const state = params.get('state');
        
        if (accessToken) {
            fetch('/auth/twitch/token', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({access_token: accessToken, state: state})
            }).then(response => {
                if (!response.ok) throw new Error('Bad response');
                document.body.innerHTML = '<h2>Authorization Successful!</h2><p>You can close this window and return to BonkScanner.</p>';
            }).catch(err => {
                document.body.innerHTML = '<h2>Error communicating with local app.</h2>';
            });
        } else {
            document.body.innerHTML = '<h2>Authorization Failed.</h2><p>No token found in URL.</p>';
        }
    </script>
</body>
</html>
"""

class OAuthRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/auth/twitch/callback":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(AUTH_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/auth/twitch/token":
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                self.send_response(400)
                self.end_headers()
                return

            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return
            if content_length < 0:
                self.send_response(400)
                self.end_headers()
                return
            if content_length > 4096:
                self.send_response(400)
                self.end_headers()
                return

            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return

            access_token = data.get("access_token")
            state = data.get("state")
            
            if not self.server.auth_thread or state != getattr(self.server.auth_thread, "state", None):
                self.send_response(400)
                self.end_headers()
                return
            
            self.send_response(200)
            self.end_headers()
            
            if self.server.auth_thread:
                self.server.auth_thread.handle_token(access_token)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging


class TwitchAuthThread(QThread):
    auth_success = Signal(str, str)  # username, access_token
    auth_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.state = secrets.token_urlsafe(16)
        self.timeout_timer = None
        # Closing the app can race with QThread startup: at that moment there
        # is no HTTP server to shut down yet.  Keep the cancellation request
        # separately so `run` never begins serving after that close.
        self._shutdown_requested = threading.Event()
        self._server_lock = threading.Lock()

    def run(self):
        try:
            if self._shutdown_requested.is_set():
                return

            server = HTTPServer(("localhost", OAUTH_PORT), OAuthRequestHandler)
            server.auth_thread = self
            with self._server_lock:
                if self._shutdown_requested.is_set():
                    server.server_close()
                    return
                self.server = server
            
            self.timeout_timer = threading.Timer(120.0, self._handle_timeout)
            self.timeout_timer.daemon = True
            self.timeout_timer.start()

            if self._shutdown_requested.is_set():
                server.server_close()
                with self._server_lock:
                    if self.server is server:
                        self.server = None
                return
            
            # Open browser
            auth_url = (
                "https://id.twitch.tv/oauth2/authorize"
                "?response_type=token"
                f"&client_id={TWITCH_CLIENT_ID}"
                f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
                "&scope=chat:read+chat:edit"
                f"&state={self.state}"
            )
            webbrowser.open(auth_url)
            
            # Do not use `serve_forever` here. `HTTPServer.shutdown()` waits
            # for that loop to begin, which leaves a race when the app closes
            # between thread startup and the call itself. A short request
            # timeout lets this QThread observe cancellation in either state.
            server.timeout = 0.2
            while not self._shutdown_requested.is_set():
                server.handle_request()
        except Exception as e:
            if not self._shutdown_requested.is_set():
                self.auth_error.emit(str(e))
        finally:
            with self._server_lock:
                server = self.server
                self.server = None
            if server is not None:
                try:
                    server.server_close()
                except Exception:
                    pass

    def _handle_timeout(self):
        self.auth_error.emit("Authorization timed out after 2 minutes.")
        self._shutdown_server()

    def handle_token(self, access_token):
        if self.timeout_timer:
            self.timeout_timer.cancel()
            
        if not access_token:
            self.auth_error.emit("Received empty token.")
            self._shutdown_server()
            return
            
        # Fetch username using the token
        import requests

        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Client-Id": TWITCH_CLIENT_ID
            }
            resp = requests.get("https://api.twitch.tv/helix/users", headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and len(data["data"]) > 0:
                    username = data["data"][0]["login"]
                    self.auth_success.emit(username, access_token)
                else:
                    self.auth_error.emit("Failed to retrieve user data from Twitch.")
            else:
                self.auth_error.emit(f"Twitch API error: {resp.status_code}")
        except Exception as e:
            self.auth_error.emit(f"Error fetching user data: {str(e)}")
            
        self._shutdown_server()

    def _shutdown_server(self):
        self._shutdown_requested.set()
        if self.timeout_timer:
            self.timeout_timer.cancel()
