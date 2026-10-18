"""NordTrace configuration (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Norwegian registry ---
    brreg_base_url: str = "https://data.brreg.no/enhetsregisteret/api"
    brreg_regnskap_url: str = "https://data.brreg.no/regnskapsregisteret/regnskap"
    brreg_timeout: float = 20.0
    brreg_branch_page_size: int = Field(default=20, ge=1, le=100)
    brreg_branch_max_pages: int = Field(default=10, ge=1, le=100)

    # Legacy model settings retained for config compatibility only. No provider
    # is implemented; these defaults are not verified provider price quotes.
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 30.0
    llm_max_cost_usd: float = 10.0
    # Price table per 1M tokens (USD). Configurable because pricing changes.
    llm_price_input_per_m: float = 0.15
    llm_price_output_per_m: float = 0.60

    # --- Configurable local limits; official run allowances must be supplied ---
    max_requests: int = 2000
    max_runtime_sec: int = 45 * 60
    max_api_cost_usd: float = 10.0
    per_company_soft_deadline_sec: float = 90.0
    finalization_reserve_sec: float = Field(default=0.0, ge=0)

    # --- Crawler limits ---
    max_pages_per_company: int = 8
    max_response_bytes: int = 5 * 1024 * 1024  # 5 MiB
    max_pdf_bytes: int = 20 * 1024 * 1024  # 20 MiB
    max_redirects: int = 5
    crawl_timeout: float = 15.0
    respect_robots: bool = True

    # --- Persistence ---
    data_dir: str = Field(default_factory=lambda: str(Path.cwd() / "data"))
    database_path: str = ""

    @model_validator(mode="after")
    def derive_database_path(self) -> Settings:
        if not self.database_path:
            self.database_path = str(Path(self.data_dir) / "nordtrace.db")
        return self

    @model_validator(mode="after")
    def enforce_public_source_policy(self) -> Settings:
        if not self.respect_robots:
            raise ValueError("robots policy cannot be disabled for public website/PDF acquisition")
        return self

    # --- HTTP identity ---
    user_agent: str = "NordTrace/1.0 (Norwegian company research agent; research use; contact via repository)"

    # --- Logging ---
    log_level: str = "INFO"


settings = Settings()
