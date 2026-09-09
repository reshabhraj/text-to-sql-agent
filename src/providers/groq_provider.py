"""Groq, through its OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider, ProviderError
from .http import post_json

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model

    @property
    def name(self) -> str:
        return "groq"

    def generate_sql(self, prompt: str) -> str:
        data = post_json(
            API_URL,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self._model,
                # Lowest temperature the endpoint accepts: the same question
                # should produce the same SQL run to run.
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            "Groq",
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Groq returned no completion text.") from None
