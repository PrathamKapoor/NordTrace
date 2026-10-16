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

Baseline commands in the fresh declared-dependency environment:

| Command | Actual result | Classification |
|---|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit -m 'not live' -q` | 227 passed, 1 failed in 36.47s; one Starlette httpx deprecation warning | rate spacing assertion measured 0.094s against 0.1s; investigate timer/sleep enforcement |
| `.\.venv\Scripts\python.exe -m ruff check src tests` | All checks passed | offline lint |
| `.\.venv\Scripts\python.exe -m mypy src/nordtrace` | Success, 29 source files | offline type check |
| `.\.venv\Scripts\python.exe -m pip check` | No broken requirements | dependency check |

The unit baseline is **not offline proof**: two PDF tests and one API test make unmarked live requests. Their success here is source-access dependent. Move live PDF checks behind opt-in markers and replace the API test's external boundary with a deterministic registry-not-found response. Full log is ignored `data/baseline-unit.log`. Python is 3.12.5.

Record each check as code, dependency, environment, source-access or credential related. Deterministic tests and mocked acquisition are never live verification. Official schema/batch/budget/snapshot acceptance and Docker execution are presently blocked; independent code work continues. No new baseline test count or measured accuracy is claimed yet.
