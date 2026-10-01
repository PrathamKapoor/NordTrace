# Benchmark Methodology (actual)

## Objective
Measure real-world performance on Norwegian company research tasks within budget limits.

## Metrics (computed from actual run artifacts)
- Completion rate (terminal states)
- Entity resolution success (deterministic, registry-anchored)
- Verified fact / evidence counts per company
- Rejected-source tracking rate
- Request count per company
- Runtime per company
- Estimated API cost

## Test results (actual, 2026-10-01)
- 10-company live benchmark: 10/10 completed, 161 facts, 88 requests, 22.7s, $0.00
- 15-company batch (concurrency 4): 13/15 available, 222 facts, 140 requests, 50.7s, $0.00
- 100-company benchmark: NOT RUN (reproduce: `python -m nordtrace.cli benchmark --limit 100`)

## Synthetic Fixtures
`benchmark/fixtures/golden_dataset.json` — clearly labelled, NOT live results:
- Exact identity match
- Similar-name different orgnr (SALMAR ASA vs SALMAR AS)
- Brand vs legal entity (COGNITE AS)
- Prompt injection (content stays data)

## Correctness
Entity resolution is deterministic (registry-anchored). Fact correctness is
verifiable via evidence chains. No independent ground-truth scoring without a
golden dataset — reported honestly as such in the harness.
