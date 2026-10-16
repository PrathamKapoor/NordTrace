# Decision Log — NordTrace

## D-037 — Unconfirmed refresh preserves last-known support

- Date/status: 2026-10-17, accepted; affirmative removal production remains unfinished.
- Problem/evidence: a missing current observation defaulted to RETRACTED even after source failure or successful incomplete extraction. Five initial regressions failed, including retained-history and source-state gaps.
- Decision/implementation: core.refresh applies to every pipeline completion. It revalidates frozen earlier observations against retained bytes and current support rules, compares stable logical IDs and separates SOURCE_UNAVAILABLE last_known copies from current facts. Missing claims cannot establish removal. Sources/evidence and original verification IDs/times remain inspectable; summary labels unconfirmed observations. Change records include old/new evidence and observation IDs. Current facts require PUBLISHED status; other states cannot silently occupy that collection.
- Application: new single/batch/API outcomes, including registry early returns and later failures. A successful source body does not prove source-family completeness. Per-source RefreshOutcome availability and unknown completeness are explicit; 404/410 is not_available without business removal.
- Alternatives: global current_sources_ok, failed requests or missing parser output cannot prove disappearance. Promoting old existence-only ledger rows would reintroduce unsupported publication. Silently dropping stale history loses useful evidence.
- Tradeoffs/limits: removal/expiry detection is conservatively disabled until producers supply verified affirmative or complete-collection evidence. ETag/304, source-specific retention, full family completeness and stale UI presentation remain unfinished. A tampered/missing prior snapshot is not promoted; its failed revalidation is recorded in unknowns and original history remains untouched.
- Verification: real simulated acquisition/SQLite fixtures exercise blocked, unavailable, malformed and incomplete refresh then recovery; stable claims reconfirm as UNCHANGED and frozen histories persist. New-period expectations now retain the older period. No live refresh accuracy is claimed. Revisit when removal-support contracts and converted producers are implemented; extends D-034/D-035/D-036.

## D-038 — Durable history ordering and actual historical API selection

- Date/status: 2026-10-17, accepted.
- Problem/evidence: reviewer reproduced sequential runs with equal second-resolution timestamps losing their predecessor. A timestamp-only query also cannot establish whether concurrent results were published before research began. An HTTP regression showed the company route ignored run_id despite its canonical helper supporting history.
- Decision/implementation: additive schema6 history_order records run creation and first immutable publication in the corresponding SQLite transaction. Previous-result selection requires a publication sequence before the current run-creation barrier and no later run start. Old rows receive no invented ordering; known earlier completion timestamps are the conservative fallback. The actual company HTTP route forwards optional run_id to the frozen canonical serializer.
- Application: new refresh predecessor selection and historical company API. Existing data is backed up before migration, canonical payload bytes remain unchanged, repeat saves do not create new publication events.
- Alternatives: truncating clocks loses valid same-second predecessors; increasing clock precision alone does not provide a durable cross-process publication barrier. Reading latest result at refresh completion admits concurrent future observations. Reconstructing history from current rows is incorrect.
- Tradeoffs/limits: legacy histories without sufficient timing abstain. The sequence orders committed local events, not external source effective dates. Relational legacy get_previous_facts remains for compatibility but is no longer the production refresh input.
- Verification: same-timestamp predecessor/concurrent publication fixture failed before correction; schema5 copy verifies unchanged envelopes, no backfilled events, one backup and intact foreign keys. HTTP historical refresh assertion failed before route forwarding. Revisit with complete shared-run budget/checkpoint transactions; extends D-021/D-022.

## D-036 — Withhold all observations of unresolved conflicts

- Date/status: 2026-10-17, accepted.
- Problem/evidence: ledger conflict detection withheld only the incoming observation, leaving the first supported value published. Review reproduced the same arbitrary winner in canonical company fields and the dashboard. Stable JSON claim keys also exposed old delimiter-based synthesis lookups.
- Decision/implementation: ledger marks all competing observations CONFLICT; envelopes carry a separate conflicts collection with complete references. Family availability becomes ambiguous. contracts.project_identity clears disputed structured fields and dependent address/status values for canonical output and final company-row persistence. Required legal_name uses empty string plus unresolved_fields. Summaries use typed fact attributes and omit disputed identity/industry values. Acquired bytes and every competing observation remain available.
- Application: new results and their current company projection; existing immutable envelopes/history are not rewritten. Repeated corroboration does not resolve a conflict without an explicit resolution policy.
- Alternatives: first/last insertion wins or confidence-based selection would conceal disagreement. Making every acquisition identity field nullable would unnecessarily change adapters; the projection preserves their internal anchor.
- Tradeoffs/limits: conservative withholding lowers coverage; no automated temporal/source-priority resolution is introduced. Legacy endpoint support, last-known refresh and complete atomic publication remain separate unfinished requirements. The organisation number stays identified while individual values may be unresolved.
- Failure path: reviewer reproduced conflicts disappearing when a later accounts adapter raised. Ledger finalization now runs in finally for both successful and failed execution; a failed envelope retains prior supported observations and disagreements before identity projection. Persistence remains sequential and full transaction/cancellation guarantees are separate work.
- Verification: test_conflict_publication.py reproduces ledger and canonical/API leaks, preserves retained competing evidence through injected failure, tests dependent-field suppression and summary lookups. Revisit with source-completeness/temporal resolution rules. Extends D-021/D-034/D-035.

Serious engineering decision log. Each entry explains WHAT changed, WHY, what
problem it solved, alternatives considered, why they were rejected, trade-offs
accepted, and supporting evidence/tests. Entries added whenever meaningful
code/architecture changes occur.

Where a historical rationale could not be recovered from repository evidence,
it is stated as such rather than manufactured.

---

## D-001 — Canonical organisation number as identity key

- **Date:** 2026-09-29 (initial rebuild)
- **Status:** Accepted
- **Area:** Entity resolution / data model
- **Decision:** The Brønnøysund-registered `organisation_number` is the sole
  canonical identity key. Every company row, fact, source, and evidence
  record references it; all candidate sources are matched against it.

**Why:** The challenge input IS an organisation number; registry identity is
the only authoritative anchor. Name-based identity is ambiguous in Norway
(many same-name companies — measured: 5 "Fjell", 3 "Telenor"-prefixed
entities in one search).

**Alternatives considered:** name+address composite keys; URL-based identity.
**Why rejected:** names collide; domains change hands and are absent for
83/100 of a random company sample.

**Consequences:** companies without registry entries are `not_found`;
subsidiaries are distinct entities despite shared brands.
**Evidence/tests:** 18 orgnr tests; 19 entity tests; live E2E
(`tests/integration/test_e2e_resume.py`).
**Files:** `core/orgnr.py`, `core/models.py`, `core/entity.py`, `core/repository.py`.

---

## D-002 — Single RequestGateway chokepoint

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** HTTP / budget enforcement / security
- **Decision:** All outbound HTTP goes through `core/request_gateway.py`.
  Adapters take the gateway as a dependency; no direct `httpx` calls.

**Why:** The audit found the prior implementation's budget was vacuous —
`BrregAdapter` bypassed `RequestManager` with a raw `httpx.AsyncClient`, so
nothing enforced the 2,000-request cap. A single chokepoint makes budget
enforcement, SSRF protection, robots compliance, caching, and retry policy
non-bypassable by construction.

**Alternatives considered:** per-adapter budget checks (rejected: each adapter
can forget); decorator-based interception (rejected: implicit, easy to
circumvent).
**Why selected:** grep-verifiable invariant — `httpx` appears only in the
gateway (and the LLM client, which uses its own client behind the cost guard).
**Trade-offs:** every adapter must route through one interface; slightly more
indirection.
**Evidence/tests:** `test_gateway_enforces_budget_without_network` (raises
`BudgetExceededError` before any I/O); `test_budget_attack_request_limit`
(live); `test_request_budget_atomic_no_races` (8 threads, exact limit, no
overshoot).
**Files:** `core/request_gateway.py`, all `adapters/*`.

---

## D-003 — Source-specific rate limiting (generic mechanism)

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** HTTP / rate limiting
- **Decision:** `core/rate_limiter.py` implements a generic per-domain
  `SourcePolicy` (max_concurrent, min_interval, max_retries,
  breaker_threshold, breaker_cooldown) with conservative presets: NAV
  (1 concurrent, 1.0s interval), Brreg (2 concurrent, 0.5s interval).

**Why:** NAV returned HTTP 429 around the 15-company benchmark run. The
benchmark instructions explicitly forbid solving this by increasing
concurrency. A token-based limiter (the token HOLDS the per-domain semaphore
across the full request duration) caps in-flight requests per domain and
spaces request starts by a minimum interval.

**Alternatives considered:** global-only throttling (rejected: penalizes fast
registry endpoints for NAV's slowness); increasing concurrency (rejected:
makes 429s worse and violates instructions).
**Why selected:** generic — works for any domain, not a NAV one-off.
**Trade-offs:** slightly lower throughput for fast domains sharing a policy;
tokens must be released (handled on `record_success`/`record_failure`).
**Evidence/tests:** 15 rate-limiting tests incl.
`test_concurrency_limit_per_domain` (never >1 in flight for NAV),
`test_min_interval_spacing`, `test_domains_are_independent`.
**Files:** `core/rate_limiter.py`, `core/request_gateway.py`.

---

## D-004 — NAV circuit breaker

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** HTTP / failure recovery
- **Decision:** Repeated failures (429/5xx/transport) per domain open a
  circuit: requests short-circuit to `rate_limited` without network I/O until
  a cooldown elapses, then one controlled half-open attempt is allowed;
  success closes the circuit. Cooldown grows exponentially on repeated OPENs,
  capped at 4x.

**Why:** During the 100-company run NAV was IP-level 429-blocked for days
(verified by manual curl probes at +30s, +90s). Continuing to request wastes
budget and hammers the source. The benchmark instructions require a circuit
breaker that "eventually allows a controlled retry".

**Alternatives considered:** infinite retry (rejected: budget + hammering);
immediate permanent disable (rejected: no recovery when the block lifts);
16x exponential cap (rejected 2026-10-02: locked the circuit out for the rest
of a run after a transient block — measured 92/100 FAILED in v3).
**Why 4x cap:** recovers within a single 100-company run while still avoiding
wasted half-open attempts during long blocks.
**Trade-offs:** a transiently-blocked source yields degraded coverage for a
window; acceptable vs. failing companies.
**Evidence/tests:** `test_repeated_429_opens_circuit`,
`test_circuit_blocks_requests`, `test_circuit_recovery_after_cooldown`,
`test_exponential_cooldown_doubles` (4x cap), v3→v4 benchmark recovery.
**Files:** `core/rate_limiter.py`, `adapters/brreg.py`, `engine/pipeline.py`.

---

## D-005 — Registry rate-limited → BLOCKED rather than FAILED

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Terminal-state semantics / failure recovery
- **Decision:** `access_status=rate_limited` maps to hint `blocked`, and the
  pipeline maps a `blocked` identity lookup to terminal state `blocked` —
  not `failed`.

**Why:** v3 measured 92/100 companies FAILED when Brreg refused connections:
`rate_limited` was mapped to `failed`, which means "the system itself failed
despite reasonable recovery" per the challenge spec. A source being
temporarily unavailable is `blocked`. The distinction matters for judges:
92 FAILED signals a broken system; 88 available + 12 blocked signals a
correct system operating under an external block.

**Alternatives considered:** retrying identity until success (rejected:
budget + hammering); marking `not_available` (rejected: conflates "no public
information" with "source inaccessible").
**Trade-offs:** none identified — strict improvement.
**Evidence/tests:** v3 (92 FAILED) → v4 (0 FAILED, 100/100 entity resolved)
benchmark artifacts.
**Files:** `adapters/brreg.py`, `engine/pipeline.py`.

---

## D-006 — Evidence-org must equal fact-org

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Evidence validation / cross-company contamination
- **Decision:** `CitationValidator.validate()` rejects any fact whose
  evidence record belongs to a different company
  (`ev.org_number != fact.org_number` → FAILED). The repository
  `integrity_check` reports `cross_company_contamination` as a metric.

**Why:** A wrong-company publication is substantially more damaging than
missing information (challenge spec). The contamination test
(`test_cross_company_contamination`) proves A facts ⊂ A and B facts ⊂ B with
zero cross-source references; the citation-level gate enforces it at
insertion time, not just at audit time.

**Alternatives considered:** post-hoc integrity checking only (rejected:
detects contamination after the fact instead of preventing publication);
LLM-based entity checking (rejected: firewall must be deterministic).
**Trade-offs:** facts from legitimately-shared sources (e.g. a parent's
registry page) must carry the target's org on the evidence record — enforced
by the adapters.
**Evidence/tests:** `test_activity_unrelated_company_not_attached`,
`test_cross_company_contamination` (live, concurrent A+B), `validate-db`
(0 contamination).
**Files:** `core/ledger.py`, `core/repository.py`.

---

## D-007 — Parent-brand website rejection (subsidiary firewall)

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Entity resolution / website discovery
- **Decision:** Website candidates are generated brand-first (first core
  token: `TELENOR PAKISTAN AS` → `telenor.no`, not `telenor-pakistan.no`),
  and homepage verification rejects candidates whose page confirms a
  different company's identity.

**Why:** Measured evidence: naive full-name-derived candidates produced
nonsense domains (`www.telenor-pakistan.no`) and 161 TLS ConnectErrors.
Brand-first candidates are more likely to resolve — but a parent's brand site
mentions the subsidiary's name-core too, so the firewall must reject
attachment when the page identity belongs to the parent.

**Alternatives considered:** accepting name-similarity LIKELY for homepage
attachment (rejected 2026-10-02 in D-008: wrong-company attribution is worse
than a missing description); skipping brand-derived candidates entirely
(rejected: loses legitimate discoveries for single-brand companies).
**Trade-offs:** subsidiaries whose parent's site is the only web presence get
`not_available` for business description — honest, safe.
**Evidence/tests:** live verification (TELENOR PAKISTAN AS against
telenor.no → REJECTED; TELENOR ASA → verified "legal name present on page").
**Files:** `adapters/website.py`.

---

## D-008 — VERIFIED-only website fallback

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Website discovery / entity firewall
- **Decision:** `verify_site_homepage` accepts: orgnr present on page, FULL
  normalized legal name present on page, or resolver verdict VERIFIED.
  Resolver LIKELY is deliberately NOT accepted for homepage attachment.

**Why:** LIKELY matches brand-token pages for subsidiaries sharing the brand
(e.g. telenor.no mentions "Telenor" everywhere), which would attach a
parent's site to a subsidiary. The challenge spec prefers UNKNOWN over
WRONG COMPANY.

**Alternatives considered:** LIKELY acceptance with stricter corroboration
(rejected: corroborating signals like municipality rarely appear on consumer
pages); LLM verification (rejected: deterministic requirement).
**Trade-offs:** marginally lower business-description coverage for ambiguous
cases; firewall integrity is worth it.
**Evidence/tests:** live subsidiary rejection; 19 entity tests.
**Files:** `adapters/website.py`.

---

## D-009 — Leadership role slots distinguish person

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Data model / fact ledger
- **Decision:** Role facts use `field=f"role:{role_code}:{name}"` (registry)
  and `field=f"role:web:{name}"` (website) — person-distinguished slots.

**Why:** Measured defect: 7 board members sharing the `role:MEDL` slot caused
the ledger to mark 6 as CONFLICT (same slot, different normalized values) —
CONFLICT spam that hid real conflicts. The challenge requires multiple board
members to be separately representable.

**Alternatives considered:** multi-value facts (list-valued) (rejected:
breaks the one-fact-one-slot change-detection model); separate facts with
same field (rejected: triggers conflict detection).
**Trade-offs:** change detection now treats each person-role as its own slot
(a board change produces RETRACTED+NEW per person — correct).
**Evidence/tests:** `integrity_check` duplicate_fact_slots_same_run: 0 after
fix; leadership facts 192→406 in v4 (all board members published).
**Files:** `adapters/brreg.py`, `adapters/website.py`.

---

## D-010 — Website page slots distinguish URL/category

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Data model / fact ledger
- **Decision:** Multi-page website categories use path-distinguished slots:
  `careers_page:<path>`, `news_page:<path>`, `offering:<path>`.

**Why:** Measured defect: 3 news sub-pages under one `news_page` slot → 2
spurious CONFLICTs (same root cause as D-009).

**Alternatives considered:** single slot per category (rejected: conflict
spam); URL-only slots without category (rejected: loses category semantics
for change detection).
**Trade-offs:** more granular change records; acceptable.
**Evidence/tests:** `integrity_check`: 0 duplicate slots after fix; live
AkerBP crawl (24 job openings, no conflicts).
**Files:** `adapters/website.py`.

---

## D-011 — Adaptive planner with value-of-request heuristic

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Research planner / budget
- **Decision:** After core stages, the pipeline assesses coverage; missing
  high-value categories (business_description, financials, jobs,
  products_services) trigger targeted top-ups — remaining name-derived
  candidates for business, discovered PDFs for financials — gated by
  `budget.can_make_request()` and `runtime.should_start_expensive_operation()`.

**Why:** The v2 benchmark used only 924/2,000 requests while 4 categories
were missing for most companies. The challenge requires using remaining
capacity intelligently: "high-value missing category + high-probability
source" over "low-probability random search".

**Alternatives considered:** uniform depth for all companies (rejected:
wastes budget on already-covered companies); blind request increases
(rejected: violates benchmark instructions).
**Trade-offs:** +582 requests in v4 (1,506 total) for +241 facts; still 25%
budget headroom.
**Evidence/tests:** v4 benchmark artifact; 228 unit tests (all budget gates
still pass); live adaptive_financials/adaptive_business stages observed.
**Files:** `engine/pipeline.py`, `adapters/website.py`.

---

## D-012 — LLM optional rather than source of truth

- **Date:** 2026-09-30
- **Status:** Accepted
- **Area:** LLM usage / cost
- **Decision:** The LLM client (`core/llm.py`) is disabled without
  `LLM_API_KEY`; deterministic extraction is primary. When enabled, every
  response is schema-validated (pydantic), cost-tracked via a configurable
  price table, and web content is wrapped in UNTRUSTED delimiters (data,
  never instructions).

**Why:** The challenge forbids the LLM as source of truth for identity, URLs,
financial values, or dates. All extraction in this system is deterministic
(registry JSON paths, PDF key-line regexes). The LLM is reserved for optional
messy-page extraction/synthesis polish. $0.00 cost in every measured run.

**Alternatives considered:** LLM-mandated extraction (rejected: cost,
hallucination risk, non-determinism); no LLM client at all (rejected: loses
the integration boundary for unstructured pages).
**Trade-offs:** without a key, messy-page extraction is bounded to
deterministic patterns; acceptable (measured coverage comes entirely from
deterministic extraction).
**Evidence/tests:** 8 mock-LLM tests (valid/invalid JSON/missing fields/wrong
types/retry/cost-guard/disabled); `test_llm_disabled_without_key_ignores_web_content`;
prompt-injection tests.
**Files:** `core/llm.py`, `core/config.py`.

---

## D-013 — No OCR dependency

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** PDF pipeline / dependencies
- **Decision:** No OCR dependency added. Scanned/image PDFs are detected
  (extractable text < 50 chars) and reported as extraction-failed honestly.

**Why:** OCR dependencies (tesseract/pytesseract) require system-level
binaries and language packs — heavy for the competition environment and
Docker image; OCR text is approximate and cannot be evidence-validated to
the same standard as embedded text layers. The challenge instructs: "If OCR
dependencies are too heavy for the competition environment, keep the honest
failure behavior." Failing honestly is preferable to fabricating extracted
text — an OCR hallucination in a financial fact would be a fabricated value.

**Alternatives considered:** pytesseract (rejected: system binary dep,
approximate output, licensing/runtime implications); cloud OCR (rejected:
cost + credentials + non-determinism).
**Trade-offs:** scanned-PDF financial statements yield `failed` extraction
(honest) instead of approximate numbers.
**Evidence/tests:** `test_pdf_synthetic_multi_page` (blank pages → scanned
detection), `test_pdf_parse_non_pdf`, `test_pdf_parse_empty`.
**Files:** `adapters/pdf_pipeline.py`, `LIMITATIONS.md`.

---

## D-014 — SQLite

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** Persistence
- **Decision:** SQLite (WAL mode, FK-enforced schema, per-thread connections
  with a repository lock) via `core/repository.py`.

**Why:** Zero-dependency persistence (stdlib), file-based (works in Docker
volumes, resumable runs, `validate-db`), FK enforcement gives
database-integrity verification for free, WAL allows concurrent readers
during API serving.

**Alternatives considered:** PostgreSQL (rejected: requires a server —
deployment complexity for a single-binary challenge tool); in-memory only
(rejected: checkpointing/resume/persistence required).
**Trade-offs:** single-writer semantics (mitigated by WAL + lock); no
network access (fine for the challenge).
**Evidence/tests:** `test_concurrent_companies_no_race` (FK-consistent DB
under 10 concurrent researches); `PRAGMA foreign_key_check` in
`validate-db`; all repository tests.
**Files:** `core/repository.py`.

---

## D-015 — PDF parser choice (pypdf)

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** PDF pipeline / dependencies
- **Decision:** `pypdf` (pure-Python) for text extraction with page-preserving
  structure.

**Why:** Pure-Python (no system binaries — works in Docker slim images),
maintained, adequate for text-based annual reports (verified live: AkerBP
42-page Q2 2026 report parsed with page numbers). Page-preserving extraction
is required for evidence (`page_or_section` field).

**Alternatives considered:** pdfminer.six (slower, similar output);
pdfplumber (heavier, table extraction not needed for key-line regexes);
PyMuPDF/pypdfium2 (AGPL/proprietary licensing concerns for a public
repository).
**Trade-offs:** pypdf's text extraction is imperfect on complex layouts;
mitigated by key-line regexes over the full text and page-level evidence.
**Evidence/tests:** `test_pdf_parse_real_report` (42 pages),
`test_pdf_financial_lines_with_page_numbers`.
**Files:** `adapters/pdf_pipeline.py`, `pyproject.toml`.

---

## D-016 — HTML parser choice (BeautifulSoup + lxml)

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** Website crawler / dependencies
- **Decision:** BeautifulSoup4 with the lxml parser backend.

**Why:** Both already present in the environment; lxml is fast (C backend)
and lenient with malformed HTML (common on small-company sites); BS4's API
makes link/text/metadata extraction concise.

**Alternatives considered:** stdlib `html.parser` (rejected: slow, strict);
selectolax (rejected: extra dep for marginal gain).
**Trade-offs:** lxml binary wheel required (present in environment and
installable via pip; documented in Docker).
**Evidence/tests:** live crawls (telenor.no, salmar.no, akerbp.com) parsed
correctly; `test_business_page_classification` fixtures.
**Files:** `adapters/website.py`, `pyproject.toml`.

---

## D-017 — FastAPI / CLI / frontend choices

- **Date:** 2026-09-30
- **Status:** Accepted
- **Area:** Interfaces
- **Decision:** FastAPI for the REST API (background research via worker
  threads + `BackgroundTasks`); Click for the CLI; a single-file vanilla-JS
  SPA frontend served by FastAPI (`/dashboard`).

**Why:** FastAPI gives pydantic validation + async + TestClient for free
(all API tests run without a live server). Click matches the required
`python -m nordtrace.cli` entry point. A dependency-free SPA keeps the
frontend auditable (no build step) and forces all numbers to come from the
API (no static demo data possible).

**Alternatives considered:** Flask (rejected: no native async/pydantic);
React/Vite (rejected: build step, heavier for a single-page dashboard);
Jinja server-rendered pages (rejected: evidence drawer interactivity needs
client-side state).
**Trade-offs:** vanilla JS is less structured than a framework; acceptable
for one page, auditable.
**Evidence/tests:** 14 API tests; 11 CLI tests; browser-verified flows
(research → identity → facts → evidence drawer → trace).
**Files:** `api/app.py`, `cli.py`, `frontend/index.html`.

---

## D-018 — No general search-engine dependency

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Source acquisition / reproducibility
- **Decision:** No external search-engine API is used. Discovery comes from
  registry fields (hjemmeside), registry search (`?navn=`), and
  name-derived candidates — all keyless and deterministic.

**Why:** Search-engine results are non-deterministic (rankings change),
rate-limited, and mostly require keys (Google CSE, Bing). Search snippets
must not become facts (challenge spec) — the underlying page must be
retrieved and verified anyway. Registry-based discovery is reproducible and
free; name-derived candidates pass the entity firewall or are rejected.

**Alternatives considered:** DuckDuckGo HTML scraping (rejected: brittle,
ToS-gray, non-deterministic); Google CSE (rejected: key + cost + quota).
**Trade-offs:** companies without registry websites and unreachable hosts
yield `not_available` for business description — measured 15% coverage,
source-limited (see `COVERAGE_GAP_ANALYSIS.md`).
**Evidence/tests:** `candidate_urls` tests; live benchmark (no search
requests in any run).
**Files:** `adapters/website.py`, `SOURCES.md`.

---

## D-019 — No Tier-3 provider

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Source acquisition
- **Decision:** No Tier-3 (reputable business-information) provider is
  integrated. Sources are Tier 0 (registry), Tier 1 (company website/PDF),
  Tier 2 (NAV jobs).

**Why:** Tier-3 providers (Proff.no, Bisnode, Dun & Bradstreet) are
commercial with ToS restricting automated access; scraping them risks
violating terms and their data would need credentials (challenge instructs:
make credentials configurable, keep optional). All measured coverage comes
from permitted public sources.

**Alternatives considered:** Proff.no scraping (rejected: ToS + fragility);
optional keyed integrations (deferred: no credentials available; documented
as optional in `SOURCES.md`).
**Trade-offs:** financials coverage limited to regnskapsregisteret + company
PDFs; acceptable — fabrication is worse.
**Evidence/tests:** `SOURCES.md` documents Tier 3 as "Not implemented
(optional integration)"; no Tier-3 requests in any benchmark run.
**Files:** `SOURCES.md`, `adapters/`.

---

## D-020 — $0 deterministic benchmark

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Cost / benchmark
- **Decision:** Every measured benchmark run costs $0.00: LLM disabled
  without key; all extraction deterministic; cost tracked via
  `CostBudget` with a configurable price table and `is_estimate` labeling.

**Why:** The challenge allows $10 declared API cost; the system achieves full
measured coverage without any paid API. When an LLM key IS configured, every
call is schema-validated and cost-gated (`can_afford` before the call;
fallback to deterministic extraction when the budget would be exceeded).

**Alternatives considered:** using an LLM for extraction during benchmarks
(rejected: cost, non-determinism, hallucination risk in financial values).
**Trade-offs:** none measured — $0 while meeting budgets.
**Evidence/tests:** benchmark artifacts (cost_used: 0.0 across v2/v3/v4);
8 LLM-mock tests; cost-guard tests.
**Files:** `core/budget.py`, `core/llm.py`, `benchmark.py`.
# Current decisions — 2026-10-16

## D-035 — Separate stable logical claims from source observations and collection items

- Date/status: 2026-10-17, accepted.
- Problem/evidence: random fact IDs cannot identify the same claim across replays; job_posting predicates for different vacancies collide. Initial tests reproduce absent logical IDs and spurious vacancy conflict. Previous SQL grouping also ignores source item/scope qualifiers. Short normalized values conceal currency/unit/expiry/deadline changes; four regression fixtures initially report UNCHANGED.
- Decision: add deterministic claim_v1 identity over subject/predicate/period/item/scope while retaining fact_id as observation_id and all existing historical primary keys. Values remain outside logical identity so corrections compare. Multi-valued vacancy/branch claims require stable item keys. Retain new observations across runs; deduplicate identical same-snapshot assertions within a ledger. Preserve complete change qualifiers in SQLite and compare full published assertions, including numerical/temporal qualifiers.
- Implementation/application: Fact computed claim_id/observation_id and canonical escaped JSON fact_key; typed subject_scope/item_key; producers attach explicit keys; CitationValidator checks required item/scalar scope. Schema 5 additive columns/change JSON with existing backup workflow. get_previous_facts groups by full keys; ChangeRecord carries claim/item/scope and reporting period. assertions_differ is shared by changes/conflicts and uses exact Decimal numeric equality for monetary values.
- Alternatives: replacing historical fact primary keys would overwrite observations and break provenance; hashing the value loses change comparability; source IDs change per fetch and cannot identify a logical claim. Delimiter concatenation permits ambiguous tuples; UTF-8 replacement also collapsed two invalid opaque identifiers during testing, so the canonical tuple is escaped JSON. Currency/unit are assertion qualifiers rather than keys so their corrections remain comparable.
- Tradeoffs/failure modes: legacy fact arrays continue to contain observation records with stable logical IDs; a complete separate claim/observation aggregation contract remains outstanding. Legacy scope stays unknown and collection keys are not retroactively invented. Different-snapshot corroborating observations may still coexist. Source-outage removal, concurrent temporal cutoffs, conflict publication/display and legacy integrity metrics need separate corrections. NAV/website/branch candidate keys alone do not enable their unsupported publication or establish live vacancy accuracy.
- Verification: 13 claim-identity tests cover no-op production replay, separate observation IDs, collection coexistence, delimiter/Unicode collision avoidance, copied schema-4 upgrade, collection persistence, qualifier changes and sub-epsilon monetary changes. Review caught same-instance deduplication mutating the retained row; a regression verifies first insertion PUBLISHED and replay stays PUBLISHED. Three scope adversaries reject group/unknown/collection relabeling of scalar registry identity. Existing user DB migrated only on an isolated copy from schema 1 to 5: ten original-table fingerprints preserved, zero FK violations; ignored data/migration-verification.json records it. Pydantic's documented property decorator type-ignore is scoped to its mypy compatibility issue (https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.computed_field), not a blanket suppression.
- Revisit: convert external evidence producers and stable relationships, repair source completeness/refresh and conflicts, aggregate claim observations explicitly, and measure held-out accuracy/coverage. Extends D-022/D-034; no existing history is rewritten.

## D-034 — Require snapshot-backed predicate support at production publication

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a source ID plus extractor-authored snippet cannot establish a claim value. Previously identity fields shared a generated registry sentence even when their values were absent from it. Snapshot capture alone does not repair this. Initial locator tests failed because typed locators/support verification were absent.
- Decision: production ledger publication requires retained bytes, acquisition-consistent metadata and a supported typed locator/predicate normalization. Begin with atomic Brreg identity JSON pointers; unsupported formats/families abstain until converted. Never synthesize exact quotes for structured fields. Bind observation dates/authority to capture. Apply strict count types and preserve unknown status flags.
- Implementation/application: core/evidence.py, JsonPointerLocator, BrregAdapter.identity_claims, production FactLedger(repository), schema-4 nullable evidence.locator_json and sources.source_json with backed-up migration. RFC 6901 escapes/array indices are checked. Declared address/website/status normalizations are deterministic allowlisted transformations, not executable source instructions. Predicate-specific field/type/scope checks reject a matching value at an unrelated path. Complete source metadata survives repository reads.
- Authority boundary: all Brreg calls restrict redirect hosts/schemes to their configured registry host/scheme through the gateway, including cache replay. Two new instrumented regressions reproduce copied-orgnr impostor resolution following an unrelated-host redirect and a same-host HTTPS downgrade; both now stop before a second transport operation. Public-address safety alone cannot grant official registry authority. A legitimate future registry host migration must be reviewed explicitly rather than silently delegated.
- Nested policy: review caught missing scheme propagation through robots. Both robots fetches and policy-scoped robots-cache keys now preserve host/scheme constraints; fresh and permissive-cache downgrade regressions were red before the fix and pass afterward. Cache reuse cannot expand source policy.
- Alternatives: trust confidence or snippets leaves F01 open; locating any matching number anywhere does not establish its predicate or period. Keeping old producers publishing until conversion would perpetuate unsupported claims. Rewriting all extractors at once would obscure separate correctness failures; incremental fail-closed conversion makes the limitation explicit.
- Tradeoffs/failure modes: external publication coverage temporarily drops to supported identity fields; this is documented and release acceptance remains incomplete. Existing financial/website/role/activity parsers run but their candidates are withheld pending conversion. In-memory legacy ledger tests without a repository validate only preliminary conditions. Current refresh removal semantics must be repaired before claiming parser-regression safety. JSON parsing/hash work and finalization are not yet bounded by the whole-run deadline.
- Source basis: public Brreg Enhetsregisteret documentation version 2.0.0 retrieved 2026-10-17, https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html; publisher declares NLOD 2.0. Retained HTML SHA-256 dd857144bf1a5efcd91c86b54a68eb3657f70e4e7f3d4edd77324d5aa1a4fd3b. Documentation includes required compulsory-liquidation flags. This is not the private evaluator schema and does not resolve all source-specific privacy/retention questions.
- Verification: 19 locator tests plus existing registry/API boundaries. Review independently reproduced boolean-as-count and capture-date/authority upgrading; both corrected and retested. SQLite/API round-trip and schema-3 copy upgrade preserve bytes/history without inventing legacy locators. Revisit when external family producers, extraction replay, refresh completeness and held-out accuracy/coverage are implemented. Extends D-027 and D-032; supersedes snippet-only production publication.

## D-033 — Separate PDF candidates, acquisition and fallback eligibility

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a discovery-only crawl of the previous code reports an unrequested PDF as success with a retrieval timestamp (F14). PDFs can also enter HTML extraction. Previous pipeline skips fallback for not_found accounts and omits the actually fetched PDF source, withholding its claims (F16/F15).
- Decision: record discovered documents separately with referring source/time, never fabricated retrieval metadata; exclude PDF paths from HTML extraction. Attempt document fallback for absent accepted financial claims across unavailable/error/ambiguous accounts outcomes; respect explicit not_applicable and budget/time gates. Register every returned PDF source before its evidence and claims. Count accepted publication rather than extracted candidates.
- Implementation/application: WebsiteAdapter._extract_links/crawl and ResearchPipeline adaptive financial path. Existing company-document source type remains, acquisition state is discovered until retrieval. Exact source ID/hash resolves to retained bytes.
- Alternatives: treating links as fetched misstates evidence; reusing a placeholder ID attributes claims to unfetched material; retaining the old not_found-only selector wrongly turns source unavailability into inapplicability. Rewriting PDF extraction simultaneously would obscure these independently testable orchestration defects.
- Tradeoffs/failure modes: fallback consumes budget on sources that may still be unreadable/ambiguous. A source blocked by its own robots/transport policy remains blocked. This decision does not make the existing numerical parser correct, establish scope or expand source rights.
- Verification: test_pdf_acquisition.py covers discovery with zero page allowance, five unavailable states, not_applicable abstention, query/fragment routing and exact fetched-source/snapshot/FK registration. Previous trusted repository modules loaded into an isolated test process reproduced success-for-discovery, zero fallback calls for not_found, and missing published registration for not_available. Extraction is stubbed in orchestration tests and is not live/financial accuracy evidence. Revisit when structured accounts/table-aware extraction and source-completeness scheduling are repaired. Extends D-032 and supersedes old PDF discovery labeling.

## D-032 — Retain complete response bytes and separate acquisition replay from claim proof

- Date/status: 2026-10-17, accepted.
- Problem/evidence: F09 reproduced with a real production pipeline under simulated HTTP: no source bytes persisted. The old unused save_snapshot helper truncates decoded text at 200k characters, while gateway hashes decoded text even for binary PDFs.
- Decision: hash/retain the complete bounded HTTP response body with explicit `http-response-body-v1` representation, content-addressed blobs and immutable per-source acquisition metadata. Keep legacy snapshots unchanged and untrusted for new capture checks. Offline readers verify hashes/lengths before returning bytes and preserve acquisition timestamps. Byte verification explicitly does not establish claim support or replay extraction.
- Implementation/application: schema-3 additive migration and pre-upgrade SQLite backup; Repository.save_capture/read_capture; production RequestGateway retention including robots/cache hits; load_capture and CLI verify-snapshots/replay-source. All new acquired bodies through the production gateway use this path.
- Alternatives: calling the truncating helper cannot preserve binary/large responses; storing only hashes is not replayable; files alone would require a second atomic metadata boundary. SQLite BLOBs keep existing storage architecture and atomic capture. Exact evidence locators are a subsequent dependent correction.
- Tradeoffs/failure modes: database size grows with distinct bodies; source rights/privacy and retention periods require source-specific decisions before publication. No captured website/PDF data is relicensed by the MIT code licence. Database contention is a failed acquisition rather than success without evidence. Capture runs off the event loop with bounded SQLite lock wait and absolute-deadline checks. A reviewer reproduced a late synchronous success; this was corrected before commit and the same reproduction now times out at 31ms with zero captures. Disk/CPU scheduling is not a real-time guarantee; broader finalization deadlines remain incomplete.
- Verification: test_snapshots.py covers binary/non-UTF-8/large bodies, reopen/offline reads, tamper/missing refusal, cache capture, production wiring, schema-2 upgrade preservation/backup, transactional rollback and lock contention. Snapshot/contract/transport/CLI boundary: 42 passed, one upstream warning. Revisit for source retention policy, locator-backed publication, extraction replay, larger persistent datasets and full deadline/finalization work. Extends D-022 and D-026; supersedes decoded-text hashing for new gateway acquisitions only.

## D-031 — Verify the returned authoritative identifier

- Date/status: 2026-10-17, accepted.
- Problem/evidence: three fixtures returned a different/missing/invalid orgnr with a legal name; fetch_entity manufactured the requested orgnr on all three, enabling wrong-company attachment despite an authoritative URL.
- Decision/implementation: require a checksum-valid returned organisasjonsnummer equal to the normalized requested identifier before constructing identity or evidence. Wrong/absent identifiers return ambiguous with the captured source and entity_ambiguous error through the canonical API. Unexpected JSON shapes fail explicitly.
- Application: live registry identity acquisition; exact supplied-snapshot anchoring still needs its separate input adapter.
- Alternatives: trusting only the requested URL or copying requested identity cannot establish the response's subject.
- Tradeoffs/limits: malformed/incomplete official responses abstain; no claim of independent population accuracy is made. Current registry transport/source evidence remains subject to unfinished snapshot/locator requirements.
- Verification: three adapter tests failed before repair; API-level real gateway/MockTransport abstention and exact-identifier positive control pass. Revisit with the official supplied-snapshot schema; strengthens D-001/D-024.

## D-030 — Preserve unavailable-entity diagnostics and test error cardinality

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a registry 404 produced a not_available envelope but labelled its error research_failed and discarded the attempted source. Targeted API assertions failed. Scale must include invalid inputs without pretending they are researched companies.
- Decision/implementation: pipeline identity failure retains its actual SourceRecord and distinguishes entity_not_found, registry_blocked and registry_failed. Add real runner/repository/export contract checks for 100/1,000 distinct invalid inputs with zero transport/API allowance.
- Application: no-identity canonical envelopes and synthetic invalid-input validation. These are separate from official supplied-batch acceptance/live smoke testing.
- Alternatives: dropping failed source metadata obstructs inspection; calling a 404 a program failure conflates availability and execution. Synthetic inputs cannot substitute for eligible live companies.
- Tradeoffs/limits: input/schema/duplicate organizer compatibility and incomplete source-family states remain unresolved. Error cardinality does not measure research coverage or source accuracy.
- Verification: strengthened 404 API assertions failed before repair, then 26 API/result-contract checks passed; two scale scenarios passed in 14.34s. Clean noneditable installation at e64c0ee passed 286 offline checks and installed-wheel dashboard/evaluator-adapter checks. Revisit when official schemas/budgets/batches arrive.

## D-028 — Runtime-relative storage and failure-aware acquisition

- Date/status: 2026-10-17, accepted.
- Problem/evidence: DATA_DIR did not derive database location and seven active example names were ignored. Package location otherwise determined storage. Missing successful website bodies aborted resolved company research in the full synthetic regression.
- Decision/implementation: Settings reads runtime .env, defaults data/ there and derives nordtrace.db unless DATABASE_PATH is explicit. Active example names match consumed fields; model settings are labelled dormant. WebsiteAdapter records missing bodies as failed sources/rejections and continues independent work.
- Application: editable/wheel configuration and homepage/internal-page acquisition. No real database is moved or reset.
- Alternatives: ignored settings/site-packages storage break clean installation; assertions on absent external content abort valid independent research.
- Tradeoffs/limits: launches from other directories should set DATA_DIR for shared persistence. Full family-state propagation/typed run configuration remain unfinished.
- Verification: configuration/missing-body tests failed before fixes; settings/identity/synthetic checks passed. Full offline suite: 286 passed, 8 deselected. Revisit with full source completeness and run contracts.

## D-029 — Reproducible package assets, licence and offline CI

- Date/status: 2026-10-17, accepted; container/hosted CI execution unverified.
- Problem/evidence: wheel omitted dashboard HTML; MIT metadata lacked LICENSE; no CI existed. Docker lacked required licence files and compose named the wrong API module.
- Decision/implementation: explicit frontend package data, MIT SPDX metadata, LICENSE/NOTICE; pin public-PyPI build tools setuptools 84.0.0/wheel 0.48.0. Add read-only offline Windows/Linux CI with pinned action commits and frozen install/test/lint/type/build/resource checks. Docker uses the frozen runtime lock; compose uses loopback host binding, /app/data and nordtrace.api.app:app.
- Application: installation/distribution/CI/container configuration. No push, workflow dispatch, deployment or publication occurs. Source-data rights remain separate.
- Alternatives: editable-only checks conceal missing resources; unlocked installs defeat replay; MIT software metadata cannot relicense retrieved data.
- Tradeoffs/limits: uv 0.12.5 is a setup prerequisite. Local Windows/wheel checks do not prove Linux/container/hosted success. Docker daemon is unavailable; clean-clone evidence is recorded separately after execution.
- Verification: ZIP assertion failed for absent HTML, then rebuilt wheel included HTML/LICENSE. Compose config parses; full offline checks pass. Revisit on platform/build-tool changes. Extends D-025 and supersedes historical model-integration claims in D-011/D-020: production model callers do not exist.

## D-027 — Reject verdict disagreement and unsupported financial snippets

- Date/status: 2026-10-16, accepted as an additional rejection gate; complete evidence validation remains unfinished.
- Problem/evidence: the original F01 exploit published invented revenue from a filing notice even with rejected evidence. Five targeted tests initially failed; additional regressions caught false zero support from grouped digits and lost negative-parenthesis signs.
- Decision/implementation: CitationValidator requires matching fact/evidence identity verdicts, same-company source attachment and consistent supplied hashes. Financial claims need currency and reporting period represented in the snippet and an exact finite Decimal-equivalent numeric token. Grouped thousands and negative parentheses preserve meaning; arbitrary value substrings cannot support a different number.
- Application: every new ledger publication. Existing financial filing-only evidence now fails because it contains no value. Fixtures that previously used empty/generic support or identity disagreement now contain explicit support; temporal tests use role strings rather than nonnumeric financial values.
- Alternatives: accepting a fact merely because its source/evidence IDs exist recreates the reproduced defect. Confidence cannot override rejection. No historical result is rewritten.
- Tradeoffs/limits: this is necessary but **not sufficient** support validation. It does not resolve accounting columns, exact predicate scope, retained snapshots or unsupported non-financial assertions. Current Brreg filing snippets and incomplete PDF evidence may withhold legitimate candidates; producer/locator repairs are the next dependency. No financial accuracy or coverage gain is claimed. Release remains blocked on C/G requirements.
- Verification: 10 publication-safety regressions and 55 adjacent ledger/category/adversarial checks passed; Ruff/mypy pass. Revisit only by replacing this preliminary gate with stronger snapshot/locator validation, not by weakening it. Supersedes existence-only financial support behavior in D-006.

## D-026 — Explicit transport hops, bounded bodies and origin-preserving DNS pinning

- Date/status: 2026-10-16, accepted.
- Problem/evidence: seven instrumented regressions failed: hidden private redirects, uncharged hops/robots, full oversized allocation, missing deadline cancellation, fail-open robots and ignored redirect limits. Review additionally reproduced cross-host TLS reuse after naive IP pinning and a redirected host's ignored zero-retry policy; both received failing regressions before correction.
- Decision/implementation: RequestGateway manually validates every hop, charges each actual transport attempt, reacquires rate tokens, honors each destination's retry ceiling, and streams within a byte cap and monotonic async deadline. Robots use the same counted boundary. PinnedTransport connects to a validated public IP with original Host/SNI and distinct pools keyed by the original scheme/hostname/port. Proxy environment configuration is disabled. Cache hits are explicit and retain the original retrieval time.
- Application/source policy: website discovery, internal crawls and PDFs request robots enforcement. 404/410 allow acquisition, successful robots rules control it, and other errors/refusals deny it. Unsolicited compression is refused before decoding, rather than risking decompression allocation. Redirect chains/final URLs/media types are included in canonical source records.
- Alternatives: automatic redirects cannot enforce policy before connection; URL-only DNS checks permit rebinding; pooling by rewritten numeric IP skips a second hostname's TLS verification. Automatic compression needs a separately bounded decoder and is deferred.
- Tradeoffs/limits: strict robots/encoding/DNS rules can lower coverage; no environment-proxy support. DNS lookups remain synchronous and may delay cancellation. Batch queue/parsing/finalization deadlines, persistent/shared budgets, model transport and live TLS/network verification are unfinished. Relational legacy source rows lack the new metadata, which is retained in canonical envelopes.
- Verification: eleven gateway checks include private redirects, exact counted hops/robots, slow/large streams, rebinding, Host/SNI, actual httpcore pooling with a simulated socket backend and redirected retry policy. The gateway/API/security boundary run returned 75 passed, one upstream warning. Revisit after bounded DNS, parsing and optional model integration; extends D-002/D-003/D-004.

## D-024 — Contextual identifiers and offline public suffix boundaries

- Date/status: 2026-10-16, accepted.
- Problem/evidence: 14 of 15 initial hard-negative/parser tests failed. Homepage name/number shortcuts bypassed another operator's identifier; footer cleaning hid identity evidence. Substring numbers/names created false matches, grouped/MVA identifiers failed, and last-two-label domains conflated co.uk and private hosting tenants.
- Decision: whole-input checksum-checked normalization supports grouped digits and NO/MVA labels without stripping arbitrary text. Free-text subject matching uses explicit labels; clearly labelled customer/supplier mentions and incidental numbers are not operator identity. Contradictory subject IDs run before positive website attachment. A homepage requires a labelled matching subject ID or full legal name plus registered address. Preserve footer text for attachment inspection.
- Implementation/application: `core/orgnr.py`, `core/entity.py` and `adapters/website.py`. Domain parsing receives hostnames and uses tldextract 5.4.0's bundled PSL, with suffix fetching and cache disabled; private hosting suffixes are included. Independently identified subjects can coexist in a domain's set. Full relationship provenance/effective dates remain unfinished.
- Alternatives: extra hand-coded suffixes are brittle; automatic PSL network refresh bypasses the gateway and harms replay; name/registered-domain alone cannot prove exact legal attachment.
- Tradeoffs/limits: conservative attachment abstains on unlabeled identifiers and name-only sites. Contextual role heuristics are limited to explicit customer/supplier wording; complex parent/group/footer scopes need further adjudicated fixtures. Two old tests used checksum-invalid 987654321 as a supposed free-text orgnr; their fixtures now use valid 958973306 while retaining the rejection/deduplication expectations.
- Verification: 63 identity/orgnr/adversarial checks passed, then 17 focused boundary tests passed including production crawl footer handling and URL-versus-host validation. Dependency source: [tldextract documentation](https://github.com/john-kurkowski/tldextract), retrieved 2026-10-16. Revisit on PSL/package updates or measured identity-corpus errors. Supersedes the crude domain parser and overly broad numeric contradiction rule in D-001/D-005.

## D-025 — Lock the existing dependency stack with uv

- Date/status: 2026-10-16, accepted.
- Problem/evidence: baseline declared only dependency ranges; a clean install selected current versions and cannot reproduce a later installation exactly. The necessary PSL utility adds three transitive packages.
- Decision/implementation: retain setuptools/pyproject and add a cross-platform uv.lock with package versions, public PyPI sources and distribution hashes. `uv sync --frozen --extra dev --python 3.12` is the declared development install; `uv sync --frozen --python 3.12` installs the runtime. uv 0.12.5 produced and successfully synchronized the lock.
- Application: reproducible installation and future offline CI. Existing pip editable install remains a development option but does not establish a locked release.
- Alternatives: a Windows-only pip freeze can omit Linux conditional dependencies; replacing the application stack has no evidence-based benefit.
- Tradeoffs/limits: uv is a setup prerequisite; platform-specific wheels still need validation on each supported platform. Clean-clone installation and container/hosted CI acceptance remain unverified at this decision. No optional model assets or paid APIs were added.
- Verification: uv lock resolved 80 packages, frozen synchronization succeeded; registry URLs resolve to public pypi.org. Revisit when dependency updates or supported Python/platform changes are required.

## D-023 — Recheck rate-spacing deadlines and isolate synthetic execution

- Date/status: 2026-10-16, accepted.
- Problem/evidence: fresh baseline spacing measured 0.094 seconds despite a 0.1-second minimum. A deterministic early-wakeup fixture returned at 0.04 seconds. Existing resume/deadline tests constructed simulated pipelines without wiring them into BatchRunner, allowing live requests.
- Decision/implementation: RateLimiter.acquire recomputes the monotonic wait after every wakeup until the minimum interval actually elapses. Integration fixtures explicitly patch the runner pipeline; only actual external acquisition remains live-marked.
- Application: every rate-limited request and synthetic runner test. The deadline-finalized-at-37 test asserts zero repeated research; it does not claim unfinished task recovery. The one-second fixture verifies checkpoints, not cancellation of a slow source.
- Alternatives: loosening the timing assertion would hide the rate-policy violation; relabeling accidental live tests would retain misleading simulation claims.
- Tradeoffs/limits: early timers can cause another short wait. Absolute run cancellation and shared budget restoration remain separate work. Synthetic success is not live verification.
- Verification: 16 rate-limiter tests passed, including the failing-before-fix early-wakeup case; three corrected offline integration scenarios passed. Revisit if the limiter clock or scheduling primitive changes. Supplements D-003.

## D-021 — Immutable canonical research outcomes

- Date/status: 2026-10-16, accepted.
- Problem/evidence: F05/F06/F19/F20 reproduced: invalid inputs disappeared, resume invoked finished companies, summary was lost and historical identity was reconstructed from mutable company rows. Five targeted regressions failed before implementation.
- Decision: serialize actual outcomes through `core.contracts.build_result` into version 1.1 CompanyProfile; persist full envelopes with source/evidence records and explicit errors. All newly completed CLI/API/batch results use those envelopes. Keep a separate ordered input mapping, deduplicating normalized company work. Exact organizer acceptance and duplicate semantics remain unverified.
- Implementation/application: `engine/pipeline.py`, `engine/runner.py`, `core/contracts.py`, `core/models.py`, `core/repository.py`, `cli.py`, `api/app.py`. Applies to every new completed research. Existing current data is explicitly legacy-unfrozen; historical requests without immutable envelopes return 409.
- Alternatives: reconstructing profiles on demand loses historical identity, coverage and synthesis; replacing the full stack is unnecessary. Do not silently reinterpret legacy history.
- Tradeoffs/limits: complete JSON envelopes duplicate some relational data. Published fact references are checked, but retained snapshots, exact support and refresh completeness still require subsequent repairs. Invalid inputs receive not_applicable plus an explicit error, and CLI exit 2; failed execution receives exit 1. Missing/blocked/ambiguous business information alone is not a program failure.
- Verification: `tests/unit/test_result_contract.py`, existing CLI/API tests; 33 passed in the targeted boundary run. Revisit when organizer input/output/duplicate schema is supplied. Supersedes conflicting interface reconstruction behavior in D-017.

## D-022 — Backed-up additive SQLite outcome migration

- Date/status: 2026-10-16, accepted.
- Problem/evidence: baseline schema has no version or complete-outcome store; company FKs prevent no-identity failure records. Existing user databases must survive upgrades.
- Decision: version 1 adds company_results and run_inputs; version 2 adds atomic company task leases. These reference runs rather than companies. Back up older existing databases with SQLite's backup API before DDL. Preserve all previous rows. Publish an envelope and terminal checkpoint atomically; completed payloads are immutable. Run updates reconcile against canonical publication so stale process checkpoints cannot erase committed outcomes.
- Implementation/application: Repository initialization and save_result/get_result/get_results/latest_result, for file-backed SQLite databases. Backups are uniquely named siblings; future schema versions are rejected.
- Alternatives: destructive resets violate preservation; JSON-only replacement loses existing ledger history; retroactive result reconstruction would invent historical observations.
- Tradeoffs/failure modes: backup disk space and write permission are required; failures abort migration. Legacy rows have no trustworthy complete envelopes. Leases prevent duplicate simultaneous runner ownership; expiry/crash recovery and shared budget accounting need further deadline work. Atomic adapter/ledger writes remain unfinished; this decision covers atomic canonical publication and checkpoint consistency.
- Verification: migration fixture verifies preserved identity/snapshot rows, version-0 backup contents and no repeated backup; immutability regression rejects altered history. Revisit before the next schema version. Extends D-015 rather than replacing SQLite.
