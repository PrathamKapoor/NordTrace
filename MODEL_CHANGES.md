# Changes by Model / Session — Documentation & Traceability Pass

**Session date:** 2026-10-02
**Base commit:** `136d7ce` · **Final commit:** (this commit)
**Scope:** documentation consistency, decision log, execution-flow documentation.
**Code changes:** none — documentation pass only (no meaningful code modified;
no behavior changed; all tests/lint/mypy re-run after documentation edits).

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
| Rewrote `BENCHMARK.md` | doc rewrite | BENCHMARK.md | Was stale ("100-company benchmark: NOT RUN" — actually executed ×3). Now documents purpose, input population, v2/v3/v4 run history, why v3 failed, what changed, why v4 recovered, final metrics from the actual artifact, exact metric interpretation (entity-resolved ≠ "100% accuracy"; verified facts ≠ independently ground-truthed), budget, limitations, diagnostic-not-official-score disclaimer |

## Discrepancies found and resolved

| Document said | Code/artifact proved | Resolution |
|---|---|---|
| `VERIFICATION_REPORT.md`: commit `71a6d458…` | Git HEAD is `136d7ce…` | Updated to `136d7ce` |
| `VERIFICATION_REPORT.md`: "Lint/type-check: Not run as a gate" | `ruff check` → 0 errors; `mypy` → 0 errors in 29 files (run 2026-10-01/02) | Section rewritten with actual results; interim claim labelled HISTORICAL |
| `BENCHMARK.md`: "100-company benchmark: NOT RUN" | `benchmark_result_v4.json` + v2/v3 artifacts: executed 3× | Rewritten with full run history and final v4 metrics |
| `SUBMISSION_READINESS.md`: request count 924/2,000 | v4 artifact: 1,506/2,000 | Updated to v4 value |
| `SUBMISSION_READINESS.md`: commit `c29db8c+` | HEAD is `136d7ce` | Updated |

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
