"""Anthropic, through the Messages API.

Optional. The repository ships it for anyone who has a key. The free-tier
providers are Groq and Gemini.
"""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider, ProviderError
from .http import post_json

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Room for the answer even when the model thinks first. This is a ceiling,
# not a spend: billing follows the tokens actually produced.
MAX_TOKENS = 8192


class AnthropicProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model

    @property
    def name(self) -> str:
        return "anthropic"

    def generate_sql(self, prompt: str) -> str:
        # No temperature here, unlike the Groq and Gemini providers. Current
        # Claude models removed the sampling parameters, and sending
        # temperature to one of them is rejected with HTTP 400. The thinking
        # parameter is left out for the same reason: its accepted values differ
        # between model generations, and omitting it works on all of them.
        data = post_json(
            API_URL,
            {
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            {
                "model": self._model,
                "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            "Anthropic",
        )
        if data.get("stop_reason") == "refusal":
            raise ProviderError("Anthropic declined to answer this prompt.")
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("Anthropic returned no content blocks.")
        # Skip thinking blocks: only the visible text blocks carry the SQL.
        text = "".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        )
        if not text.strip():
            raise ProviderError("Anthropic returned an empty response.")
        return text
