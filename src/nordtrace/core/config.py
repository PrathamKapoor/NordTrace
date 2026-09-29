"""NordTrace configuration (pydantic-settings)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(APP_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Norwegian registry ---
    brreg_base_url: str = "https://data.brreg.no/enhetsregisteret/api"
    brreg_regnskap_url: str = "https://data.brreg.no/regnskapsregisteret/regnskap"
    brreg_timeout: float = 20.0

    # --- NAV jobs ---
    nav_job_search_url: str = "https://arbeidsplassen.nav.no/stillinger/api/search"

    # --- LLM (optional; system degrades to deterministic extraction without a key) ---
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 30.0
    llm_max_cost_usd: float = 10.0
    # Price table per 1M tokens (USD). Configurable because pricing changes.
    llm_price_input_per_m: float = 0.15
    llm_price_output_per_m: float = 0.60

    # --- Budgets (challenge limits) ---
    max_requests: int = 2000
    max_runtime_sec: int = 45 * 60
    max_api_cost_usd: float = 10.0
    per_company_soft_deadline_sec: float = 90.0

    # --- Crawler limits ---
    max_pages_per_company: int = 8
    max_response_bytes: int = 5 * 1024 * 1024  # 5 MiB
    max_pdf_bytes: int = 20 * 1024 * 1024      # 20 MiB
    max_redirects: int = 5
    crawl_timeout: float = 15.0
    respect_robots: bool = True

    # --- Persistence ---
    data_dir: str = str(APP_ROOT / "data")
    database_path: str = str(APP_ROOT / "data" / "nordtrace.db")

    # --- HTTP identity ---
    user_agent: str = (
        "NordTrace/1.0 (Norwegian company research agent; "
        "research use; contact via repository)"
    )

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def is_live_llm_configured(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
