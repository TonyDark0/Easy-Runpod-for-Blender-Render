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


def authorize(path):
    client = json.loads(Path(path).read_text(encoding="utf-8"))["installed"]
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
                      response_type="code", scope="https://www.googleapis.com/auth/drive.file",
                      access_type="offline", prompt="consent", state=state,
                      code_challenge=challenge, code_challenge_method="S256")
        webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
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
    return dict(client_id=client["client_id"], client_secret=client["client_secret"],
                refresh_token=token["refresh_token"])
