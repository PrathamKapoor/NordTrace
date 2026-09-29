"""SQLite persistence layer.

Schema (FK-enforced, WAL mode):
  runs        → research runs
  companies   → canonical identities (one row per orgnr)
  sources     → retrieved documents (FK → runs, companies)
  evidence    → snippets supporting facts (FK → sources)
  facts       → the fact ledger (FK → companies, sources, evidence)
  changes     → fact-level diffs (FK → runs, companies)
  trace       → research trace events (FK → runs)
  snapshots   → source content snapshots by hash

All writes are transactional. The fact ledger is the source of truth.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from nordtrace.core.models import (
    ChangeRecord,
    CompanyIdentity,
    CompanyProfile,
    Coverage,
    EvidenceRecord,
    Fact,
    FactStatus,
    ResearchMetadata,
    ResearchRun,
    RunState,
    SourceRecord,
    TraceEvent,
    utcnow,
)

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT,
    completed_at    TEXT,
    state           TEXT NOT NULL DEFAULT 'running',
    request_count   INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    companies_json  TEXT NOT NULL DEFAULT '[]',
    company_states_json TEXT NOT NULL DEFAULT '{}',
    requested_by    TEXT NOT NULL DEFAULT 'cli',
    budget_json     TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    org_number      TEXT PRIMARY KEY,
    legal_name      TEXT NOT NULL,
    identity_json   TEXT NOT NULL,
    first_seen_run  TEXT,
    last_verified_at TEXT,
    last_run_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(legal_name);

CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    org_number      TEXT NOT NULL REFERENCES companies(org_number) ON DELETE CASCADE,
    url             TEXT,
    domain          TEXT,
    source_type     TEXT NOT NULL,
    authority_tier  INTEGER NOT NULL,
    title           TEXT,
    retrieved_at    TEXT,
    published_at    TEXT,
    http_status     INTEGER,
    content_hash    TEXT,
    access_status   TEXT NOT NULL,
    error_detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_run ON sources(run_id);
CREATE INDEX IF NOT EXISTS idx_sources_org ON sources(org_number);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    url             TEXT,
    source_title    TEXT,
    source_type     TEXT,
    authority_tier  INTEGER NOT NULL DEFAULT 4,
    retrieved_at    TEXT,
    published_at    TEXT,
    evidence_text   TEXT,
    page_or_section TEXT,
    content_hash    TEXT,
    entity_match_details TEXT NOT NULL DEFAULT '{}',
    entity_verdict  TEXT NOT NULL,
    org_number      TEXT NOT NULL REFERENCES companies(org_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_org ON evidence(org_number);

CREATE TABLE IF NOT EXISTS facts (
    fact_id         TEXT PRIMARY KEY,
    org_number      TEXT NOT NULL REFERENCES companies(org_number) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    field           TEXT NOT NULL,
    value_json      TEXT,
    normalized_value_json TEXT,
    unit            TEXT,
    currency        TEXT,
    valid_from      TEXT,
    valid_to        TEXT,
    reporting_period TEXT,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    evidence_id     TEXT NOT NULL REFERENCES evidence(evidence_id),
    retrieved_at    TEXT,
    published_at    TEXT,
    entity_verdict  TEXT NOT NULL,
    fact_confidence REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL,
    conflict_note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_facts_org ON facts(org_number);
CREATE INDEX IF NOT EXISTS idx_facts_run ON facts(run_id);
CREATE INDEX IF NOT EXISTS idx_facts_slot ON facts(org_number, category, field, reporting_period);

CREATE TABLE IF NOT EXISTS changes (
    change_id       TEXT PRIMARY KEY,
    org_number      TEXT NOT NULL REFERENCES companies(org_number) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    change_type     TEXT NOT NULL,
    field           TEXT NOT NULL,
    category        TEXT NOT NULL,
    previous_value_json TEXT,
    current_value_json  TEXT,
    previous_source_id   TEXT,
    current_source_id    TEXT,
    detected_at     TEXT,
    explanation     TEXT
);
CREATE INDEX IF NOT EXISTS idx_changes_org_run ON changes(org_number, run_id);

CREATE TABLE IF NOT EXISTS trace_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    org_number      TEXT,
    timestamp       TEXT NOT NULL,
    stage           TEXT NOT NULL,
    message         TEXT NOT NULL,
    level           TEXT NOT NULL DEFAULT 'info',
    details_json    TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    content_hash    TEXT NOT NULL,
    url             TEXT,
    retrieved_at    TEXT NOT NULL,
    content_text    TEXT NOT NULL,
    PRIMARY KEY (content_hash, url)
);
"""


class Repository:
    """Thread-safe SQLite repository. One connection per thread via a lock."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self.conn
            conn.executescript(_SCHEMA)
            conn.commit()

    # ------------------------------------------------------------ runs
    def create_run(self, run: ResearchRun, budget_json: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO runs (run_id, started_at, state, companies_json, company_states_json, requested_by, budget_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (run.run_id, run.started_at or utcnow().isoformat(), run.state,
                 json.dumps(run.companies), json.dumps(run.company_states), run.requested_by, budget_json),
            )
            self.conn.commit()

    def update_run(self, run: ResearchRun) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE runs SET completed_at=?, state=?, request_count=?, estimated_cost_usd=?, companies_json=?, company_states_json=? WHERE run_id=?",
                (run.completed_at, run.state, run.request_count, run.estimated_cost_usd,
                 json.dumps(run.companies), json.dumps(run.company_states), run.run_id),
            )
            self.conn.commit()

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        return ResearchRun(
            run_id=row["run_id"], started_at=row["started_at"], completed_at=row["completed_at"],
            state=row["state"], request_count=row["request_count"], estimated_cost_usd=row["estimated_cost_usd"],
            companies=json.loads(row["companies_json"]), company_states=json.loads(row["company_states_json"]),
            requested_by=row["requested_by"],
        )

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id, started_at, completed_at, state, request_count, estimated_cost_usd, company_states_json FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "run_id": r["run_id"], "started_at": r["started_at"], "completed_at": r["completed_at"],
                "state": r["state"], "request_count": r["request_count"],
                "estimated_cost_usd": r["estimated_cost_usd"],
                "companies": json.loads(r["company_states_json"]),
            }
            for r in rows
        ]

    def run_company_state(self, run_id: str, org_number: str) -> Optional[str]:
        row = self.conn.execute("SELECT company_states_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["company_states_json"]).get(org_number)

    def mark_company_state(self, run_id: str, org_number: str, state: str) -> None:
        with self._lock:
            row = self.conn.execute("SELECT company_states_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return
            states = json.loads(row["company_states_json"])
            states[org_number] = state
            self.conn.execute("UPDATE runs SET company_states_json=? WHERE run_id=?", (json.dumps(states), run_id))
            self.conn.commit()

    def unfinished_companies(self, run_id: str) -> List[str]:
        run = self.get_run(run_id)
        if not run:
            return []
        return [c for c in run.companies if c not in run.company_states]

    # ------------------------------------------------------------ companies
    def upsert_company(self, identity: CompanyIdentity, run_id: str) -> None:
        with self._lock:
            existing = self.conn.execute(
                "SELECT first_seen_run FROM companies WHERE org_number=?", (identity.organisation_number,)
            ).fetchone()
            first = existing["first_seen_run"] if existing else run_id
            self.conn.execute(
                "INSERT INTO companies (org_number, legal_name, identity_json, first_seen_run, last_verified_at, last_run_id) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(org_number) DO UPDATE SET legal_name=excluded.legal_name, identity_json=excluded.identity_json, "
                "last_verified_at=excluded.last_verified_at, last_run_id=excluded.last_run_id",
                (identity.organisation_number, identity.legal_name, identity.model_dump_json(), first,
                 utcnow().isoformat(), run_id),
            )
            self.conn.commit()

    def get_company(self, org_number: str) -> Optional[CompanyIdentity]:
        row = self.conn.execute("SELECT identity_json FROM companies WHERE org_number=?", (org_number,)).fetchone()
        if not row:
            return None
        return CompanyIdentity.model_validate_json(row["identity_json"])

    def get_previous_facts(self, org_number: str, exclude_run_id: str) -> List[Fact]:
        """Latest published facts for a company from any earlier run."""
        rows = self.conn.execute(
            """
            SELECT f.* FROM facts f
            JOIN runs r ON r.run_id = f.run_id
            WHERE f.org_number = ? AND f.run_id != ? AND f.status = ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at) FROM runs r2
                  JOIN facts f2 ON f2.run_id = r2.run_id
                  WHERE f2.org_number = ? AND f2.run_id != ? AND f2.status = ? AND f2.fact_key_slot = f.fact_key_slot
              )
            """.replace("f.fact_key_slot", "f.category || '|' || f.field || '|' || COALESCE(f.reporting_period,'')")
             .replace("f2.fact_key_slot", "f2.category || '|' || f2.field || '|' || COALESCE(f2.reporting_period,'')"),
            (org_number, exclude_run_id, FactStatus.PUBLISHED.value, org_number, exclude_run_id, FactStatus.PUBLISHED.value),
        ).fetchall()
        facts = [self._row_to_fact(r) for r in rows]
        # dedupe by fact slot, keep latest retrieved
        seen: Dict[str, Fact] = {}
        for f in facts:
            k = f.fact_key()
            if k not in seen or (f.retrieved_at or "") > (seen[k].retrieved_at or ""):
                seen[k] = f
        return list(seen.values())

    # ------------------------------------------------------------ sources
    def insert_source(self, source: SourceRecord) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO sources (source_id, run_id, org_number, url, domain, source_type, authority_tier, title, retrieved_at, published_at, http_status, content_hash, access_status, error_detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source.source_id, source.org_number or "", source.org_number or "", source.url, source.domain,
                 source.source_type, source.authority_tier, source.title, source.retrieved_at, source.published_at,
                 source.http_status, source.content_hash, source.access_status, source.error_detail),
            )
            # source.org_number may be None for discovery-phase fetches; keep FK valid
            if not source.org_number:
                self.conn.execute("UPDATE sources SET org_number=NULL, run_id=NULL WHERE source_id=?", (source.source_id,))
            self.conn.commit()

    def insert_sources_bulk(self, sources: Iterable[SourceRecord], run_id: str, org_number: str) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO sources (source_id, run_id, org_number, url, domain, source_type, authority_tier, title, retrieved_at, published_at, http_status, content_hash, access_status, error_detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (s.source_id, run_id, org_number, s.url, s.domain, s.source_type, s.authority_tier,
                     s.title, s.retrieved_at, s.published_at, s.http_status, s.content_hash, s.access_status, s.error_detail)
                    for s in sources
                ],
            )
            self.conn.commit()

    def get_sources(self, org_number: str, run_id: Optional[str] = None) -> List[SourceRecord]:
        q = "SELECT * FROM sources WHERE org_number=?"
        args: list = [org_number]
        if run_id:
            q += " AND run_id=?"
            args.append(run_id)
        rows = self.conn.execute(q, args).fetchall()
        return [self._row_to_source(r) for r in rows]

    # ------------------------------------------------------------ evidence
    def insert_evidence(self, ev: EvidenceRecord) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO evidence (evidence_id, source_id, url, source_title, source_type, authority_tier, retrieved_at, published_at, evidence_text, page_or_section, content_hash, entity_match_details, entity_verdict, org_number) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev.evidence_id, ev.source_id, ev.url, ev.source_title, ev.source_type, ev.authority_tier,
                 ev.retrieved_at, ev.published_at, ev.evidence_text, ev.page_or_section, ev.content_hash,
                 json.dumps(ev.entity_match_details, ensure_ascii=False), ev.entity_verdict, ev.org_number),
            )
            self.conn.commit()

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        row = self.conn.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        return self._row_to_evidence(row) if row else None

    def evidence_for_company(self, org_number: str, run_id: Optional[str] = None) -> List[EvidenceRecord]:
        q = ("SELECT e.* FROM evidence e JOIN sources s ON s.source_id = e.source_id WHERE e.org_number=?")
        args: list = [org_number]
        if run_id:
            q += " AND s.run_id=?"
            args.append(run_id)
        rows = self.conn.execute(q, args).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    # ------------------------------------------------------------ facts
    def insert_fact(self, fact: Fact) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO facts (fact_id, org_number, run_id, category, field, value_json, normalized_value_json, unit, currency, valid_from, valid_to, reporting_period, source_id, evidence_id, retrieved_at, published_at, entity_verdict, fact_confidence, status, conflict_note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fact.fact_id, fact.org_number, fact.run_id or "", fact.category, fact.field,
                 _dump(fact.value), _dump(fact.normalized_value), fact.unit, fact.currency,
                 fact.valid_from, fact.valid_to, fact.reporting_period, fact.source_id, fact.evidence_id,
                 fact.retrieved_at, fact.published_at, fact.entity_verdict, fact.fact_confidence,
                 fact.status, fact.conflict_note),
            )
            self.conn.commit()

    def insert_facts_bulk(self, facts: Iterable[Fact]) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO facts (fact_id, org_number, run_id, category, field, value_json, normalized_value_json, unit, currency, valid_from, valid_to, reporting_period, source_id, evidence_id, retrieved_at, published_at, entity_verdict, fact_confidence, status, conflict_note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (f.fact_id, f.org_number, f.run_id or "", f.category, f.field, _dump(f.value),
                     _dump(f.normalized_value), f.unit, f.currency, f.valid_from, f.valid_to, f.reporting_period,
                     f.source_id, f.evidence_id, f.retrieved_at, f.published_at, f.entity_verdict,
                     f.fact_confidence, f.status, f.conflict_note)
                    for f in facts
                ],
            )
            self.conn.commit()

    def get_facts(self, org_number: str, run_id: Optional[str] = None,
                  statuses: Optional[List[str]] = None) -> List[Fact]:
        q = "SELECT * FROM facts WHERE org_number=?"
        args: list = [org_number]
        if run_id:
            q += " AND run_id=?"
            args.append(run_id)
        if statuses:
            q += f" AND status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        rows = self.conn.execute(q + " ORDER BY category, field", args).fetchall()
        return [self._row_to_fact(r) for r in rows]

    # ------------------------------------------------------------ changes
    def insert_changes(self, changes: Iterable[ChangeRecord]) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO changes (change_id, org_number, run_id, change_type, field, category, previous_value_json, current_value_json, previous_source_id, current_source_id, detected_at, explanation) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (c.change_id, c.org_number, c.run_id, c.change_type, c.field, c.category,
                     _dump(c.previous_value), _dump(c.current_value), c.previous_source_id,
                     c.current_source_id, c.detected_at, c.explanation)
                    for c in changes
                ],
            )
            self.conn.commit()

    def get_changes(self, org_number: str, limit: int = 100) -> List[ChangeRecord]:
        rows = self.conn.execute(
            "SELECT * FROM changes WHERE org_number=? ORDER BY detected_at DESC LIMIT ?", (org_number, limit)
        ).fetchall()
        return [self._row_to_change(r) for r in rows]

    # ------------------------------------------------------------ trace
    def add_trace(self, run_id: str, event: TraceEvent, org_number: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO trace_events (run_id, org_number, timestamp, stage, message, level, details_json) VALUES (?,?,?,?,?,?,?)",
                (run_id, org_number, event.timestamp, event.stage, event.message, event.level,
                 json.dumps(event.details, ensure_ascii=False) if event.details else None),
            )
            self.conn.commit()

    def get_trace(self, run_id: str, org_number: Optional[str] = None) -> List[TraceEvent]:
        q = "SELECT * FROM trace_events WHERE run_id=?"
        args: list = [run_id]
        if org_number:
            q += " AND (org_number=? OR org_number IS NULL)"
            args.append(org_number)
        rows = self.conn.execute(q + " ORDER BY id", args).fetchall()
        return [
            TraceEvent(timestamp=r["timestamp"], stage=r["stage"], message=r["message"], level=r["level"],
                       details=json.loads(r["details_json"]) if r["details_json"] else None)
            for r in rows
        ]

    # ------------------------------------------------------------ snapshots
    def save_snapshot(self, url: str, content_hash: str, text: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots (content_hash, url, retrieved_at, content_text) VALUES (?,?,?,?)",
                (content_hash, url, utcnow().isoformat(), text[:200000]),
            )
            self.conn.commit()

    def get_snapshot(self, content_hash: str, url: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT content_text FROM snapshots WHERE content_hash=? AND url=?", (content_hash, url)
        ).fetchone()
        return row["content_text"] if row else None

    def get_previous_hash(self, url: str, exclude_run_id: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT s.content_hash FROM sources s JOIN runs r ON r.run_id=s.run_id "
            "WHERE s.url=? AND s.access_status='success' AND s.run_id != ? ORDER BY r.started_at DESC LIMIT 1",
            (url, exclude_run_id),
        ).fetchone()
        return row["content_hash"] if row else None

    # ------------------------------------------------------------ row mappers
    def _row_to_source(self, r) -> SourceRecord:
        return SourceRecord(
            source_id=r["source_id"], url=r["url"], domain=r["domain"], source_type=r["source_type"],
            authority_tier=r["authority_tier"], title=r["title"], retrieved_at=r["retrieved_at"],
            published_at=r["published_at"], http_status=r["http_status"], content_hash=r["content_hash"],
            access_status=r["access_status"], error_detail=r["error_detail"],
            org_number=r["org_number"],
        )

    def _row_to_evidence(self, r) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=r["evidence_id"], source_id=r["source_id"], url=r["url"],
            source_title=r["source_title"], source_type=r["source_type"], authority_tier=r["authority_tier"],
            retrieved_at=r["retrieved_at"], published_at=r["published_at"], evidence_text=r["evidence_text"],
            page_or_section=r["page_or_section"], content_hash=r["content_hash"],
            entity_match_details=json.loads(r["entity_match_details"] or "{}"),
            entity_verdict=r["entity_verdict"], org_number=r["org_number"],
        )

    def _row_to_fact(self, r) -> Fact:
        return Fact(
            fact_id=r["fact_id"], org_number=r["org_number"], category=r["category"], field=r["field"],
            value=_load(r["value_json"]), normalized_value=_load(r["normalized_value_json"]),
            unit=r["unit"], currency=r["currency"], valid_from=r["valid_from"], valid_to=r["valid_to"],
            reporting_period=r["reporting_period"], source_id=r["source_id"], evidence_id=r["evidence_id"],
            retrieved_at=r["retrieved_at"], published_at=r["published_at"], entity_verdict=r["entity_verdict"],
            fact_confidence=r["fact_confidence"], status=r["status"], conflict_note=r["conflict_note"],
            run_id=r["run_id"],
        )

    def _row_to_change(self, r) -> ChangeRecord:
        return ChangeRecord(
            change_id=r["change_id"], org_number=r["org_number"], run_id=r["run_id"],
            change_type=r["change_type"], field=r["field"], category=r["category"],
            previous_value=_load(r["previous_value_json"]), current_value=_load(r["current_value_json"]),
            previous_source_id=r["previous_source_id"], current_source_id=r["current_source_id"],
            detected_at=r["detected_at"], explanation=r["explanation"],
        )

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _dump(v) -> Optional[str]:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False, default=str)


def _load(s: Optional[str]):
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s
