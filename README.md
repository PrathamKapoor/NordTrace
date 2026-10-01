# NordTrace — Norwegian Company Intelligence Agent

> Evidence-backed research agent for Norwegian companies, built on public
> registries and permitted sources. Every published fact is traceable to its
> source. No fabricated data.

---

## What it does

Give it a Norwegian organisation number and it will:

1. Validate the number (format + modulus-11 checksum).
2. Resolve the canonical identity from **Brønnøysundregistrene** (live API).
3. Retrieve real public information:
   - registry entity (name, form, status, address, NACE, capital, employees)
   - board/management roles
   - annual accounts (revenue, result, assets, equity, liabilities, currency, period)
   - branch units
   - the company's own website (description, contact, careers, news)
   - job postings from **NAV Arbeidsplassen**
   - dated registry activity events
4. Verify every fact belongs to the target company (deterministic matching).
5. Reject wrong-company candidates and record the rejection.
6. Attach evidence (URL, content hash, retrieval date, entity verdict) to every fact.
7. Detect changes between runs and preserve history.
8. Respect budgets: 2,000 requests / 45 min / $10 declared API cost.
9. Persist everything to SQLite and expose it via REST API + dashboard.

---

## Architecture

```
Organisation number
   ↓  validation (mod11 checksum)
Canonical Entity Resolution        ← Brreg enheter (live)
   ↓  verified identity
Source Discovery                   ← registry hjemmeside, regnskap, NAV, branches
   ↓
Structured Data Acquisition        ← RequestGateway (budget/SSRF/robots/cache)
   ↓
Fact Extraction                    ← deterministic parsing (registry JSON, PDF text)
   ↓
Entity Verification                ← signal-based resolver + publication firewall
   ↓
Evidence Validation                ← citation validator (fact→evidence→source chain)
   ↓
Fact Ledger                        ← SQLite, the source of truth
   ↓
Change Detection                   ← fact-slot diff vs previous runs
   ↓
Evidence-Grounded Synthesis        ← summary from verified facts only
   ↓
Final Company Profile              ← API + dashboard
```

The LLM is **optional** (disabled without `LLM_API_KEY`; cost stays $0.00) and
never the source of truth for identity, URLs, financial values, or dates.

---

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (Git Bash: source .venv/Scripts/activate)
pip install -e .
```

Requires Python 3.11+ (developed and tested on 3.13).

## Environment variables

Copy `.env.example` → `.env`. All optional; defaults work for public registry access:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_API_KEY` | *(empty)* | Optional LLM key — system degrades to deterministic extraction without it |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `gpt-4o-mini` | Model for optional extraction/synthesis polish |
| `MAX_REQUESTS` | `2000` | Hard global request limit |
| `MAX_RUNTIME_SEC` | `2700` | Hard global runtime limit (45 min) |
| `MAX_API_COST_USD` | `10.0` | Declared external API cost limit |
| `MAX_PAGES_PER_COMPANY` | `8` | Crawler page cap |
| `DATA_DIR` | `./data` | SQLite storage |

No secrets are committed. `.env` is gitignored.

---

## One-command execution

```bash
# Single company (live research, ~20s, ~13 requests, $0.00)
python -m nordtrace.cli research 982463718

# Batch from CSV (one orgnr per line or with header)
python -m nordtrace.cli batch companies.csv --concurrency 4

# Resume an interrupted batch
python -m nordtrace.cli resume <run_id>

# Benchmark (live companies from registry search)
python -m nordtrace.cli benchmark --limit 10

# Validate a result file
python -m nordtrace.cli validate result.json

# REST API + dashboard
python -m nordtrace.cli serve          # http://127.0.0.1:8000/dashboard
```

Example input: `982463718` (Telenor ASA — live-verified).

Example output (abridged, real):

```json
{
  "run_id": "run_7b5c37f5…",
  "organisation_number": "982463718",
  "status": "available",
  "company": { "legal_name": "TELENOR ASA", "organisation_form": "ASA", "status": "active",
               "municipality": "BÆRUM", "industry_code": "61.100",
               "website": "https://www.telenor.no/", "employee_count": 374 },
  "facts": [ { "category": "financials", "field": "revenue", "value": 678000000.0,
               "currency": "NOK", "reporting_period": "FY2024",
               "source_id": "src_…", "evidence_id": "ev_…", "entity_verdict": "VERIFIED" } ],
  "changes": [],
  "summary": "TELENOR ASA (orgnr 982463718) …",
  "sources": [ { "url": "https://data.brreg.no/enhetsregisteret/api/enheter/982463718",
                 "authority_tier": 0, "access_status": "success", "content_hash": "…" } ],
  "coverage": { "identity": "found", "business_description": "found", "industry": "found",
                "financials": "found", "leadership": "found", "jobs": "found",
                "recent_activity": "found" },
  "research_metadata": { "request_count": 13, "estimated_cost_usd": 0.0,
                         "duration_sec": 18.2, "stages_executed": ["validation","identity",
                         "roles","financials","website","jobs","activity","changes","synthesis"] }
}
```

---

## Test results (actual, 2026-10-01)

| Suite | Command | Result |
|---|---|---|
| Unit tests (194 tests) | `pytest tests/unit` | **181 passed** |
| Live registry integration | `pytest tests/integration -m live` | **5 passed** (full E2E, refresh, budget attack, concurrency, resume) |
| Live CLI research | `python -m nordtrace.cli research 982463718` | **available**, 21–23 facts, 13 requests, $0.00, ~20s |
| 10-company benchmark | `python -m nordtrace.cli benchmark --limit 10` | 10/10 completed, 10/10 entity resolved, 161 facts, 88 requests, 22.7s |
| 15-company batch | harness, concurrency 4 | 13/15 available, 15/15 entity resolved, 222 facts, 140 requests, 50.7s |
| Resume test | interrupt + resume batch | completed companies skipped, states preserved |
| Refresh test | same company ×2 | 23 unchanged facts detected between runs |
| Frontend flow | browser automation | research → identity → facts → evidence drawer → trace, all real data |

**100-company benchmark: NOT RUN** (would take ~6 min at measured throughput and
~900 requests; registry rate limits make it feasible but it was not executed in
this environment — run `python -m nordtrace.cli benchmark --limit 100` to reproduce).

---

## What requires credentials

- **LLM extraction/synthesis polish**: needs `LLM_API_KEY`. Without it the
  system uses deterministic extraction only (which is what all measured results
  above reflect — $0.00 cost).
- Everything else (Brreg, NAV, company websites) is public and keyless.

## Known limitations

See `LIMITATIONS.md`. Key points:

- Annual accounts come from the public regnskapsregisteret endpoint (the
  latest filed year; companies with custom layouts — banks, insurers — may be
  unavailable → reported as `not_available`, never fabricated).
- PDF financial extraction works on text-based PDFs; scanned/image PDFs are
  reported as extraction-failed honestly.
- NAV job postings carry employer names without orgnr → entity verification
  is name/municipality-based; ambiguous postings are rejected, not merged.
- Website discovery uses the registry `hjemmeside` field; companies without a
  registered website get conservative name-derived candidates that must pass
  identity verification (or are rejected).
- No general news search (no keyless provider implemented); "recent activity"
  comes from dated registry signals only.

---

## Documentation

| File | Purpose |
|---|---|
| `README.md` | This file |
| `ARCHITECTURE.md` | System architecture |
| `METHODOLOGY.md` | Evidence pipeline + methodology |
| `SOURCES.md` | Source tiers (all verified live) |
| `EVIDENCE_MODEL.md` | Evidence structure + publication rules |
| `ENTITY_RESOLUTION.md` | Identity matching + firewall |
| `REFRESH_MODEL.md` | Change detection + refresh |
| `COST_MODEL.md` | Cost tracking design |
| `BENCHMARK.md` | Benchmark methodology |
| `LIMITATIONS.md` | Known limitations |
| `AUDIT.md` | Forensic audit of prior claims (2026-09-29) |
| `VERIFICATION_REPORT.md` | Actual verification commands + results (2026-10-01) |

---

## Git / Authorship

All commits: `PrathamKapoor <prathamkapoor027@gmail.com>`. No AI/model
collaborator attribution in repository history.

## License

MIT
