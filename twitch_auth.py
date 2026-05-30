import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import requests
import webbrowser
import secrets
from PySide6.QtCore import QObject, QThread, Signal

# Replace with the actual Twitch Application Client ID from the Developer Console.
# The app must have http://localhost:17846/auth/twitch/callback as a registered Redirect URI.
TWITCH_CLIENT_ID = "4tvblbz0dp1v9pgufiz3oaqg8vxphl"
OAUTH_PORT = 17846
REDIRECT_URI = f"http://localhost:{OAUTH_PORT}/auth/twitch/callback"


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
        if self.path.startswith("/auth/twitch/callback"):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(AUTH_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/auth/twitch/token":
            content_length = int(self.headers.get("Content-Length", 0))
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

    def run(self):
        try:
            self.server = HTTPServer(("localhost", OAUTH_PORT), OAuthRequestHandler)
            self.server.auth_thread = self
            
            self.timeout_timer = threading.Timer(120.0, self._handle_timeout)
            self.timeout_timer.daemon = True
            self.timeout_timer.start()
            
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
            
            # Run server to wait for callback
            self.server.serve_forever()
        except Exception as e:
            self.auth_error.emit(str(e))

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
        if self.timeout_timer:
            self.timeout_timer.cancel()
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            self.server = None
