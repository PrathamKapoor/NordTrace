# Architecture — NordTrace

## Overview
Evidence-backed Norwegian company intelligence agent. Real implementations, live-verified.

## Key Modules (actual)
- `core/models` — domain entities (CompanyIdentity, Fact, Evidence, Source, Change, Coverage, Run)
- `core/orgnr` — Norwegian organisation number validation (modulus-11 checksum)
- `core/request_gateway` — the ONLY outbound HTTP path (budget, SSRF guard, robots, cache+hash, retry/backoff, size limits)
- `core/budget` — RequestBudget (atomic, hard stop), RuntimeBudget (global deadline + phases), CostBudget (price table)
- `core/repository` — SQLite persistence with FKs, indexes, WAL mode
- `core/entity` — deterministic entity resolution + publication firewall (signal-based)
- `core/ledger` — fact ledger with citation validation + conflict detection
- `core/changes` — fact-slot-level change detection (NEW/CHANGED/RETRACTED/UNCHANGED/SOURCE_UNAVAILABLE)
- `core/synthesis` — evidence-grounded summary from verified facts only
- `core/llm` — optional LLM client (schema validation, cost tracking; disabled without key)
- `adapters/brreg` — live registry adapter (entity, roles, regnskap, underenheter)
- `adapters/website` — website discovery + focused crawler + page classification
- `adapters/pdf_pipeline` — real PDF extraction (pypdf) with page numbers + Norwegian number parsing
- `adapters/nav_jobs` — live NAV Arbeidsplassen job search + employer verification
- `adapters/activity` — registry-signal activity facts (zero fabrication)
- `engine/pipeline` — adaptive research orchestrator (validation → identity → roles → financials → website → jobs → activity → changes → synthesis)
- `engine/runner` — bounded-async batch runner (checkpointing, resume, deadline)
- `api/app` — real REST API backed by SQLite
- `frontend/` — real SPA consuming the API (evidence-first dashboard)
- `cli` — research/batch/resume/benchmark/validate/serve
- `benchmark` — real evaluator over actual run artifacts

## Data Flow (actual, live-verified)
```
Organisation number → validation (mod11) → Brreg enheter (live)
  → canonical identity → roles + regnskap + branches (live)
  → website discovery + focused crawl (SSRF-guarded, robots-aware)
  → NAV job search (live) + registry activity signals
  → fact ledger (citation-validated, conflicts detected)
  → change detection vs previous runs
  → evidence-grounded synthesis
  → SQLite persistence → REST API → dashboard
```

## Design Principles (enforced)
- LLM never the source of truth for identity, URLs, financial values, or dates.
- Every published fact must have verified evidence (citation validator).
- Every rejected source is logged and visible in the UI.
- Single HTTP gateway: budget/SSRF/robots enforcement cannot be bypassed.
- Request budget 2,000 / runtime 45 min / cost $10 — hard limits.
