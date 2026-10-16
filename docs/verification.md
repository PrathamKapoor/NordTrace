# Current implementation verification

Date: 2026-10-16. This record supersedes historical PASS statements for the current implementation assignment without erasing previous run history.

## Checkout and environment baseline

- Repository: `C:\Projects\NordTrace`; branch `main`; starting HEAD `2fea06eefb7a019d1a0d85ef2e919f384e9e4d0b`; initial working tree clean.
- Origin fetch/push: `https://github.com/PrathamKapoor/NordTrace.git`. No parent Git repository at `C:\Projects` or `C:\`; root `.git` is the only nested boundary found. No applicable AGENTS.md found.
- Repository-local identity: `PrathamKapoor <prathamkapoor027@gmail.com>`; both `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` verified before any new commit. No global configuration changed.
- Available Python: 3.13.14 default, 3.12 and 3.10. Isolated `.venv` created with `py -3.12 -m venv .venv`; install started with `.\.venv\Scripts\python.exe -m pip install -e '.[dev]'`. Baseline check results will be recorded after actual completion.
- Docker CLI 29.8.1 present; daemon unavailable (dockerDesktopLinuxEngine pipe absent). Container build/run verification blocked.

## Inventory

`git ls-files` lists a setuptools src-layout Python package, Click CLI, FastAPI and one vanilla HTML frontend. pyproject.toml declares Python >=3.11, MIT metadata, 22 unpinned runtime requirements and a dev extra. No tracked lockfile, LICENSE or CI workflow exists at baseline. There are unit/integration tests and pytest.ini; live markers exist, but all unit network independence must be rechecked. Scripts/data/cache directories are local untracked/ignored content and must not be committed wholesale.

Existing docs include README, FLOW, DECISIONS (D-001 through D-020), ARCHITECTURE, AUDIT, BENCHMARK, COST_MODEL, ENTITY_RESOLUTION, EVIDENCE_MODEL, REFRESH_MODEL, SOURCES, METHODOLOGY, LIMITATIONS, MODEL_CHANGES, SUBMISSION_READINESS and VERIFICATION_REPORT plus coverage reports. Their previous test/coverage claims are historical. Generated benchmark results were already tracked; preserve them as historical, not new release evidence.

SQLite is synchronous, thread-local, WAL and FK-enabled. Baseline tables: runs, companies, sources, evidence, facts, changes, trace_events and snapshots. Sources/evidence/facts require a company identity; there is no complete-outcome table. Snapshot text helpers exist. The schema uses CREATE IF NOT EXISTS without versioned migrations. Local databases are ignored and require backup before schema changes.

Settings read a root .env with case-insensitive names, but DATA_DIR and database_path are independent defaults. Optional model clients exist; constructor availability does not establish production use. Dockerfile installs declared project requirements; compose exposes the API. Deployment is outside authorized scope.

## Result classification

2026-10-17 boundary: frozen synchronization succeeded; full `python -m pytest -q`: **286 passed, 8 deselected**, one upstream warning in 19.17s. Earlier full run: 280 passed/1 missing-body failure; the targeted missing-body assertion failed before correction. Configuration tests reproduced ignored names/disconnected/runtime-directory paths. Ruff/mypy passed; uv pip check found all 77 installed packages compatible. Compose parses; daemon execution remains blocked.

Packaging: a failing ZIP assertion proved index.html missing from `uv build --wheel --out-dir data/package-check`; after repair, wheel includes HTML and LICENSE. Build tools are pinned to public-PyPI verified setuptools 84.0.0/wheel 0.48.0. tldextract's bundled PSL declares a 2025-04-07 cutoff. CI configuration exists locally; hosted execution is unverified. Clean-clone evidence follows only after actual execution.

Publication correction: original exploit/verdict/period/substr-value tests initially returned 5 failures, 2 passes. Grouped-zero/sign fixtures then exposed three additional failures. Final targeted command over publication-safety, ledger, coverage-category and adversarial tests returned 65 passed in 1.16s, with Ruff/mypy passing. This is rejection-gate verification, not independently measured financial precision. Current filing-only financial candidates are withheld; source snapshot, locator and table-semantic repairs remain release blockers.

Transport correction: seven regressions initially failed. Two review regressions for cross-host TLS pool reuse and redirected retry policy also failed before correction. Final gateway/API/security boundary command returned 75 passed, one upstream warning in 4.60s; Ruff and mypy passed. Gateway-only coverage is 11 tests, including actual httpcore pools over a simulated network backend. This proves control-flow/handshake identity separation without making a live certificate-validation claim. No live company collection was used to validate this change.

Identity/PSL correction: initial boundary corpus produced 14 failures and 1 pass. After repair, the identity/orgnr/adversarial command returned 63 passed in 1.20s; expanded focused boundary checks returned 17 passed in 1.04s. These are synthetic semantic fixtures, not an independent Norwegian-population accuracy estimate. tldextract 5.4.0 uses bundled PSL data without network refresh. `uv lock` resolved 80 packages; `uv sync --frozen --extra dev` succeeded using uv 0.12.5 and public PyPI sources. Clean-clone and Linux/container results are still unverified.

Rate/simulation correction: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_rate_limiting.py -q` returned 16 passed in 17.80s. `.\.venv\Scripts\python.exe -m pytest tests/integration/test_contamination_scale.py -m 'not live' -q` returned 3 passed, 1 deselected in 2.93s after explicitly wiring the fake pipelines. These supersede the earlier stopped resume test; neither proves slow-request cancellation or real coverage.

Review regressions: repeated calls and concurrent resumes initially exposed immutable-payload/checkpoint conflicts; a two-connection stale run update could erase a published checkpoint. Targeted tests failed before fixes. Final targeted command (result-contract, CLI and API files) returned **37 passed**, one upstream warning, in 3.35s; Ruff passed and mypy passed for 30 source files. A broader unit run excluding the known rate-spacing defect returned 236 passed, 4 deselected in 23.13s before the last added stale-checkpoint test.

The existing simulated 100-company integration passed. The resume-at-37 test defines but does not wire its simulated pipeline and attempted live acquisition; it was stopped and has no valid simulated result. Its fixture needs repair.

Test isolation correction: the old CLI fixture initially let six newly persisted invalid test runs enter `data/nordtrace.db`. The fixture now uses a temporary database. The six exact run IDs were compared with the pre-migration backup, checked to contain only the two invalid fixture inputs and no sources, then removed transactionally after a second SQLite backup. Foreign-key checking passed. Both backups and an exact cleanup manifest are retained under ignored data/. Existing history was preserved; no database reset/restoration was used.

Canonical-outcome correction: five targeted regressions failed against the starting code; after implementation `.\.venv\Scripts\python.exe -m pytest tests/unit/test_result_contract.py tests/unit/test_cli.py tests/unit/test_api.py -q` returned **33 passed**, one upstream Starlette deprecation warning, in 2.95s. Acquisition in the API missing-company test is an instrumentable httpx 404 fixture, not a live registry check. Migration preservation is tested on a generated legacy database, not on the user's real databases. Exact snapshot/locator validation, complete publication transactions and budget-restoring resume are outstanding.

Baseline commands in the fresh declared-dependency environment:

| Command | Actual result | Classification |
|---|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit -m 'not live' -q` | 227 passed, 1 failed in 36.47s; one Starlette httpx deprecation warning | rate spacing assertion measured 0.094s against 0.1s; investigate timer/sleep enforcement |
| `.\.venv\Scripts\python.exe -m ruff check src tests` | All checks passed | offline lint |
| `.\.venv\Scripts\python.exe -m mypy src/nordtrace` | Success, 29 source files | offline type check |
| `.\.venv\Scripts\python.exe -m pip check` | No broken requirements | dependency check |

The unit baseline is **not offline proof**: two PDF tests and one API test make unmarked live requests. Their success here is source-access dependent. Move live PDF checks behind opt-in markers and replace the API test's external boundary with a deterministic registry-not-found response. Full log is ignored `data/baseline-unit.log`. Python is 3.12.5.

Record each check as code, dependency, environment, source-access or credential related. Deterministic tests and mocked acquisition are never live verification. Official schema/batch/budget/snapshot acceptance and Docker execution are presently blocked; independent code work continues. No new baseline test count or measured accuracy is claimed yet.
