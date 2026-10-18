# NordTrace

Norwegian company research with retained evidence. Implementation is **in progress**. Current publication supports exact registry identity fields and parent-verified subunit relationships. Website, roles, activity and financial candidates remain withheld until their producers satisfy the typed support checks. NAV search is retired; hiring stays explicitly blocked until the documented feed and its update/retention requirements are implemented. A [real100-input registry-only smoke baseline](docs/registry-smoke-report.md) retained complete profiles/evidence:430 matching transport operations,1087 supported claims and224.094seconds. External gains and independent accuracy remain unmeasured. Frozen baseline briefs retain a documented wording defect; new briefs distinguish final verification states without claiming public information is absent.

The financial brief template preserves each claim's amount, currency, unit, period and entity scope; incomplete or unsafe values are withheld. Monetary change notices require evidence inspection because change records do not contain complete old/new qualifiers. These guards do not enable financial publication or establish parser accuracy.

News indexes and general careers pages are retained as resource candidates; they do not establish dated events or active vacancies. Their substantive claims remain unpublished until typed evidence and identity checks are implemented.

Acquisition DNS runs outside the event loop with at most 16 outstanding OS lookups per process. Caller cancellation and process exit do not wait for a stuck lookup; its capacity slot stays occupied until the OS returns. This does not establish hard bounds on synchronous parsing, storage, SSL setup or export. DNS cancellation after a request reservation is charged as unstarted, rather than a failed HTTP dispatch.

## Install

Verified on Windows with Python 3.12.5 and a fresh virtual environment:

```powershell
uv sync --frozen --extra dev --python 3.12
```

The package declares Python >=3.11; other runtimes/Linux/container execution are unverified. For a noneditable installation, add `--no-editable` to the same command. Dependencies and build tools are pinned through uv.lock/pyproject.toml. Model providers are unavailable: no key is needed and legacy model settings cannot enable calls. Website/PDF robots checks are mandatory; `RESPECT_ROBOTS=false` is rejected.

At `19adb1d`, a new locked noneditable environment installed 77 packages and passed CLI/export/validation, retained-bundle replay, health/dashboard and packaged-licence checks outside the source checkout. All 36 installed code/assets matched the committed source. This installation check used invalid inputs and made no company acquisitions; its scope differs from full testing. The latest full local regression passed 754 offline tests in 325.95 seconds, with 8 live checks excluded and one upstream warning. Details and exact commands are in [verification](docs/verification.md). Dashboard script checks pass; real browser verification remains blocked. Hosted CI and Docker execution remain unverified; the local Docker daemon was unavailable.

## Research and inspect

```powershell
.venv/Scripts/python.exe -m nordtrace.cli research 982463718 --output data/profile.json
.venv/Scripts/python.exe -m nordtrace.cli batch companies.jsonl --output data/results.json --bundle data/audit.zip
.venv/Scripts/python.exe -m nordtrace.cli verify-bundle data/audit.zip
.venv/Scripts/python.exe -m nordtrace.cli serve
```

The server defaults to `127.0.0.1:8000`; the dashboard is `/dashboard`. Intended use is local research. The evidence drawer checks retained snapshots and shows the supporting JSON value, pointer, dates and qualifiers for the selected run. Public serving/access controls and full UI/browser review remain unfinished; local browser verification was blocked by a tool startup error.

CSV/TXT uses first-column identifiers with an optional exact header. JSONL uses UTF-8 objects, one per record:

```json
{"organisation_number":"982463718"}
```

Additional fields are selection metadata and cannot establish identity, configure research or change budgets. `.jsonl` selects JSONL automatically; use `--input-format jsonl` for another filename. Malformed containers fail before research. Invalid identifier strings receive terminal error envelopes. Duplicate normalized numbers share one result and an ordered input mapping preserves every occurrence; this local duplicate policy still needs organizer confirmation.

CLI exit 0 means execution completed with honest availability states; exit 1 indicates research failure, support-check failure or benchmark budget overrun; exit 2 indicates invalid inputs. Failure takes precedence when a batch also contains invalid inputs. Unknown business values are not zero-filled.

## Limits, storage and resume

For an observed smoke run, commit the intended code and use a dedicated process from the clean source checkout:

```powershell
.venv/Scripts/python.exe -m nordtrace.cli smoke companies.jsonl --live --output data/smoke-new --max-requests 2000 --max-runtime-sec 900 --per-company-sec 30 --finalization-reserve-sec 20 --concurrency 4
.venv/Scripts/python.exe -m nordtrace.cli verify-bundle data/smoke-new/evidence.zip
```

These are example local parameters, not official competition limits. The command creates a new isolated database, retains the exact inputs and complete canonical results, independently counts HTTP transport dispatches, exports/verifies raw snapshots and writes a hashed manifest last. It disables model keys/paid calls and permits acquisition only from `https://data.brreg.no`. Websites/PDFs stay explicitly blocked for this registry-only baseline; external coverage is not measured. Existing output directories are refused. Results can include failed, blocked or unavailable companies; completion is distinct from successful coverage. Runtime overruns are reported as failures, but synchronous parsing/storage/export are not hard deadline bounded. See D-065/D-066 in [DECISIONS](DECISIONS.md). No independent accuracy or live smoke result follows from having this command.

Copy `.env.example` to `.env` only when needed. Settings load from the launch directory; secrets and generated artifacts are ignored by Git.

| Setting | Behavior |
|---|---|
| `DATA_DIR` | Defaults to the runtime directory's data folder; derives DATA_DIR/nordtrace.db |
| `DATABASE_PATH` | Explicit override of the derived database path |
| `MAX_REQUESTS` | Local default 2000; attempted redirects/retries/robots are reserved before transport |
| `MAX_RUNTIME_SEC` | Local default 2700; cooperative acquisition cutoff, not a hard bound on synchronous storage/parsing |
| `FINALIZATION_RESERVE_SEC` | Explicit acquisition headroom for finalization, default 0 |
| `PER_COMPANY_SOFT_DEADLINE_SEC` | Historical name for a limit that now cancels company acquisition |
| `MAX_API_COST_USD` | Local default 10; deterministic production makes no paid model calls |

These defaults are **not confirmed organizer budgets**. Supply the actual limits for a run; do not extrapolate a 100-company allowance to larger batches. Paid-cost reservation attempts explicitly fail as unsupported; atomic reservation/reconciliation must be implemented before enabling a paid provider. Some hard deadline/output guards also remain incomplete.

```powershell
.venv/Scripts/python.exe -m nordtrace.cli resume RUN_ID
.venv/Scripts/python.exe -m nordtrace.cli export-run RUN_ID --output data/recovered-audit.zip
.venv/Scripts/python.exe -m nordtrace.cli verify-snapshots RUN_ID
.venv/Scripts/python.exe -m nordtrace.cli replay-source SOURCE_ID --output data/source.bin
```

SQLite retains immutable canonical envelopes, observations, captures and checkpoints. Resume restores consumed allowances and the original deadline, skips completed inputs and does not grant a fresh allowance. Missing legacy accounting produces explicit failures/unknown counters. Existing databases receive backed-up additive migrations; legacy history is not silently rewritten as newly verified.

Audit ZIPs contain canonical results.jsonl, retained raw content-addressed bytes, a local schema, a completion manifest and starter-example.jsonl. The latter is a documented projection of the public starter example, **not private organizer acceptance**. Registry-listed websites remain registered_website; structured evidence uses JSON pointers/raw values with null claim_span, and unknown per-company request/cost attribution remains null. Whole-run telemetry is in the manifest. Offline verification checks hashes, metadata, locators, supported values and exact correspondence.

Existing ZIP destinations are preserved. Export capacity defaults to 256 MiB of uncompressed payload; use `--export-max-bytes` for batch or `--max-bytes` for export/verify. Portable artifacts appear after all terminal envelopes exist; acquisition checkpoints remain SQLite. Snapshot rights are source-specific and do not imply redistribution permission. Historical results are frozen; source outages preserve last-known values and do not prove retraction. Full extraction replay, affirmative removal/expiry and conditional 304 refresh remain incomplete.

## Reproducible evaluation inputs

The public eligible universe is selection metadata, separate from the organizer's supplied frozen identity snapshot/private batch. Download it to a local data folder, then verify and select:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
Invoke-WebRequest -Uri 'https://www.builderr.ai/signalpost-company-universe-2025.jsonl.gz' -OutFile data/universe.jsonl.gz
.venv/Scripts/python.exe -m nordtrace.cli sample-universe data/universe.jsonl.gz --output data/samples --seed nordtrace-eligible-evaluation-2026-10-18
.venv/Scripts/python.exe -m nordtrace.cli benchmark --orgnr-file data/samples/development.jsonl --output data/benchmark.json
```

The sampler verifies published compressed/uncompressed hashes and writes development.jsonl, held_out.jsonl and manifest.json. Default is 100 per partition; use `--development-size 1000 --held-out-size 1000` for larger nested samples. Fixed seeded partitions prevent cases moving from held-out into development. Unknown employee metadata stays unknown. Balanced rare-stratum oversampling is disclosed; it is not a population recall estimate. Consume only a complete manifest; failed publication can leave partial files without one. Existing directories/locks are refused.

Actual local samples from all 411,160 eligible records cover 38 of 41 metadata strata per partition, explicitly recording the gaps. Their files, hashes, seed, source lines, populations and quotas are retained under ignored data/evaluation-samples/. **These are input samples, not researched profiles or a live smoke-test report.** See [BENCHMARK.md](BENCHMARK.md) for selection evidence and limitations.

Benchmark requires supplied inputs and processes all occurrences by default. Explicit `--limit N` records exclusions. Completed envelopes, availability, supported identity resolution, logical claims, corroborating observations and retained source-record inventory are separate measures. Registry output cannot inflate non-registry counts. Independent precision/recall/financial accuracy remain null without adjudicated references; no official score is computed.

## Verify and follow the implementation

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m mypy src/nordtrace
```

Dashboard script checks use Node.js24.19.0 and built-in modules only (`node --test tests/frontend/evidence.test.cjs`); no npm install is needed. Python tests explicitly skip that optional check when Node is unavailable; CI configures the pinned Node release. These script checks do not replace real browser/keyboard/mobile validation.

Default tests exclude live checks. `pytest -m live` opts into external access and must be assessed separately; deterministic fixtures do not establish live accuracy.

- [Implementation tracker](docs/implementation-tracker.md): requirements, F01–F28, status and remaining gates.
- [Verification](docs/verification.md): exact commands, failures, scoped passes, artifacts and limitations.
- [Evaluator contract](docs/evaluator-contract.md): retrieved versions/hashes, unresolved limits/schema/duplicate rules.
- [FLOW.md](FLOW.md) and [DECISIONS.md](DECISIONS.md): actual call chains and material decisions.
- [SOURCES.md](SOURCES.md): access, attribution, retention and source-specific rights.

Core stack remains Python, Click, FastAPI/Pydantic, httpx and SQLite. The production path is input validation → exact entity acquisition → candidate acquisition through the gateway → retained snapshot/locator validation → stable claim/conflict ledger → outage-safe refresh/synthesis → atomic canonical publication → CLI/API/bundle. Only supported producers publish. Financial semantics/table extraction, external producers, full UI evidence inspection, hard synchronous bounds and representative independent accuracy remain open.

Earlier feature claims and live numbers are preserved in Git (`git show 8aa7e06:README.md`) and the historical section of BENCHMARK.md; they are superseded by the current verification record. No remote push, PR, deployment, email or submission has been performed.

## Licence

Project code: [MIT](LICENSE). See [NOTICE.md](NOTICE.md) and SOURCES.md for dependency/data distinctions. Downloaded source material is not automatically MIT.
