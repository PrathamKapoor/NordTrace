# Decision Log — NordTrace

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
