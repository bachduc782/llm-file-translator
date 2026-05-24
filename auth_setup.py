"""Google OAuth 2.0 setup — custom flow using urllib to bypass requests SSL issues on Python 3.14."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import config


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _pkce_pair() -> tuple[str, str]:
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


# ── Local callback server ─────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    code:  str | None = None
    error: str | None = None

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.code  = params.get("code",  [None])[0]
        _Handler.error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<h2>The authentication flow has completed. You may close this window.</h2>"
        )
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *_):
        pass


# ── Token exchange (pure urllib — no requests) ────────────────────────────────

def _exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    body = urllib.parse.urlencode({
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cred_file  = config.GOOGLE_CREDENTIALS_FILE
    token_file = config.GOOGLE_TOKEN_FILE

    if not os.path.exists(cred_file):
        print(f"ERROR: credentials file not found at '{cred_file}'")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        return

    with open(cred_file, encoding="utf-8") as f:
        raw = json.load(f)

    info          = raw.get("installed") or raw.get("web")
    client_id     = info["client_id"]
    client_secret = info["client_secret"]

    # Start local callback server on random port
    server   = HTTPServer(("localhost", 0), _Handler)
    port     = server.server_address[1]
    redirect = f"http://localhost:{port}/"

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode({
            "response_type":         "code",
            "client_id":             client_id,
            "redirect_uri":          redirect,
            "scope":                 " ".join(config.GOOGLE_OAUTH_SCOPES),
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
            "access_type":           "offline",
        })
    )

    print(f"\nPlease visit this URL to authorize this application:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server.serve_forever()  # blocks until _Handler shuts it down

    if _Handler.error:
        print(f"ERROR: Authorization failed: {_Handler.error}")
        return
    if not _Handler.code:
        print("ERROR: No authorization code received.")
        return

    print("Exchanging authorization code for token...")
    try:
        token_data = _exchange_code(client_id, client_secret, _Handler.code, redirect, code_verifier)
    except Exception as e:
        print(f"ERROR: Token exchange failed: {e}")
        return

    # Save in format compatible with google.oauth2.credentials.Credentials.from_authorized_user_file
    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({
            "token":         token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_uri":     "https://oauth2.googleapis.com/token",
            "client_id":     client_id,
            "client_secret": client_secret,
            "scopes":        config.GOOGLE_OAUTH_SCOPES,
        }, f, indent=2)

    print(f"Authentication successful! Token saved to '{token_file}'")


if __name__ == "__main__":
    main()
