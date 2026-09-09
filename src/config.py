"""Configuration loaded from the environment.

Every setting has a default that works with no .env file at all, so tests and
CI can run the mock provider without any API key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROVIDERS = ("mock", "groq", "gemini", "anthropic")
DEFAULT_PROVIDER = "mock"
DEFAULT_DATABASE_PATH = "data/sample.db"
DEFAULT_ROW_LIMIT = 500
DEFAULT_QUERY_TIMEOUT_SECONDS = 10

ROOT = Path(__file__).resolve().parent.parent

# The environment variable holding the key for each provider that needs one.
# The mock provider is absent on purpose: it never needs a key.
KEY_VARS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

MODEL_VARS = {
    "groq": "GROQ_MODEL",
    "gemini": "GEMINI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
}


class ConfigError(Exception):
    """A configuration problem worth one clear sentence, not a stack trace."""


@dataclass(frozen=True)
class Settings:
    provider: str
    groq_api_key: str
    groq_model: str
    gemini_api_key: str
    gemini_model: str
    anthropic_api_key: str
    anthropic_model: str
    database_url: str
    database_path: Path
    row_limit: int
    query_timeout_seconds: int

    @property
    def uses_postgres(self) -> bool:
        return bool(self.database_url)

    @property
    def api_key(self) -> str:
        """The key for the active provider. Empty string for the mock."""
        return getattr(self, f"{self.provider}_api_key", "")

    @property
    def model(self) -> str:
        """The model name for the active provider. Empty string for the mock."""
        return getattr(self, f"{self.provider}_model", "")


def _env(name: str, default: str = "") -> str:
    """Read a variable, treating an empty or whitespace value as unset."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got '{raw}'.") from None


def load_settings(provider_override: str | None = None) -> Settings:
    """Build Settings from .env and the environment.

    The provider is resolved first, with provider_override (the --provider flag)
    winning over LLM_PROVIDER, and only that provider's key is then required.
    So LLM_PROVIDER=groq with no key plus --provider mock is not an error.
    """
    load_dotenv()

    provider = (provider_override or _env("LLM_PROVIDER") or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise ConfigError(
            f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}."
        )

    database_path = Path(_env("DATABASE_PATH", DEFAULT_DATABASE_PATH))
    if not database_path.is_absolute():
        database_path = ROOT / database_path

    settings = Settings(
        provider=provider,
        groq_api_key=_env("GROQ_API_KEY"),
        groq_model=_env("GROQ_MODEL"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL"),
        database_url=_env("DATABASE_URL"),
        database_path=database_path,
        row_limit=_env_int("ROW_LIMIT", DEFAULT_ROW_LIMIT),
        query_timeout_seconds=_env_int("QUERY_TIMEOUT_SECONDS", DEFAULT_QUERY_TIMEOUT_SECONDS),
    )

    key_var = KEY_VARS.get(provider)
    if key_var and not settings.api_key:
        raise ConfigError(
            f"{key_var} is not set. Add it to .env or choose LLM_PROVIDER=mock."
        )
    model_var = MODEL_VARS.get(provider)
    if model_var and not settings.model:
        raise ConfigError(
            f"{model_var} is not set. Copy the default from .env.example into .env."
        )
    return settings
