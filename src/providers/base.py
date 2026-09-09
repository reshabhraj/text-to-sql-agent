"""The one interface every LLM provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """A provider call failed, described in one readable sentence."""


class LLMProvider(ABC):
    """Turns a prompt into SQL text. Implementations must not validate it."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider name, reported in results and in the eval output."""

    @abstractmethod
    def generate_sql(self, prompt: str) -> str:
        """Return the model's raw response text for prompt."""
