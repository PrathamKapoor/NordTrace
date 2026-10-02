# Changes by Model / Session — Documentation & Traceability Pass

**Session date:** 2026-10-02
**Base commit:** `136d7ce` · **Intermediate commit:** `d8419f7` · **Final commit:** (this commit)
**Scope:** documentation consistency, decision log, execution-flow documentation.
**Code changes:** NO production code was changed in this session
(`git diff --stat d8419f7` — the final session diff — touches only FLOW.md,
MODEL_CHANGES.md, README.md; all documentation). All tests/lint/mypy re-run
after documentation edits.

### Session boundary

**Existing before this session** (committed at or before `136d7ce`/`d8419f7`):
all production code (`src/nordtrace/**`), all tests, benchmark artifacts,
AUDIT.md, ARCHITECTURE.md, METHODOLOGY.md, SOURCES.md, EVIDENCE_MODEL.md,
ENTITY_RESOLUTION.md, REFRESH_MODEL.md, COST_MODEL.md, LIMITATIONS.md,
COVERAGE docs.

**Changed by this session** (git diff vs starting commit `d8419f7`):
FLOW.md (+518 lines), MODEL_CHANGES.md, README.md (Engineering Transparency
section + doc index). No other files touched.

## What this session changed

| Change | Type | Files | Reason |
|---|---|---|---|
| Created `DECISIONS.md` | new doc | DECISIONS.md | Engineering decision log (D-001…D-020): WHAT/WHY/alternatives/trade-offs/evidence for every meaningful decision embodied in the system |
| Created `FLOW.md` | new doc | FLOW.md | Actual end-to-end execution flow with function-level relationships (inspected from code, not assumed); Mermaid diagram; failure paths |
| Created `MODEL_CHANGES.md` | new doc | MODEL_CHANGES.md | This file — session-level change record |
| Fixed stale commit reference `71a6d458` → `136d7ce` | doc fix | VERIFICATION_REPORT.md | Report pointed at an outdated HEAD; current submission commit is `136d7ce` |
| Fixed stale "Not run as a gate" lint/type-check section | doc fix | VERIFICATION_REPORT.md | Final verification proves ruff 0 errors + mypy 0 errors; contradiction removed, historical interim state labelled |
| Labelled interim live-source checks as HISTORICAL | doc fix | VERIFICATION_REPORT.md | Sections retained for traceability, explicitly marked superseded by final v4 verification |
| Fixed stale commit `c29db8c+` → `136d7ce` | doc fix | SUBMISSION_READINESS.md | Judge-facing commit reference must be HEAD |
| Fixed stale request count 924/2,000 → 1,506/2,000 | doc fix | SUBMISSION_READINESS.md | v4 artifact (`benchmark_result_v4.json`) measured 1,506 requests; 924 was the v2 baseline |
| Expanded `FLOW.md` (second pass) | doc rewrite | FLOW.md | Added required sections verified against code: Representative Call Chains (A–N with nested calls + line refs), Data lifecycle (where each transformation happens; source hashes/snapshots honestly marked not-in-main-path; temporal slots + all five change states), Implemented Decision Logic (rules/predicates/thresholds/heuristics — not model reasoning), Source selection flow (implemented adapters only), Security flow (decimal/octal/hex IP + CGNAT — implemented and tested), Budget flow (global vs source-specific, actual ordering), full Failure flow (20 failure modes × 7 columns) |
| Rewrote `BENCHMARK.md` | doc rewrite | BENCHMARK.md | Was stale ("100-company benchmark: NOT RUN" — actually executed ×3). Now documents purpose, input population, v2/v3/v4 run history, why v3 failed, what changed, why v4 recovered, final metrics from the actual artifact, exact metric interpretation (entity-resolved ≠ "100% accuracy"; verified facts ≠ independently ground-truthed), budget, limitations, diagnostic-not-official-score disclaimer |

## Discrepancies found and resolved

| Document said | Code/artifact proved | Resolution |
|---|---|---|
| `VERIFICATION_REPORT.md`: commit `71a6d458…` | Git HEAD is `136d7ce…` | Updated to `136d7ce` |
| `VERIFICATION_REPORT.md`: "Lint/type-check: Not run as a gate" | `ruff check` → 0 errors; `mypy` → 0 errors in 29 files (run 2026-10-01/02) | Section rewritten with actual results; interim claim labelled HISTORICAL |
| `BENCHMARK.md`: "100-company benchmark: NOT RUN" | `benchmark_result_v4.json` + v2/v3 artifacts: executed 3× | Rewritten with full run history and final v4 metrics |
| `SUBMISSION_READINESS.md`: request count 924/2,000 | v4 artifact: 1,506/2,000 | Updated to v4 value |
| `SUBMISSION_READINESS.md`: commit `c29db8c+` | HEAD is `136d7ce` | Updated |

## Code audit findings while writing FLOW.md (verified against source)

| Item | Finding | Documentation treatment |
|---|---|---|
| `BrregAdapter.fetch_underenheter` | Implemented but NOT called in the main pipeline path (`research_company` never invokes it) | Marked "implemented but not in the main execution path" in FLOW.md source table |
| `repository.save_snapshot` / `get_snapshot` / `get_previous_hash` | Defined but not called in production paths (refresh compares previous facts via `repo.get_previous_facts`; in-run gateway cache deduplicates) | Marked honestly in FLOW.md data lifecycle |
| `ledger.temporal_view` / `mark_source_unavailable` | Reachable helpers; used in tests only | Marked "(test-only in main src; reachable helper)" in FLOW.md |
| `_JOB_TEXT_HINTS` (website.py:543) | Dead constant (defined, never used) | Not described as active execution |
| Frontend endpoint usage | Uses POST /research, GET /research/{run_id}, GET /companies/{orgnr}, GET /companies/{orgnr}/sources, GET /runs/{runId}/trace. Does NOT call /facts, /changes, /batch, /run-status | FLOW.md documents which routes the frontend consumes; other routes remain available API surface |

## 1,000-profile requirement investigation

**Finding:** no requirement — and no artifact — concerning 1,000 profiles
exists anywhere in the repository. Searched: README, SUBMISSION_READINESS,
VERIFICATION_REPORT, BENCHMARK, docs/, benchmark/, AUDIT.md, configuration,
scripts. The documented challenge constraints are ~100 companies per run
(2,000 requests / 45 min / $10). The repository proves a **100-company live
benchmark** (v4: 88 available, 100/100 entity resolved, 1,420 verified facts,
1,506/2,000 requests, $0.00). **No 1,000-profile submission artifact is
present and none is claimed.**

## Historical vs current

- Historical benchmark values (v2: 1,179 facts / 924 requests; interim
  10/15-company runs) are retained where explicitly labelled historical
  (`VERIFICATION_REPORT.md` §3, `COVERAGE_IMPROVEMENT_REPORT.md` before/after
  tables) — they are the traceability record of the improvement pass.
- Current submission documentation (README headline metrics,
  SUBMISSION_READINESS, VERIFICATION_REPORT final sections, BENCHMARK.md)
  refers to the final v4 state and HEAD `136d7ce`.

## Verification re-run after changes

| Check | Result |
|---|---|
| `python -m pytest tests/unit -q` | 228 passed |
| `ruff check src/ tests/` | 0 errors |
| `mypy src/nordtrace` | 0 errors in 29 source files |
| `benchmark_result_v4.json` values re-read | 100 companies, 100/100 entity resolved, 88 available, 12 not_available, 1,420 facts, 662 evidence, 1,506/2,000 requests, 469.8s/2,700s, $0.00 |
