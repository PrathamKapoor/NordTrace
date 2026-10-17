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

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from nordtrace.core.models import (
    ChangeRecord,
    CompanyIdentity,
    CompanyProfile,
    EvidenceRecord,
    Fact,
    FactStatus,
    ResearchRun,
    RunBudgetState,
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
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 6:
                raise ValueError(f"database schema {version} is newer than supported version 6")
            if version < 6 and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone():
                # SQLite backup includes committed WAL data; never overwrite a previous backup.
                backup_path = self.db_path.with_name(
                    self.db_path.name + f".pre-v{version + 1}-{time.time_ns()}.bak"
                )
                with sqlite3.connect(str(backup_path)) as backup:
                    conn.backup(backup)
            conn.executescript(_SCHEMA)
            if version == 0:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS company_results (
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        result_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        PRIMARY KEY (run_id, result_key)
                    );
                    CREATE TABLE IF NOT EXISTS run_inputs (
                        run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                        inputs_json TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            if version < 2:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS company_claims (
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        result_key TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        lease_until REAL NOT NULL,
                        PRIMARY KEY (run_id, result_key)
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                """)
            if version < 3:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS snapshot_blobs (
                        content_hash TEXT PRIMARY KEY,
                        content BLOB NOT NULL,
                        byte_count INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS source_captures (
                        source_id TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL REFERENCES snapshot_blobs(content_hash),
                        metadata_json TEXT NOT NULL
                    );
                    PRAGMA user_version=3;
                    COMMIT;
                """)
            if version < 4:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE evidence ADD COLUMN locator_json TEXT;
                    ALTER TABLE sources ADD COLUMN source_json TEXT;
                    PRAGMA user_version=4;
                    COMMIT;
                """)
            if version < 5:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE facts ADD COLUMN item_key TEXT;
                    ALTER TABLE facts ADD COLUMN subject_scope TEXT NOT NULL DEFAULT 'unknown';
                    ALTER TABLE changes ADD COLUMN change_json TEXT;
                    PRAGMA user_version=5;
                    COMMIT;
                """)
            if version < 6:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS history_order (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        result_key TEXT,
                        UNIQUE(run_id, result_key)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_creation_order
                        ON history_order(run_id) WHERE result_key IS NULL;
                    PRAGMA user_version=6;
                    COMMIT;
                """)
            conn.commit()

    def try_claim_company(self, run_id: str, key: str, owner: str, lease_seconds: float) -> bool:
        """SQLite lease prevents two workers/processes from owning the same task."""
        now = time.time()
        with self._lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if self.conn.execute(
                "SELECT 1 FROM company_results WHERE run_id=? AND result_key=?", (run_id, key)
            ).fetchone():
                return False
            cursor = self.conn.execute(
                "INSERT INTO company_claims VALUES (?,?,?,?) "
                "ON CONFLICT(run_id,result_key) DO UPDATE SET owner=excluded.owner, lease_until=excluded.lease_until "
                "WHERE company_claims.lease_until<=?",
                (run_id, key, owner, now + lease_seconds, now),
            )
            return cursor.rowcount == 1

    def release_company(self, run_id: str, key: str, owner: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "DELETE FROM company_claims WHERE run_id=? AND result_key=? AND owner=?", (run_id, key, owner)
            )

    def save_result(self, result: CompanyProfile) -> None:
        """Atomically publish an immutable envelope and its terminal checkpoint.

        No company FK: invalid, blocked and unregistered inputs remain inspectable.
        Existing pre-contract rows are retained without invented historical envelopes.
        """
        result = CompanyProfile.model_validate(result.model_dump())
        payload = json.dumps(result.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        with self._lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            existing = self.conn.execute(
                "SELECT payload_json FROM company_results WHERE run_id=? AND result_key=?",
                (result.run_id, result.organisation_number),
            ).fetchone()
            if existing and existing[0] != payload:
                raise ValueError("completed research results are immutable")
            self.conn.execute(
                "INSERT OR IGNORE INTO company_results VALUES (?,?,?)",
                (result.run_id, result.organisation_number, payload),
            )
            if not existing:
                self.conn.execute(
                    "INSERT INTO history_order(run_id,result_key) VALUES (?,?)",
                    (result.run_id, result.organisation_number),
                )
            row = self.conn.execute(
                "SELECT company_states_json FROM runs WHERE run_id=?", (result.run_id,)
            ).fetchone()
            states = json.loads(row[0])
            states[result.organisation_number] = result.status
            self.conn.execute(
                "UPDATE runs SET company_states_json=? WHERE run_id=?", (json.dumps(states), result.run_id)
            )

    def get_result(self, run_id: str, result_key: str) -> Optional[CompanyProfile]:
        row = self.conn.execute(
            "SELECT payload_json FROM company_results WHERE run_id=? AND result_key=?", (run_id, result_key)
        ).fetchone()
        return CompanyProfile.model_validate_json(row[0]) if row else None

    def get_results(self, run_id: str) -> List[CompanyProfile]:
        run = self.get_run(run_id)
        if run is None:
            return []
        rows = self.conn.execute(
            "SELECT result_key, payload_json FROM company_results WHERE run_id=?", (run_id,)
        ).fetchall()
        by_key = {row[0]: CompanyProfile.model_validate_json(row[1]) for row in rows}
        return [by_key[key] for key in run.companies if key in by_key]

    def latest_result(self, result_key: str) -> Optional[CompanyProfile]:
        row = self.conn.execute(
            "SELECT payload_json FROM company_results WHERE result_key=? ORDER BY rowid DESC LIMIT 1",
            (result_key,),
        ).fetchone()
        return CompanyProfile.model_validate_json(row[0]) if row else None

    def previous_result(self, result_key: str, current_run_id: str) -> Optional[CompanyProfile]:
        """Frozen previous envelope, excluding later or concurrently completed runs."""
        row = self.conn.execute(
            "SELECT c.payload_json FROM company_results c "
            "JOIN runs previous ON previous.run_id=c.run_id "
            "JOIN runs current ON current.run_id=? "
            "LEFT JOIN history_order published ON published.run_id=c.run_id "
            "AND published.result_key=c.result_key "
            "LEFT JOIN history_order cutoff ON cutoff.run_id=current.run_id AND cutoff.result_key IS NULL "
            "WHERE c.result_key=? AND c.run_id!=current.run_id "
            "AND julianday(previous.started_at)<=julianday(current.started_at) "
            "AND (published.sequence<cutoff.sequence OR (published.sequence IS NULL AND "
            "julianday(json_extract(c.payload_json,'$.research_metadata.completed_at'))"
            "<julianday(current.started_at))) "
            "ORDER BY julianday(previous.started_at) DESC,published.sequence DESC,c.rowid DESC LIMIT 1",
            (current_run_id, result_key),
        ).fetchone()
        return CompanyProfile.model_validate_json(row[0]) if row else None

    def save_run_inputs(self, run_id: str, inputs: List[dict]) -> None:
        with self._lock, self.conn:
            self.conn.execute("INSERT INTO run_inputs VALUES (?,?)", (run_id, json.dumps(inputs)))

    @contextmanager
    def _budget_transaction(self, deadline_unix: float) -> Iterator[sqlite3.Connection]:
        """Short bounded lock wait; a slow writer cannot reset/overdraw a budget."""
        wait = min(0.05, max(0, deadline_unix - time.time()))
        connection = sqlite3.connect(str(self.db_path), timeout=wait)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_run_budget(self, run_id: str) -> tuple[RunBudgetState, int, float]:
        row = self.conn.execute(
            "SELECT budget_json,request_count,estimated_cost_usd FROM runs WHERE run_id=?", (run_id,),
        ).fetchone()
        if row is None or row["budget_json"] is None:
            raise ValueError("original run budget is unavailable")
        return RunBudgetState.model_validate_json(row["budget_json"]), row["request_count"], row["estimated_cost_usd"]

    def initialize_run_budget(
        self, run_id: str, state: RunBudgetState, used: int = 0, cost: float = 0,
    ) -> None:
        with self._budget_transaction(state.deadline_unix) as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("run not found")
            if row["budget_json"] is not None:
                return  # First initializer is authoritative; never replace a run's limits.
            if row["request_count"] or row["estimated_cost_usd"] or json.loads(row["company_states_json"]):
                raise ValueError("original budget unknown for a run that already has work")
            connection.execute(
                "UPDATE runs SET budget_json=?,request_count=?,estimated_cost_usd=? WHERE run_id=?",
                (state.model_dump_json(), used, cost, run_id),
            )

    def reserve_run_requests(self, run_id: str, n: int, elapsed: float) -> bool:
        state, _, _ = self.get_run_budget(run_id)
        with self._budget_transaction(state.deadline_unix) as connection:
            row = connection.execute("SELECT budget_json,request_count FROM runs WHERE run_id=?", (run_id,)).fetchone()
            state = RunBudgetState.model_validate_json(row["budget_json"])
            now = time.time()
            if (now >= state.deadline_unix or now < state.last_seen_unix - 0.01
                    or max(elapsed, state.elapsed_floor_sec) >= state.configuration.max_runtime_sec
                    or row["request_count"] + n > state.configuration.max_requests):
                return False
            state.elapsed_floor_sec = max(state.elapsed_floor_sec, elapsed)
            state.last_seen_unix = now
            connection.execute(
                "UPDATE runs SET request_count=request_count+?,budget_json=? WHERE run_id=?",
                (n, state.model_dump_json(), run_id),
            )
            return True

    def record_run_transport(
        self, run_id: str, success: bool, retry: bool, started: bool = True, **labels: Optional[str],
    ) -> None:
        state, _, _ = self.get_run_budget(run_id)
        with self._budget_transaction(state.deadline_unix) as connection:
            row = connection.execute("SELECT budget_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            state = RunBudgetState.model_validate_json(row["budget_json"])
            key = "unstarted_reservations" if not started else ("successful" if success else "failed")
            state.telemetry[key] = state.telemetry.get(key, 0) + 1
            state.telemetry["retries"] = state.telemetry.get("retries", 0) + int(retry and started)
            for label, value in labels.items():
                if value and started:
                    counts = state.telemetry.setdefault("by_" + label, {})
                    counts[value] = counts.get(value, 0) + 1
            connection.execute("UPDATE runs SET budget_json=? WHERE run_id=?", (state.model_dump_json(), run_id))

    def checkpoint_run_budget(self, run_id: str, elapsed: float, cost: float) -> None:
        state, _, _ = self.get_run_budget(run_id)
        with self._budget_transaction(state.deadline_unix) as connection:
            row = connection.execute("SELECT budget_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            state = RunBudgetState.model_validate_json(row["budget_json"])
            state.elapsed_floor_sec = max(state.elapsed_floor_sec, elapsed)
            state.last_seen_unix = max(state.last_seen_unix, time.time())
            connection.execute(
                "UPDATE runs SET budget_json=?,estimated_cost_usd=MAX(estimated_cost_usd,?) WHERE run_id=?",
                (state.model_dump_json(), cost, run_id),
            )

    def get_run_inputs(self, run_id: str) -> List[dict]:
        row = self.conn.execute("SELECT inputs_json FROM run_inputs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else []

    # ------------------------------------------------------------ runs
    def create_run(self, run: ResearchRun, budget_json: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO runs (run_id, started_at, state, companies_json, company_states_json, requested_by, budget_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.started_at or utcnow().isoformat(),
                    run.state,
                    json.dumps(run.companies),
                    json.dumps(run.company_states),
                    run.requested_by,
                    budget_json,
                ),
            )
            self.conn.execute("INSERT INTO history_order(run_id) VALUES (?)", (run.run_id,))
            self.conn.commit()

    def update_run(self, run: ResearchRun) -> None:
        with self._lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                "SELECT company_states_json FROM runs WHERE run_id=?", (run.run_id,)
            ).fetchone()
            states = json.loads(row[0]) if row else {}
            states.update(run.company_states)
            # Publication is authoritative, including when a different process
            # committed after this caller read the run checkpoint.
            for result in self.conn.execute(
                "SELECT result_key,payload_json FROM company_results WHERE run_id=?", (run.run_id,)
            ):
                states[result[0]] = json.loads(result[1])["status"]
            run.company_states = states
            self.conn.execute(
                "UPDATE runs SET completed_at=?, state=?, request_count=MAX(request_count,?), "
                "estimated_cost_usd=MAX(estimated_cost_usd,?), companies_json=?, company_states_json=? WHERE run_id=?",
                (
                    run.completed_at,
                    run.state,
                    run.request_count,
                    run.estimated_cost_usd,
                    json.dumps(run.companies),
                    json.dumps(states),
                    run.run_id,
                ),
            )
            self.conn.commit()

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        return ResearchRun(
            run_id=row["run_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            state=row["state"],
            request_count=row["request_count"],
            estimated_cost_usd=row["estimated_cost_usd"],
            companies=json.loads(row["companies_json"]),
            company_states=json.loads(row["company_states_json"]),
            requested_by=row["requested_by"],
        )

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id, started_at, completed_at, state, request_count, estimated_cost_usd, company_states_json FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "run_id": r["run_id"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "state": r["state"],
                "request_count": r["request_count"],
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
        with self._lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                "SELECT company_states_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not row:
                return
            states = json.loads(row["company_states_json"])
            result = self.conn.execute(
                "SELECT payload_json FROM company_results WHERE run_id=? AND result_key=?", (run_id, org_number)
            ).fetchone()
            states[org_number] = json.loads(result[0])["status"] if result else state
            self.conn.execute(
                "UPDATE runs SET company_states_json=? WHERE run_id=?", (json.dumps(states), run_id)
            )
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
                (
                    identity.organisation_number,
                    identity.legal_name,
                    identity.model_dump_json(),
                    first,
                    utcnow().isoformat(),
                    run_id,
                ),
            )
            self.conn.commit()

    def get_company(self, org_number: str) -> Optional[CompanyIdentity]:
        row = self.conn.execute(
            "SELECT identity_json FROM companies WHERE org_number=?", (org_number,)
        ).fetchone()
        if not row:
            return None
        return CompanyIdentity.model_validate_json(row["identity_json"])

    def get_previous_facts(self, org_number: str, exclude_run_id: str) -> List[Fact]:
        """Latest published facts for a company from any earlier run."""
        rows = self.conn.execute(
            "SELECT f.* FROM facts f JOIN runs r ON r.run_id=f.run_id "
            "WHERE f.org_number=? AND f.run_id!=? AND f.status=? "
            "ORDER BY r.started_at DESC,f.rowid DESC",
            (org_number, exclude_run_id, FactStatus.PUBLISHED.value),
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
                (
                    source.source_id,
                    source.org_number or "",
                    source.org_number or "",
                    source.url,
                    source.domain,
                    source.source_type,
                    source.authority_tier,
                    source.title,
                    source.retrieved_at,
                    source.published_at,
                    source.http_status,
                    source.content_hash,
                    source.access_status,
                    source.error_detail,
                ),
            )
            # source.org_number may be None for discovery-phase fetches; keep FK valid
            if not source.org_number:
                self.conn.execute(
                    "UPDATE sources SET org_number=NULL, run_id=NULL WHERE source_id=?", (source.source_id,)
                )
            self.conn.commit()

    def insert_sources_bulk(self, sources: Iterable[SourceRecord], run_id: str, org_number: str) -> None:
        with self._lock:
            rows = [
                (
                    s.source_id,
                    run_id,
                    org_number,
                    s.url,
                    s.domain,
                    s.source_type,
                    s.authority_tier,
                    s.title,
                    s.retrieved_at,
                    s.published_at,
                    s.http_status,
                    s.content_hash,
                    s.access_status,
                    s.error_detail,
                    s.model_dump_json(),
                )
                for s in sources
                if s.source_id and org_number
            ]
            if rows:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO sources (source_id, run_id, org_number, url, domain, source_type, authority_tier, title, retrieved_at, published_at, http_status, content_hash, access_status, error_detail, source_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
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
                "INSERT OR REPLACE INTO evidence (evidence_id, source_id, url, source_title, source_type, authority_tier, retrieved_at, published_at, evidence_text, page_or_section, content_hash, entity_match_details, entity_verdict, org_number, locator_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev.evidence_id,
                    ev.source_id,
                    ev.url,
                    ev.source_title,
                    ev.source_type,
                    ev.authority_tier,
                    ev.retrieved_at,
                    ev.published_at,
                    ev.evidence_text,
                    ev.page_or_section,
                    ev.content_hash,
                    json.dumps(ev.entity_match_details, ensure_ascii=False),
                    ev.entity_verdict,
                    ev.org_number,
                    ev.locator.model_dump_json() if ev.locator else None,
                ),
            )
            self.conn.commit()

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        row = self.conn.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        return self._row_to_evidence(row) if row else None

    def evidence_for_company(self, org_number: str, run_id: Optional[str] = None) -> List[EvidenceRecord]:
        q = "SELECT e.* FROM evidence e JOIN sources s ON s.source_id = e.source_id WHERE e.org_number=?"
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
                "INSERT OR REPLACE INTO facts (fact_id, org_number, run_id, category, field, value_json, normalized_value_json, unit, currency, valid_from, valid_to, reporting_period, source_id, evidence_id, retrieved_at, published_at, entity_verdict, fact_confidence, status, conflict_note, item_key, subject_scope) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fact.fact_id,
                    fact.org_number,
                    fact.run_id or "",
                    fact.category,
                    fact.field,
                    _dump(fact.value),
                    _dump(fact.normalized_value),
                    fact.unit,
                    fact.currency,
                    fact.valid_from,
                    fact.valid_to,
                    fact.reporting_period,
                    fact.source_id,
                    fact.evidence_id,
                    fact.retrieved_at,
                    fact.published_at,
                    fact.entity_verdict,
                    fact.fact_confidence,
                    fact.status,
                    fact.conflict_note,
                    fact.item_key,
                    fact.subject_scope,
                ),
            )
            self.conn.commit()

    def insert_evidence_bulk(self, evidence: Iterable[EvidenceRecord]) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO evidence (evidence_id, source_id, url, source_title, source_type, authority_tier, retrieved_at, published_at, evidence_text, page_or_section, content_hash, entity_match_details, entity_verdict, org_number, locator_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        e.evidence_id,
                        e.source_id,
                        e.url,
                        e.source_title,
                        e.source_type,
                        e.authority_tier,
                        e.retrieved_at,
                        e.published_at,
                        e.evidence_text,
                        e.page_or_section,
                        e.content_hash,
                        json.dumps(e.entity_match_details, ensure_ascii=False),
                        e.entity_verdict,
                        e.org_number,
                        e.locator.model_dump_json() if e.locator else None,
                    )
                    for e in evidence
                ],
            )
            self.conn.commit()

    def insert_facts_bulk(self, facts: Iterable[Fact]) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO facts (fact_id, org_number, run_id, category, field, value_json, normalized_value_json, unit, currency, valid_from, valid_to, reporting_period, source_id, evidence_id, retrieved_at, published_at, entity_verdict, fact_confidence, status, conflict_note, item_key, subject_scope) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        f.fact_id,
                        f.org_number,
                        f.run_id or "",
                        f.category,
                        f.field,
                        _dump(f.value),
                        _dump(f.normalized_value),
                        f.unit,
                        f.currency,
                        f.valid_from,
                        f.valid_to,
                        f.reporting_period,
                        f.source_id,
                        f.evidence_id,
                        f.retrieved_at,
                        f.published_at,
                        f.entity_verdict,
                        f.fact_confidence,
                        f.status,
                        f.conflict_note,
                        f.item_key,
                        f.subject_scope,
                    )
                    for f in facts
                ],
            )
            self.conn.commit()

    def get_facts(
        self, org_number: str, run_id: Optional[str] = None, statuses: Optional[List[str]] = None
    ) -> List[Fact]:
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
                "INSERT OR REPLACE INTO changes (change_id, org_number, run_id, change_type, field, category, previous_value_json, current_value_json, previous_source_id, current_source_id, detected_at, explanation, change_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        c.change_id,
                        c.org_number,
                        c.run_id,
                        c.change_type,
                        c.field,
                        c.category,
                        _dump(c.previous_value),
                        _dump(c.current_value),
                        c.previous_source_id,
                        c.current_source_id,
                        c.detected_at,
                        c.explanation,
                        c.model_dump_json(),
                    )
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
                (
                    run_id,
                    org_number,
                    event.timestamp,
                    event.stage,
                    event.message,
                    event.level,
                    json.dumps(event.details, ensure_ascii=False) if event.details else None,
                ),
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
            TraceEvent(
                timestamp=r["timestamp"],
                stage=r["stage"],
                message=r["message"],
                level=r["level"],
                details=json.loads(r["details_json"]) if r["details_json"] else None,
            )
            for r in rows
        ]

    # ------------------------------------------------------------ snapshots
    def save_capture(self, source: SourceRecord, content: bytes, *, deadline: Optional[float] = None) -> None:
        """Atomically retain the complete bounded response body and acquisition metadata.

        These blobs are local audit material, not a licence to redistribute source data.
        Legacy truncated text snapshots are deliberately not promoted to this store.
        """
        digest = hashlib.sha256(content).hexdigest()
        if source.content_hash != digest:
            raise ValueError("snapshot hash differs from retained response bytes")
        if source.snapshot_representation != "http-response-body-v1":
            raise ValueError("unsupported snapshot representation")
        payload = source.model_dump_json()

        def check_time() -> None:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("snapshot persistence deadline exceeded")

        check_time()
        # A dedicated short-wait connection avoids the repository's 30-second busy
        # timeout and thread-local connections lingering in an executor pool.
        timeout = min(0.05, max(0, deadline - time.monotonic())) if deadline is not None else 0.05
        conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            check_time()
            existing = conn.execute(
                "SELECT content, byte_count FROM snapshot_blobs WHERE content_hash=?", (digest,)
            ).fetchone()
            if existing and (bytes(existing["content"]) != content or existing["byte_count"] != len(content)):
                raise ValueError("existing snapshot integrity failure")
            conn.execute(
                "INSERT OR IGNORE INTO snapshot_blobs VALUES (?,?,?)", (digest, content, len(content))
            )
            previous = conn.execute(
                "SELECT metadata_json FROM source_captures WHERE source_id=?", (source.source_id,)
            ).fetchone()
            if previous and previous["metadata_json"] != payload:
                raise ValueError("source capture metadata is immutable")
            conn.execute(
                "INSERT OR IGNORE INTO source_captures VALUES (?,?,?)", (source.source_id, digest, payload)
            )
            check_time()
            conn.commit()
        finally:
            conn.close()  # rolls back on any exception before commit

    def read_capture(self, source_id: str) -> tuple[SourceRecord, bytes]:
        """Read and independently verify retained bytes; never refetch missing evidence."""
        row = self.conn.execute(
            "SELECT c.metadata_json,c.content_hash,b.content,b.byte_count "
            "FROM source_captures c LEFT JOIN snapshot_blobs b ON b.content_hash=c.content_hash "
            "WHERE c.source_id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"source capture {source_id} is missing")
        source = SourceRecord.model_validate_json(row["metadata_json"])
        if row["content"] is None:
            raise ValueError("snapshot integrity failure: missing blob")
        body = bytes(row["content"])
        digest = hashlib.sha256(body).hexdigest()
        if (
            digest != row["content_hash"] or digest != source.content_hash
            or len(body) != row["byte_count"] or source.source_id != source_id
            or source.snapshot_representation != "http-response-body-v1"
        ):
            raise ValueError("snapshot integrity failure")
        return source, body

    def save_snapshot(self, url: str, content_hash: str, text: str) -> None:
        """Legacy text store, retained for historical compatibility only."""
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
        if r["source_json"]:
            return SourceRecord.model_validate_json(r["source_json"])
        return SourceRecord(
            source_id=r["source_id"],
            url=r["url"],
            domain=r["domain"],
            source_type=r["source_type"],
            authority_tier=r["authority_tier"],
            title=r["title"],
            retrieved_at=r["retrieved_at"],
            published_at=r["published_at"],
            http_status=r["http_status"],
            content_hash=r["content_hash"],
            access_status=r["access_status"],
            error_detail=r["error_detail"],
            org_number=r["org_number"],
        )

    def _row_to_evidence(self, r) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=r["evidence_id"],
            source_id=r["source_id"],
            url=r["url"],
            source_title=r["source_title"],
            source_type=r["source_type"],
            authority_tier=r["authority_tier"],
            retrieved_at=r["retrieved_at"],
            published_at=r["published_at"],
            evidence_text=r["evidence_text"],
            page_or_section=r["page_or_section"],
            content_hash=r["content_hash"],
            entity_match_details=json.loads(r["entity_match_details"] or "{}"),
            entity_verdict=r["entity_verdict"],
            org_number=r["org_number"],
            locator=json.loads(r["locator_json"]) if r["locator_json"] else None,
        )

    def _row_to_fact(self, r) -> Fact:
        return Fact(
            fact_id=r["fact_id"],
            org_number=r["org_number"],
            category=r["category"],
            field=r["field"],
            value=_load(r["value_json"]),
            normalized_value=_load(r["normalized_value_json"]),
            unit=r["unit"],
            currency=r["currency"],
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            reporting_period=r["reporting_period"],
            item_key=r["item_key"],
            subject_scope=r["subject_scope"],
            source_id=r["source_id"],
            evidence_id=r["evidence_id"],
            retrieved_at=r["retrieved_at"],
            published_at=r["published_at"],
            entity_verdict=r["entity_verdict"],
            fact_confidence=r["fact_confidence"],
            status=r["status"],
            conflict_note=r["conflict_note"],
            run_id=r["run_id"],
        )

    def _row_to_change(self, r) -> ChangeRecord:
        if r["change_json"]:
            return ChangeRecord.model_validate_json(r["change_json"])
        return ChangeRecord(
            change_id=r["change_id"],
            org_number=r["org_number"],
            run_id=r["run_id"],
            change_type=r["change_type"],
            field=r["field"],
            category=r["category"],
            previous_value=_load(r["previous_value_json"]),
            current_value=_load(r["current_value_json"]),
            previous_source_id=r["previous_source_id"],
            current_source_id=r["current_source_id"],
            detected_at=r["detected_at"],
            explanation=r["explanation"],
        )

    def integrity_check(self) -> Dict[str, object]:
        """Database integrity: FKs, duplicates, orphans. For validate-db."""
        issues: Dict[str, object] = {}
        # foreign key violations
        fk = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        issues["foreign_key_violations"] = len(fk)
        # duplicate facts within the SAME run (same org + slot) — history across
        # runs is legitimate; within one run a slot must appear once
        dup_facts = self.conn.execute(
            """
            SELECT org_number, category, field, COALESCE(reporting_period,'') as period,
                item_key,subject_scope,run_id,COUNT(*) as n
            FROM facts GROUP BY org_number,category,field,period,item_key,subject_scope,run_id HAVING n > 1
            """
        ).fetchall()
        issues["duplicate_fact_slots_same_run"] = len(dup_facts)
        # duplicate source rows within the same run (same url) — retries share one
        # source_id; duplicates here indicate a request-tracking bug
        dup_src = self.conn.execute(
            "SELECT url, run_id, COUNT(DISTINCT source_id) as n FROM sources WHERE url IS NOT NULL GROUP BY url, run_id HAVING n > 1"
        ).fetchall()
        issues["duplicate_source_urls_same_run"] = len(dup_src)
        # orphaned evidence (evidence whose source is missing)
        orphan_ev = self.conn.execute(
            "SELECT COUNT(*) FROM evidence e LEFT JOIN sources s ON s.source_id = e.source_id WHERE s.source_id IS NULL"
        ).fetchone()[0]
        issues["orphaned_evidence"] = orphan_ev
        # orphaned facts (fact whose source or evidence missing)
        orphan_f = self.conn.execute(
            "SELECT COUNT(*) FROM facts f LEFT JOIN sources s ON s.source_id = f.source_id WHERE s.source_id IS NULL"
        ).fetchone()[0]
        orphan_f2 = self.conn.execute(
            "SELECT COUNT(*) FROM facts f LEFT JOIN evidence e ON e.evidence_id = f.evidence_id WHERE e.evidence_id IS NULL"
        ).fetchone()[0]
        issues["orphaned_facts"] = orphan_f + orphan_f2
        # cross-company contamination: facts whose evidence org differs
        cross = self.conn.execute(
            "SELECT COUNT(*) FROM facts f JOIN evidence e ON e.evidence_id = f.evidence_id WHERE f.org_number != e.org_number"
        ).fetchone()[0]
        issues["cross_company_contamination"] = cross
        # invalid company references
        invalid_company = self.conn.execute(
            "SELECT COUNT(*) FROM facts f LEFT JOIN companies c ON c.org_number = f.org_number WHERE c.org_number IS NULL"
        ).fetchone()[0]
        issues["invalid_company_refs"] = invalid_company
        issues["ok"] = not any(v for k, v in issues.items() if k != "ok")
        return issues

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
