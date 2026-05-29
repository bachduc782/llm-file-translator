from __future__ import annotations

import os
import ssl
from dotenv import load_dotenv

load_dotenv()

# requestsのSSLコンテキストを早期にパッチ — Python 3.14のUNEXPECTED_EOFを回避
def _patch_requests_ssl():
    try:
        import requests
        from requests.adapters import HTTPAdapter

        class _TLSAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                ctx = ssl.create_default_context()
                if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
                    ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
                try:
                    import certifi
                    ctx.load_verify_locations(certifi.where())
                except ImportError:
                    pass
                kwargs["ssl_context"] = ctx
                super().init_poolmanager(*args, **kwargs)

        _orig = requests.Session.__init__

        def _patched(self):
            _orig(self)
            self.mount("https://", _TLSAdapter())

        requests.Session.__init__ = _patched
    except Exception:
        pass

_patch_requests_ssl()

# ── プロバイダー定義 ──────────────────────────────────────────────────────────

PROVIDERS = {
    "openrouter": {
        "label":      "OpenRouter",
        "base_url":   "https://openrouter.ai/api/v1",
        "headers":    {
            "HTTP-Referer": "https://llm-file-translator",
            "X-Title":      "LLM File Translator",
        },
        "default_model": "google/gemini-2.0-flash-exp:free",
        "models": [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "deepseek/deepseek-chat:free",
        ],
        "rate_limit": 20,   # req/min — 無料枠向けの保守値
    },
    "nvidia": {
        "label":      "NVIDIA NIM",
        "base_url":   "https://integrate.api.nvidia.com/v1",
        "headers":    {},
        "default_model": "meta/llama-3.1-70b-instruct",
        "models": [
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "nvidia/nemotron-4-340b-instruct",
            "mistralai/mistral-7b-instruct-v0.3",
            "microsoft/phi-3-mini-128k-instruct",
        ],
        "rate_limit": 40,   # req/min
    },
}

# ── アクティブプロバイダー状態（実行時切替可能）────────────────────────────

_active_provider: str = os.environ.get("PROVIDER", "openrouter")
_api_keys: dict[str, str] = {
    "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
    "nvidia":     os.environ.get("NVIDIA_API_KEY", ""),
}
_models: dict[str, str] = {
    "openrouter": os.environ.get("OPENROUTER_MODEL", PROVIDERS["openrouter"]["default_model"]),
    "nvidia":     os.environ.get("NVIDIA_MODEL",     PROVIDERS["nvidia"]["default_model"]),
}


def get_active_provider() -> str:
    return _active_provider


def set_active_provider(provider: str) -> None:
    global _active_provider
    assert provider in PROVIDERS, f"Unknown provider: {provider}"
    _active_provider = provider


def get_api_key(provider: str | None = None) -> str:
    return _api_keys.get(provider or _active_provider, "")


def set_api_key(provider: str, key: str) -> None:
    _api_keys[provider] = key


def get_model(provider: str | None = None) -> str:
    return _models.get(provider or _active_provider, "")


def set_model(provider: str, model: str) -> None:
    _models[provider] = model


def get_llm_config() -> dict:
    """アクティブプロバイダーのLLM接続設定を返す。"""
    p    = _active_provider
    info = PROVIDERS[p]
    return {
        "base_url":   info["base_url"],
        "api_key":    _api_keys.get(p) or "none",
        "model":      _models.get(p) or info["default_model"],
        "headers":    info["headers"],
        "rate_limit": info.get("rate_limit", 20),
    }


def save_to_env() -> None:
    """現在のプロバイダー設定を.envファイルに保存する。"""
    env_path = ".env"
    try:
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    def _set(key: str, value: str) -> None:
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                lines[i] = f"{key}={value}\n"
                return
        lines.append(f"{key}={value}\n")

    _set("PROVIDER",          _active_provider)
    _set("OPENROUTER_API_KEY", _api_keys.get("openrouter", ""))
    _set("OPENROUTER_MODEL",   _models.get("openrouter", ""))
    _set("NVIDIA_API_KEY",     _api_keys.get("nvidia", ""))
    _set("NVIDIA_MODEL",       _models.get("nvidia", ""))

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


# Google OAuth設定
GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "config/google_credentials.json")
GOOGLE_TOKEN_FILE        = os.environ.get("GOOGLE_TOKEN_FILE",        "config/google_token.json")
GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]
