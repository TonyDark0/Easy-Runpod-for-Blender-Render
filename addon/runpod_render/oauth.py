import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from .transport import request

SCOPE = "https://www.googleapis.com/auth/drive.file"


def load_client(path=""):
    source = Path(path) if path else Path(__file__).with_name("google_client.json")
    if not source.is_file():
        raise ValueError("Public Google sign-in is not configured in this build. "
                         "Use your Desktop OAuth JSON in Advanced for testing.")
    client = json.loads(source.read_text(encoding="utf-8")).get("installed", {})
    if not client.get("client_id", "").endswith(".apps.googleusercontent.com") or not client.get("client_secret"):
        raise ValueError("Select a Google OAuth client of type Desktop app")
    return client


def authorize(path="", cancel=None):
    client = load_client(path)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            parts = urlsplit(self.path)
            args = parse_qs(parts.query)
            if parts.path != "/" or args.get("state") != [state]:
                self.send_error(400)
                return
            result.update(args)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Return to Blender to check the connection.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/"
        params = dict(client_id=client["client_id"], redirect_uri=redirect,
                      response_type="code", scope=SCOPE,
                      access_type="offline", prompt="consent", state=state,
                      code_challenge=challenge, code_challenge_method="S256")
        webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Google sign-in cancelled")
            server.handle_request()
    if "code" not in result:
        raise RuntimeError("Google authorization was denied or timed out")
    form = dict(client_id=client["client_id"], client_secret=client["client_secret"],
                redirect_uri=redirect, code_verifier=verifier, code=result["code"][0],
                grant_type="authorization_code")
    with request("https://oauth2.googleapis.com/token", method="POST",
                 data=urlencode(form).encode(),
                 headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
        token = json.load(response)
    if "refresh_token" not in token:
        raise RuntimeError("Google did not grant offline access. Reconnect Google Drive.")
    return dict(client_id=client["client_id"], client_secret=client["client_secret"],
                refresh_token=token["refresh_token"])
