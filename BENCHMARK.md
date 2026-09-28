# Benchmark Methodology

## Objective
Measure real-world performance on Norwegian company research tasks within budget limits.

## Metrics
- Completion rate (% of companies with terminal state)
- Entity resolution success rate
- Verified fact count per company
- Request count per company
- Runtime per company
- Rejected-source tracking rate
- Change detection accuracy (on synthetic fixtures with known differences)
- Cost per company

## Synthetic Fixtures
Used for deterministic tests:
- Exact identity match
- Similar-name company (name overlap, different org number)
- Parent/subsidiary confusion
- Ambiguous website domain
- Conflicting source (same company, different dates)
- Historical vs current value conflict

## Integration Tests
Use real permitted sources (Brreg public endpoint) with known valid organisation numbers.

## Benchmark Execution
```bash
python -m nordtrace.cli benchmark
```

Results saved to `benchmark_result.json`.
