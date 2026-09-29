# NordTrace — Forensic Audit Report

**Audit date:** 2026-09-29
**Prior claim:** "complete NordTrace Norwegian company intelligence agent"
**Audited commit:** `5fa0068`

---

## 1. Claim-by-claim findings

| # | Claim (from prior README/report) | Actual implementation | Evidence | Gap | Severity | Required fix |
|---|---|---|---|---|---|---|
| 1 | "Registry adapter (Brreg) with timeout/retry/caching" | `BrregAdapter.resolve` performs an HTTP GET but **discards the JSON body** — never parses it, never builds `CompanyIdentity` from it. `extract_facts` fabricates two facts from the constructor argument, not from source data. No retry, no cache. | `src/nordtrace/core/adapters.py:34-116` — response consumed only for status/hash; comment on line 87 admits "In a real implementation, parse registry JSON". | Registry research non-functional. Identity comes from caller, not registry. | **Critical** | Parse real Brreg JSON into `CompanyIdentity` + facts; add retry/backoff/cache; route through RequestManager (currently bypassed via raw `httpx.AsyncClient`). |
| 2 | "Entity resolution and wrong-company firewall" | `EntityResolver.match` is string-contains on raw text with naive suffix-stripping (`replace("as","")` corrupts every word containing "as"). OrgNr contradiction check only after a 9-digit regex; no name-similarity scoring, no address/industry/website signals, no related-entity handling. | `src/nordtrace/core/entity.py:13-32`; `match("...987654321...", target 912345678)` returned `AMBIGUOUS` in first test run, not `REJECTED`. | Near-identical names merge; subsidiaries can be conflated with parents; firewall rejects nothing unless a 9-digit foreign number appears. | **Critical** | Rewrite with signal-based scoring (name similarity, orgnr, domain, address, municipality), normalized company-name handling for Norwegian suffixes, deterministic verdicts, adversarial tests. |
| 3 | "Request budget enforced globally, no bypass allowed" | `RequestManager` exists but **nothing uses it**. `BrregAdapter` calls `httpx.AsyncClient` directly. No other code path performs HTTP at all. The budget counter therefore counts only what voluntarily reports itself. | `grep -rn "httpx\|requests" src/` → only `adapters.py` (bypass) and `request_manager.py` itself. | Budget enforcement is vacuous today; real research will bypass or double-implement it. | **Critical** | Make `RequestManager` the sole HTTP gateway; adapters must take it as a dependency; add tests that prove bypass is impossible and limit cannot be exceeded. |
| 4 | "Runtime budget (45 min per-company/soft)" | `RuntimeBudget.deadline_reached()` returns `time_remaining() <= 120` — i.e. the *global* run reports "deadline reached" with 2 minutes left regardless of per-company state; `should_stop_expensive` threshold arbitrary; nothing in the pipeline consults it. | `src/nordtrace/core/budget.py:42-56`. No call sites. | Ambiguous semantics; no enforcement. | **High** | Implement global run deadline + per-company deadline; global wins; stages check between steps; tests with fake slow sources. |
| 5 | "Cost tracking ($10)" | `CostTracker` is a dict accumulator with no price table, no token accounting, no LLM integration (LLM client doesn't exist at all). | `src/nordtrace/core/budget.py:58-77`. No call sites. | Cost numbers can only be fabricated. | **High** | Implement LLM client with token usage capture, configurable price table, estimated-cost labeling; degrade gracefully without key. |
| 6 | "CLI (research, batch, resume, benchmark, validate)" | `research` writes a profile with `legal_name="Unknown (…)"`, zero facts, zero sources, `terminal_state="available"` — **fabricates success without research**. `batch` prints a message. `resume` prints a message. `benchmark` prints "Not fully implemented". `validate` checks 3 keys. | `src/nordtrace/cli.py:27-97`. | None of the commands perform research; results are misleading. | **Critical** | Wire all five commands to the real engine; remove fabricated "available" state. |
| 7 | "REST API" | Every endpoint returns hardcoded JSON (`{"status": "completed", "results": []}`), ignores the database entirely. `POST /research` returns `"status": "started"` without starting anything. | `src/nordtrace/api.py` full file. | API is a facade. | **Critical** | Back every endpoint with SQLite persistence; background research task for POST; validation errors for bad orgnr; 404 for unknown companies. |
| 8 | "Frontend works — evidence-first dashboard" | Single static HTML file. The search handler hardcodes `"Verified Company AS"`, `42 / 2,000 requests`, `$0.84` — **fake data presented as run output**. No fetch() to the API at all. | `src/nordtrace/frontend/templates/index.html` (`searchCompany()` sets fixed strings; "Run Dashboard" section is literal text). | UI displays fabricated results; violates benchmark-honesty rules. | **Critical** | Rebuild as real SPA against API endpoints; every number from backend; remove all hardcoded results. |
| 9 | "Benchmark harness runs batch evaluation" | `BenchmarkHarness.run_company` returns a **hardcoded dict** (`"verified_facts": 3, "request_count": 5, "duration_sec": 3.2`) for every company without doing anything. | `src/nordtrace/benchmark.py:14-24`. | Fake benchmark scores — exactly what the challenge forbids. | **Critical** | Real evaluator computing metrics from actual run artifacts; honest "not independently verifiable" where ground truth is absent. |
| 10 | "Database schema" | Tables defined (sources, facts, evidence, profiles, runs, changes) but **no foreign keys, no indexes**, and — critically — **nothing ever writes to or reads from it** except `init_db()`. | `src/nordtrace/core/database.py`; `grep init_db` → only README instructions. | Persistence is decoration. | **High** | Real repository layer with FKs, indexes, WAL, transactional writes; used by engine and API. |
| 11 | "Change detection / refresh" | `ChangeRecord`/models only. No comparison code exists anywhere. | `grep -rn "ChangeRecord" src/` → models.py only. | Refresh unimplemented. | **Critical** | Fact-level diff engine; snapshot hashes; preserved history; refresh tests. |
| 12 | "Website discovery / crawler / PDF / jobs / activity adapters" | **Directories `src/nordtrace/research/{crawler,financial,pdf,jobs,activity}/` are empty** (contain no files). No code exists. | `ls src/nordtrace/research/*`. | Entire research phase absent. | **Critical** | Implement all five for real, with live-source integration where permitted. |
| 13 | "Organisation number validation" | Checksum computed then **ignored** (`pass` on the 10 case; no boolean returned; validator only checks digit count). | `src/nordtrace/core/models.py` `validate_orgnr`. | Invalid orgnrs accepted. | **High** | Correct modulus-11 validation; tests incl. 917289121 (registered format but failing checksum) and valid known orgnrs. |
| 14 | "Tests cover important failure modes" | 4 tests total, one of which failed on first audit run (firewall not rejecting wrong company). Coverage of budget=2 trivial assertions; no adapter/API/CLI/refresh/security tests. | `pytest tests/ -v` → 4 items, 1 failure pre-fix. | Test suite cannot support any completion claim. | **Critical** | Expand per audit spec (identity 10+, entity 15+, evidence 15+, budget 10+, refresh 15+, adapters 15+, API 10+, CLI 10+, security 10+, E2E 5+). |
| 15 | "Security: prompt-injection defense via system instructions outranking crawled content" | No LLM integration exists → statement vacuous. No SSRF protections (crawler doesn't exist). `.env` gitignored correctly; no secrets found. | `grep -rn "llm\|LLM" src/` → config var only. | Unverifiable claim. | **High** | Implement trust boundary in real LLM path + SSRF guard for the real crawler + tests. |
| 16 | "Documentation complete" | Docs describe non-existent behavior (e.g. README claims frontend "works", benchmark "runs batch evaluation"). | README vs. items above. | Docs misrepresent reality. | **High** | Rewrite post-implementation: separate Implemented / Partial / Requires credentials / Not tested. |

---

## 2. Feature classification

| Feature | Status | Evidence | Required action |
|---|---|---|---|
| OrgNr validation | **BROKEN** | Checksum computed, result discarded | Fix + tests |
| Brreg lookup | **STUB** | HTTP call made, response body discarded | Real parse + models |
| Website discovery | **MISSING** | No code | Implement |
| Website crawling | **MISSING** | No code | Implement |
| Financial research | **MISSING** | No code (live API verified: `regnskapsregisteret`) | Implement |
| PDF extraction | **MISSING** | No code | Implement |
| Job research | **MISSING** | No code (live API verified: NAV stillinger) | Implement |
| Public activity | **MISSING** | No code | Implement |
| Entity matching | **PARTIAL** | String contains + buggy suffix strip | Rewrite w/ signals |
| Wrong-company firewall | **BROKEN** | Failed audit test pre-fix | Rewrite + adversarial tests |
| Evidence extraction | **MISSING** | No code creates Evidence | Implement |
| Citation validation | **MISSING** | No code | Implement |
| Fact ledger | **STUB** | Model exists, never persisted | Repository + FKs |
| Change detection | **MISSING** | No code | Implement |
| Refresh | **MISSING** | No code | Implement |
| Request budget | **STUB** | Exists, zero call sites, bypassable | Enforce via gateway |
| Runtime budget | **STUB** | Exists, ambiguous, zero call sites | Global deadline + tests |
| Cost budget | **STUB** | No pricing, no LLM | LLM client + price table |
| Batch execution | **STUB** | Prints message | Implement |
| Resume | **MISSING** | Prints message | Implement |
| LLM extraction | **MISSING** | No code | Implement + fallback |
| LLM synthesis | **MISSING** | No code | Implement + fallback |
| API | **STUB** | Hardcoded responses | Back with persistence |
| Frontend | **FAKE** | Hardcoded demo values | Rebuild as real client |
| Benchmark | **FAKE** | Hardcoded metrics | Real evaluator |
| Security (SSRF/injection) | **MISSING** | No attack surface exists yet | Implement with crawler/LLM |

**Conclusion: the prior "complete" report is false.** 9 of 26 features are missing entirely, 10 are stubs or broken, the two "works" claims (benchmark, frontend) are actively fabricated. The only genuinely working components are: module imports, 2 budget dataclasses, and a static HTML page.

---

## 3. Verified live sources (probe evidence, 2026-09-29)

| Source | Endpoint | Verified behavior |
|---|---|---|
| Brreg entity | `https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}` | 200 with full identity (Telenor ASA 982463718); 404 for unregistered; checksum-invalid numbers rejected |
| Brreg roles | `.../enheter/{orgnr}/roller` | 200; DAGL/STYR roles with names (SalMar 960514718: Frode Arntsen DAGL, Gustav Witzøe LEDE) |
| Brreg search | `.../enheter?navn=&overordnetEnhet=` | 200; name search works; `overordnetEnhet` filter returns 0 in practice (konsern not modeled) |
| Brreg underenheter | `.../underenheter?overordnetEnhet=` | 200; branch units with own orgnr |
| Brreg updates | `.../oppdateringer/enheter` | 200; cursor-paged change feed (`oppdateringsid`, `endringstype`) |
| Brreg regnskap | `https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` | 200; real FY2025 figures — Equinor 923609016: revenue 67,956,000,000 USD; SalMar 958973306: revenue 24,024,793,000 NOK; period, currency, journalnr present. **Note: `hent-regnskap` paths are 404; the working path is `/regnskapsregisteret/regnskap/`** |
| NAV jobs | `https://arbeidsplassen.nav.no/stillinger/api/search?q=` | 200; real postings w/ employer, title, location, published, expires, applicationdue, FINN reference. Employer has no orgnr → **entity verification required via name/domain** |
| Company websites | e.g. `telenor.no/om/` | 200; parseable text; some hosts fail TLS handshake (curl exit 35) → retry/fallback needed |
| LLM | none | No `LLM_API_KEY` configured in this environment → deterministic extraction is primary; LLM optional |

---

## 4. Fix plan (order)

1. **Foundation truth**: correct orgnr validation; RequestManager as the only HTTP gateway (budget, cache, robots, SSRF guard, size limits); real repository layer (FKs, WAL).
2. **Identity**: Brreg entity + roles + regnskap parsed into models; canonical entity resolution; signal-based entity matching; publication firewall.
3. **Research**: website discovery + focused crawler; PDF pipeline (financial statements when PDF-linked); NAV jobs adapter; activity via registry signals (registrations, konkurs, underAvvikling,oppdateringer) — no fabricated news.
4. **Evidence**: source/evidence records created for every retrieval; citation validator; fact ledger; conflicts; temporal fields.
5. **Refresh**: snapshots + fact-level diff; change records; preserved history; resume via run checkpointing.
6. **Intelligence**: coverage matrix; adaptive planner; LLM extraction behind schema validation with cost accounting + deterministic fallback; synthesis from ledger only.
7. **Scale**: bounded-async batch; deadline manager; checkpoint/resume; budget attack tests.
8. **API/UI**: real endpoints backed by SQLite; real frontend consuming API; evidence drawer; trace; run dashboard.
9. **Evaluation**: golden fixtures (labelled synthetic); adversarial suite (10 cases); live tests behind `-m live`; real benchmark evaluator.
10. **Docs**: rewrite honestly; VERIFICATION_REPORT.md with actual commands and results.

Every claim in the final README will map to a command that was actually run.
