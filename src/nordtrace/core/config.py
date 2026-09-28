from __future__ import annotations

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Registry
    brreg_api_url: str = "https://data.brreg.no/enhetsregisteret/api/enheter"
    brreg_timeout: int = 30

    # LLM / AI
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_max_cost_usd: float = 10.0
    llm_max_tokens: int = 4000

    # Runtime / Scale
    max_requests: int = 2000
    max_runtime_min: int = 45
    max_companies_batch: int = 100

    # Cache / DB
    cache_dir: str = "./cache"
    database_url: str = "sqlite:///nordtrace.db"

    # Logging
    log_level: str = "INFO"

    # Web / Security
    user_agent: str = "NordTrace/1.0"
    allowed_domains: Optional[str] = None


settings = Settings()
