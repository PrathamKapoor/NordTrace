# Implementation tracker

Updated: 2026-10-17. Historical claims in older documents are not current verification. Status vocabulary: `not_started`, `in_progress`, `implemented_unverified`, `verified`, `blocked`. Defect rows remain `not_started` until reproduced or explicitly shown inapplicable; inspection alone does not establish a fix.

## Requirements and release gates

| Requirement | Acceptance scope | Owner component | Verification | Status | Evidence / limitation |
|---|---|---|---|---|---|
| 1.1–1.4 | Local author/committer; preserve history/remotes; no attribution or external publication | Git | identity and post-commit inspection; remote comparison | in_progress | Clean main at 2fea06e; local identity configured/verified |
| 1.5–1.7 | Preserve user work; verify repository/boundaries; read local instructions | Git / workspace | status/diff/origin/parent/nested inspection | verified | 2026-10-16: clean; origin correct; only root .git; no AGENTS.md found |
| 1.8–1.10 | Autonomous coherent verified units; no unauthorized credentials/charges | workflow | diff, command and commit audit | in_progress | No external write or paid API authorized |
| 2.1–2.4 | Normalize input, exact identity, permitted discovery, bounded retrieval | orgnr/entity/adapters/gateway | identity/source/transport corpus | not_started |  |
| 2.5–2.8 | Retain snapshots; atomic located claims; entity/scope/support gate | models/ledger/repository | snapshot and publication tests | not_started |  |
| 2.9–2.12 | Honest availability, refresh, grounded brief and complete replayable envelope | changes/synthesis/contracts | refresh, interface, replay tests | not_started |  |
| 3 | Current contract/version/schema/ambiguities; no official score or submission | docs/evaluator-contract.md | retrieve four primary sources | in_progress | Contract v2 effective 2026-08-26 retrieved 2026-10-16; no JSON schema or numeric budgets published |
| 4 | Recheck audited architecture; retain sound stack | src/nordtrace | tracked inventory and HEAD | verified | Actual checkout exactly audited HEAD; Python/Click/FastAPI/SQLite retained |
| 5.1–5.2 | Inventory dependencies, runtime, DB, Docker/CI, existing docs/history | docs/verification.md | read files/schema/settings/documents | in_progress | Python 3.12 chosen; Docker CLI present; daemon unavailable |
| 5.3–5.6 | Isolated baseline install/checks; classify failures; current tracker/metrics | docs/verification.md | declared editable dev installation; pytest/lint/type | verified | Fresh Python 3.12.5 installation; baseline 227 passed/1 rate failure; lint/type/pip-check passed. Live unit leakage corrected and rate defect reproduced/fixed; see verification.md |
| A.input | Versioned run input; supplied batches/snapshot; duplicate policy and input mapping | core/contracts.py; runner | contract inputs and duplicates | not_started |  |
| A.output | One serializer; terminal states/reasons; identity/claims/evidence/coverage/errors | core/contracts.py; repository | schema, failed/no-identity persistence | implemented_unverified | Canonical versioned immutable outcomes and reference checks verified; full locator/snapshot/relationship/family-state contracts unfinished |
| A.export | Incremental atomic export/completion manifest; isolation of failures; exit codes | cli.py; runner | invalid/missing/interrupted/cardinality tests | implemented_unverified | Atomic JSON export, failure isolation, invalid/duplicate mapping, documented exit codes, synthetic 100/1000 invalid cardinality verified; streaming/external manifest/interruption unfinished |
| B.parse | Checksum/source-context orgnr; public suffix parsing; contradictions | core/orgnr.py; core/entity.py | hard-negative parsing/identity corpus | not_started |  |
| B.subject | Snapshot identity anchor; justified shared domains; legal/brand/group/operator relationships | core/entity.py; models | shared-domain, subsidiary and rebrand fixtures | not_started |  |
| B.publish | Inspectable ambiguous/rejected candidates; group scope; exact-company gate | core/ledger.py; adapters | wrong-company adversarial tests | not_started |  |
| C.snapshot | Content-addressed retained representation; requested/final URLs, chain, dates, rights, versions | gateway/repository/models | hash verification / offline replay | implemented_unverified | Full raw body/schema-3 capture, acquisition metadata and hash-verified offline byte replay tested; exact locators, source-specific rights/retention and extraction replay unfinished; PDF discovery labels corrected |
| C.support | JSON/text/PDF locators, raw value/normalization; identity/acquisition/value/metadata checks | ledger/adapters | tampered/missing/unsupported support fixtures | not_started |  |
| C.claim | Derived formula provenance; stable qualified item identity; conflicts and observations | models/ledger/changes | jobs/events/branches/replay/concurrency fixtures | not_started |  |
| C.storage | Complete outcomes incl failures; atomic publication; retry safety; versioned backed-up migrations | repository | upgrade copy/history/rollback tests | implemented_unverified | No-identity immutable outcomes, publication/checkpoint transaction, schema-2 backup/migration and stale-update tests verified; whole-ledger transactions/observations remain unfinished |
| C.retention | Source rights/privacy and inactive vacancy retention | SOURCES.md | documented rights decisions | not_started |  |
| D.transport | One policy boundary incl models/search/robots/browser; pinned safe DNS; manual bounded redirects | request_gateway.py | IPv4/IPv6/rebinding/private-hop tests | not_started |  |
| D.bounds | Stream/decompression/PDF processing caps; actual telemetry; robots/error/terms policy | gateway/adapters | slow/large source and independent instrumentation | not_started |  |
| D.retry | Domain rate limits, bounded Retry-After/deadline, recoverable circuit breakers | rate_limiter.py | retry exhaustion/storm/recovery tests | not_started |  |
| D.budgets | Supplied parameters, manifest, atomic requests/cost, retry reconciliation | budget.py; runner | parallel and depleted budget tests | not_started |  |
| D.execution | Absolute deadlines incl queue/parsing/finalization, reserve output/time, complete skeletons | runner/pipeline | deadline/cancellation/interruption tests | not_started |  |
| D.resume | Durable claims/checkpoints, restore same-run allowances, process/task ownership | runner/repository | resume@37/repeated/concurrent resume tests | not_started |  |
| E.observation | Per-source/family completeness and separate publication/retrieval/effective/verification times | models/changes | paired refresh fixtures | not_started |  |
| E.revalidate | ETag/Last-Modified/304 retained-content revalidation and no-op replay | gateway/changes | 304 and identical snapshot tests | not_started |  |
| E.change | Affirmative removals; stale last known on outage; multi-item expiry/roles/branches/corrections/periods | changes.py | known refresh scenario matrix | not_started |  |
| E.history | Frozen identity, claims, relationships, summary and changes per run | repository/api | historical reconstruction after updates | implemented_unverified | Complete new envelopes frozen, identity/summary after update tested; legacy history explicitly unavailable; relationship contract unfinished |
| F.1–F.2 | Paginated branches and repaired website/adaptive acquisition | brreg/website/pipeline | integration and marginal coverage measurement | not_started |  |
| F.3–F.5 | Bounded permitted search candidates; contact/legal/Organization; sitemaps/canonical URLs | discovery/website | fetched candidate evidence + coverage ablation | not_started |  |
| F.6 | Concrete business/products/location/contact claims with spans | website.py | adjudicated extraction corpus | not_started |  |
| F.7–F.8 | NAV documented authenticated feed/rights; employer match; JobPosting/ATS vacancy semantics | nav_jobs.py; website.py | schema/rights review and vacancy fixtures | not_started |  |
| F.9 | Dated individual news/feeds; separate publication/event dates | activity/website | event fixtures and recall | not_started |  |
| F.10–F.11 | New sources only after rights/access/utility measurement; JS only measured/accounted | SOURCES.md; gateway | written source decisions/ablation | not_started |  |
| G.structured | Verified accounts schema, entity, history, period/currency/scale/scope, Decimal | brreg.py | financial fixture matrix/exact match | not_started |  |
| G.pdf | Rows plus comparative headers, units, zero/sign/commas, entity/group, locators, abstention | pdf_pipeline.py | required financial fixture matrix | not_started |  |
| G.layout | Evaluate layout/OCR before adoption; bounded scanned/encrypted/large inputs, asset rights | pdf_pipeline.py; docs | representative parser comparison | not_started |  |
| H.model | Deterministic mode; actual optional callers; candidate locators, injection/value validation | llm/ledger | no-key/disabled/malformed/injection tests | not_started |  |
| H.cost | Provider/model/prompt/schema/usage/attempt/cost/failure tracking | llm/budget | retry/concurrency/schema drift tests | not_started |  |
| H.brief | Grounded persisted synthesis with claim references, changes/unknowns/qualifiers | synthesis/repository | brief evidence and interface equivalence | not_started |  |
| H.schedule | Transparent broad then targeted passes; marginal utility; declared cache/cutoff | runner/pipeline | fixed-sample scheduler ablation | not_started |  |
| I.profile | Search; actual states; identity/relationships; concise grounded brief/comparison | api/frontend | API/UI integration tests | not_started |  |
| I.evidence | Actual snippets/JSON/PDF locations, dates/hash/basis; stale/conflict/history views | api/frontend | evidence drawer and frozen-history tests | not_started |  |
| I.access | Keyboard/mobile/readability/loading/empty/error; XSS/safe links; bounded local serving | api/frontend | accessibility and security review | not_started |  |
| 8.dataset | Seeded official development/held-out stratification; manifest hashes; independent adjudication/provenance | evaluation | dataset manifest and label review | not_started |  |
| 8.corpus | Hard-negative identities, refresh scenarios, fixed-cutoff baseline and ablations | evaluation/tests | release corpus and paired comparison | not_started |  |
| 8.metrics | Precision/wrong-company/abstentions/recall; financial exact match; evidence/replay; refresh; cardinality | evaluation | reference-based report with uncertainty | not_started |  |
| 8.operations | Independent actual requests/time; p50/p95; API cost; official weights only; research lessons | evaluation/docs | transport instrumented report, primary source review | not_started |  |
| 9.docs | Canonical README; reuse uppercase FLOW/DECISIONS; tracker; architecture/contract/source/evidence/refresh/cost/security | root/docs | dated consistency review | in_progress | Useful historical docs retained |
| 9.repo | Semantic modules; licensed fixtures; ignored generated/secret/build data; locked dependencies/licence/CI | pyproject/tests/.github | clean lock install/package/offline CI | not_started |  |
| 9.flow | Implemented trigger/call chain/data/checks/budgets/states/errors/retry/checkpoint/example/test per flow | FLOW.md | code-to-flow review | not_started |  |
| 9.decisions | Continue D-020: date/status/problem/decision/implementation/alternatives/limits/tests/revisit | DECISIONS.md | same-unit dated decision records | not_started |  |
| 10 | Read/reproduce/implement/verify/docs/diff/local-commit loop; truthful handoff on context limits | workflow/docs | commit evidence and handoff | in_progress | User-specified inline execution order applies |
| 11.safety | Zero observed wrong-company/unsupported finance; all claims resolve; full finance semantics; unknown safe; redirects blocked | release tests | stated adjudicated sample and locator checks | not_started |  |
| 11.persistence | No-op replay/outages/known changes/history/resume/migrations | release tests | paired fixtures and upgrade tests | not_started |  |
| 11.execution | Every input envelope; canonical interface; measured hard budgets; clean install; offline vs live; no publication | release checks | contract/scale/transport/install audit | not_started |  |
| 11.coverage | Held-out gains/ablations; precision/evidence; supplied scale or parameterized 100/1000; real 100 smoke | evaluation | retained full evidence-complete outputs/report | not_started |  |
| 12.A–12.J | Final status/repository/contract/corrections/features/validation/performance/run/artifacts/risks | delivery report | actual final HEAD/status/evidence inspection | not_started |  |
| X01 | Stale submission hash and historical PASS claims | README/SUBMISSION_READINESS/VERIFICATION_REPORT | date and verified release commit | verified | Candidate hash labelled historical, current readiness explicitly incomplete; dated verification/architecture superseding records |
| X02 | MIT declaration without licence | LICENSE; pyproject.toml | ownership/history and package inspection | verified | Author/history metadata checked; MIT LICENSE/NOTICE included in wheel; source data not relicensed |
| X03 | Unpinned install / absent hosted CI evidence | lock/.github | fresh locked install; local CI commands (hosted unverified) | implemented_unverified | Clean noneditable clone at e64c0ee: locked install + 286 offline tests/lint/types + installed wheel dashboard verified. Hosted/Linux/container evidence unavailable |
| X04 | Env example not consumed; DATA_DIR disconnected | config.py; .env.example | isolated settings tests | verified | Four settings tests cover derivation, override, consumed names and runtime directory |
| X05 | Brand-biased benchmark / uncounted discovery budget / misleading metrics | benchmark.py | universe sample and shared instrumentation | not_started |  |
| X06 | Early timer wakeup bypasses spacing; synthetic runner fixtures invoke real networking | rate_limiter.py; integration tests | early-wakeup regression and wired fake pipelines | verified | 16 limiter tests and three explicitly offline integration scenarios pass; no slow-source cancellation claim |
| X07 | Missing successful body aborts independent company research | website.py | missing-body fixture and synthetic scale regression | verified | Failed source/rejection preserves independent work; full regression passes |
| X08 | Wheel omits dashboard HTML; Docker package/API wiring | pyproject/Docker/compose | wheel resources/config/runtime | implemented_unverified | HTML omission fixed, wheel resources verified, compose parses; daemon blocked |
| X09 | Registry response overwrites its own subject with requested orgnr | brreg.py; pipeline.py | wrong/missing/invalid ID and canonical API abstention | verified | Three negative fixtures failed before guard; exact returned ID required, ambiguity/source preserved; positive control covers valid resolution |

## Audit defect register

| ID | Hypothesis to recheck | Owner component | Required verification | Status | Evidence / disposition |
|---|---|---|---|---|---|
| F01 | Value support / rejected evidence | core/ledger.py | unsupported financial and verdict fixtures | implemented_unverified | Original exploit and verdict disagreement reproduced/fixed; 10 safety regressions pass. Exact snapshot/locator/predicate support still unfinished; filing-only financial candidates withheld |
| F02 | Homepage contradictory orgnr | core/entity.py; adapters/website.py | contradictory homepage fixture | verified | Contradiction bypass reproduced; test_identity_boundaries checks name/target-ID overrides and footer-preserving crawl; complex scopes separately tracked |
| F03 | PDF table, period, scale and scope | adapters/pdf_pipeline.py | financial fixture matrix | not_started | Not yet reproduced in this checkout |
| F04 | Redirect safety and accounting | core/request_gateway.py | private redirect transport instrumentation | verified | Instrumented private redirect sends only initial operation; safe hops match actual transport counts; loop/limit tests pass; live network separately unverified |
| F05 | Complete batch envelopes | cli.py; engine/runner.py | input/output cardinality contract tests | implemented_unverified | Reproduced dropped invalid inputs; complete results/input mapping now exported; contract tests pass. Interrupted/scale/export manifest checks outstanding |
| F06 | Resume schedules completed companies | engine/runner.py | spy actual research calls | verified | test_result_contract.py::test_resume_only_invokes_unfinished_companies failed before repair, passes afterward; budget restoration tracked separately |
| F07 | Outage causes retraction | core/changes.py | source outage and recovery fixtures | not_started | Not yet reproduced in this checkout |
| F08 | Replay duplicates logical claims | core/models.py; core/repository.py | snapshot replay / stable item tests | not_started | Not yet reproduced in this checkout |
| F09 | Research does not retain snapshots | engine/pipeline.py; core/repository.py | production snapshot hash resolution | verified | Production omission reproduced/fixed. Every actual successful gateway body retained; real pipeline under simulated HTTP resolves all successful registry/home/PDF sources to hash-verified captures. Offline byte replay/migration/tamper tests pass; full extraction replay and source-specific retention remain separately unfinished |
| F10 | Hard runtime and body bounds | core/request_gateway.py; engine/runner.py | slow stream, queued work and deadline tests | implemented_unverified | Stream byte cap and absolute fetch cancellation verified; synchronous DNS, queued companies, parsing and finalization reserve remain unresolved |
| F11 | Branches unwired | adapters/brreg.py; engine/pipeline.py | paginated parent-mapped branches | not_started | Not yet reproduced in this checkout |
| F12 | NAV municipality corroboration | adapters/nav_jobs.py; core/entity.py | real employer evidence fixtures | not_started | Not yet reproduced in this checkout |
| F13 | Vacancy fact-slot collisions | core/models.py; core/ledger.py | distinct vacancy IDs coexist | not_started | Not yet reproduced in this checkout |
| F14 | Discovered PDFs marked fetched | adapters/website.py | unrequested PDF discovery fixture | verified | Prior code reproduced success on an unrequested PDF; discovery now has no retrieval status/hash/time, links bypass HTML extraction |
| F15 | Fetched PDF source unregistered | engine/pipeline.py | PDF source/evidence FK resolution | verified | Prior pipeline rejected stub extracted claim due absent source; exact returned PDF acquisition source now registered before claims and resolves retained bytes/FKs; parser accuracy not claimed |
| F16 | Unavailable accounts skip fallback | engine/pipeline.py | fallback state decision matrix | verified | Prior not_found path makes zero PDF requests; matrix now covers missing/not_available/blocked/ambiguous/failed fallback and explicit not_applicable abstention under existing budgets |
| F17 | Adaptive option has no effect | adapters/website.py | new-work crawl instrumentation | not_started | Not yet reproduced in this checkout |
| F18 | Optional model has no callers | core/llm.py; core/synthesis.py | no-key, optional-caller, injection tests | verified | Dormant helper accurately documented; complete_schema has no production callers; no model integration claimed |
| F19 | API omits persisted summary | api/app.py; core/repository.py | CLI/API/batch canonical equivalence | verified | build_result persists synthesis; test_canonical_history_retains_summary_identity_and_failure_without_company checks the API payload |
| F20 | Historical API reads present identity | api/app.py; core/repository.py | frozen run after later research | verified | Immutable historical envelopes tested after changed identity/summary; legacy historical envelopes explicitly unavailable |
| F21 | Evidence drawer lacks spans | api/app.py; frontend/index.html | supporting snippet/locator endpoint and UI | not_started | Not yet reproduced in this checkout |
| F22 | Activity cites wrong registry payload | engine/pipeline.py; adapters/activity.py | entity versus accounts attribution | not_started | Not yet reproduced in this checkout |
| F23 | News index treated as dated event | adapters/website.py; adapters/activity.py | dated individual events / unknown dates | not_started | Not yet reproduced in this checkout |
| F24 | Discovery skips robots | adapters/website.py; core/request_gateway.py | homepage robots enforcement | verified | Homepage discovery requests robots; gateway denial/error tests prevent content retrieval and charge robots operations; PDFs also opt in |
| F25 | Uncounted transports | core/request_gateway.py; core/llm.py | independent request instrumentation | implemented_unverified | Redirect/robots operations match instrumented mock transport; optional model transport and whole-run live accounting remain unresolved |
| F26 | Cost reservations non-atomic | core/budget.py; core/llm.py | parallel reservations/retries | not_started | Not yet reproduced in this checkout |
| F27 | Unjustified currency / absent period | adapters/brreg.py; core/ledger.py | missing semantics abstention | not_started | Not yet reproduced in this checkout |
| F28 | Orgnr and registrable-domain parsing | core/orgnr.py; core/entity.py | grouped IDs, substrings, public suffix fixtures | verified | NO/MVA/groups/checksums, incidental digits, substring guards, co.uk/private suffixes and hostname-boundary tests pass; bundled PSL cannot fetch network |

## External dependencies

| Dependency | Status | Concrete evidence | Independent work |
|---|---|---|---|
| Docker daemon | blocked | `docker info --format '{{.ServerVersion}}'`: named pipe dockerDesktopLinuxEngine absent (2026-10-16) | Windows Python 3.12 isolated checks |
| Official schema/batch/budget/snapshot | blocked | Retrieved v2 contract describes organizer-supplied formats/resources but provides no JSON Schema or actual input assets | Explicit compatibility adapter and synthetic scale checks; acceptance unverified |
| Live credentials / paid APIs | blocked | No authorization to use personal credentials or incur charges | Deterministic and transport-mocked paths; primary public docs |
