"""Application configuration, loaded from environment / .env.

Everything the brief says should be configurable lives here. Defaults are chosen
so the app runs with no API key and no cost (mock provider).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider selection -----------------------------------------------------
    # "mock"   -> regex extraction + hashed-trigram embeddings, no API key, free.
    # "openai" -> real OpenAI calls (costs money; requires OPENAI_API_KEY).
    llm_provider: str = "mock"
    openai_api_key: str | None = None

    # Models (only used by the openai provider) ------------------------------
    extraction_model: str = "gpt-5-mini"
    matching_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"

    # Storage paths ----------------------------------------------------------
    db_path: str = "data/app.db"
    uploads_dir: str = "data/uploads"

    # Behaviour --------------------------------------------------------------
    request_timeout_s: float = 60.0
    log_level: str = "INFO"

    # Cost estimation (USD per 1M tokens). Defaults are rough gpt-5-mini figures;
    # set to your real rates in .env. Only used to estimate per-document cost.
    openai_input_cost_per_1m: float = 0.25
    openai_output_cost_per_1m: float = 2.00

    def using_openai(self) -> bool:
        return self.llm_provider.lower() == "openai"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
