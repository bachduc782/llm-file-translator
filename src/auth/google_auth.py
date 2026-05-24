"""Google OAuth 2.0 authentication helpers."""

from __future__ import annotations

import os
import config


class _UrllibRequest:
    """google.auth transport.Request implementation using urllib — avoids requests SSL issues."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=60, **kwargs):
        import urllib.request as _ul
        from google.auth import exceptions as _ex

        req = _ul.Request(url, data=body, method=method.upper())
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with _ul.urlopen(req, timeout=timeout) as resp:
                return _UrllibResponse(resp.status, dict(resp.headers), resp.read())
        except Exception as exc:
            raise _ex.TransportError(str(exc)) from exc


class _UrllibResponse:
    def __init__(self, status, headers, data):
        self.status  = status
        self.headers = headers
        self.data    = data


def _load_credentials():
    """Load and refresh Google OAuth credentials from token file."""
    from google.oauth2.credentials import Credentials

    token_file = config.GOOGLE_TOKEN_FILE
    if not os.path.exists(token_file):
        raise RuntimeError(
            f"Google token not found at '{token_file}'. "
            "Run: python auth_setup.py"
        )

    creds = Credentials.from_authorized_user_file(token_file, config.GOOGLE_OAUTH_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(_UrllibRequest())
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def build_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_load_credentials(), cache_discovery=False)


def build_sheets_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_load_credentials(), cache_discovery=False)


def build_docs_service():
    from googleapiclient.discovery import build
    return build("docs", "v1", credentials=_load_credentials(), cache_discovery=False)
