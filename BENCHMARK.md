# Benchmark Methodology

## Purpose

Measure real-world performance of the research pipeline on Norwegian company
research tasks within the challenge budget limits (2,000 requests / 45 min /
$10 declared API cost). The benchmark is a **diagnostic, evidence-based
measurement** — not an independent ground-truth accuracy benchmark.

## Input population

Companies are fetched **live at runtime** from the Brreg search endpoint
(`enheter?navn=<term>`) across ~29 generic Norwegian industry/brand search
terms. No organisation numbers are hard-coded; every run uses a fresh sample
and a fresh temp database. This tests generalization to unseen companies.

## Metrics (computed from actual run artifacts)

- Completion rate (terminal states: available / not_available / blocked / failed)
- Entity resolution success (deterministic, registry-anchored)
- Verified fact / evidence counts per company
- Rejected-source tracking rate
- Request count per company
- Runtime per company
- Estimated API cost
- Information gain: facts/company, requests/company, facts/request

## Metric interpretation (exact meaning)

- **"100/100 entity resolved"** means: for 100 of 100 inputs, the pipeline
  produced a canonical identity from the registry, or a definitive
  not_found/not_applicable/blocked terminal state. It does NOT mean "100%
  accuracy".
- **"1,420 verified facts"** means: 1,420 facts that passed the system's
  evidence-validation pipeline (citation validator: source retrieved,
  evidence present, entity verdict VERIFIED/LIKELY, org match). They are
  verified *by the system's evidence chain*, not independently
  ground-truthed. This benchmark is diagnostic/evidence-based; it is not an
  independent ground-truth accuracy benchmark.

## Run history (actual, all executed)

### v2 baseline (2026-10-01)
88/100 available · 100/100 entity resolved · 1,179 facts · 643 evidence ·
924/2,000 requests · 280s/2,700s · $0.00

### v3 regression (mid-pass, 2026-10-01)
**92/100 FAILED** — root cause: Brreg refused connections (TCP ConnectError
cascade) → circuit breaker OPEN → `rate_limited` access status was wrongly
mapped to terminal state `failed` instead of degrading. Measured evidence:
28 sources with `access_status=failed, http_status=None` (ConnectError),
5 `rate_limited`.

### v4 final (2026-10-01, artifact `benchmark_result_v4.json`)
| Metric | Value |
|---|---|
| Companies attempted | 100 |
| Entity resolved | 100/100 |
| `available` | 88 |
| `not_available` | 12 (no registry website / no accounts — honest) |
| `failed` / `ambiguous` | 0 / 0 |
| Verified facts | 1,420 (evidence-pipeline-verified; not independently ground-truthed) |
| Evidence records | 662 |
| Rejected sources | 437 |
| Requests | 1,506 / 2,000 |
| Runtime | 469.8s / 2,700s |
| Cost | $0.0000 / $10.00 (deterministic extraction; LLM disabled without key) |
| facts/request | 0.94 |

## Why v3 failed and what was changed

1. **Mapping bug**: `BrregAdapter` mapped `access_status=rate_limited` to hint
   `failed`; the pipeline treated any non-`found` identity hint as terminal
   failure. Fix: `rate_limited` → `blocked` hint (source temporarily
   unavailable); pipeline maps `blocked` → terminal state `blocked`.
2. **Circuit-breaker lockout**: exponential cooldown (2^n, cap 16x) kept the
   circuit open for the rest of the run after a transient block. Fix: cap
   reduced to 4x so the circuit recovers within a single 100-company run.

## Why v4 recovered

- Registry failures now degrade to `blocked` terminal states (company still
  gets a terminal result; the run continues).
- Cooldown cap lets the circuit half-open and close again on success within
  the run (v4: 0 failed, 100/100 entity resolved).
- All other protection (budget hard stop, Retry-After, per-domain concurrency)
  remained intact.

## Budget (v4)

- Requests: 1,506/2,000 (75%) — hard stop verified by tests
- Runtime: 469.8s/2,700s (17%) — global deadline verified by tests
- Cost: $0.00/$10.00 — LLM disabled without key; deterministic extraction only

## Synthetic fixtures

`benchmark/fixtures/golden_dataset.json` — clearly labelled SYNTHETIC, NOT live
results: exact identity match, similar-name different orgnr, brand vs legal
entity, prompt injection (content stays data).

## Limitations

- Coverage of missing categories is source-limited (see
  `docs/COVERAGE_GAP_ANALYSIS.md` for measured failure modes per category).
- NAV was IP-level rate-limited (429) throughout the v4 run; jobs coverage
  comes from company careers pages instead.
- Fact correctness is verifiable via evidence chains, not independent
  ground truth; entity resolution is deterministic (registry-anchored).

## Interpretation

The local benchmark is diagnostic/evidence-based. It is not the official
competition score, and no rank/percentile/qualification is claimed from it.
