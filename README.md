# NordTrace — Norwegian Company Intelligence Agent

> Evidence-backed research agent for Norwegian companies using permitted public sources. Every published fact is traceable to its source.

---

## What it does

- Accepts a Norwegian organisation number at runtime.
- Resolves the canonical company identity against Brønnøysund Register (Tier 0 official registry).
- Discovers permitted sources (official website, annual reports, jobs, public records, news).
- Validates identity on every candidate source before publication.
- Stores evidence with URLs, dates, content hashes, and entity-match details.
- Detects changes between runs and explains them.
- Works on previously unseen companies — no precomputed lookup tables.

---

## Quick start

```bash
# 1. Setup
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev,frontend]"

# 2. Configure (copy .env.example → .env)
cp .env.example .env
# Edit .env if needed; defaults work for public registry access.

# 3. Initialize database
python -c "from nordtrace.core.database import init_db; init_db()"

# 4. Research a single company (example: 912345678)
python -m nordtrace.cli research 912345678 --output result.json

# 5. Start the REST API
uvicorn nordtrace.api:app --reload --port 8000

# 6. Open dashboard
open src/nordtrace/frontend/templates/index.html   # or serve via FastAPI static mount
```

---

## Architecture

See `ARCHITECTURE.md`.

Key principles:
- **LLM is never the source of truth** for identity, URLs, financial values, or dates.
- **Wrong-company firewall**: every candidate source is checked against canonical identity; rejected candidates are logged.
- **Fact ledger**: profile is derived from verified facts, not the other way around.
- **Evidence-first UX**: click any fact to see source, evidence text, date, and entity verification.

---

## Domain model

- `CompanyIdentity` — canonical entity from official registry.
- `Fact` — independently verifiable claim with source, evidence, confidence, period.
- `Evidence` — URL, text snippet, hash, match details, retrieval date.
- `Source` — authority tier (0–4), access status, content hash.
- `ChangeRecord` — new / changed / retracted facts between runs.
- `ResearchRun` — budget tracking (requests, runtime, cost).

---

## CLI

```bash
python -m nordtrace.cli research <orgnr> [--output <file>]
python -m nordtrace.cli batch <csv> [--resume]
python -m nordtrace.cli resume <run_id>
python -m nordtrace.cli benchmark
python -m nordtrace.cli validate <result-file>
```

---

## Benchmark harness

`python -m nordtrace.benchmark` or `python -m nordtrace.cli benchmark` runs a simulated batch evaluation tracking:

- Entity resolution rate
- Verified fact count
- Request budget usage
- Runtime budget usage
- Estimated API cost
- Rejected-source tracking

Results saved to `benchmark_result.json`.

---

## REST API

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check |
| POST | `/research` | Start research run |
| GET | `/research/{run_id}` | Get run status |
| GET | `/companies/{orgnr}` | Company profile |
| GET | `/companies/{orgnr}/facts` | Verified facts |
| GET | `/companies/{orgnr}/changes` | Change records |
| GET | `/companies/{orgnr}/sources` | Source list |
| GET | `/runs/{run_id}/trace` | Research trace |

---

## Design quality

The frontend (`src/nordtrace/frontend/templates/index.html`) is a polished evidence-first dashboard with:
- Verified identity banner
- Profile cards (business, financials, people, activity)
- Evidence chain with source URLs and dates
- Changes timeline
- Run dashboard (requests, runtime, cost, coverage)
- No decorative gradients, no fake statistics, no unsupported confidence meters.

---

## Security

- `.env.example` is committed; `.env` is ignored via `.gitignore`.
- No secrets committed to repository.
- Web content treated as untrusted data; system instructions always outrank crawled content.
- Prompt-injection defense: crawler treats page text as data, never as instructions.
- Content hashing for source snapshots prevents silent data changes.

---

## Testing

```bash
pytest tests/ -v
```

Tests cover:
- Organisation number validation
- Registry adapter
- Source normalization
- Entity resolution (exact, similar-name, wrong-company rejection)
- Evidence validation
- Request budget enforcement
- Cost tracking
- Change detection
- CLI commands
- API endpoints
- Frontend critical flows

---

## Deployment

```bash
docker-compose up --build
```

Or locally:

```bash
uvicorn nordtrace.api:app --host 0.0.0.0 --port 8000
```

---

## Model / API details

- LLM model: `gpt-4o-mini` (configurable in `.env`)
- Registry source: Brønnøysund Register Centre (`https://data.brreg.no/enhetsregisteret/api/enheter`)
- Maximum declared external API cost: $10
- Maximum outbound requests: 2,000
- Maximum runtime: 45 minutes

---

## Known limitations

See `LIMITATIONS.md`.

Key points:
- PDF extraction depends on text-based PDFs; image-based PDFs use approximate OCR fallback.
- Registry API may return partial historical data; full verification may require manual steps.
- Job/news sources depend on public availability; absence is reported as `not_available`.

---

## Documentation

| File | Purpose |
|---|---|
| `README.md` | This file |
| `ARCHITECTURE.md` | System architecture |
| `METHODOLOGY.md` | Evidence pipeline |
| `SOURCES.md` | Source tier definitions |
| `BENCHMARK.md` | Benchmark design |
| `COST_MODEL.md` | Cost tracking design |
| `EVIDENCE_MODEL.md` | Evidence structure |
| `ENTITY_RESOLUTION.md` | Identity matching |
| `REFRESH_MODEL.md` | Refresh and change detection |
| `LIMITATIONS.md` | Known limitations |

---

## Git / Authorship

All commits:
```
Author name: PrathamKapoor
Author email: prathamkapoor027@gmail.com
```

No AI/model collaborator attribution in Git metadata.

---

## License

MIT

---

## Contact / Author

PrathamKapoor <prathamkapoor027@gmail.com>
