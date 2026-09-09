"""Provider selection.

Providers are imported lazily and looked up by name, so adding one is a matter
of dropping in a module: nothing here changes. It also means the mock path
never imports a network library and never needs an API key.
"""

from __future__ import annotations

import importlib

from ..config import ConfigError, Settings
from .base import LLMProvider, ProviderError

__all__ = ["LLMProvider", "ProviderError", "get_provider"]

# provider name -> (module inside this package, class to instantiate)
PROVIDER_CLASSES = {
    "mock": ("mock_provider", "MockProvider"),
    "groq": ("groq_provider", "GroqProvider"),
    "gemini": ("gemini_provider", "GeminiProvider"),
    "anthropic": ("anthropic_provider", "AnthropicProvider"),
}


def get_provider(settings: Settings) -> LLMProvider:
    """Build the provider named by settings. Its key was checked at load time."""
    try:
        module_name, class_name = PROVIDER_CLASSES[settings.provider]
    except KeyError:
        raise ConfigError(f"Unknown provider '{settings.provider}'.") from None
    try:
        module = importlib.import_module(f".{module_name}", __package__)
    except ImportError as exc:
        raise ConfigError(
            f"Provider '{settings.provider}' could not be loaded ({exc}). "
            "Run: pip install -r requirements.txt"
        ) from None
    return getattr(module, class_name)(settings)
