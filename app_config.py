"""Standalone config module — stores settings in %APPDATA%\\LLM-Translator\\settings.json."""

from __future__ import annotations
import json
import os

PROVIDERS: dict = {
    "openrouter": {
        "label":         "OpenRouter",
        "base_url":      "https://openrouter.ai/api/v1",
        "headers":       {"HTTP-Referer": "https://llm-file-translator", "X-Title": "LLM File Translator"},
        "default_model": "google/gemini-2.0-flash-exp:free",
        "models": [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "deepseek/deepseek-chat:free",
        ],
        "rate_limit": 20,
    },
    "nvidia": {
        "label":         "NVIDIA NIM",
        "base_url":      "https://integrate.api.nvidia.com/v1",
        "headers":       {},
        "default_model": "meta/llama-3.1-70b-instruct",
        "models": [
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "nvidia/nemotron-4-340b-instruct",
            "mistralai/mistral-7b-instruct-v0.3",
        ],
        "rate_limit": 40,
    },
}


def _config_dir() -> str:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    d = os.path.join(base, "LLM-Translator")
    os.makedirs(d, exist_ok=True)
    return d


def _config_file() -> str:
    return os.path.join(_config_dir(), "settings.json")


def _load() -> dict:
    try:
        with open(_config_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_cfg: dict = _load()


def get_active_provider() -> str:
    return _cfg.get("provider", "openrouter")


def set_active_provider(p: str) -> None:
    _cfg["provider"] = p


def get_api_key(provider: str | None = None) -> str:
    return _cfg.get("api_keys", {}).get(provider or get_active_provider(), "")


def set_api_key(provider: str, key: str) -> None:
    _cfg.setdefault("api_keys", {})[provider] = key


def get_model(provider: str | None = None) -> str:
    p = provider or get_active_provider()
    return _cfg.get("models", {}).get(p, PROVIDERS[p]["default_model"])


def set_model(provider: str, model: str) -> None:
    _cfg.setdefault("models", {})[provider] = model


def save() -> None:
    with open(_config_file(), "w", encoding="utf-8") as f:
        json.dump(_cfg, f, indent=2, ensure_ascii=False)


def get_llm_config() -> dict:
    p    = get_active_provider()
    info = PROVIDERS[p]
    return {
        "base_url":   info["base_url"],
        "api_key":    get_api_key(p) or "none",
        "model":      get_model(p),
        "headers":    info["headers"],
        "rate_limit": info.get("rate_limit", 20),
    }


def log_dir() -> str:
    d = os.path.join(_config_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d
