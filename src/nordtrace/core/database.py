from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from nordtrace.core.config import settings

DB_PATH = Path(settings.cache_dir) / "nordtrace.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            url TEXT,
            domain TEXT,
            source_type TEXT,
            authority_tier INTEGER,
            retrieved_at TEXT,
            published_at TEXT,
            http_status INTEGER,
            content_hash TEXT,
            access_status TEXT,
            raw_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            fact_id TEXT PRIMARY KEY,
            company_org_number TEXT,
            category TEXT,
            field TEXT,
            value_json TEXT,
            normalized_value_json TEXT,
            unit TEXT,
            currency TEXT,
            valid_from TEXT,
            valid_to TEXT,
            reporting_period TEXT,
            source_id TEXT,
            evidence_id TEXT,
            retrieved_at TEXT,
            published_at TEXT,
            entity_confidence TEXT,
            fact_confidence REAL,
            status TEXT,
            conflict_note TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT,
            url TEXT,
            source_title TEXT,
            source_type TEXT,
            retrieved_at TEXT,
            published_at TEXT,
            evidence_text TEXT,
            page_section TEXT,
            content_hash TEXT,
            entity_match_details_json TEXT,
            entity_confidence TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            profile_id TEXT PRIMARY KEY,
            organisation_number TEXT UNIQUE,
            profile_json TEXT,
            last_researched_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            completed_at TEXT,
            status TEXT,
            request_count INTEGER,
            estimated_cost_usd REAL,
            companies_json TEXT,
            terminal_states_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS changes (
            change_id TEXT PRIMARY KEY,
            run_id TEXT,
            company_org_number TEXT,
            change_type TEXT,
            field TEXT,
            previous_value_json TEXT,
            current_value_json TEXT,
            previous_source_id TEXT,
            current_source_id TEXT,
            detected_at TEXT,
            explanation TEXT
        )
    """)
    conn.commit()
    conn.close()
