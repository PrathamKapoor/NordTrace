# Architecture — NordTrace

## Overview
Evidence-backed Norwegian company intelligence agent.

## Key Modules
- `core/models`: Domain entities (Company, Fact, Evidence, Source)
- `core/adapters`: Source adapters (Brreg, Website, Financial, PDF)
- `core/entity`: Canonical entity resolution and wrong-company firewall
- `core/budget`: Request, runtime, and cost budgets
- `core/request_manager`: Central HTTP manager (no bypass)
- `cli`: Command-line interface (`research`, `batch`, `resume`, `benchmark`, `validate`)
- `api`: FastAPI REST endpoints
- `frontend`: Evidence-first research dashboard

## Data Flow
```
Organisation Number
  → Registry Adapter
    → Canonical Identity
      → Source Discovery (website, financial, jobs, news)
        → Evidence Validation
          → Fact Ledger
            → Change Detection
              → Synthesis
```

## Design Principles
- LLM is never the source of truth for identity, URLs, or financial values.
- Every published fact must have verified evidence.
- Every rejected source is logged.
- Request budget enforced globally.
- Runtime budget enforced globally.
- Cost budget enforced globally.
