# NordTrace — Verification Report

**Date:** 2026-10-01
**Repository commit:** `71a6d458a60cd9db3609dec7ac18265d3beb5d79` (main)
**Author:** `PrathamKapoor <prathamkapoor027@gmail.com>`
**Python:** 3.13.14 (Windows, win32)
**Environment:** Windows 11, AMD Ryzen 7 7435HS, local network with internet access

Every claim below corresponds to a command that was actually run on 2026-10-01.

---

## 1. Test results

| Command | Result |
|---|---|
| `python -m pytest tests/unit -q` | **181 passed**, 1 warning (anyio deprecation, not ours), 47–55s |
| `python -m pytest tests/integration -q -m live` | **5 passed**, 72–74s (live network to Brreg + NAV) |
| Total | **186 passed** |

Unit suite coverage:
- orgnr validation: 18 tests (valid registered, checksum failures, separators, digit counts)
- entity matching: 19 tests (foreign orgnr, similar names, parent/subsidiary, brand, domains)
- ledger/changes: 20 tests (citation validation, conflicts, temporal, source-unavailable, change types)
- budget/security: 28 tests (hard stops, atomicity, runtime phases, cost formula, SSRF, URLs)
- adapters: 38 tests (PDF extraction incl. real 42-page report, number parsing, classification, contacts, addresses)
- API: 14 tests (all endpoints, validation errors, 404s, dedupe)
- CLI: 11 tests (help, CSV parsing, invalid input, validate, result structure)
- adversarial: 11 tests (10 adversarial cases + firewall preference)
- security: 11 tests (URLs, secrets, prompt injection, input validation)

Live integration suite (5):
- `test_e2e_full_research` — orgnr → identity → facts → evidence → source chain → persisted
- `test_e2e_refresh_detects_changes` — same company ×2, previous facts + history preserved
- `test_budget_attack_request_limit` — exhausted budget → terminal state, counter unchanged (no bypass)
- `test_concurrent_companies_no_race` — 10 concurrent researches, counter within limit, FK-consistent DB
- `test_resume_skips_completed` — completed companies not rerun

## 2. Lint / type-check

Not run as a gate (no project lint config enforced in this environment; ruff/mypy
listed in pyproject optional-deps but not installed). Code is hand-formatted to
a consistent style. **Not verified via tooling — stated honestly.**

## 3. Live-source verification (actual runs)

| Check | Result |
|---|---|
| `python -m nordtrace.cli research 982463718` | `available`; 21–23 verified facts; 27 evidence; 13 sources; 13 requests; **$0.0000**; ~20–29s |
| `python -m nordtrace.cli validate /tmp/result.json` | `Validation passed.` |
| `python -m nordtrace.cli benchmark --limit 10` | 10/10 completed; 10/10 entity resolved; 0 ambiguous, 0 failed; 161 facts; 125 evidence; 17 rejected sources; **88/2000 requests**; **$0.0000/$10.00**; **22.7s/2700s**; budgets OK |
| 15-company batch (harness, concurrency 4) | 13/15 available; 15/15 entity resolved; 222 facts; 167 evidence; 31 rejected; **140/2000 requests**; 50.7s; **$0.0000** |
| Brreg entity lookup | 200 real data (TELENOR ASA); 404 for unregistered; checksum-invalid rejected |
| Brreg regnskap | 200 real FY2024/FY2025 figures (Equinor 67,956,000,000 USD; SalMar 24,024,793,000 NOK) |
| NAV jobs | 200 real postings (Telenor: 31 hits; Salmar AS: verified employer) |
| Real PDF pipeline | AkerBP Q2 2026 report: 42 pages parsed, 5 financial lines with page numbers |

## 4. Runtime / request / cost measurements

| Metric | Single company | 10-company | 15-company |
|---|---|---|---|
| Runtime | ~20–29s | 22.7s | 50.7s |
| Requests | 13 | 88 | 140 |
| Est. API cost | $0.0000 | $0.0000 | $0.0000 |
| Verified facts | 21–23 | 161 | 222 |
| Entity resolved | ✓ | 10/10 | 15/15 |

Extrapolated 100-company run: ~900 requests, ~6 min, $0.00 — within all budgets
(but **not executed**; see §6).

## 5. Demonstrated behaviors (live)

- **Identity lock**: `✓ registry identity verified` (dashboard badge from real Brreg data)
- **Evidence chain**: fact → evidence → source → URL → content hash, all persisted; browser-verified evidence drawer opens with real source URL + hash + entity verdict
- **Wrong-company protection**: foreign-orgnr candidates REJECTED (19 entity tests + adversarial suite); rejected sources visible in UI
- **Change intelligence**: same company ×2 → 23 unchanged facts detected; refresh preserves history
- **Budget intelligence**: dashboard shows real request/runtime/cost from run metadata
- **Honest uncertainty**: missing financials/leadership/jobs reported as "Not publicly available", never fabricated
- **Resume**: interrupted batch → `resume` skips completed companies, states preserved
- **Concurrency**: 10 parallel researches, counter exact, FK-consistent DB
- **Failure recovery**: NAV 429s handled (retry/backoff); Brreg 404 → not_found; malformed PDF → honest failure

## 6. Not tested / not executed

- **100-company benchmark: NOT RUN.** Registry rate limits (NAV 429s observed at
  15 companies) make it feasible but it was not executed in this environment.
  Reproduce: `python -m nordtrace.cli benchmark --limit 100`.
- **Lint/type-check: NOT RUN as a gate** (tools not installed here).
- **LLM path: NOT RUN live** (no API key configured). Deterministic fallback
  verified; schema-validation logic unit-tested; live LLM calls require `LLM_API_KEY`.
- **Docker build: NOT RUN** (Docker not available locally; Dockerfile +
  docker-compose provided, documented as untested locally).
- **Scanned-PDF OCR fallback: NOT IMPLEMENTED** (text-based PDFs verified;
  scanned PDFs honestly reported as extraction-failed).

## 7. Known limitations

See `LIMITATIONS.md`. Summary:
- Annual accounts: latest filed year via public regnskapsregisteret; custom-layout
  filers (banks/insurers) may be unavailable → `not_available`, never fabricated.
- Job employer verification is name-based (NAV carries no orgnr) → ambiguous
  postings rejected.
- No keyless general news search; recent activity from dated registry signals only.
- `hent-regnskap` paths are 404; working path is `/regnskapsregisteret/regnskap/{orgnr}`.

## 8. Quality gates (20 from audit spec)

| Gate | Status |
|---|---|
| 1. No TODO/stub in production paths | ✅ (grep-verified: no TODO/FIXME/pass in src/) |
| 2. Every claimed adapter executable | ✅ (live-verified: Brreg, regnskap, NAV, website, PDF, activity) |
| 3. Real registry lookup | ✅ (live: TELENOR ASA full identity) |
| 4. Real source retrieval | ✅ (gateway live: registry, NAV, company sites, PDFs) |
| 5. Evidence persisted | ✅ (SQLite evidence table, browser-verified drawer) |
| 6. Wrong-company evidence rejected | ✅ (firewall + 19 entity tests + adversarial suite) |
| 7. Financial values cannot be fabricated | ✅ (deterministic extraction; null → not_available; LLM disabled without key) |
| 8. Refresh detects actual changes | ✅ (live ×2 run: 23 unchanged detected; unit tests all change types) |
| 9. 2,000 request limit cannot be bypassed | ✅ (single gateway; hard stop tested; atomic counter; no bypass) |
| 10. Global runtime deadline exists | ✅ (RuntimeBudget + phases; deadline-reached tested) |
| 11. CLI performs research | ✅ (live research command verified) |
| 12. API performs research | ✅ (background research verified via TestClient) |
| 13. Frontend displays real backend state | ✅ (browser-verified; zero static demo data) |
| 14. Batch execution works | ✅ (10 + 15-company runs) |
| 15. Resume works | ✅ (interrupt + resume verified) |
| 16. End-to-end test passes | ✅ (5 live integration tests) |
| 17. No fake benchmark claims | ✅ (harness computes from artifacts; correctness note honest) |
| 18. No secrets | ✅ (grep-verified) |
| 19. Git identity correct | ✅ (`PrathamKapoor <prathamkapoor027@gmail.com>`) |
| 20. Clean repo installable | ✅ (`pip install -e .` used; `python -m nordtrace.cli` works) |

## 9. Reproduce everything

```bash
python -m pytest tests/unit -q
python -m pytest tests/integration -q -m live
python -m nordtrace.cli research 982463718 --output result.json
python -m nordtrace.cli validate result.json
python -m nordtrace.cli benchmark --limit 10
python -m nordtrace.cli serve   # → http://127.0.0.1:8000/dashboard
```
