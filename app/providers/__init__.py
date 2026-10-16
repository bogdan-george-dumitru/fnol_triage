"""LLM provider abstraction.

Two implementations exist behind one interface:
  - OpenAIProvider: real OpenAI calls (gpt-5-mini + text-embedding-3-small).
  - MockProvider:   regex extraction + hashed char-trigram "embeddings".
                    Needs no API key, so the app, tests and eval always run;
                    it also serves as a non-LLM baseline in the eval.

`get_provider()` picks one based on configuration.
"""
from __future__ import annotations

from app.config import Settings, get_settings

from .base import LLMProvider


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the configured provider instance."""
    settings = settings or get_settings()
    if settings.using_openai():
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(settings)
    from .mock import MockProvider

    return MockProvider(settings)


__all__ = ["LLMProvider", "get_provider"]
