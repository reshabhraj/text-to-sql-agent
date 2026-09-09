"""Google Gemini, through the AI Studio REST endpoint."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider, ProviderError
from .http import post_json

API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model

    @property
    def name(self) -> str:
        return "gemini"

    def generate_sql(self, prompt: str) -> str:
        data = post_json(
            API_URL_TEMPLATE.format(model=self._model),
            {"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            },
            "Gemini",
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned no candidate text.") from None
        # Reasoning models return their thinking as parts flagged "thought".
        # Only the visible answer is SQL.
        text = "".join(
            part["text"] for part in parts if "text" in part and not part.get("thought")
        )
        if not text.strip():
            raise ProviderError("Gemini returned an empty response.")
        return text
