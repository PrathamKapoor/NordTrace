## D-077 — Literal Organization candidates without publication authority

- Date/status: 2026-10-18, accepted for candidate extraction only.
- Problem/evidence: homepage extraction used meta text or an arbitrary first400characters, truncated values and marked coverage found without supported locations. Fifteen then25 authored gateway/CAS fixtures reproduced this. Full-page identity alone cannot identify the subject or value of embedded data.
- Decision/implementation: core.structured_data.organization_descriptions is a pure restricted literal-JSON reader called by WebsiteAdapter.crawl on an accepted homepage. Accept only canonical Schema.org context strings, Organization/Corporation types, exact whitespace/case-normalized legalName (or name if legalName is absent), and a checksum-valid target NO-prefixed vatID or explicitly labelled PropertyValue organisation identifier. Recognized contradictory IDs abstain. Preserve exact descriptions, script index among all scripts, JSON pointer and identity-field pointers. Keep competing nodes. Remove arbitrary prefix and unidentified meta-description fallback.
- Publication boundary: candidates are EXTRACTED with zero publication confidence and diagnostic locations in existing entity_match_details, without an authoritative locator. The production snapshot ledger rejects publication. Adapter coverage is ambiguous for candidates, never found. SQLite/canonical evidence and portable audits retain diagnostics/bytes while published facts and synthesis omit the descriptions. Existing1.1 result/bundle schema is unchanged. A source-authored assertion is not independent truth; these diagnostics are not an HTML support contract.
- Bounds/errors: maximum32script elements,65,536characters per embedded script,128top-level/direct-graph nodes,16identifier entries,64container nesting levels and4,000description characters. Script/node overflow abstains for the affected whole collection. Strict JSON rejects duplicate keys/nonfinite constants. Unsupported contexts/aliases, external scripts, TextObjects, reference expansion and malformed data abstain with diagnostics. Reject Unicode surrogate scalars before retaining descriptions: review reproduced an otherwise valid registry run failing UTF8 publication on an escaped unpaired surrogate. Valid Unicode pairs remain supported. No context/reference fetching, JS, model or command execution occurs.
- Evidence/alternatives: primary Schema.org Organization/legalName/vatID/identifier/description and W3C JSON-LD1.1 were checked2026-10-18; URLs/version notes are in SOURCES.md. This is not full JSON-LD/Schema.org processing. A generic context resolver adds network/semantic complexity; name/confidence-only shortcuts weaken identity. Existing dependencies suffice. Fixtures are authored synthetic material, with no live trial or source-rights grant inferred from documentation.
- Limitations/revisit: decoded cache text is candidate input, not independent snapshot support. Retained official identity-anchor linkage, website/redirect relationships, typed HTML locator/encoding/version compatibility, language/item identity, conflicts and source-specific rights remain external-publication prerequisites. Financial/promotional statements within descriptions remain unverified. HTML parsing has no hard CPU/memory cancellation guarantee; JSON bounds do not establish the run deadline. No external coverage or independent accuracy gain is measured. Revisit at the typed support/rights gate rather than raising confidence.
- Verification: tests/unit/test_website_structured_candidates.py exercises actual acquisition/CAS/ledger, pointers, capacity/depth, forbidden reference networking, competing descriptions, instruction-like data, Unicode and production retention/export. Review40passed/no further material findings. Exact results are in docs/verification.md. No migration/dependency/historical artifact rewrite.

## D-076 — Check internal-page identity before removing footer content

- Date/status: 2026-10-18, accepted.
- Problem/evidence: homepage identity retained its footer, but focused internal pages removed the footer and checked only the first4,000characters. Eight real gateway/CAS fixtures reproduced foreign labelled subject identifiers being ignored, even with the target identifier elsewhere on the page. The production support gate withheld website claims, but candidate identity and coverage were still misleading and unsafe to reuse for new extraction.
- Decision/implementation: WebsiteAdapter.crawl parses each acquired internal page once, evaluates its complete uncleaned visible text against the target using the actual final source URL, and rejects contradictory identity before generating evidence, facts or family coverage. _identity_text preserves nearest-block context boundaries and br/hr line boundaries while joining inline spans. Homepage checks use the same helper. This prevents an unrelated Customer service heading from disguising a foreign footer as a customer mention. Only accepted pages enter the existing bounded content-cleaning path. The captured response and rejection reason remain inspectable; no source bytes are rewritten.
- Application: contact, products/services, careers, news and leadership candidate extraction on focused internal pages. Existing EntityResolver context rules remain authoritative: an explicitly labelled customer mention is not a document subject, while an unclassified conflicting legal identifier conservatively rejects. A shared domain or target identifier elsewhere cannot override that rejection. This does not prove exclusive domain ownership, resolve all footer/operator relationships, or implement structured-data identity.
- Alternatives/tradeoffs: checking a longer prefix still loses later legal information; stripping footers first loses operator evidence. Scanning the already size-capped page text costs additional CPU relative to a4,000character prefix. Parsing is still synchronous and has no hard CPU cancellation guarantee. Some legitimate multi-entity pages will abstain until explicit relationship semantics exist. No new source, dependency, database/result schema, publication rule or stored historical result changes.
- Verification: tests/unit/test_website_page_identity.py has four page classes with foreign footer, foreign late-body beyond20,000characters, separate customer heading, br/hr context boundaries, explicit customer footer and target footer controls. Three homepage helper controls cover block context and inline identifier spans. It checks exact retained bytes, rejection provenance, no candidate/evidence from rejected pages, family state and four charged requests. Review reproduced the separate-heading residual before its correction; added br/hr regressions also failed before correction. Adjacent suites and exact results are recorded in docs/verification.md. Revisit when typed HTML evidence and explicit multi-subject/operator relationships are implemented. Extends D-024 and D-073.

# Decision Log — NordTrace

## D-075 — Retire the unwired paid model transport and reject unsupported reservations

- Date/status: 2026-10-18, accepted.
- Problem/evidence: a configured key activated the optional client's direct HTTPX transport, despite no extraction/synthesis callers, no source boundary and no atomic retry-cost reservation. Five of seven new base-client policy tests failed; dummy credentials only reached a mocked provider. An isolated earlier installation with an AST-identical CostBudget accepted four concurrent0.6reservations against a1.0limit while holding/recording zero. This is not evidence of actual billed spend.
- Decision/implementation: remove the unsafe provider transport, request/prompt/retry parsing and unused pipeline construction/close calls. Retain LLMClient/LLMResult signatures as an explicitly unavailable compatibility interface: enabled is read-only false and complete_schema always returns disabled with no session, request, token or cost activity. Legacy delimiter constants remain import-compatible formatting tokens, not security controls. No configured key/URL or mutable flag can enable a provider.
- Cost contract: CostBudget.try_reserve now raises NotImplementedError instead of claiming unheld funds; can_afford is explicitly advisory. Historical/manual accounting remains available and is not rewritten. Atomic persisted cost reservation, retry reconciliation and uncertain billing remain unimplemented prerequisites for any future paid source. Disabling calls proves no current model spend, not implemented atomic billing or model quality.
- Configuration/tests: legacy model settings remain accepted for compatibility but are unused and not current provider-price quotes. Remove the misleading key-presence capability property and unsupported provider/pricing entries from .env.example. Remove eight subclass/mock-only tests that replaced complete_schema and did not verify its retry/guard implementation; seven base-client policy tests now exercise actual disabled behavior, concurrent requests, zero transport/session creation and explicit reservation failure. Existing security checks permit absent unsupported keys while rejecting non-placeholder values in all active example assignments.
- Alternatives/tradeoffs: leaving a merely documented unsafe transport lets a future caller/key activate it accidentally; enabling a paid provider would require authorization, integrated transport, durable reservations and measured benefit that do not exist. Retiring unused implementation preserves deterministic research and truthful capability claims. Direct users of the old helper now receive unsupported status; there was no working production feature to retain. No provider SDK, model asset, dependency, source publication, schema or database migration is added.
- Verification: tests/unit/test_model_policy.py plus security/adversarial/configuration/budget/result/summary/smoke checks; exact red/green and scoped review in docs/verification.md. Full regression is recorded there when complete. No live credentials, provider/network call or external charge was used. Revisit only with an authorized provider/access decision, atomic cost accounting, deterministic evidence gates and a measured evaluation plan.

## D-074 — Keep DNS outside the event loop and reconcile cancelled connection work

- Date/status: 2026-10-18, accepted.
- Problem/evidence: synchronous getaddrinfo in URL validation and connection pinning blocked the event loop. A100ms run could not cancel resolution; a subprocess with a10second resolver fixture exceeded its4second completion limit. Moving resolution to the default executor alone would still permit executor shutdown to wait for the blocking call.
- Decision/implementation: _resolve_host_async runs OS lookups in daemon threads, with a process-wide ceiling of16 outstanding OS calls. A cancelled caller discards its result, while the actual worker retains its capacity slot until the OS call finishes. Waiting for capacity is cancellable. Worker errors propagate; late results never publish into cancelled futures or closed event loops. Workers perform DNS only, never HTTP, storage or publication. Thread startup failure releases capacity.
- URL/connection policy: pure _normalize_url applies scheme/host/source-domain policy before DNS; asynchronous acquisition then checks every returned address. The synchronous validate_url utility remains for non-acquisition callers. _exchange performs final connection DNS after a charged reservation but before marking HTTP transport started. A frozen private destination object binds the addresses to HTTPX's normalized host; PinnedTransport rechecks host/public addresses, removes the object and connects numerically with original Host/SNI. There is no independent hostname resolution after this pin. Direct transport calls without prepared metadata still resolve safely.
- Accounting: cancellation during final DNS leaves the reservation charged and explicitly unstarted, with zero HTTP dispatches and no source-health failure. Rate-limit health counts completed exchange attempts after connection resolution, rather than acquired permits; cancelling an unused permit releases it without increasing request/failure counts. Existing spacing remains conservative. Independent transport instrumentation and budget telemetry agree in the blocked-DNS fixture.
- Alternatives/tradeoffs: synchronous DNS defeats cancellation; ordinary non-daemon executor work may delay process exit; unbounded abandoned workers create resource exhaustion. Per-query subprocesses or a new resolver dependency add startup/platform/operational costs without current measured benefit. The16-call ceiling is a local resource safeguard, not an organizer request limit. OS DNS cannot be killed by this implementation: if all calls remain stuck, later DNS waits until capacity returns or the run deadline expires. Long-lived processes may need operational restart if the OS never returns. No full-system hard-deadline claim is made; synchronous parser, storage, SSL-context construction and export bounds remain open.
- Verification: tests/unit/test_dns_deadlines.py covers gateway and pinning cancellation, real subprocess completion with a deliberately sleeping resolver, retained capacity across20cancelled callers plus a later caller, charged/unstarted accounting against TransportAudit, prepared destination host/private/empty hard negatives and source-policy rejection before DNS. Adjacent redirects/robots/body/rate/smoke tests and review are recorded in docs/verification.md. The slow-body fixture now gives resolver/client startup500ms and an unconsumed2second stream, retaining closure/zero-read/one-request checks and adding a1second wall ceiling. No live DNS/source/model call, schema, migration or dependency change. Revisit for platform support, resolver service adoption, persistent process recovery or any new transport.

## D-073 — Separate page resources from dated events and vacancies

- Date/status: 2026-10-18, accepted.
- Problem/evidence: a fetched news index produced a recent_activity/news_page fact and found coverage without an event/date. An empty careers page produced jobs/careers_page and found coverage. A date elsewhere in a news index does not establish an attributable event. Strict production validation already withheld these candidates, but adapter semantics were still misleading.
- Decision/implementation: WebsiteAdapter.crawl retains news/general careers pages as EXTRACTED resources candidates with news_page/careers_page fields and the final URL as stable item key/value. No arbitrary page summary is promoted as an event/vacancy. News resource discovery does not set recent_activity found; careers discovery sets jobs found only when the existing individual posting extractor actually returns candidates. Those posting heuristics remain unverified and production-withheld.
- Scope: internal candidate classification only. resources is not a scored family or new organizer contract. No resource typed support rule was added: production retains candidate/evidence/source links and rejects publication through the existing snapshot gate. No active-vacancy assertion, dated-event extraction, unknown event date, website ownership upgrade or external coverage gain is introduced. Existing frozen results stay untouched.
- Alternatives/tradeoffs: deleting all page provenance loses useful discovery evidence; retaining resource pages in jobs/activity overstates factual coverage. A resource URL is acquisition/discovery metadata, not proof of the page's substantive assertions. Actual individual events require attributable content, dates and typed locators before publication. Source fetching, robots, budgets and deadlines are unchanged; no dependency/migration required.
- Verification: tests/unit/test_website_resources.py uses real gateway/CAS/adapter paths for undated and incidentally dated news indexes and an empty careers page; a complete pipeline fixture retains both rejected candidates without published event/job/resource claims or found coverage. Exact independent four-operation adapter count accounts for separate discovery/domain-restricted robots keys. Adjacent tests and scoped review: docs/verification.md. Revisit when enabling typed resource/event/vacancy support or candidate-level coverage semantics.

## D-072 — Preserve monetary precision and each observation's qualifiers in briefs

- Date/status: 2026-10-18, accepted.
- Problem/evidence: the legacy financial template rounded float values to integers, omitted currency on Decimal/string values, dropped scale/scope and placed every metric under revenue's reporting year. Change text truncated large monetary values without units/currency. Production financial publication is withheld; these are downstream safeguards, not a completed financial extractor.
- Decision/implementation: synthesis._financial_text renders the existing Fact.value with Decimal fixed-point formatting and no rounding, conversion or scale inference. Each metric retains its own explicit currency, literal unit, reporting period and scope plus claim reference. Missing/unknown qualifiers or unsupported/nonfinite numeric representations withhold that fragment. Values exceeding256integer-plus-fraction digits are withheld before fixed-point expansion; other supported metrics remain visible with a withholding notice.
- Change semantics: current ChangeRecord lacks old/new currency and units. Monetary change notices therefore retain kind/field/claim reference and direct inspection to qualified evidence, omitting amounts rather than borrowing current qualifiers or truncating digits. Nonfinancial change wording stays unchanged. Rich qualified old/new values require a later versioned change contract.
- Scope/alternatives: new deterministic brief rendering only; no financial support predicate, model, source, schema, migration, coverage state or frozen result is changed. Separate per-metric periods avoid inventing a shared year. Displaying literal units avoids silently multiplying a source value; guessing NOK or group attachment remains prohibited. Float precision already lost upstream cannot be recovered by formatting; the producer must still supply correctly supported values. Decimal conversion here does not complete Decimal extraction.
- Tradeoffs/limits: briefs are longer; the safety bound can abstain on extreme but otherwise legitimate numbers. Unit labels and periods are not established by the renderer: production snapshot-backed support must justify them. Group/branch/brand observations retain their scope rather than becoming legal-entity amounts. Financial/table/PDF semantics, numerical change contracts and the full fixture matrix remain incomplete.
- Verification: tests/unit/test_summary_financials.py explicitly uses the preliminary legacy ledger for template mechanics, never production proof. Cases include fractional/negative/zero values, preserved zero precision, large Decimal and numeric-string values, mixed periods/currencies/scales/scopes, unresolved qualifiers, partial safe rendering, oversized expansion and NEW/CHANGED/RETRACTED text. Measured red/green, adjacent API/history checks and reviewer results: docs/verification.md. Revisit when enabling any financial publication or extending monetary/change schemas.

## D-071 — Enforce website robots policy at the gateway

- Date/status: 2026-10-18, accepted.
- Problem/evidence: Settings accepted false boolean/string/environment values for respect_robots, and the gateway then bypassed a site's denial. A second regression showed company_website/company_document callers could opt out independently. These are source-policy defects even though the current adapters explicitly request checks.
- Decision/implementation: Settings rejects disabling the public policy; RequestGateway._robots_allows no longer consults a mutable global opt-out. RequestGateway._fetch requires robots checks for website/document source types, before either cached content or transport. Caller opt-in still supports other public source types. Redirects retain the same check and existing accounting/deadline gates.
- Scope: public website/PDF acquisition. Generic robots-file requests and documented registry API calls retain their separate policy, avoiding recursive robots acquisition. This does not establish permission under every site's terms or enable any new source.
- Alternatives/tradeoffs: silently ignoring false configuration hides a misconfigured deployment; retaining adapter-only checks allows future callers to bypass policy. The recognized setting remains for compatibility but false is an explicit startup error. Source typing remains an adapter responsibility; generic acquisition is not an unrestricted website interface. Runtime settings mutation cannot disable required checks.
- Verification: eight deterministic regressions include configuration/environment, runtime mutation and caller opt-out with robots403; denied content is never requested and the robots operation is charged. Adjacent source allowance, redirect, homepage, PDF and configuration tests plus reviewer results are recorded in docs/verification.md. No schema, data migration, credential use or live acquisition. Revisit when adding source types or changing robots error/redirect/cache policy.

## D-070 — Reference displayed claims and preserve registered subunit context

- Date/status: 2026-10-18, accepted.
- Problem/evidence: deterministic briefs displayed supported values without logical claim references and omitted already verified subunits. A registered subunit is not automatically an active workplace or the target legal entity.
- Decision/implementation: `build_summary` adds stable bracketed claim IDs beside displayed identity, description, industry/code, employee, role/activity and financial-template values. Change/new-observation references use recorded logical claim IDs where present. Supported subunit examples retain their own organisation number, physical address and explicit closure/deletion qualifiers. Display at most three parent/item-key-matched observations, with an additional-observations notice rather than an invented total branch count. Activity headings no longer imply recency merely from the category; source-authored string values are not silently truncated.
- Scope: text rendering only, from the existing published ledger and verified change records. No extractor, source, publication predicate, schema, migration or model is enabled. Financial/website/role/activity producers remain withheld until their support contracts are implemented. A reference does not establish support by itself; the existing snapshot/locator validator remains authoritative. Historical summaries stay frozen.
- Alternatives/tradeoffs: a source URL cannot replace a claim reference; display-only sequence numbers would need a separate mapping contract. Full stable IDs are auditable but lengthen machine briefs; UI shortening/resolution remains a presentation task. Truncating subunit output without notice could imply completeness; describing all records as active workplaces would misstate closure/scope. Financial scalar/period/scope formatting is still an unfinished separate safeguard.
- Verification: real mocked-acquisition/storage profile tests link all displayed identity/subunit references to snapshot-backed published claims, preserve zero employees and closed units, and exercise a four-unit display cap. A preliminary legacy-ledger hard negative cannot attach a foreign parent. Additional legacy template cases explicitly test rendering only, not real publication of withheld predicates. Exact results/review in docs/verification.md. Revisit with new supported predicates, a structured brief-reference contract or financial formatting changes.

## D-069 — Separate initial observations, new knowledge and comparable changes

- Date/status: 2026-10-18, accepted.
- Problem/evidence: initial profiles described NEW observations as changes since a previous run. Identical refreshes said either first run or no changes, and newly supported fields could imply the company itself changed.
- Decision/implementation: `build_summary` receives the actual `previous_run_id` from pipeline final refresh. With no earlier run it labels initial verified observations; an empty published ledger cannot claim any verified observations. With a prior run, CHANGED/RETRACTED records describe changes in verified observations, while NEW records appear separately as newly verified knowledge. No-change wording only says no material change was established among comparable verified observations, including source-outage cases.
- Scope/tradeoffs: deterministic new briefs only; underlying observations/change records, refresh removal safeguards and frozen summaries remain unchanged. A previous failed run may precede newly verified information, so NEW remains knowledge rather than an asserted business change. Concise briefs still cap displayed changes; the canonical list remains inspectable. Claim-reference and complete financial qualifier presentation are separate unfinished requirements.
- Alternatives: treating every NEW claim as business change invents history; a single first-or-no-change sentence hides the known previous-run relationship. Rebuilding saved briefs would alter history and was rejected.
- Verification: three initial regressions failed before implementation; actual first/identical/renamed runs and frozen history then pass with adjacent refresh/conflict checks. An added empty-ledger regression failed before guarding the initial observation statement. Exact results and review are in docs/verification.md. Revisit when affirmative removals, restatements or richer temporal relationships are introduced.

## D-068 — Describe verification outcomes without inventing public absence

- Date/status: 2026-10-18, accepted.
- Problem/evidence: the real registry baseline acquired accounts successfully but withheld unsupported monetary candidates; briefs still said accounts were not publicly available. Leadership/activity templates similarly inferred absence from missing supported observations. Canonical unknowns were generated before final refresh, omitting blocked/unresolved/failed states or disagreeing with coverage.
- Decision/implementation: `synthesis.unknowns_for_coverage` supplies one state-aware vocabulary for canonical unknowns, deterministic brief and legacy API fallback. Not verified, no supported observation, blocked, unresolved/conflicting, failed and not applicable remain distinct. Missing-value templates describe verification, not whether a business fact exists publicly. Pipeline computes unknowns after `apply_refresh`, retaining its support/outage diagnostics and conflict notice.
- Scope: new research outcomes and dynamically constructed legacy API unknown lists. Previously persisted canonical summaries/results, including the real100 baseline, remain immutable. No candidate gains publication authority and no source is fetched or reclassified by this text correction.
- Alternatives/tradeoffs: replacing every message with generic unavailable would still hide important state distinctions; reconstructing old saved summaries would violate historical views. This is deterministic state-derived explanation, not a search-completeness claim. Claim references, first-observation/change wording and full financial numerical qualifiers remain separate unfinished work.
- Verification: seven failing availability/production/outage/history tests preceded correction; adjacent financial/NAV/refresh/conflict and API/history paths pass. Review found no material issues; exact commands/counts in docs/verification.md. Revisit on state-contract changes, source completeness or synthesis versioning.

## D-067 — Keep public acquisition stateless at the pinned transport

- Date/status: 2026-10-18, accepted.
- Problem/evidence: actual one-input Brreg preflight at0d207ae returned an entity200 and a server session cookie. HTTPX automatically attached that cookie to the next public request; smoke refused it. Retained failure artifacts show one dispatched operation versus two gateway attempts and exit1, not a successful smoke.
- Decision/implementation: `PinnedTransport.handle_async_request` copies request headers and removes Cookie before constructing the physical pinned request. Public acquisition does not replay server session state. Host/TLS identity, origin policy, body caps, accounting and Authorization refusal remain intact. No credential is imported or guard weakened.
- Alternatives/tradeoffs: accepting all cookies would broaden public acquisition into session behavior; clearing a shared jar before each request has concurrency races. Dropping cookies at the physical boundary is explicit and independent of jar timing. Sites requiring cookies may become unavailable; an authenticated/session source needs a separate documented access decision and implementation. HTTPX may hold received cookies transiently in memory; they are not forwarded by this public transport.
- Live follow-up: corrected first-input preflight and real100registry-only baseline completed at8a90719; measured report and retained artifact hashes in docs/registry-smoke-report.md. Baseline briefs have known state-wording defects; no release/accuracy claim.
- Verification: real HTTPX client/pinned transport with two source responses and synthetic Set-Cookie reproduces the guard failure before correction, then verifies two successful cookie-free dispatches. Adjacent source/security/transport tests and review are in docs/verification.md. An export-overrun fixture's wall-time assumption also failed under load; its independent smoke clock now advances deterministically after actual offline verification, without altering the scheduler clock. Revisit if permitted session-based acquisition is introduced.

## D-066 — Persist run source origins and use a registry-only smoke baseline

- Date/status: 2026-10-18, accepted.
- Problem/evidence: public smoke acquisition must exclude guessed domains before their access decision is established. Request limits cannot express permitted sources. Origin restrictions do not grant source rights.
- Decision/implementation: `RunConfiguration.allowed_source_origins` accepts bare HTTP(S) origins, normalizing case/default ports. Null preserves historical absence of an allowlist; empty denies all. `BudgetManager` persists/restores it. `RequestGateway._fetch` applies it before DNS, robots, cached redirect reuse and every hop, alongside adapter restrictions. Local exclusions record blocked/discovery time without fictional retrieval/hash/HTTP status. Robots cache keys include the run policy.
- Smoke scope: default `https://data.brreg.no` only; other origins refused, explicit deny-all allowed. Artifacts declare `deterministic_registry_only_no_models`. Websites/PDFs are blocked, so this repaired-core baseline cannot measure external coverage. Public Brreg/NLOD documentation was rechecked; personal-data retention/redistribution remain separate obligations.
- Compatibility: this additive optional field changes generated local1.1 schema. Review reproduced rejection of retained100/1000 bundles. The verifier recognizes exactly the installed schema and prior schema differing only by absence of this property. Both still require matching archive hashes, exact schema equality and support validation. Legacy-shaped result data cannot declare the new field; legacy projections omit its new null default during equality checking. Historical bytes remain unchanged; arbitrary schema variants remain rejected. Future incompatible changes require explicit versioning.
- Alternatives/tradeoffs: page/time limits cannot serve as a fake registry-only switch; a process-local source list would disappear on resume. Legacy null does not declare every source approved. Origin-level permission is broader than endpoint terms, so adapter/credential policies still apply. Dormant model transport is not repaired by this change.
- Verification: strict-origin/DNS/transport/redirect/cache/robots/deny-all-resume fixtures and production smoke/export tests. Review reproduced robots-cache leakage and old bundle incompatibility; failing regressions preceded both corrections. Exact results are in docs/verification.md. Revisit for new sources, supplied organizer policy or contract version changes.

## D-065 — Measure supplied-input smoke runs at the HTTP transport boundary

- Date/status: 2026-10-18, accepted.
- Problem/evidence: the benchmark produces honest canonical operational counts but had no reproducible command combining independent transport observation, explicit local limits and portable evidence. Metadata sample selection and synthetic cardinality tests cannot establish a live 100-company smoke result.
- Decision/implementation: `smoke` uses `smoke.run_smoke`, the existing `BenchmarkHarness.evaluate_batch`, canonical serializer, `export_run` and `verify_bundle`. The CLI requires `--live`, a clean installed source checkout and explicit request/runtime/company/finalization limits. It records that checkout's HEAD. Cost allowance is zero; model keys are disabled, official registry endpoints and crawler caps are fixed, robots enabled. Original settings are restored. No extra discovery allowance is created.
- Transport: a dedicated-process observer wraps `httpx.AsyncHTTPTransport.handle_async_request` below the production pinned transport, counting dispatches including errors. Query values, headers and bodies are excluded from this log; credential-bearing requests are refused before dispatch. The observer is restored on errors. Its count is compared with gateway operation telemetry; reservations remain a separate count. This is an exact HTTP dispatch count, not DNS/TCP packet instrumentation or proof of successful acquisition.
- Artifacts/state: an exclusively created output directory retains the exact supplied input, isolated database, canonical results, operational report, transport log and evidence ZIP. Hashes and a completion manifest are written after offline support/snapshot validation. Company failures remain complete envelopes. An unexpected failure preserves durable work without the outer completion manifest; existing outputs are never overwritten. The ZIP has its own independent completion semantics.
- Alternatives/tradeoffs: reusing only gateway counters would not independently detect hidden clients; a packet proxy would change pinned networking and require extra infrastructure. The observer patches a process-wide method and settings, so this command belongs in a dedicated process, never inside a concurrent API service. The implementation adds no dependencies. The local input cap is 16 MiB/10000 occurrences and ZIP capacity remains 256 MiB; these are not organizer limits.
- Budget/error semantics: invalid inputs exit2; research/integrity/accounting errors or observed budget overruns exit1 and take precedence. Review reproduced a successful exit despite a recorded synchronous publication overrun. An additional regression reproduced an export/verification overrun. Both research and observed end-to-end duration now affect exit status. Synchronous work and final manifest writing are not hard deadline bounded; end-to-end timing stops immediately before manifest construction/writing. Do not describe this as a hard runtime guarantee.
- Verification: `tests/unit/test_smoke.py` exercises real runner/publication/export with only HTTP transport mocked, duplicate/invalid input mapping, retained bytes/offline replay, exclusive output, disabled keys, failed dispatch, credential refusal, restoration, injected verification failure, uncounted dispatch and finalization/export overruns. See `docs/verification.md` for exact results. Live evidence and independent adjudication remain separate requirements. Revisit when adding paid/model clients, a new transport library, source rights, non-process use or an official evaluator contract.

## D-064 — Retire undocumented NAV search until the feed contract is implemented

- Date/status: 2026-10-18, accepted.
- Problem/evidence: current official feed documentation exposes employer.orgnr and requires bearer-authenticated feed/update processing. It also publishes a free experiment token; credentials cannot honestly be declared universally unavailable. The old adapter instead called an anonymous search URL and matched names without employer identifiers. Two new fixtures reproduced that network call and lack of an honest blocked hiring state. No published job support rule exists.
- Source/access decision: use the documented feed only after gateway-accounted authentication, exact employer evidence, active/inactive synchronization and compliant retention are implemented. Official terms require updating/removing displayed vacancies and handling personal data appropriately. Token access alone does not establish those capabilities or authorize using live credentials. No public/private token was retrieved or used, no consumer registration or organizer/source contact occurred. Source URLs/hashes/retrievals are in SOURCES.md and ignored local audit metadata.
- Implementation: NavJobsAdapter now returns a local blocked SourceRecord at the current feed URL with no HTTP status, retrieval timestamp, content hash or evidence/claims. Rejection code nav_feed_not_implemented explains the missing integration; it never asserts no vacancies. Remove the obsolete anonymous search setting/path. Pipeline records this zero-I/O policy result without a request-budget gate; future acquisition must use the gateway. Job-board sources map to the jobs family, and blocked/robots-denied/rate-limited refresh states remain blocked. Hiring unknowns say not verified rather than no postings found.
- Alternatives/tradeoffs: continuing undocumented search wastes requests and retains unsupported matching assumptions. Silently returning an empty successful result fabricates negative hiring evidence. Implementing a detached feed parser without source/update/retention support would be unwired functionality. This change reduces candidate acquisition; it does not add vacancy coverage or complete F12. The real feed, employer identity locators, privacy retention and evaluator reproducibility remain unfinished.
- Verification: test_nav_policy.py initial2failed3.82s; five final policy/state cases cover zero transport/reservations, truthful discovery-only metadata, canonical blocked state/wording and per-source blocked states. The adaptive budget fixture now spends its allowance through a permitted internal website redirect chain instead of the retired NAV path; it counts both robots policy contexts (11 operations) and retains available/no-PDF versus failed/pending-PDF assertions. An initial replacement using registry redirects exhausted website headroom; the fixture was corrected to consume its budget through actual eligible late website work, not by weakening expectations.44NAV/adaptive/rate/accounts passed33.20s, reviewer8NAV/adaptivepassed11.40s/no findings; full regression in docs/verification.md. Revisit when the complete feed/access/retention contract can be implemented and tested; never revive name-only undocumented search.

## D-063 — Qualify legal-entity accounts before creating monetary candidates

- Date/status: 2026-10-18, accepted.
- Problem/evidence: fourteen fixtures reproduced default NOK, missing/invalid periods, missing/foreign entity IDs, newer consolidated accounts replacing legal-entity results and arbitrary selection between competing same-period records. The retained official OpenAPI1.1.16 defines Regnskap.valuta as a string, regnskapsperiode dates and SELSKAP/KONSERN scope; it does not establish the monetary unit/scale needed for publication.
- Decision/implementation: BrregAdapter.fetch_accounts filters exact checksummed string subject and explicit SELSKAP before chronology. Unknown scope/identity with no qualified record abstains; complete valid ordered ISO dates are required before selecting the newest legal-entity period. Distinct competing newest records remain ambiguous; identical duplicate records do not create arbitrary competing values. Require an explicit three-uppercase-letter source currency, without claiming an independent ISO currency-list validation. Never infer NOK. Preserve full start/end dates as reporting_period, legal_entity scope, raw values including zero/negative and original capture time. This is candidate qualification, not monetary accuracy verification.
- Evidence/publication: candidate evidence points to the exact retained JSON record and displays its actual canonical JSON. Initial facts are EXTRACTED, with publication_support=unimplemented and unit_scale_basis=unresolved. Current production CitationValidator still rejects financial predicates; no new monetary publication is enabled. Decimal normalization, scale semantics, exact cell/field support and the PDF fixture matrix remain unfinished. PDF hardcoded currency and unsafe table inference are not repaired by this decision.
- State flow: review of production finalization reproduced ambiguous accounts becoming not_available and malformed accounts becoming blocked. The pipeline now records per-account-source refresh outcomes after candidate validation, distinguishing failed, blocked, ambiguous, inapplicable and absence. Found-but-unpublishable candidates are ambiguous with an explicit unit/value-support reason. Coverage preserves those states; successful acquisition alone cannot claim available financials. Review also reproduced source403/410 state loss caused by generic adapter failure; blocked/robots-denied/rate-limited now remain blocked and404/410 remain unavailable, while malformed200 stays failed. Existing permitted PDF fallback remains active for unresolved accounts.
- Alternatives/tradeoffs: selecting max period before scope could attach group revenue; filling missing dates/currency fabricates qualifiers; silently choosing an amended same-year record requires ordering semantics not yet established. Conservative abstention sacrifices candidate coverage, especially ambiguous amendments/layouts. Record-level locators support inspection but do not establish each monetary value's units or column meaning. Existing immutable published history is unchanged; no migration or financial release score is claimed.
- Verification: test_accounts_qualifiers.py initial14failed1.73s, first14passed1.75s. Production state controls3failed7.84s before propagation repair; final18passed8.36s include replay of selected JSON record and real validator rejection. Earlier40qualifier/PDF/activity/safetypassed16.38s; expanded55passed52.22s.403/410controls2red5.61s before transport-state repair; final43passed32.98s/reviewer20passed12.37s. Revisit when authoritative unit semantics, restatement ordering and complete financial locator/Decimal rules are implemented; do not weaken publication to increase counts.

## D-062 — Inspect frozen evidence through retained snapshot validation

- Date/status: 2026-10-18, accepted.
- Problem/evidence: F21's drawer fetched the current sources list and displayed only identifiers/metadata. Its company loader ignored runId. Five API cases initially failed because no run-scoped evidence endpoint existed; script checks reproduced latest-only company loading and source-only drawer requests.
- Decision/implementation: add GET /companies/{orgnr}/evidence/{evidence_id}?run_id= with explicit nordtrace-evidence-view-v1 output. Resolve the exact frozen canonical result and require referenced evidence membership in current/conflicting/last-known claims. Read the retained capture, verify acquisition metadata and rerun CitationValidator against actual bytes before returning the evidence/source/claim states and verified snapshot metadata. Missing/corrupt content returns409 snapshot_unavailable; failed support returns409 claim_support_invalid. Invalid identifiers return422, unknown run/company/evidence404, and unavailable canonical results409. Never refetch or fabricate missing content.
- UI: selected run IDs now scope company, trace and evidence requests. Native View evidence buttons open a labelled nonmodal region with loading/error states; Close/Escape restore trigger state/focus. Request sequence fencing suppresses late responses after closure/new selection. Review reproduced old evidence surviving a new profile commit, overlapping company responses replacing the newer selection and old traces surviving a failed new trace fetch. Company-load sequencing now fences those responses, winning render invalidates the drawer again, and trace loading/failure explicitly clears prior content. Show actual JSON pointer/raw source value, stored display, normalization, original retrieval/source-publication dates, scope/period/currency/unit and snapshot hash/representation. Technical provenance stays in an expandable detail section. Missing values say Not verified. A document/value locator is not an invented exact prose quote.
- Security/alternatives: all source values are escaped; external links accept only absolute HTTP(S), without credentials/control characters, through one helper. Reusing current relational sources would mix history; silently falling back to URL retrieval would invalidate replay. No PDF viewer, frontend framework or browser dependency was added. Existing unsupported candidate/legacy profiles are not promoted by this view. Full UI accessibility, stale/conflict collection presentation, parser hard bounds and public-serving controls remain unfinished.
- Verification/reproducibility: test_evidence_view.py covers actual pipeline captures, old/new runs, missing/tampered snapshots, frozen membership and persisted unsupported-value corruption. Node built-in tests execute the actual inline script for unsafe links/escaping, historical URLs, snapshot failure, pending-close sequencing, overlapping company loads and trace failure. Node24.19.0 is tested locally, optional for Python-only users and explicitly installed in CI with pinned setup-node commit; official GitHub tag/Node release checksum metadata were checked. No npm modules. Browser runtime failed twice before setup with kernel-assets os error3; no visual/real-keyboard/mobile result is claimed. docs/verification.md records exact checks/review. Revisit on new locator formats, PDF support, source retention policy or authenticated deployment; preserve frozen membership and fail-closed replay.

## D-061 — Retire the ineffective adaptive website pass

- Date/status: 2026-10-18, accepted.
- Problem/evidence: F17 reproduced two actual WebsiteAdapter.crawl invocations for the same input after business-description candidates failed publication. skip_verified_domains was accepted but never read; no new candidate set or frontier existed. Gateway caching could avoid a second homepage HTTP operation, but it did not make duplicate parsing/extraction useful adaptive research.
- Decision/implementation: remove the unused internal crawl argument and the pipeline's adaptive_business repeat. Keep the ordinary website pass and the independently budgeted accounts-to-discovered-PDF fallback. Existing unsupported website candidates stay withheld; missing business evidence remains explicit instead of rerunning identical work.
- Why/alternatives: implementing a durable remaining-candidate frontier/search/sitemap scheduler is separate work requiring evidence and source policy. Pretending the ignored flag provides discovery was misleading. Removing a no-op argument and redundant caller is the smallest complete correction permitted by F17, without inventing coverage gains.
- Tradeoffs/application: no second business crawl now occurs; a future targeted pass must supply genuinely new bounded candidates/tasks and prove marginal verified coverage. Cache hits are distinct from network operations, so this fixture does not claim saved HTTP requests, runtime improvement or recall gain. Existing20/15second financial headroom thresholds remain. Review additionally reproduced a false failure when completed stages spent exactly ten requests with no PDFs remaining. The fallback now checks actual candidate existence and financial eligibility before the adaptive_financials request gate; a real pending PDF still produces an honest exhausted-budget failure.
- Verification: test_adaptive_work.py wraps the real crawler, gateway and ledger; one initial failure3.76s observed2calls. Initial adaptive/PDF/outcome boundary24passed23.57s; two additional review controls failed before correcting the residual budget gate. Corrected26passed33.33s. Existing financial fallback state matrix still verifies actual PDF fetch/source registration and inapplicable abstention. Review and regression evidence are recorded in docs/verification.md. Revisit when permitted search/sitemap/structured extraction supports a real new-work scheduler.

## D-060 — Malformed successful registry records are failures, not absence

- Date/status: 2026-10-18, accepted.
- Problem/evidence: nine HTTP200 fixtures reproduced falsy names being labelled not_found, whitespace-only names being resolved and nonempty containers raising Pydantic errors. A malformed response cannot establish that a legal entity does not exist.
- Decision/implementation: BrregAdapter.fetch_entity preserves existing official-endpoint validation and actual404 handling, validates the response object and exact requested identifier, then requires navn to be a nonempty string before parsing CompanyIdentity. Missing/invalid names return failed with registry identity name missing or invalid. Wrong/missing identifiers remain ambiguous even if the name is also malformed. No replacement name is invented or copied from input metadata.
- Application/why: applies to successful live entity responses; only affirmative official404 follows the existing not_found path. Pipeline maps malformed successful records to failed/registry_failed, preserves their captured200 source and explicit family refresh state, and does not create a company or publish claims. Schema failure and absence must remain distinct for refresh, output and measurement.
- Alternatives/tradeoffs: treating empty names as absence hides schema drift; accepting whitespace silently claims resolution; relying on Pydantic gives inconsistent thrown versus structured failures. Broader registry field schema/version validation remains unfinished, and these fixtures do not prove live population precision.
- Verification: test_registry_schema.py has nine direct malformed-name cases plus production persisted outcome controls for absent name200, conflicting identifier+absent name and authoritative404. Initial9failed1.77s; registry/activity boundary63passed9.65s; scoped reviewer20schema/identitypassed3.24s/no material findings. Full regression evidence is recorded in docs/verification.md. Revisit if official schema introduces a genuinely distinct unavailable-name state or supplied frozen snapshots use another documented schema; do not infer absence from missing fields.

## D-059 — Activity reads its retained entity capture

- Date/status: 2026-10-18, accepted.
- Problem/evidence: F22 reproduced in the production pipeline: an accounts response with a2099 registration date was supplied to activity while citing entity bytes with a2024 date; accounts404 suppressed activity despite successful entity acquisition. A shared payload variable crossed endpoint boundaries.
- Decision/implementation: remove the payload parameter from ActivityAdapter.extract_activity. The pipeline supplies the resolved identity and entity SourceRecord; the adapter reads Repository.read_capture(source_id), checks immutable acquisition metadata, exact official entity endpoint, successful acquisition and matching checksummed subject, then parses those retained bytes. Missing/tampered/wrong-subject/nonentity captures raise explicit errors; pipeline failure handling preserves already accepted identity observations. Evidence/observation retrieval time comes from the capture, never the extraction clock or URL cache. Legacy candidates carry a JSON-root locator/raw captured document and actual JSON display; generated interpretations stay separately labelled with publication_support=unimplemented. The root locator identifies the source document and does not establish event/value support. Initial status is EXTRACTED; publication still rejects unsupported activity predicates.
- Scope/why: source binding is necessary even while legacy activity candidates fail the existing publication gate. Loading by URL or passing another caller-managed dictionary can select accounts or a newer cached response. No extra acquisition is needed; all reads are offline. Removing the internal argument is preferable to accepting an untrusted dictionary and merely trusting its source label.
- Alternatives/tradeoffs: reusing entity fetch cache is simpler but mutable and URL-keyed. Silent abstention on capture corruption would hide execution failure. Full typed dated-event extraction is separate work; current status/employee/capital/register candidates do not prove event semantics and remain unpublished. This decision does not claim F23, financial correctness or external coverage is repaired.
- Verification: test_activity_capture.py reproduces wrong endpoint payload and accounts-outage dependence, verifies production pipeline extraction against entity bytes with successful/404 accounts, and rejects metadata/subject/endpoint/missing/tampered captures while ignoring poisoned URL cache. Eight cases pass; docs/verification.md records review/regression evidence. Revisit when typed activity locators and independently labelled event producers replace legacy candidates; never reintroduce caller-selected unbound payloads.

## D-058 — Fixed disjoint partitions and balanced eligible-universe samples

- Date/status: 2026-10-18, accepted.
- Problem/evidence: brand-selected benchmarks cannot establish population coverage. Public eligible universe now has verified compressed/uncompressed hashes and411,160 records. Metadata-only inspection found41 strata and6 singletons; unknown employee metadata must not become zero. Initial joint allocation could move held-out cases into development when sample size increased; a single-stratum regression reproduced this before any population samples were generated.
- Decision/implementation: sampling.py and CLI sample-universe verify both expected hashes, validate strict UTF-8 JSONL/string/checksummed unique IDs, cap compressed bytes64MiB, line bytes1MiB and configurable raw bytes(default256MiB), then perform two streaming passes. SHA-256(seed, partition, normalized ID) parity fixes development/held-out membership independently of requested sizes. Within each partition, seeded round-robin quotas balance available metadata strata; bounded rank heaps choose without replacement. Larger samples are nested within their own partition, never crossing partitions. No source acquisition, research, database or model call occurs.
- Strata/application: AS versus other legal-form metadata; unknown/recorded-zero/1–9/10–49/50+ integer employee metadata; recorded website presence; literal holding-label/64–66 code-prefix/other industry metadata. These are selection categories, not adjudicated current company facts. Unknown/noninteger/negative employee entries remain unknown. Source metadata cannot configure acquisition or grant identity. Separate fixed-partition populations and missing strata are reported; no assumption that all municipal/similar-name/shared-domain cases appear in100 records.
- Why/alternatives: unstratified brand discovery is biased; retaining all parsed records is unnecessary; choosing development then held-out from one size-dependent rank pool leaks hold-out membership on expansion. Balancing rare strata improves diagnostic case coverage but oversamples them. Counts/quotas are transparent, not invented official family weights or population recall estimates. Independent labels, hard negatives and fixed-snapshot ablations remain necessary.
- Publication/preservation: stage in a verified sibling temporary directory, exclusively reserve final directory, hard-link two JSONL files and manifest last. This avoids POSIX directory-rename replacement of a concurrently created empty directory. Preexisting outputs/locks are refused; only the owned temporary directory/closed lock are cleaned. Publication failure can leave a partial final directory without a completion manifest; retry at a new path, never automatically delete user data. Hard-link support is required. Hash/rank work is offline preparation, not a claimed exemption from organizer budgets.
- Evidence/limits: seed nordtrace-eligible-evaluation-2026-10-18 yields205,421 development/205,739 held-out population records; real100/1000-per-split samples are disjoint/nested and each reports3 unrepresented strata. Source cutoffs remain unknown rather than fabricated; source hashes/URL, physical lines, selected IDs, populations/quotas and file hashes are retained. Sample files are inputs, not researched profiles or smoke-test results. Source-specific rights remain separate from code MIT; local audit only. docs/verification.md records measured57.203/56.953s and zero workload socket connections, plus tests/review. Revisit for alternate target populations, unbiased weighted estimation, source schema/hash changes or new stratification requirements.

## D-057 — Isolate configuration derivation tests from process overrides

- Date/status: 2026-10-18, accepted.
- Problem/evidence: fresh frozen install at db04f03 installed77 packages and built the wheel, but the full suite returned594pass/1fail/8live excluded281.48s when validation explicitly set DATABASE_PATH to an isolated clone database. The derivation test disabled .env files but inherited this process override; application precedence was correct.
- Decision/implementation: tests/unit/test_configuration.py removes DATABASE_PATH only in the test that requires it absent, and adds an independent positive control proving environment DATABASE_PATH overrides a derived DATA_DIR location. No production setting, database or precedence is changed.
- Why/alternatives: changing the expected path to the inherited override would stop testing derivation; removing the application override would break supported configuration. Relying on the developer's unset environment would keep the suite fragile.
- Application/limits: offline tests only. The isolated five-case run passes with DATABASE_PATH intentionally present. Full fresh-checkout verification must be rerun and reported honestly; this does not repair broader source, financial or deadline gates.
- Verification: `.venv/Scripts/python.exe -m pytest tests/unit/test_configuration.py -q --tb=short` with DATABASE_PATH set:5passed0.80s; docs/verification.md records fresh-install context and subsequent results. Revisit when settings/aliases change. Extends D-028's configuration verification without changing semantics.

## D-056 — Canonical operational benchmarks without implicit brand discovery

- Date/status: 2026-10-18, accepted.
- Problem/evidence: benchmark counted only available outcomes as completed, counted not-found/invalid outcomes as resolved, iterated raw duplicate strings instead of canonical keys and opened an unrelated20-request brand-search budget. CLI silently selected first10 supplied records and returned success for invalid inputs. Five initial regressions failed.
- Decision/implementation: BenchmarkHarness.evaluate_batch uses BatchRunner with the supplied/default frozen budget, canonical results/input mapping and exact cardinality validation. The retired fetch_live_companies method now rejects with a supplied-input requirement and never acquires data. CLI requires --orgnr-file, accepts existing strict CSV/JSONL parsing and processes all occurrences by default. Explicit --limit records original input count/hash and excluded indices. Input/report aliases or changes during reading abort before repository access. Reports are atomic; failures/invalid inputs use established exit codes, while support-check failures or actual budget overruns take exit1 precedence.
- Measurement semantics: completed means one persisted terminal envelope per unique required key, including failed/not-found/invalid. Availability is separate. Entity resolution requires a current legal-name observation passing snapshot validation and matching structured identity; a status label/DTO alone cannot establish it. Every counted supported observation is rechecked against retained evidence; claims count distinct logical claim_id, so corroborating observations do not inflate ratios. Corrupt snapshots preserve recorded execution status but fail support counting. Source-record inventory explicitly includes history and is not current retrieval or byte-retention proof; current transport counts come from run telemetry. Registry/registry_accounts claims are excluded from external-source counts. Per-family company counts are observed output, not recall. Independent precision/recall/financial exact match remain null/unmeasured without adjudicated labels. No official score is computed.
- Why/alternatives: reusing mutable relational rows loses frozen coverage/identity, and self-labelled verified counts cannot establish accuracy. Keeping a separate brand discovery budget would hide costs/bias. Requiring an explicit sample is safer until reproducible eligible-population sampling is implemented. A compatibility failure for the retired discovery helper is intentional; no misleading no-op option remains.
- Tradeoffs/limits: benchmark report version changes to nordtrace-operational-benchmark-v1; callers using old information_gain/correctness fields must migrate. Explicit first-N selection is transparent but is not representative sampling. Input hash double-check detects accidental concurrent edits, not a malicious local process changing bytes between reads. Current gate supports narrow registry/subunit claims; this repair adds no external coverage. Independent gold, sampling, ablations, uncertainty and real100 smoke remain unfinished. Synchronous report/SQLite timing limits remain known gaps.
- Verification: test_benchmark_contract.py plus CLI/input/result tests cover duplicates, all outcome classes, unsupported identity DTO, missing discovery, complete inputs versus explicit limit, snapshot tamper, independently counted mocked transports, input preservation/provenance and an exceeded runtime despite complete invalid-input envelopes. Initial discovery regression inadvertently entered the old public network path before isolation; no request measurement or researched profiles were established, and it is not live verification. Corrected regression and subsequent tests use isolated transport. Exact commands/counts are in docs/verification.md. Revisit with independent references and public-universe sampling. Supersedes misleading benchmark metrics/discovery behavior in older readiness records.

## D-055 — Explicit projection of the public starter example

- Date/status: 2026-10-18, accepted.
- Problem/evidence: the public OUTPUT_CONTRACT.md illustrates claims/evidence/run/operations keys; canonical envelopes use facts. No formal organizer schema or field taxonomy was supplied. A registry-listed website is not proof of official site attachment; generated structured evidence display is not an exact source quote; cumulative run counters are not per-company costs.
- Decision/implementation: retain canonical results.jsonl and add starter-example.jsonl as a declared optional projection in audit bundle v1. core.export._starter_example runs only after production canonical support validation. Claims preserve stable IDs, scope/item/period/unit/currency, all canonical qualifiers and evidence references. Map identity.website to registered_website, never official_website. Evidence carries source-class vocabulary unchanged, exact locator/raw value, snapshot hash and display text; claim_span stays null for structured data. This is a documented local mapping, not an invented private grader schema.
- Semantics/application: available claims contain current published facts only. Conflicts/last-known/coverage/refresh/relationships embedded in canonical branch values remain separately labelled, not silently republished as current. The six-state company availability is retained; the local lifecycle mapping is failed for failed research, completed for other terminal research outcomes. These lifecycle labels are illustrative and need organizer confirmation. Missing company-specific requests/cost are null with a manifest whole-run accounting reference; recorded company duration is carried only when finite/nonnegative. No extraction/identity/budget decisions come from the projection.
- Why/alternatives: replacing canonical output risks losing qualifiers and history; inventing quotes/allocating run costs would fabricate provenance. Preserve useful common example keys while declaring unresolved compatibility. No field is promoted to external verified coverage merely by renaming.
- Integrity/compatibility: manifest records projection version/path/hash and unverified acceptance. Canonical rows are checked unchanged during the second streaming export pass. Offline verification reconstructs the projection from canonical rows and compares type-sensitive normalized JSON, catching tampering even if its file hash is recomputed (zero differs from false). Older v1 bundles without projection remain supported. Capacity includes both representations; hard output deadline limitations remain D-054.
- Verification: test_starter_projection.py plus export/input suites; initial8red,8green, then zero-to-false tamper red before typed JSON comparison. Pure constructed financial mapping test proves qualifier preservation only, not financial source accuracy or publication. See docs/verification.md for measured results. Revisit when formal organizer schema, duplicate policy, structured-locator convention or per-company telemetry becomes available. Extends D-054; exact organizer acceptance remains unverified.

## D-054 — Portable canonical JSONL and atomic completion

- Date/status: 2026-10-18, accepted.
- Problem/evidence: whole-JSON exports referred to snapshots held only in SQLite. Hashes alone cannot replay. Initial portable tests failed because no export path existed; subsequent review reproduced colliding output paths and unchecked operations/schema metadata.
- Decision/implementation: core/export.py writes results.jsonl (unchanged canonical envelopes), local result-schema.json, unique retained raw objects and manifest.json last. Export revalidates exact input mapping/cardinality, projected identity, deterministic claim support and capture metadata/hash. SnapshotReader lets CitationValidator read either SQLite or a portable archive. Flush/fsync precedes exclusive same-directory hard-link publication; existing destinations/concurrent winners are preserved and only the owned temporary file is removed on failure. CLI batch --bundle exports after research; export-run and verify-bundle work offline. Batch rejects colliding JSON/bundle destinations before repository access.
- Why/alternatives: separate files lack one atomic completion point; a hash without bytes is insufficient; premature flattening loses scope/period/item identity. ZIP_STORED needs no dependency and preserves representation. A typed operations contract distinguishes whole-run recorded totals/configuration/telemetry from unavailable/null legacy accounting. Schema label/hash/content must agree with the installed local schema; tampering with a claim and recomputing its file hash still fails retained-value validation.
- Application/limits: this local nordtrace-audit-bundle-v1 format is not the public starter's flattened claims projection or official acceptance. Acquisition checkpoints remain SQLite; portable artifacts appear only after every terminal envelope exists. export-run reads rows/blobs individually; batch still builds its existing whole-JSON payload. Configurable uncompressed capacity defaults256MiB locally, separate from research budgets. Same-filesystem hard links are required; unsupported filesystems fail safely. Disk/serialization deadlines and hostile ZIP central-directory allocation are not hard bounded. Installed pinned schema/support rules are required for verification; future schema changes need versioning.
- Accounting/rights: manifest records observation time and whether run finalization was recorded; counters are whole-run, not inferred per-company costs. Missing original budget exports unavailable/null, corrupted budgets fail. Shared request_telemetry_snapshot recomputes derived usage/remaining/transport/unresolved fields from one durable tuple; verifier rejects inconsistent counters. Source rights remain source-specific; artifacts are for local audit. Unsigned internal support verification proves neither independent truth/authenticity nor redistribution permission/full extraction replay.
- Verification: test_export_bundle.py covers portability after DB closes, canonical identity, zero values, mapping, missing/tampered captures/results, unsupported/recomputed-hash claims, unsafe paths, destination/capacity, CLI, missing accounting and required operations/schema. See docs/verification.md for measured commands/counts. Revisit for official projection/schema, distribution rights, streaming acquisition export or unsupported filesystems. Extends D-021/D-053.

## D-052 — Recheck structured assertions and retain observation verification time

- Date/status: 2026-10-17, accepted.
- Problem/evidence: four post-serializer drift fixtures published unsupported company names, counts, capital or group flags while their facts remained correctly supported. Two older-evidence fixtures showed current parse/write timestamps in canonical identity and the company index despite a retained January cutoff. A real gateway cache fixture also showed cache hits replacing the recorded retrieval timestamp with cache-creation wall time.
- Decision/implementation: Repository.publish_result independently requires the structured company to equal the supported project_identity result before new publication. project_identity sets last_verified_at to the latest timezone-aware published target legal-entity identity observation; other subjects/families and missing/invalid/naive dates cannot advance it. Company index writes that value, including null unknown, rather than utcnow. HTTP200 creates its SourceRecord first and seeds CachedResponse time from the same recorded acquisition instant; cache hits retain that original retrieval time. Research completion time remains separately recorded.
- Application: newly built/persisted production results, current company index and cache provenance. An identical already-persisted envelope is still read idempotently; frozen historical data is not rewritten. Older profiles may carry earlier timestamp semantics and remain inspectable as history rather than being silently relabelled with an invented cutoff.
- Alternatives: trusting only the serializer leaves a mutable DTO bypass at storage. Parse/publication time does not establish a new source observation. Unknown timestamps cannot use the current clock as a fallback. Lexicographic date comparison fails across UTC offsets, so valid instants are compared as aware datetimes.
- Tradeoffs/limits: company last_verified_at means the newest supported identity observation, not that every field/family was freshly fetched; individual claim/source dates remain authoritative. Cache TTL retains existing policy and timestamp granularity, not a new conditional304 revalidation mechanism. Full cache-policy manifests, historical-policy labels, low-level legacy mutation enforcement and hard processing limits remain unfinished. No migration, dependency or wire-schema change is needed.
- Verification/revisit: six initial pipeline/persistence cases failed15.75s, then source-boundary and metadata arithmetic controls passed. A cache fixture initially hit the existing depleted-budget precheck; with allowance to reach the cache branch it reproduced timestamp drift1.56s and now uses one independently observed HTTP operation. Initial11cases passed15.69s, adjacent34gateway/snapshot/projection checks passed30.48s. Review reproduced last-observation-order timestamp selection on corroborating same-field facts; both orders now have regressions and timestamps use all qualifying observations before field collapse. Revisit with per-field freshness/304 contracts or revised timestamp schema; extends D-047/D-050.
- Regression fixture evidence: a broad run exposed an existing100ms setup race in the delayed-reservation-commit test, which observed no charged reservation. Its fault is now injected by advancing both clocks after asserting the actual row charge; prior safety/accounting assertions are retained and production timing logic is unchanged. See verification.md for failed and final measurements.

## D-051 — Finalize expired crashed tasks without fresh acquisition

- Date/status: 2026-10-17, accepted.
- Problem/evidence: three real runner/SQLite resume cases produced zero required envelopes after a foreign lease expired: request allowance depleted, absolute deadline expired or legacy budget unavailable. Scheduling correctly refused fresh acquisition, but publication still refused the stale owner indefinitely. A synchronized two-connection test then reproduced concurrent failure finalizers racing with different immutable payload timestamps.
- Decision/implementation: save_result may retire an expired foreign lease only for a failed terminal envelope from an explicitly identified owner, inside the same publication/checkpoint transaction. It does not claim acquisition or change any budget. Live foreign ownership, ownerless callers and nonfailed results still cannot bypass a lease. A committed immutable result fences the late old publisher; rollback restores both the expired lease and absent result. Existing unique worker owner tokens already fence normal expired-task takeover, so no redundant generation schema is introduced.
- Concurrency: a differing completed payload raises typed ResultAlreadyPublishedError (a ValueError). Runner failure-finalization paths adopt the actual existing canonical envelope on that specific competing-result race. Other validation/storage errors propagate; live foreign ownership remains visibly incomplete until its owner finishes or lease expires.
- Application: depleted/expired/unknown-budget resume, cancellation/failure finalization and concurrent finalizers. Completed companies are not researched again; original counters/limits remain authoritative. No remote requests or model calls are needed for recovery.
- Alternatives: resetting allowance merely to claim tasks violates same-run budgets; deleting a live lease risks competing work; accepting a stale available result can overwrite terminal failure. A separate generation counter adds migration complexity when unique per-worker tokens plus immutable terminal results already fence the tested lifecycle.
- Tradeoffs/limits: existing leases use wall-clock TTL and are not inferred dead before expiry. Clock skew, renewal/heartbeats and hard synchronous storage bounds remain open. This does not claim distributed exactly-once execution or recover work whose valid acquisition allowance/lease remain unknown. Follower execution can remain incomplete while a foreign lease is live, by design.
- Verification/revisit: test_crash_recovery.py covers three expired-lease budget conditions, repeated resume, no research calls, two concurrent finalizer budget paths, live/unowned/nonfailed refusal, rollback and late-owner fencing before/after terminal commit. Initial three cases and concurrent immutable race failed before their fixes;39crash/deadline/persistent-budget checks pass. Revisit for heartbeat/distributed clocks or changed ownership contract; extends D-041/D-044/D-050.

## D-050 — Publish company outcomes and relational projections in one transaction

- Date/status: 2026-10-17, accepted.
- Problem/evidence: three production fixtures reproduced partial current-company/ledger rows after a late facts failure, a committed envelope after an injected post-save exception, and visibility of partial rows to a separate SQLite connection. Existing helper commits crossed the intended company publication boundary. Review further reproduced a failed identity refresh missing from relational changes/sources after moving those writes.
- Decision/implementation: Repository.publish_result owns one outer BEGIN IMMEDIATE/commit covering owner/immutable-envelope checks, terminal checkpoint/history ordering, supported company projection, source/evidence rows, all candidate observations and changes. Selected existing bulk helpers defer commit only inside this thread-local publication scope; standalone behavior is retained. Pipeline assembles ledger observations and refresh changes without writing them; it no longer publishes an early current-company row. Captures, budget accounting and trace remain durable acquisition/diagnostic records outside this transaction. Publication independently revalidates snapshot support for current/conflicting/last-known assertions.
- Consistency: candidates must have the current subject/run and unique observation IDs; published/conflicting candidates must exactly match canonical observations, which cannot be omitted. Changes require the current subject/run and unique IDs too. Existing source/evidence/observation/change IDs may be reused only with identical stored content; prior refresh provenance keeps its original associations. Any mismatch rolls back the envelope and all projections. Existing completed envelopes remain immutable/idempotent.
- Application: production direct research, runner, CLI/API research and cancellation finalization. If a refresh has no new identity but an earlier company row exists, preserve that row while publishing failure sources/changes. A never-resolved input gets a complete canonical failure envelope without inventing a company to satisfy legacy relational FKs. Separate readers see either the old committed profile or the new complete publication.
- Alternatives: sequencing individual commits leaves partially visible or conflicting results. Deleting partial rows afterward cannot safely restore historical identity under concurrency. Holding the write transaction across network acquisition would block unrelated work; source captures therefore remain separately committed and inspectable after rollback.
- Tradeoffs/limits: publication does synchronous SQLite work and repeats support validation; disk/parser/serialization bounds remain unfinished. Legacy low-level mutation helpers and generic save_result remain compatibility interfaces, not independent publication-proof APIs; full append-only observation/schema enforcement for every caller remains unfinished. Crash lease recovery, incremental exports and model cost reservations are separate open tasks. No migration/reset is needed; schema6 history is preserved.
- Verification/revisit: test_atomic_publication.py covers late-write rollback with/without existing history, separate-reader visibility, foreign-owner refusal, candidate disagreement/evidence collision, blocked refresh projections and change-ID/subject/run/duplicate integrity. Initial three cases, two drift cases, the review refresh case and four change-integrity cases failed before their respective fixes. Projection's intermediate-row fixture now requires no publication until commit. Refresh/replay/cancellation/contracts/conflicts exercise adjacent behavior. Revisit with storage latency measurements, broader immutable schema or organizer transaction/export requirements; extends D-036/D-038/D-044/D-047.

## D-049 — Recover bounded transient budget-writer contention

- Date/status: 2026-10-17, accepted.
- Problem/evidence: the corrected projection full regression hit a real four-connection budget reservation failure: BEGIN IMMEDIATE exhausted its250ms busy wait although no allowance was overspent. An isolated retry passed. A new deterministic fixture holds a real SQLite writer until the first busy timeout, reproducing the failure without manufacturing an exception.
- Decision/implementation: Repository._budget_transaction retries only SQLITE_BUSY/SQLITE_LOCKED during BEGIN IMMEDIATE, including extended error codes. Each busy wait is at most250ms; cumulative acquisition uses both a one-second monotonic ceiling and the supplied absolute run deadline, with a short bounded backoff. After acquiring, the caller body executes once and commit errors propagate; body/commit mutations are never retried. Other errors propagate immediately with rollback/close.
- Application: shared budget initialization, request reservation, telemetry and budget checkpoint lock acquisition. Request reservation still checks original limits/deadline inside the transaction and commits before HTTP. No fresh allowance or uncharged transport is introduced.
- Alternatives: increasing an unbounded connection timeout would stall expired runs; treating locks as budget depletion confuses infrastructure failure with exhausted allowance; replaying whole transactions risks duplicate charges or side effects. Immediate failure on a normal temporary writer caused observed avoidable company failures.
- Tradeoffs/limits: a contended synchronous budget call may now wait up to one second instead of250ms, shortened by the original run deadline. Exhausted contention still raises honestly. Disk/connect/commit and wider synchronous parsing/finalization are not hard-bounded by this acquisition ceiling. Crash ownership/cost reservations remain unfinished.
- Verification/revisit: test_budget_locking.py exercises real busy-timeout recovery, held-lock absolute cutoff, real read-only BEGIN refusal without retry, and injected body-busy rollback without replay. Adjacent persistent-budget/cancellation32cases pass. Revisit with measured high-contention scheduling or an asynchronous storage boundary; extends D-041/D-042.

## D-048 — Preserve invalid input records and reject unknown explicit schemas

- Date/status: 2026-10-17, accepted.
- Problem/evidence: CSV substring detection silently skipped orgbad and every later org-prefixed value, even after a valid first input. Explicit unsupported result versions passed permissive unversioned checks. Malformed quotes could merge records and begin research; non-object result JSON raised exceptions instead of validation errors.
- Decision/implementation: cli._read_csv treats only the first nonblank CSV record as a possible header, requiring an exact case-insensitive first-cell label: orgnr, org_number, organisation_number, organization_number or organisasjonsnummer. UTF-8/BOM and strict comma-separated parsing finish before repository/research access. Blank physical lines are separators; explicit empty/whitespace cells remain invalid inputs. Later header-like strings and invalid values remain in ordered input mapping. validate_result rejects every explicit version except string1.1 and returns a diagnostic for non-object JSON; only absent schema_version selects legacy structural validation.
- Application: CLI batch CSV/TXT ingestion and local single-result validation. Repeated normalized/invalid keys still share an envelope with every input occurrence mapped separately under D-021. This is a documented local adapter policy; official CSV/header/duplicate schema acceptance remains unverified.
- Alternatives: heuristic header guesses silently change the required batch; dropping invalid rows hides failures. Treating an unknown version as legacy invents compatibility. No automatic dialect sniffing is added: comma-separated first-column input remains the supported interface.
- Tradeoffs/limits: a reserved first-record label is always a header; there is no explicit headerless override. Malformed encoding/CSV aborts import before research rather than inventing record boundaries. Missing-version legacy validation remains intentionally weaker and is not snapshot-support or official-evaluator validation. Full current1.1 validation also checks structure/references, not retained bytes.
- Verification/revisit: test_input_validation.py has23 cases, including real CLI invalid/duplicate/empty export cardinality and malformed input before repository access. Initial14cases and five non-object cases failed before correction; input/CLI/contract46passed, independently reviewed. Revisit when organizer input/schema or additional dialect requirements are supplied.

## D-047 — Project company values from supported atomic claims

- Date/status: 2026-10-17, accepted.
- Problem/evidence: retained registry JSON containing boolean capital and share count was converted by the acquisition DTO to monetary1.0/one share without corresponding supported facts. Parser-drift fixtures also exposed unsupported employee counts and legal names through the structured company and summary even though the claim gate withheld them.
- Decision/implementation: core.contracts.project_identity receives the published identity facts and projects only same-subject, legal-entity, scalar identity predicates. Their accepted values control the projection; absent support clears a business field and records previously populated fields as unresolved. Required legacy name/status fields use empty/unknown placeholders. Pipeline projects before the initial current-company write and final persistence; build_result applies the same rule. Synthesis obtains the legal name from the ledger, with an unresolved-name placeholder when absent.
- Application: newly built canonical CLI/API/batch results and current company rows, including partial failures. Raw acquisition identity remains local for discovery; retained source content is unchanged. Historical envelopes remain frozen and readable under their existing schema.
- Alternatives: trusting parsed fields bypasses locator/value verification. Adding capital facts without Decimal/currency/scale semantics would publish unsupported money. A strict new DTO validator would break historical envelope reads. These fields can be restored individually when proper typed extraction/support rules exist.
- Tradeoffs/limits: less structured registry detail is exposed until conversion; this is publication safety, not an external-coverage gain. The helper retains its conflict-only mode for existing isolated callers without a fact list; production always supplies one. This does not complete immutable observation transactions or authenticate arbitrary caller-created Fact objects outside the production ledger.
- Verification/revisit: test_identity_projection.py uses real pipeline acquisition, capture/locator validation and SQLite for boolean capital, supported zero, parser drift, intermediate current rows, idempotence, accepted-value precedence and frozen results. Review reproduced an independently supported municipality being cleared by missing full-address support; dependency withholding now applies to actual conflicts separately. Four projection and seven conflict cases pass. Revisit when new identity predicates acquire supported typed rules; extends D-033/D-036/D-046.

## D-046 — Bind registry identity authority to captured official acquisition

- Date/status: 2026-10-17, accepted.
- Problem/evidence: nine initial tests published a legal name from internally consistent captures on foreign/incorrect endpoints or populated company identity from a configured mirror. Three further fixtures published subunits despite a foreign canonical URL, foreign redirect hop or credentials. A declared authority tier and body identifier did not prove the asserted registry source semantics.
- Decision/implementation: core.evidence.require_registry_identity_acquisition binds canonical/requested/final URLs and all redirect hops to official HTTPS/default443 exact target entity lookup, without credentials, query projections, fragments or control characters. BrregAdapter checks it before resolving successful identity or authoritative404 absence; snapshot publication checks it independently. Early identity outcomes explicitly retain their ambiguity/blocked/failure state in family refresh metadata instead of guessing from HTTP status. Subunit publication now inspects every URL and credentials, retaining exact parent-filter validation with blank values included.
- Application: new live registry identity acquisition, every supported identity publication and refresh revalidation; subunit publication. Configured mirror200/404 responses remain inspectable/ambiguous and cannot leak structured identity or claim authoritative absence. Existing transport policy still blocks unsafe connections before acquisition.
- Alternatives: trusting self-declared tier/orgnr or just the final URL leaves provenance bypasses. Treating any configured mirror as the supplied official snapshot invents a cutoff/version trust contract. Official snapshot input needs a separate explicit adapter, still unfinished.
- Tradeoffs/limits: legitimate unofficial mirrors cannot serve as authoritative anchors, and a future official endpoint/query change requires a reviewed policy/schema update. This is provenance validation on retained acquisition metadata, not cryptographic proof against a hostile local database owner. It does not solve unsupported non-atomic structured identity fields, source rights, broad relationship scope or full historical policy versioning.
- Verification/revisit: test_registry_authority.py has32 URL-position adversaries, mirror200/404 and explicit-default-port control. Three subunit regressions failed before correction. Registry/locator/subunit boundary87passed; scoped reviewer also87passed with no material findings. Revisit when official snapshot/evaluator contracts or registry routes change; extends D-040/D-045.

## D-045 — Record outcome reasons independently from coverage

- Date/status: 2026-10-17, accepted.
- Problem/evidence: initial nine assertions reproduced identity-only success labelled not_available, deleted entity research labelled not_applicable, and absent persisted reasons. Further regressions reproduced budget-truncated success, generic reasons for direct depleted/expired execution and an adapter headroom skip labelled completed despite no website request.
- Decision/implementation: completed exact registry resolution produces available independently of family counts. Deletion is a legal status rather than an invented eligibility exclusion. Conflicts remain ambiguous; failed/interrupted execution preserves supported partial claims. Pipeline acquisition guards and website headroom diagnostics explicitly record unfinished work and typed budget/deadline reasons. Website's existing six/four-request thresholds remain unchanged in this unit. Ignored homepage self-links are excluded before headroom diagnostics; paired fixtures show identical eight-request acquisition with/without that link.
- Contract/application: optional status_reason is additive to the local1.1 adapter. build_result records the actual reason; CLI/API/batch read the same immutable canonical result. Existing missing reasons stay unknown/null and historical payloads are not rewritten. Private organizer schema acceptance remains unverified. A completed result with source gaps does not claim broad coverage or independent accuracy.
- Alternatives: family-count thresholds conflate sparse information with failed research; automatically excluding deleted companies invents a contract rule. Inferring old reasons from present claims changes history. Reporting skipped adapter work as completed hides resource limits.
- Tradeoffs/limits: available rates may change because their previous meaning was defective; this is not a recall/precision improvement and historical benchmark figures are not comparable as completion metrics. Broad per-family completeness and legacy benchmark metrics still require repair. The retained website headroom heuristic can leave allowance unused and needs measured scheduling work.
- Verification/revisit: production pipeline snapshots, historical HTTP selection, canonical batch export, six-state serializer and budget/headroom fixtures in test_outcome_semantics.py fail before correction and pass afterward. Adjacent cancellation, conflict, rate, subunit and API checks exercise integration. Revisit when explicit official eligibility/status schema or source-scheduler measurements are supplied; extends D-021/D-043/D-044.

## D-043 — Cancel cooperative acquisition and retain partial results

- Date/status: 2026-10-17, accepted.
- Problem/evidence: four new tests reproduced company/global overruns, cancellation with no envelopes and continued adapter work after its limit. The old per-company setting was only logged after completion. An explicit finalization reserve existed in the contract but had no effect.
- Decision/implementation: bound runner and direct pipeline acquisition by the smaller company/run work allowance; gateway uses that same cutoff. FINALIZATION_RESERVE_SEC is explicit, defaults0 for compatibility and must leave acquisition time. Pipeline cancellation finalizes supported ledger/refresh data before propagating; timer outcomes retain specific reasons. Queue fallback preserves every locally unowned unfinished input without starting it. Provider TimeoutError remains an execution error unless the actual timer expired.
- Application: CLI, API, batch and direct pipeline invocation; frozen budget settings survive resume. Invalid input remains not_applicable. Missing legacy terminal envelopes are explicit failures, including unknown-budget runs.
- Alternatives: post-hoc logging cannot enforce scheduling; dropping partial ledgers loses valid evidence; classifying every TimeoutError as a deadline invents execution history. Killing a whole process would currently lose its in-memory ledger and is not substituted for cooperative cancellation.
- Tradeoffs/limits: synchronous DNS/parsing/serialization/disk stalls still lack hard cancellation. Reserve time does not guarantee finalization on a stalled filesystem. SQLite budget lock wait increased from50ms to250ms/remaining deadline after an observed four-connection Windows contention failure; failure remains observable with no transport permission. Process-kill recovery and output-capacity reservation are separate unfinished work.
- Verification/revisit: test_execution_deadlines.py starts with failing semantic regressions and checks real runner/pipeline persistence. Budget, canonical and API checks exercise adjacent paths. Revisit for isolated untrusted parsers, bounded storage/export and hard release runtime gates; extends D-041/D-042.

## D-044 — Drain workers and enforce result ownership on interruption

- Date/status: 2026-10-17, accepted.
- Problem/evidence: review reproduced a cancelled follower publishing failure for a live owner, and a checkpoint exception leaving a sibling running after the runner closed its pipeline. A further fixture reproduced resource leakage when fallback result storage failed.
- Decision/implementation: Repository.save_result checks the current company lease owner within its publication transaction. Runner passes its owner through production persistence and all fallback writes. It cancels and drains its tasks on every exceptional gather exit and releases leases in finally. Pipeline close surrounds the entire finalizer, including fallback storage. External cancellation remains the controlling exception when cleanup storage fails; those failures are logged without claiming durable output. Ordinary storage failures remain exceptions.
- Application: concurrent run/resume workers, queued tasks and ordinary/external cancellation. A follower leaves a foreign-owned company pending rather than overwriting it. The run has no completed_at while envelopes remain missing; canonical batch cardinality checks reject a falsely complete export. The live owner can later publish its own result.
- Alternatives: taking over on follower cancellation would cancel unrelated authorized work without coordinated run cancellation; a read-before-write ownership check races with another connection. Silently returning complete would violate input cardinality.
- Tradeoffs/limits: a cancelled follower cannot independently guarantee all-input terminal output while another owner remains active. Hard-killed worker leases still need generation-based crash recovery; sequential legacy facts/current-company rows are not yet a fully fenced observation transaction. Unwritable storage raises an observable error and cannot promise durable envelopes.
- Verification/revisit: follower/leader race, checkpoint-error drain, readonly-result-storage cleanup and cancellation masking in both runner/direct pipeline all failed before correction and pass afterward. Revisit with process fencing and durable task skeletons; extends D-021/D-043.

## D-041 — Freeze and restore durable run request allowances

- Date/status: 2026-10-17, accepted; full cost/scheduler enforcement remains unfinished.
- Problem/evidence: replacement workers used fresh default budgets; unknown legacy usage could be ignored, and stale run updates could lower counters. Initial four budget regressions failed. Completed/pending fixture runs lacked declared original budgets, so scheduler fixtures now seed explicit known allowances.
- Decision/implementation: RunConfiguration is a validated model re-exported through contracts for compatibility. Version1 RunBudgetState freezes effective limits, absolute deadline, elapsed floor and telemetry in existing runs.budget_json; no DDL/history rewrite is needed. CLI/batch and API background jobs bind this state before work. PersistentRequestBudget reserves requests in short cross-connection SQLite transactions before network; counts remain consumed after crash. Resume restores original limits and known consumption, excluding any larger replacement defaults. Unknown legacy limits produce honest failure envelopes and no fresh acquisition.
- Application: CLI/API/batch. Standalone low-level gateway/pipeline callers can explicitly bind a run; unbound budgets remain in-memory and do not claim durable resume. Invalid inputs do not need a transport allowance. Published metadata carries effective configuration; unknown original limits are null. Existing canonical envelopes remain unchanged.
- Alternatives: checkpoint-only accounting loses requests after crash; in-process locks do not protect independent workers. Inferring old limits from current defaults silently grants a new allowance. Replacing the database or rewriting legacy history is unnecessary.
- Tradeoffs/limits: reservation writes add I/O; an interrupted reservation stays conservatively charged. SQLite lock waits are bounded to50ms/remaining deadline, but complete publication/parsing/DNS/finalization bounds are not yet established. Recorded cost is restored, but optional model cost reservations and cross-process aggregation remain unfinished; production model callers are disabled. Wall-clock regression refuses unsafe deadline restoration. Default numeric limits remain local, not organizer-authorized values.
- Verification: test_persistent_budgets.py exercises replacement settings, four independent connections, consumed/expired/legacy runs, shared elapsed exhaustion, gateway redirect/cache counts and repeated CLI failures. Synthetic100/1000 invalid inputs preserve exact envelopes. Revisit with externally supplied evaluator limits, shared model reservations and hard scheduler finalization; extends D-021/D-022/D-038.

## D-042 — Fence transport after reservation and always release permits

- Date/status: 2026-10-17, accepted.
- Problem/evidence: durable accounting introduced a fallible write before rate-token release. Review reproduced a stranded domain semaphore after a telemetry lock error. A delayed reservation commit also let HTTP start after the deadline. Repeated no-pending CLI resume initially returned0 for a stored failure.
- Decision/implementation: gateway releases rate tokens in nested finally regardless of accounting success, rechecks the deadline immediately before transport and separates started HTTP operations from known unstarted and unresolved charged reservations. RateLimitToken.cancel releases unused capacity without blaming source health. CLI uses one result-derived exit policy, including the no-pending path.
- Application: all gateway calls, durable or in-memory, and research/batch/resume CLI reporting. Reservations are not automatically refunded after uncertain persistence.
- Alternatives: releasing only after successful bookkeeping deadlocks shared-source work; relying on asyncio.timeout alone misses synchronous commit delay. Treating a locally cancelled request as a failed source can trip unrelated circuit breakers. A successful resume exit with stored execution failures hides programmatic errors.
- Tradeoffs/limits: late synchronous storage can consume wall time; the fence prevents a subsequent HTTP connection but does not claim real-time disk guarantees. Unresolved telemetry is explicit after failed writes. Outer task cancellation/finalization and paid model transport remain separate work.
- Verification: writer-contention and slow-commit regressions failed before correction; actual gateway transport/rate tests pass. The late commit makes zero HTTP operations while preserving one charged unstarted reservation. Revisit on transport/accounting changes; extends D-026/D-041.

## D-039 — Paginated, parent-verified registered subunits

- Date/status: 2026-10-17, accepted; representative external recall remains unmeasured.
- Problem/evidence: branch adapter had no pipeline caller, returned only one page, ignored explicit overordnetEnhet and used postal/incorrect address semantics. Pipeline/foreign-parent fixtures failed before repair. Primary schema-v2 docs and one bounded public request confirmed zero-based pages and beliggenhetsadresse.
- Decision/implementation: pipeline acquires bounded constructed pages, registers every source and retains accepted records through incomplete acquisition. BranchResult separates evidence, facts, pages, rejection reasons and completeness. Raw parent/unit identifiers are validated; brreg-subunit-v1 supplies normalized registered relationship attributes with exact record JSON pointers. Snapshot support binds official HTTPS/default443 endpoint, parent query, raw record, stable unit key and legal-entity scope.
- Application: identity-anchored Brreg subunits. The parent has a registered subunit; registration alone does not establish a separate legal entity or an active workplace. Missing physical fields do not borrow postal/target municipality. Closure dates remain source dates rather than inferred status.
- Alternatives: following untrusted next links can escape source policy; a single-source tuple cannot retain multiple page snapshots. Query filters alone do not prove every returned record belongs to the target. Copying target fields manufactures identity corroboration.
- Tradeoffs/limits: local page bounds can leave partial collections; concurrent registry updates can prevent stable totals. Reported pagination completeness is a traversal result, not an atomic registry cutoff or permission to infer removal. No generic source-disappearance producer is introduced. Live evidence is one limited company, not representative recall or the required100-company smoke.
- Verification: synthetic schema fixtures exercise complete/partial pages, empty collection, foreign/missing parents, exact snapshots, value/key/scope/endpoint tampering and malformed bounds. Four counted live registry requests returned identity plus three registered subunits with independent transport count4 and zero declared API cost; artifacts remain ignored under data/verification-runs. Revisit with official snapshot input, removal support and representative evaluation; extends D-034/D-035/D-037.

## D-040 — Exact registry origins and requested record bounds

- Date/status: 2026-10-17, accepted.
- Problem/evidence: review reproduced two records overriding configured page size1 via response metadata, and an alternate-port redirect publishing as official registry evidence. Three targeted regressions failed before correction.
- Decision/implementation: validate the requested record bound before iterating, refusing oversized count/declared size. Gateway allowed_origins binds scheme/hostname/effective port at initial, redirect, cache and nested robots boundaries. Brreg declares the configured origin for every registry request. Branch publication additionally binds official HTTPS/default443 origin.
- Application: all Brreg acquisition origin constraints and subunit extraction bounds. Default-port normalization is allowed; alternate-port hops are blocked before connection. Generic website acquisition keeps its documented broader policy unless an origin restriction is supplied.
- Alternatives: host/scheme-only checks let other services on the same hostname inherit authority; trusting pagination metadata permits untrusted responses to raise configured processing limits. A publication-only rejection would still make the prohibited request.
- Tradeoffs/limits: configured registry mirrors do not automatically qualify as official branch evidence. Generic CPU/DNS/finalization bounds and model transport accounting remain separate unfinished work.
- Verification: registry alternate-port fixture now makes one connection; fabricated alternate-port capture cannot publish; requested-size fixture rejects before emitting facts. Fresh/permissive-cached robots preserve origin policy. Revisit on intentional provider-origin migration; extends D-026/D-034.

## D-037 — Unconfirmed refresh preserves last-known support

- Date/status: 2026-10-17, accepted; affirmative removal production remains unfinished.
- Problem/evidence: a missing current observation defaulted to RETRACTED even after source failure or successful incomplete extraction. Five initial regressions failed, including retained-history and source-state gaps.
- Decision/implementation: core.refresh applies to every pipeline completion. It revalidates frozen earlier observations against retained bytes and current support rules, compares stable logical IDs and separates SOURCE_UNAVAILABLE last_known copies from current facts. Missing claims cannot establish removal. Sources/evidence and original verification IDs/times remain inspectable; summary labels unconfirmed observations. Change records include old/new evidence and observation IDs. Current facts require PUBLISHED status; other states cannot silently occupy that collection.
- Application: new single/batch/API outcomes, including registry early returns and later failures. A successful source body does not prove source-family completeness. Per-source RefreshOutcome availability and unknown completeness are explicit; 404/410 is not_available without business removal.
- Alternatives: global current_sources_ok, failed requests or missing parser output cannot prove disappearance. Promoting old existence-only ledger rows would reintroduce unsupported publication. Silently dropping stale history loses useful evidence.
- Tradeoffs/limits: removal/expiry detection is conservatively disabled until producers supply verified affirmative or complete-collection evidence. ETag/304, source-specific retention, full family completeness and stale UI presentation remain unfinished. A tampered/missing prior snapshot is not promoted; its failed revalidation is recorded in unknowns and original history remains untouched.
- Verification: real simulated acquisition/SQLite fixtures exercise blocked, unavailable, malformed and incomplete refresh then recovery; stable claims reconfirm as UNCHANGED and frozen histories persist. New-period expectations now retain the older period. No live refresh accuracy is claimed. Revisit when removal-support contracts and converted producers are implemented; extends D-034/D-035/D-036.

## D-038 — Durable history ordering and actual historical API selection

- Date/status: 2026-10-17, accepted.
- Problem/evidence: reviewer reproduced sequential runs with equal second-resolution timestamps losing their predecessor. A timestamp-only query also cannot establish whether concurrent results were published before research began. An HTTP regression showed the company route ignored run_id despite its canonical helper supporting history.
- Decision/implementation: additive schema6 history_order records run creation and first immutable publication in the corresponding SQLite transaction. Previous-result selection requires a publication sequence before the current run-creation barrier and no later run start. Old rows receive no invented ordering; known earlier completion timestamps are the conservative fallback. The actual company HTTP route forwards optional run_id to the frozen canonical serializer.
- Application: new refresh predecessor selection and historical company API. Existing data is backed up before migration, canonical payload bytes remain unchanged, repeat saves do not create new publication events.
- Alternatives: truncating clocks loses valid same-second predecessors; increasing clock precision alone does not provide a durable cross-process publication barrier. Reading latest result at refresh completion admits concurrent future observations. Reconstructing history from current rows is incorrect.
- Tradeoffs/limits: legacy histories without sufficient timing abstain. The sequence orders committed local events, not external source effective dates. Relational legacy get_previous_facts remains for compatibility but is no longer the production refresh input.
- Verification: same-timestamp predecessor/concurrent publication fixture failed before correction; schema5 copy verifies unchanged envelopes, no backfilled events, one backup and intact foreign keys. HTTP historical refresh assertion failed before route forwarding. Revisit with complete shared-run budget/checkpoint transactions; extends D-021/D-022.

## D-036 — Withhold all observations of unresolved conflicts

- Date/status: 2026-10-17, accepted.
- Problem/evidence: ledger conflict detection withheld only the incoming observation, leaving the first supported value published. Review reproduced the same arbitrary winner in canonical company fields and the dashboard. Stable JSON claim keys also exposed old delimiter-based synthesis lookups.
- Decision/implementation: ledger marks all competing observations CONFLICT; envelopes carry a separate conflicts collection with complete references. Family availability becomes ambiguous. contracts.project_identity clears disputed structured fields and dependent address/status values for canonical output and final company-row persistence. Required legal_name uses empty string plus unresolved_fields. Summaries use typed fact attributes and omit disputed identity/industry values. Acquired bytes and every competing observation remain available.
- Application: new results and their current company projection; existing immutable envelopes/history are not rewritten. Repeated corroboration does not resolve a conflict without an explicit resolution policy.
- Alternatives: first/last insertion wins or confidence-based selection would conceal disagreement. Making every acquisition identity field nullable would unnecessarily change adapters; the projection preserves their internal anchor.
- Tradeoffs/limits: conservative withholding lowers coverage; no automated temporal/source-priority resolution is introduced. Legacy endpoint support, last-known refresh and complete atomic publication remain separate unfinished requirements. The organisation number stays identified while individual values may be unresolved.
- Failure path: reviewer reproduced conflicts disappearing when a later accounts adapter raised. Ledger finalization now runs in finally for both successful and failed execution; a failed envelope retains prior supported observations and disagreements before identity projection. Persistence remains sequential and full transaction/cancellation guarantees are separate work.
- Verification: test_conflict_publication.py reproduces ledger and canonical/API leaks, preserves retained competing evidence through injected failure, tests dependent-field suppression and summary lookups. Revisit with source-completeness/temporal resolution rules. Extends D-021/D-034/D-035.

Serious engineering decision log. Each entry explains WHAT changed, WHY, what
problem it solved, alternatives considered, why they were rejected, trade-offs
accepted, and supporting evidence/tests. Entries added whenever meaningful
code/architecture changes occur.

Where a historical rationale could not be recovered from repository evidence,
it is stated as such rather than manufactured.

---

## D-001 — Canonical organisation number as identity key

- **Date:** 2026-09-29 (initial rebuild)
- **Status:** Accepted
- **Area:** Entity resolution / data model
- **Decision:** The Brønnøysund-registered `organisation_number` is the sole
  canonical identity key. Every company row, fact, source, and evidence
  record references it; all candidate sources are matched against it.

**Why:** The challenge input IS an organisation number; registry identity is
the only authoritative anchor. Name-based identity is ambiguous in Norway
(many same-name companies — measured: 5 "Fjell", 3 "Telenor"-prefixed
entities in one search).

**Alternatives considered:** name+address composite keys; URL-based identity.
**Why rejected:** names collide; domains change hands and are absent for
83/100 of a random company sample.

**Consequences:** companies without registry entries are `not_found`;
subsidiaries are distinct entities despite shared brands.
**Evidence/tests:** 18 orgnr tests; 19 entity tests; live E2E
(`tests/integration/test_e2e_resume.py`).
**Files:** `core/orgnr.py`, `core/models.py`, `core/entity.py`, `core/repository.py`.

---

## D-002 — Single RequestGateway chokepoint

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** HTTP / budget enforcement / security
- **Decision:** All outbound HTTP goes through `core/request_gateway.py`.
  Adapters take the gateway as a dependency; no direct `httpx` calls.

**Why:** The audit found the prior implementation's budget was vacuous —
`BrregAdapter` bypassed `RequestManager` with a raw `httpx.AsyncClient`, so
nothing enforced the 2,000-request cap. A single chokepoint makes budget
enforcement, SSRF protection, robots compliance, caching, and retry policy
non-bypassable by construction.

**Alternatives considered:** per-adapter budget checks (rejected: each adapter
can forget); decorator-based interception (rejected: implicit, easy to
circumvent).
**Why selected:** grep-verifiable invariant — `httpx` appears only in the
gateway (and the LLM client, which uses its own client behind the cost guard).
**Trade-offs:** every adapter must route through one interface; slightly more
indirection.
**Evidence/tests:** `test_gateway_enforces_budget_without_network` (raises
`BudgetExceededError` before any I/O); `test_budget_attack_request_limit`
(live); `test_request_budget_atomic_no_races` (8 threads, exact limit, no
overshoot).
**Files:** `core/request_gateway.py`, all `adapters/*`.

---

## D-003 — Source-specific rate limiting (generic mechanism)

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** HTTP / rate limiting
- **Decision:** `core/rate_limiter.py` implements a generic per-domain
  `SourcePolicy` (max_concurrent, min_interval, max_retries,
  breaker_threshold, breaker_cooldown) with conservative presets: NAV
  (1 concurrent, 1.0s interval), Brreg (2 concurrent, 0.5s interval).

**Why:** NAV returned HTTP 429 around the 15-company benchmark run. The
benchmark instructions explicitly forbid solving this by increasing
concurrency. A token-based limiter (the token HOLDS the per-domain semaphore
across the full request duration) caps in-flight requests per domain and
spaces request starts by a minimum interval.

**Alternatives considered:** global-only throttling (rejected: penalizes fast
registry endpoints for NAV's slowness); increasing concurrency (rejected:
makes 429s worse and violates instructions).
**Why selected:** generic — works for any domain, not a NAV one-off.
**Trade-offs:** slightly lower throughput for fast domains sharing a policy;
tokens must be released (handled on `record_success`/`record_failure`).
**Evidence/tests:** 15 rate-limiting tests incl.
`test_concurrency_limit_per_domain` (never >1 in flight for NAV),
`test_min_interval_spacing`, `test_domains_are_independent`.
**Files:** `core/rate_limiter.py`, `core/request_gateway.py`.

---

## D-004 — NAV circuit breaker

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** HTTP / failure recovery
- **Decision:** Repeated failures (429/5xx/transport) per domain open a
  circuit: requests short-circuit to `rate_limited` without network I/O until
  a cooldown elapses, then one controlled half-open attempt is allowed;
  success closes the circuit. Cooldown grows exponentially on repeated OPENs,
  capped at 4x.

**Why:** During the 100-company run NAV was IP-level 429-blocked for days
(verified by manual curl probes at +30s, +90s). Continuing to request wastes
budget and hammers the source. The benchmark instructions require a circuit
breaker that "eventually allows a controlled retry".

**Alternatives considered:** infinite retry (rejected: budget + hammering);
immediate permanent disable (rejected: no recovery when the block lifts);
16x exponential cap (rejected 2026-10-02: locked the circuit out for the rest
of a run after a transient block — measured 92/100 FAILED in v3).
**Why 4x cap:** recovers within a single 100-company run while still avoiding
wasted half-open attempts during long blocks.
**Trade-offs:** a transiently-blocked source yields degraded coverage for a
window; acceptable vs. failing companies.
**Evidence/tests:** `test_repeated_429_opens_circuit`,
`test_circuit_blocks_requests`, `test_circuit_recovery_after_cooldown`,
`test_exponential_cooldown_doubles` (4x cap), v3→v4 benchmark recovery.
**Files:** `core/rate_limiter.py`, `adapters/brreg.py`, `engine/pipeline.py`.

---

## D-005 — Registry rate-limited → BLOCKED rather than FAILED

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Terminal-state semantics / failure recovery
- **Decision:** `access_status=rate_limited` maps to hint `blocked`, and the
  pipeline maps a `blocked` identity lookup to terminal state `blocked` —
  not `failed`.

**Why:** v3 measured 92/100 companies FAILED when Brreg refused connections:
`rate_limited` was mapped to `failed`, which means "the system itself failed
despite reasonable recovery" per the challenge spec. A source being
temporarily unavailable is `blocked`. The distinction matters for judges:
92 FAILED signals a broken system; 88 available + 12 blocked signals a
correct system operating under an external block.

**Alternatives considered:** retrying identity until success (rejected:
budget + hammering); marking `not_available` (rejected: conflates "no public
information" with "source inaccessible").
**Trade-offs:** none identified — strict improvement.
**Evidence/tests:** v3 (92 FAILED) → v4 (0 FAILED, 100/100 entity resolved)
benchmark artifacts.
**Files:** `adapters/brreg.py`, `engine/pipeline.py`.

---

## D-006 — Evidence-org must equal fact-org

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Evidence validation / cross-company contamination
- **Decision:** `CitationValidator.validate()` rejects any fact whose
  evidence record belongs to a different company
  (`ev.org_number != fact.org_number` → FAILED). The repository
  `integrity_check` reports `cross_company_contamination` as a metric.

**Why:** A wrong-company publication is substantially more damaging than
missing information (challenge spec). The contamination test
(`test_cross_company_contamination`) proves A facts ⊂ A and B facts ⊂ B with
zero cross-source references; the citation-level gate enforces it at
insertion time, not just at audit time.

**Alternatives considered:** post-hoc integrity checking only (rejected:
detects contamination after the fact instead of preventing publication);
LLM-based entity checking (rejected: firewall must be deterministic).
**Trade-offs:** facts from legitimately-shared sources (e.g. a parent's
registry page) must carry the target's org on the evidence record — enforced
by the adapters.
**Evidence/tests:** `test_activity_unrelated_company_not_attached`,
`test_cross_company_contamination` (live, concurrent A+B), `validate-db`
(0 contamination).
**Files:** `core/ledger.py`, `core/repository.py`.

---

## D-007 — Parent-brand website rejection (subsidiary firewall)

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Entity resolution / website discovery
- **Decision:** Website candidates are generated brand-first (first core
  token: `TELENOR PAKISTAN AS` → `telenor.no`, not `telenor-pakistan.no`),
  and homepage verification rejects candidates whose page confirms a
  different company's identity.

**Why:** Measured evidence: naive full-name-derived candidates produced
nonsense domains (`www.telenor-pakistan.no`) and 161 TLS ConnectErrors.
Brand-first candidates are more likely to resolve — but a parent's brand site
mentions the subsidiary's name-core too, so the firewall must reject
attachment when the page identity belongs to the parent.

**Alternatives considered:** accepting name-similarity LIKELY for homepage
attachment (rejected 2026-10-02 in D-008: wrong-company attribution is worse
than a missing description); skipping brand-derived candidates entirely
(rejected: loses legitimate discoveries for single-brand companies).
**Trade-offs:** subsidiaries whose parent's site is the only web presence get
`not_available` for business description — honest, safe.
**Evidence/tests:** live verification (TELENOR PAKISTAN AS against
telenor.no → REJECTED; TELENOR ASA → verified "legal name present on page").
**Files:** `adapters/website.py`.

---

## D-008 — VERIFIED-only website fallback

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Website discovery / entity firewall
- **Decision:** `verify_site_homepage` accepts: orgnr present on page, FULL
  normalized legal name present on page, or resolver verdict VERIFIED.
  Resolver LIKELY is deliberately NOT accepted for homepage attachment.

**Why:** LIKELY matches brand-token pages for subsidiaries sharing the brand
(e.g. telenor.no mentions "Telenor" everywhere), which would attach a
parent's site to a subsidiary. The challenge spec prefers UNKNOWN over
WRONG COMPANY.

**Alternatives considered:** LIKELY acceptance with stricter corroboration
(rejected: corroborating signals like municipality rarely appear on consumer
pages); LLM verification (rejected: deterministic requirement).
**Trade-offs:** marginally lower business-description coverage for ambiguous
cases; firewall integrity is worth it.
**Evidence/tests:** live subsidiary rejection; 19 entity tests.
**Files:** `adapters/website.py`.

---

## D-009 — Leadership role slots distinguish person

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Data model / fact ledger
- **Decision:** Role facts use `field=f"role:{role_code}:{name}"` (registry)
  and `field=f"role:web:{name}"` (website) — person-distinguished slots.

**Why:** Measured defect: 7 board members sharing the `role:MEDL` slot caused
the ledger to mark 6 as CONFLICT (same slot, different normalized values) —
CONFLICT spam that hid real conflicts. The challenge requires multiple board
members to be separately representable.

**Alternatives considered:** multi-value facts (list-valued) (rejected:
breaks the one-fact-one-slot change-detection model); separate facts with
same field (rejected: triggers conflict detection).
**Trade-offs:** change detection now treats each person-role as its own slot
(a board change produces RETRACTED+NEW per person — correct).
**Evidence/tests:** `integrity_check` duplicate_fact_slots_same_run: 0 after
fix; leadership facts 192→406 in v4 (all board members published).
**Files:** `adapters/brreg.py`, `adapters/website.py`.

---

## D-010 — Website page slots distinguish URL/category

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Data model / fact ledger
- **Decision:** Multi-page website categories use path-distinguished slots:
  `careers_page:<path>`, `news_page:<path>`, `offering:<path>`.

**Why:** Measured defect: 3 news sub-pages under one `news_page` slot → 2
spurious CONFLICTs (same root cause as D-009).

**Alternatives considered:** single slot per category (rejected: conflict
spam); URL-only slots without category (rejected: loses category semantics
for change detection).
**Trade-offs:** more granular change records; acceptable.
**Evidence/tests:** `integrity_check`: 0 duplicate slots after fix; live
AkerBP crawl (24 job openings, no conflicts).
**Files:** `adapters/website.py`.

---

## D-011 — Adaptive planner with value-of-request heuristic

- **Date:** 2026-10-02
- **Status:** Accepted
- **Area:** Research planner / budget
- **Decision:** After core stages, the pipeline assesses coverage; missing
  high-value categories (business_description, financials, jobs,
  products_services) trigger targeted top-ups — remaining name-derived
  candidates for business, discovered PDFs for financials — gated by
  `budget.can_make_request()` and `runtime.should_start_expensive_operation()`.

**Why:** The v2 benchmark used only 924/2,000 requests while 4 categories
were missing for most companies. The challenge requires using remaining
capacity intelligently: "high-value missing category + high-probability
source" over "low-probability random search".

**Alternatives considered:** uniform depth for all companies (rejected:
wastes budget on already-covered companies); blind request increases
(rejected: violates benchmark instructions).
**Trade-offs:** +582 requests in v4 (1,506 total) for +241 facts; still 25%
budget headroom.
**Evidence/tests:** v4 benchmark artifact; 228 unit tests (all budget gates
still pass); live adaptive_financials/adaptive_business stages observed.
**Files:** `engine/pipeline.py`, `adapters/website.py`.

---

## D-012 — LLM optional rather than source of truth

- **Date:** 2026-09-30
- **Status:** Accepted
- **Area:** LLM usage / cost
- **Decision:** The LLM client (`core/llm.py`) is disabled without
  `LLM_API_KEY`; deterministic extraction is primary. When enabled, every
  response is schema-validated (pydantic), cost-tracked via a configurable
  price table, and web content is wrapped in UNTRUSTED delimiters (data,
  never instructions).

**Why:** The challenge forbids the LLM as source of truth for identity, URLs,
financial values, or dates. All extraction in this system is deterministic
(registry JSON paths, PDF key-line regexes). The LLM is reserved for optional
messy-page extraction/synthesis polish. $0.00 cost in every measured run.

**Alternatives considered:** LLM-mandated extraction (rejected: cost,
hallucination risk, non-determinism); no LLM client at all (rejected: loses
the integration boundary for unstructured pages).
**Trade-offs:** without a key, messy-page extraction is bounded to
deterministic patterns; acceptable (measured coverage comes entirely from
deterministic extraction).
**Evidence/tests:** 8 mock-LLM tests (valid/invalid JSON/missing fields/wrong
types/retry/cost-guard/disabled); `test_llm_disabled_without_key_ignores_web_content`;
prompt-injection tests.
**Files:** `core/llm.py`, `core/config.py`.

---

## D-013 — No OCR dependency

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** PDF pipeline / dependencies
- **Decision:** No OCR dependency added. Scanned/image PDFs are detected
  (extractable text < 50 chars) and reported as extraction-failed honestly.

**Why:** OCR dependencies (tesseract/pytesseract) require system-level
binaries and language packs — heavy for the competition environment and
Docker image; OCR text is approximate and cannot be evidence-validated to
the same standard as embedded text layers. The challenge instructs: "If OCR
dependencies are too heavy for the competition environment, keep the honest
failure behavior." Failing honestly is preferable to fabricating extracted
text — an OCR hallucination in a financial fact would be a fabricated value.

**Alternatives considered:** pytesseract (rejected: system binary dep,
approximate output, licensing/runtime implications); cloud OCR (rejected:
cost + credentials + non-determinism).
**Trade-offs:** scanned-PDF financial statements yield `failed` extraction
(honest) instead of approximate numbers.
**Evidence/tests:** `test_pdf_synthetic_multi_page` (blank pages → scanned
detection), `test_pdf_parse_non_pdf`, `test_pdf_parse_empty`.
**Files:** `adapters/pdf_pipeline.py`, `LIMITATIONS.md`.

---

## D-014 — SQLite

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** Persistence
- **Decision:** SQLite (WAL mode, FK-enforced schema, per-thread connections
  with a repository lock) via `core/repository.py`.

**Why:** Zero-dependency persistence (stdlib), file-based (works in Docker
volumes, resumable runs, `validate-db`), FK enforcement gives
database-integrity verification for free, WAL allows concurrent readers
during API serving.

**Alternatives considered:** PostgreSQL (rejected: requires a server —
deployment complexity for a single-binary challenge tool); in-memory only
(rejected: checkpointing/resume/persistence required).
**Trade-offs:** single-writer semantics (mitigated by WAL + lock); no
network access (fine for the challenge).
**Evidence/tests:** `test_concurrent_companies_no_race` (FK-consistent DB
under 10 concurrent researches); `PRAGMA foreign_key_check` in
`validate-db`; all repository tests.
**Files:** `core/repository.py`.

---

## D-015 — PDF parser choice (pypdf)

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** PDF pipeline / dependencies
- **Decision:** `pypdf` (pure-Python) for text extraction with page-preserving
  structure.

**Why:** Pure-Python (no system binaries — works in Docker slim images),
maintained, adequate for text-based annual reports (verified live: AkerBP
42-page Q2 2026 report parsed with page numbers). Page-preserving extraction
is required for evidence (`page_or_section` field).

**Alternatives considered:** pdfminer.six (slower, similar output);
pdfplumber (heavier, table extraction not needed for key-line regexes);
PyMuPDF/pypdfium2 (AGPL/proprietary licensing concerns for a public
repository).
**Trade-offs:** pypdf's text extraction is imperfect on complex layouts;
mitigated by key-line regexes over the full text and page-level evidence.
**Evidence/tests:** `test_pdf_parse_real_report` (42 pages),
`test_pdf_financial_lines_with_page_numbers`.
**Files:** `adapters/pdf_pipeline.py`, `pyproject.toml`.

---

## D-016 — HTML parser choice (BeautifulSoup + lxml)

- **Date:** 2026-09-29
- **Status:** Accepted
- **Area:** Website crawler / dependencies
- **Decision:** BeautifulSoup4 with the lxml parser backend.

**Why:** Both already present in the environment; lxml is fast (C backend)
and lenient with malformed HTML (common on small-company sites); BS4's API
makes link/text/metadata extraction concise.

**Alternatives considered:** stdlib `html.parser` (rejected: slow, strict);
selectolax (rejected: extra dep for marginal gain).
**Trade-offs:** lxml binary wheel required (present in environment and
installable via pip; documented in Docker).
**Evidence/tests:** live crawls (telenor.no, salmar.no, akerbp.com) parsed
correctly; `test_business_page_classification` fixtures.
**Files:** `adapters/website.py`, `pyproject.toml`.

---

## D-017 — FastAPI / CLI / frontend choices

- **Date:** 2026-09-30
- **Status:** Accepted
- **Area:** Interfaces
- **Decision:** FastAPI for the REST API (background research via worker
  threads + `BackgroundTasks`); Click for the CLI; a single-file vanilla-JS
  SPA frontend served by FastAPI (`/dashboard`).

**Why:** FastAPI gives pydantic validation + async + TestClient for free
(all API tests run without a live server). Click matches the required
`python -m nordtrace.cli` entry point. A dependency-free SPA keeps the
frontend auditable (no build step) and forces all numbers to come from the
API (no static demo data possible).

**Alternatives considered:** Flask (rejected: no native async/pydantic);
React/Vite (rejected: build step, heavier for a single-page dashboard);
Jinja server-rendered pages (rejected: evidence drawer interactivity needs
client-side state).
**Trade-offs:** vanilla JS is less structured than a framework; acceptable
for one page, auditable.
**Evidence/tests:** 14 API tests; 11 CLI tests; browser-verified flows
(research → identity → facts → evidence drawer → trace).
**Files:** `api/app.py`, `cli.py`, `frontend/index.html`.

---

## D-018 — No general search-engine dependency

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Source acquisition / reproducibility
- **Decision:** No external search-engine API is used. Discovery comes from
  registry fields (hjemmeside), registry search (`?navn=`), and
  name-derived candidates — all keyless and deterministic.

**Why:** Search-engine results are non-deterministic (rankings change),
rate-limited, and mostly require keys (Google CSE, Bing). Search snippets
must not become facts (challenge spec) — the underlying page must be
retrieved and verified anyway. Registry-based discovery is reproducible and
free; name-derived candidates pass the entity firewall or are rejected.

**Alternatives considered:** DuckDuckGo HTML scraping (rejected: brittle,
ToS-gray, non-deterministic); Google CSE (rejected: key + cost + quota).
**Trade-offs:** companies without registry websites and unreachable hosts
yield `not_available` for business description — measured 15% coverage,
source-limited (see `COVERAGE_GAP_ANALYSIS.md`).
**Evidence/tests:** `candidate_urls` tests; live benchmark (no search
requests in any run).
**Files:** `adapters/website.py`, `SOURCES.md`.

---

## D-019 — No Tier-3 provider

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Source acquisition
- **Decision:** No Tier-3 (reputable business-information) provider is
  integrated. Sources are Tier 0 (registry), Tier 1 (company website/PDF),
  Tier 2 (NAV jobs).

**Why:** Tier-3 providers (Proff.no, Bisnode, Dun & Bradstreet) are
commercial with ToS restricting automated access; scraping them risks
violating terms and their data would need credentials (challenge instructs:
make credentials configurable, keep optional). All measured coverage comes
from permitted public sources.

**Alternatives considered:** Proff.no scraping (rejected: ToS + fragility);
optional keyed integrations (deferred: no credentials available; documented
as optional in `SOURCES.md`).
**Trade-offs:** financials coverage limited to regnskapsregisteret + company
PDFs; acceptable — fabrication is worse.
**Evidence/tests:** `SOURCES.md` documents Tier 3 as "Not implemented
(optional integration)"; no Tier-3 requests in any benchmark run.
**Files:** `SOURCES.md`, `adapters/`.

---

## D-020 — $0 deterministic benchmark

- **Date:** 2026-10-01
- **Status:** Accepted
- **Area:** Cost / benchmark
- **Decision:** Every measured benchmark run costs $0.00: LLM disabled
  without key; all extraction deterministic; cost tracked via
  `CostBudget` with a configurable price table and `is_estimate` labeling.

**Why:** The challenge allows $10 declared API cost; the system achieves full
measured coverage without any paid API. When an LLM key IS configured, every
call is schema-validated and cost-gated (`can_afford` before the call;
fallback to deterministic extraction when the budget would be exceeded).

**Alternatives considered:** using an LLM for extraction during benchmarks
(rejected: cost, non-determinism, hallucination risk in financial values).
**Trade-offs:** none measured — $0 while meeting budgets.
**Evidence/tests:** benchmark artifacts (cost_used: 0.0 across v2/v3/v4);
8 LLM-mock tests; cost-guard tests.
**Files:** `core/budget.py`, `core/llm.py`, `benchmark.py`.
# Current decisions — 2026-10-16

## D-035 — Separate stable logical claims from source observations and collection items

- Date/status: 2026-10-17, accepted.
- Problem/evidence: random fact IDs cannot identify the same claim across replays; job_posting predicates for different vacancies collide. Initial tests reproduce absent logical IDs and spurious vacancy conflict. Previous SQL grouping also ignores source item/scope qualifiers. Short normalized values conceal currency/unit/expiry/deadline changes; four regression fixtures initially report UNCHANGED.
- Decision: add deterministic claim_v1 identity over subject/predicate/period/item/scope while retaining fact_id as observation_id and all existing historical primary keys. Values remain outside logical identity so corrections compare. Multi-valued vacancy/branch claims require stable item keys. Retain new observations across runs; deduplicate identical same-snapshot assertions within a ledger. Preserve complete change qualifiers in SQLite and compare full published assertions, including numerical/temporal qualifiers.
- Implementation/application: Fact computed claim_id/observation_id and canonical escaped JSON fact_key; typed subject_scope/item_key; producers attach explicit keys; CitationValidator checks required item/scalar scope. Schema 5 additive columns/change JSON with existing backup workflow. get_previous_facts groups by full keys; ChangeRecord carries claim/item/scope and reporting period. assertions_differ is shared by changes/conflicts and uses exact Decimal numeric equality for monetary values.
- Alternatives: replacing historical fact primary keys would overwrite observations and break provenance; hashing the value loses change comparability; source IDs change per fetch and cannot identify a logical claim. Delimiter concatenation permits ambiguous tuples; UTF-8 replacement also collapsed two invalid opaque identifiers during testing, so the canonical tuple is escaped JSON. Currency/unit are assertion qualifiers rather than keys so their corrections remain comparable.
- Tradeoffs/failure modes: legacy fact arrays continue to contain observation records with stable logical IDs; a complete separate claim/observation aggregation contract remains outstanding. Legacy scope stays unknown and collection keys are not retroactively invented. Different-snapshot corroborating observations may still coexist. Source-outage removal, concurrent temporal cutoffs, conflict publication/display and legacy integrity metrics need separate corrections. NAV/website/branch candidate keys alone do not enable their unsupported publication or establish live vacancy accuracy.
- Verification: 13 claim-identity tests cover no-op production replay, separate observation IDs, collection coexistence, delimiter/Unicode collision avoidance, copied schema-4 upgrade, collection persistence, qualifier changes and sub-epsilon monetary changes. Review caught same-instance deduplication mutating the retained row; a regression verifies first insertion PUBLISHED and replay stays PUBLISHED. Three scope adversaries reject group/unknown/collection relabeling of scalar registry identity. Existing user DB migrated only on an isolated copy from schema 1 to 5: ten original-table fingerprints preserved, zero FK violations; ignored data/migration-verification.json records it. Pydantic's documented property decorator type-ignore is scoped to its mypy compatibility issue (https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.computed_field), not a blanket suppression.
- Revisit: convert external evidence producers and stable relationships, repair source completeness/refresh and conflicts, aggregate claim observations explicitly, and measure held-out accuracy/coverage. Extends D-022/D-034; no existing history is rewritten.

## D-034 — Require snapshot-backed predicate support at production publication

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a source ID plus extractor-authored snippet cannot establish a claim value. Previously identity fields shared a generated registry sentence even when their values were absent from it. Snapshot capture alone does not repair this. Initial locator tests failed because typed locators/support verification were absent.
- Decision: production ledger publication requires retained bytes, acquisition-consistent metadata and a supported typed locator/predicate normalization. Begin with atomic Brreg identity JSON pointers; unsupported formats/families abstain until converted. Never synthesize exact quotes for structured fields. Bind observation dates/authority to capture. Apply strict count types and preserve unknown status flags.
- Implementation/application: core/evidence.py, JsonPointerLocator, BrregAdapter.identity_claims, production FactLedger(repository), schema-4 nullable evidence.locator_json and sources.source_json with backed-up migration. RFC 6901 escapes/array indices are checked. Declared address/website/status normalizations are deterministic allowlisted transformations, not executable source instructions. Predicate-specific field/type/scope checks reject a matching value at an unrelated path. Complete source metadata survives repository reads.
- Authority boundary: all Brreg calls restrict redirect hosts/schemes to their configured registry host/scheme through the gateway, including cache replay. Two new instrumented regressions reproduce copied-orgnr impostor resolution following an unrelated-host redirect and a same-host HTTPS downgrade; both now stop before a second transport operation. Public-address safety alone cannot grant official registry authority. A legitimate future registry host migration must be reviewed explicitly rather than silently delegated.
- Nested policy: review caught missing scheme propagation through robots. Both robots fetches and policy-scoped robots-cache keys now preserve host/scheme constraints; fresh and permissive-cache downgrade regressions were red before the fix and pass afterward. Cache reuse cannot expand source policy.
- Alternatives: trust confidence or snippets leaves F01 open; locating any matching number anywhere does not establish its predicate or period. Keeping old producers publishing until conversion would perpetuate unsupported claims. Rewriting all extractors at once would obscure separate correctness failures; incremental fail-closed conversion makes the limitation explicit.
- Tradeoffs/failure modes: external publication coverage temporarily drops to supported identity fields; this is documented and release acceptance remains incomplete. Existing financial/website/role/activity parsers run but their candidates are withheld pending conversion. In-memory legacy ledger tests without a repository validate only preliminary conditions. Current refresh removal semantics must be repaired before claiming parser-regression safety. JSON parsing/hash work and finalization are not yet bounded by the whole-run deadline.
- Source basis: public Brreg Enhetsregisteret documentation version 2.0.0 retrieved 2026-10-17, https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html; publisher declares NLOD 2.0. Retained HTML SHA-256 dd857144bf1a5efcd91c86b54a68eb3657f70e4e7f3d4edd77324d5aa1a4fd3b. Documentation includes required compulsory-liquidation flags. This is not the private evaluator schema and does not resolve all source-specific privacy/retention questions.
- Verification: 19 locator tests plus existing registry/API boundaries. Review independently reproduced boolean-as-count and capture-date/authority upgrading; both corrected and retested. SQLite/API round-trip and schema-3 copy upgrade preserve bytes/history without inventing legacy locators. Revisit when external family producers, extraction replay, refresh completeness and held-out accuracy/coverage are implemented. Extends D-027 and D-032; supersedes snippet-only production publication.

## D-033 — Separate PDF candidates, acquisition and fallback eligibility

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a discovery-only crawl of the previous code reports an unrequested PDF as success with a retrieval timestamp (F14). PDFs can also enter HTML extraction. Previous pipeline skips fallback for not_found accounts and omits the actually fetched PDF source, withholding its claims (F16/F15).
- Decision: record discovered documents separately with referring source/time, never fabricated retrieval metadata; exclude PDF paths from HTML extraction. Attempt document fallback for absent accepted financial claims across unavailable/error/ambiguous accounts outcomes; respect explicit not_applicable and budget/time gates. Register every returned PDF source before its evidence and claims. Count accepted publication rather than extracted candidates.
- Implementation/application: WebsiteAdapter._extract_links/crawl and ResearchPipeline adaptive financial path. Existing company-document source type remains, acquisition state is discovered until retrieval. Exact source ID/hash resolves to retained bytes.
- Alternatives: treating links as fetched misstates evidence; reusing a placeholder ID attributes claims to unfetched material; retaining the old not_found-only selector wrongly turns source unavailability into inapplicability. Rewriting PDF extraction simultaneously would obscure these independently testable orchestration defects.
- Tradeoffs/failure modes: fallback consumes budget on sources that may still be unreadable/ambiguous. A source blocked by its own robots/transport policy remains blocked. This decision does not make the existing numerical parser correct, establish scope or expand source rights.
- Verification: test_pdf_acquisition.py covers discovery with zero page allowance, five unavailable states, not_applicable abstention, query/fragment routing and exact fetched-source/snapshot/FK registration. Previous trusted repository modules loaded into an isolated test process reproduced success-for-discovery, zero fallback calls for not_found, and missing published registration for not_available. Extraction is stubbed in orchestration tests and is not live/financial accuracy evidence. Revisit when structured accounts/table-aware extraction and source-completeness scheduling are repaired. Extends D-032 and supersedes old PDF discovery labeling.

## D-032 — Retain complete response bytes and separate acquisition replay from claim proof

- Date/status: 2026-10-17, accepted.
- Problem/evidence: F09 reproduced with a real production pipeline under simulated HTTP: no source bytes persisted. The old unused save_snapshot helper truncates decoded text at 200k characters, while gateway hashes decoded text even for binary PDFs.
- Decision: hash/retain the complete bounded HTTP response body with explicit `http-response-body-v1` representation, content-addressed blobs and immutable per-source acquisition metadata. Keep legacy snapshots unchanged and untrusted for new capture checks. Offline readers verify hashes/lengths before returning bytes and preserve acquisition timestamps. Byte verification explicitly does not establish claim support or replay extraction.
- Implementation/application: schema-3 additive migration and pre-upgrade SQLite backup; Repository.save_capture/read_capture; production RequestGateway retention including robots/cache hits; load_capture and CLI verify-snapshots/replay-source. All new acquired bodies through the production gateway use this path.
- Alternatives: calling the truncating helper cannot preserve binary/large responses; storing only hashes is not replayable; files alone would require a second atomic metadata boundary. SQLite BLOBs keep existing storage architecture and atomic capture. Exact evidence locators are a subsequent dependent correction.
- Tradeoffs/failure modes: database size grows with distinct bodies; source rights/privacy and retention periods require source-specific decisions before publication. No captured website/PDF data is relicensed by the MIT code licence. Database contention is a failed acquisition rather than success without evidence. Capture runs off the event loop with bounded SQLite lock wait and absolute-deadline checks. A reviewer reproduced a late synchronous success; this was corrected before commit and the same reproduction now times out at 31ms with zero captures. Disk/CPU scheduling is not a real-time guarantee; broader finalization deadlines remain incomplete.
- Verification: test_snapshots.py covers binary/non-UTF-8/large bodies, reopen/offline reads, tamper/missing refusal, cache capture, production wiring, schema-2 upgrade preservation/backup, transactional rollback and lock contention. Snapshot/contract/transport/CLI boundary: 42 passed, one upstream warning. Revisit for source retention policy, locator-backed publication, extraction replay, larger persistent datasets and full deadline/finalization work. Extends D-022 and D-026; supersedes decoded-text hashing for new gateway acquisitions only.

## D-031 — Verify the returned authoritative identifier

- Date/status: 2026-10-17, accepted.
- Problem/evidence: three fixtures returned a different/missing/invalid orgnr with a legal name; fetch_entity manufactured the requested orgnr on all three, enabling wrong-company attachment despite an authoritative URL.
- Decision/implementation: require a checksum-valid returned organisasjonsnummer equal to the normalized requested identifier before constructing identity or evidence. Wrong/absent identifiers return ambiguous with the captured source and entity_ambiguous error through the canonical API. Unexpected JSON shapes fail explicitly.
- Application: live registry identity acquisition; exact supplied-snapshot anchoring still needs its separate input adapter.
- Alternatives: trusting only the requested URL or copying requested identity cannot establish the response's subject.
- Tradeoffs/limits: malformed/incomplete official responses abstain; no claim of independent population accuracy is made. Current registry transport/source evidence remains subject to unfinished snapshot/locator requirements.
- Verification: three adapter tests failed before repair; API-level real gateway/MockTransport abstention and exact-identifier positive control pass. Revisit with the official supplied-snapshot schema; strengthens D-001/D-024.

## D-030 — Preserve unavailable-entity diagnostics and test error cardinality

- Date/status: 2026-10-17, accepted.
- Problem/evidence: a registry 404 produced a not_available envelope but labelled its error research_failed and discarded the attempted source. Targeted API assertions failed. Scale must include invalid inputs without pretending they are researched companies.
- Decision/implementation: pipeline identity failure retains its actual SourceRecord and distinguishes entity_not_found, registry_blocked and registry_failed. Add real runner/repository/export contract checks for 100/1,000 distinct invalid inputs with zero transport/API allowance.
- Application: no-identity canonical envelopes and synthetic invalid-input validation. These are separate from official supplied-batch acceptance/live smoke testing.
- Alternatives: dropping failed source metadata obstructs inspection; calling a 404 a program failure conflates availability and execution. Synthetic inputs cannot substitute for eligible live companies.
- Tradeoffs/limits: input/schema/duplicate organizer compatibility and incomplete source-family states remain unresolved. Error cardinality does not measure research coverage or source accuracy.
- Verification: strengthened 404 API assertions failed before repair, then 26 API/result-contract checks passed; two scale scenarios passed in 14.34s. Clean noneditable installation at e64c0ee passed 286 offline checks and installed-wheel dashboard/evaluator-adapter checks. Revisit when official schemas/budgets/batches arrive.

## D-028 — Runtime-relative storage and failure-aware acquisition

- Date/status: 2026-10-17, accepted.
- Problem/evidence: DATA_DIR did not derive database location and seven active example names were ignored. Package location otherwise determined storage. Missing successful website bodies aborted resolved company research in the full synthetic regression.
- Decision/implementation: Settings reads runtime .env, defaults data/ there and derives nordtrace.db unless DATABASE_PATH is explicit. Active example names match consumed fields; model settings are labelled dormant. WebsiteAdapter records missing bodies as failed sources/rejections and continues independent work.
- Application: editable/wheel configuration and homepage/internal-page acquisition. No real database is moved or reset.
- Alternatives: ignored settings/site-packages storage break clean installation; assertions on absent external content abort valid independent research.
- Tradeoffs/limits: launches from other directories should set DATA_DIR for shared persistence. Full family-state propagation/typed run configuration remain unfinished.
- Verification: configuration/missing-body tests failed before fixes; settings/identity/synthetic checks passed. Full offline suite: 286 passed, 8 deselected. Revisit with full source completeness and run contracts.

## D-029 — Reproducible package assets, licence and offline CI

- Date/status: 2026-10-17, accepted; container/hosted CI execution unverified.
- Problem/evidence: wheel omitted dashboard HTML; MIT metadata lacked LICENSE; no CI existed. Docker lacked required licence files and compose named the wrong API module.
- Decision/implementation: explicit frontend package data, MIT SPDX metadata, LICENSE/NOTICE; pin public-PyPI build tools setuptools 84.0.0/wheel 0.48.0. Add read-only offline Windows/Linux CI with pinned action commits and frozen install/test/lint/type/build/resource checks. Docker uses the frozen runtime lock; compose uses loopback host binding, /app/data and nordtrace.api.app:app.
- Application: installation/distribution/CI/container configuration. No push, workflow dispatch, deployment or publication occurs. Source-data rights remain separate.
- Alternatives: editable-only checks conceal missing resources; unlocked installs defeat replay; MIT software metadata cannot relicense retrieved data.
- Tradeoffs/limits: uv 0.12.5 is a setup prerequisite. Local Windows/wheel checks do not prove Linux/container/hosted success. Docker daemon is unavailable; clean-clone evidence is recorded separately after execution.
- Verification: ZIP assertion failed for absent HTML, then rebuilt wheel included HTML/LICENSE. Compose config parses; full offline checks pass. Revisit on platform/build-tool changes. Extends D-025 and supersedes historical model-integration claims in D-011/D-020: production model callers do not exist.

## D-027 — Reject verdict disagreement and unsupported financial snippets

- Date/status: 2026-10-16, accepted as an additional rejection gate; complete evidence validation remains unfinished.
- Problem/evidence: the original F01 exploit published invented revenue from a filing notice even with rejected evidence. Five targeted tests initially failed; additional regressions caught false zero support from grouped digits and lost negative-parenthesis signs.
- Decision/implementation: CitationValidator requires matching fact/evidence identity verdicts, same-company source attachment and consistent supplied hashes. Financial claims need currency and reporting period represented in the snippet and an exact finite Decimal-equivalent numeric token. Grouped thousands and negative parentheses preserve meaning; arbitrary value substrings cannot support a different number.
- Application: every new ledger publication. Existing financial filing-only evidence now fails because it contains no value. Fixtures that previously used empty/generic support or identity disagreement now contain explicit support; temporal tests use role strings rather than nonnumeric financial values.
- Alternatives: accepting a fact merely because its source/evidence IDs exist recreates the reproduced defect. Confidence cannot override rejection. No historical result is rewritten.
- Tradeoffs/limits: this is necessary but **not sufficient** support validation. It does not resolve accounting columns, exact predicate scope, retained snapshots or unsupported non-financial assertions. Current Brreg filing snippets and incomplete PDF evidence may withhold legitimate candidates; producer/locator repairs are the next dependency. No financial accuracy or coverage gain is claimed. Release remains blocked on C/G requirements.
- Verification: 10 publication-safety regressions and 55 adjacent ledger/category/adversarial checks passed; Ruff/mypy pass. Revisit only by replacing this preliminary gate with stronger snapshot/locator validation, not by weakening it. Supersedes existence-only financial support behavior in D-006.

## D-026 — Explicit transport hops, bounded bodies and origin-preserving DNS pinning

- Date/status: 2026-10-16, accepted.
- Problem/evidence: seven instrumented regressions failed: hidden private redirects, uncharged hops/robots, full oversized allocation, missing deadline cancellation, fail-open robots and ignored redirect limits. Review additionally reproduced cross-host TLS reuse after naive IP pinning and a redirected host's ignored zero-retry policy; both received failing regressions before correction.
- Decision/implementation: RequestGateway manually validates every hop, charges each actual transport attempt, reacquires rate tokens, honors each destination's retry ceiling, and streams within a byte cap and monotonic async deadline. Robots use the same counted boundary. PinnedTransport connects to a validated public IP with original Host/SNI and distinct pools keyed by the original scheme/hostname/port. Proxy environment configuration is disabled. Cache hits are explicit and retain the original retrieval time.
- Application/source policy: website discovery, internal crawls and PDFs request robots enforcement. 404/410 allow acquisition, successful robots rules control it, and other errors/refusals deny it. Unsolicited compression is refused before decoding, rather than risking decompression allocation. Redirect chains/final URLs/media types are included in canonical source records.
- Alternatives: automatic redirects cannot enforce policy before connection; URL-only DNS checks permit rebinding; pooling by rewritten numeric IP skips a second hostname's TLS verification. Automatic compression needs a separately bounded decoder and is deferred.
- Tradeoffs/limits: strict robots/encoding/DNS rules can lower coverage; no environment-proxy support. DNS lookups remain synchronous and may delay cancellation. Batch queue/parsing/finalization deadlines, persistent/shared budgets, model transport and live TLS/network verification are unfinished. Relational legacy source rows lack the new metadata, which is retained in canonical envelopes.
- Verification: eleven gateway checks include private redirects, exact counted hops/robots, slow/large streams, rebinding, Host/SNI, actual httpcore pooling with a simulated socket backend and redirected retry policy. The gateway/API/security boundary run returned 75 passed, one upstream warning. Revisit after bounded DNS, parsing and optional model integration; extends D-002/D-003/D-004.

## D-024 — Contextual identifiers and offline public suffix boundaries

- Date/status: 2026-10-16, accepted.
- Problem/evidence: 14 of 15 initial hard-negative/parser tests failed. Homepage name/number shortcuts bypassed another operator's identifier; footer cleaning hid identity evidence. Substring numbers/names created false matches, grouped/MVA identifiers failed, and last-two-label domains conflated co.uk and private hosting tenants.
- Decision: whole-input checksum-checked normalization supports grouped digits and NO/MVA labels without stripping arbitrary text. Free-text subject matching uses explicit labels; clearly labelled customer/supplier mentions and incidental numbers are not operator identity. Contradictory subject IDs run before positive website attachment. A homepage requires a labelled matching subject ID or full legal name plus registered address. Preserve footer text for attachment inspection.
- Implementation/application: `core/orgnr.py`, `core/entity.py` and `adapters/website.py`. Domain parsing receives hostnames and uses tldextract 5.4.0's bundled PSL, with suffix fetching and cache disabled; private hosting suffixes are included. Independently identified subjects can coexist in a domain's set. Full relationship provenance/effective dates remain unfinished.
- Alternatives: extra hand-coded suffixes are brittle; automatic PSL network refresh bypasses the gateway and harms replay; name/registered-domain alone cannot prove exact legal attachment.
- Tradeoffs/limits: conservative attachment abstains on unlabeled identifiers and name-only sites. Contextual role heuristics are limited to explicit customer/supplier wording; complex parent/group/footer scopes need further adjudicated fixtures. Two old tests used checksum-invalid 987654321 as a supposed free-text orgnr; their fixtures now use valid 958973306 while retaining the rejection/deduplication expectations.
- Verification: 63 identity/orgnr/adversarial checks passed, then 17 focused boundary tests passed including production crawl footer handling and URL-versus-host validation. Dependency source: [tldextract documentation](https://github.com/john-kurkowski/tldextract), retrieved 2026-10-16. Revisit on PSL/package updates or measured identity-corpus errors. Supersedes the crude domain parser and overly broad numeric contradiction rule in D-001/D-005.

## D-025 — Lock the existing dependency stack with uv

- Date/status: 2026-10-16, accepted.
- Problem/evidence: baseline declared only dependency ranges; a clean install selected current versions and cannot reproduce a later installation exactly. The necessary PSL utility adds three transitive packages.
- Decision/implementation: retain setuptools/pyproject and add a cross-platform uv.lock with package versions, public PyPI sources and distribution hashes. `uv sync --frozen --extra dev --python 3.12` is the declared development install; `uv sync --frozen --python 3.12` installs the runtime. uv 0.12.5 produced and successfully synchronized the lock.
- Application: reproducible installation and future offline CI. Existing pip editable install remains a development option but does not establish a locked release.
- Alternatives: a Windows-only pip freeze can omit Linux conditional dependencies; replacing the application stack has no evidence-based benefit.
- Tradeoffs/limits: uv is a setup prerequisite; platform-specific wheels still need validation on each supported platform. Clean-clone installation and container/hosted CI acceptance remain unverified at this decision. No optional model assets or paid APIs were added.
- Verification: uv lock resolved 80 packages, frozen synchronization succeeded; registry URLs resolve to public pypi.org. Revisit when dependency updates or supported Python/platform changes are required.

## D-023 — Recheck rate-spacing deadlines and isolate synthetic execution

- Date/status: 2026-10-16, accepted.
- Problem/evidence: fresh baseline spacing measured 0.094 seconds despite a 0.1-second minimum. A deterministic early-wakeup fixture returned at 0.04 seconds. Existing resume/deadline tests constructed simulated pipelines without wiring them into BatchRunner, allowing live requests.
- Decision/implementation: RateLimiter.acquire recomputes the monotonic wait after every wakeup until the minimum interval actually elapses. Integration fixtures explicitly patch the runner pipeline; only actual external acquisition remains live-marked.
- Application: every rate-limited request and synthetic runner test. The deadline-finalized-at-37 test asserts zero repeated research; it does not claim unfinished task recovery. The one-second fixture verifies checkpoints, not cancellation of a slow source.
- Alternatives: loosening the timing assertion would hide the rate-policy violation; relabeling accidental live tests would retain misleading simulation claims.
- Tradeoffs/limits: early timers can cause another short wait. Absolute run cancellation and shared budget restoration remain separate work. Synthetic success is not live verification.
- Verification: 16 rate-limiter tests passed, including the failing-before-fix early-wakeup case; three corrected offline integration scenarios passed. Revisit if the limiter clock or scheduling primitive changes. Supplements D-003.

## D-021 — Immutable canonical research outcomes

- Date/status: 2026-10-16, accepted.
- Problem/evidence: F05/F06/F19/F20 reproduced: invalid inputs disappeared, resume invoked finished companies, summary was lost and historical identity was reconstructed from mutable company rows. Five targeted regressions failed before implementation.
- Decision: serialize actual outcomes through `core.contracts.build_result` into version 1.1 CompanyProfile; persist full envelopes with source/evidence records and explicit errors. All newly completed CLI/API/batch results use those envelopes. Keep a separate ordered input mapping, deduplicating normalized company work. Exact organizer acceptance and duplicate semantics remain unverified.
- Implementation/application: `engine/pipeline.py`, `engine/runner.py`, `core/contracts.py`, `core/models.py`, `core/repository.py`, `cli.py`, `api/app.py`. Applies to every new completed research. Existing current data is explicitly legacy-unfrozen; historical requests without immutable envelopes return 409.
- Alternatives: reconstructing profiles on demand loses historical identity, coverage and synthesis; replacing the full stack is unnecessary. Do not silently reinterpret legacy history.
- Tradeoffs/limits: complete JSON envelopes duplicate some relational data. Published fact references are checked, but retained snapshots, exact support and refresh completeness still require subsequent repairs. Invalid inputs receive not_applicable plus an explicit error, and CLI exit 2; failed execution receives exit 1. Missing/blocked/ambiguous business information alone is not a program failure.
- Verification: `tests/unit/test_result_contract.py`, existing CLI/API tests; 33 passed in the targeted boundary run. Revisit when organizer input/output/duplicate schema is supplied. Supersedes conflicting interface reconstruction behavior in D-017.

## D-022 — Backed-up additive SQLite outcome migration

- Date/status: 2026-10-16, accepted.
- Problem/evidence: baseline schema has no version or complete-outcome store; company FKs prevent no-identity failure records. Existing user databases must survive upgrades.
- Decision: version 1 adds company_results and run_inputs; version 2 adds atomic company task leases. These reference runs rather than companies. Back up older existing databases with SQLite's backup API before DDL. Preserve all previous rows. Publish an envelope and terminal checkpoint atomically; completed payloads are immutable. Run updates reconcile against canonical publication so stale process checkpoints cannot erase committed outcomes.
- Implementation/application: Repository initialization and save_result/get_result/get_results/latest_result, for file-backed SQLite databases. Backups are uniquely named siblings; future schema versions are rejected.
- Alternatives: destructive resets violate preservation; JSON-only replacement loses existing ledger history; retroactive result reconstruction would invent historical observations.
- Tradeoffs/failure modes: backup disk space and write permission are required; failures abort migration. Legacy rows have no trustworthy complete envelopes. Leases prevent duplicate simultaneous runner ownership; expiry/crash recovery and shared budget accounting need further deadline work. Atomic adapter/ledger writes remain unfinished; this decision covers atomic canonical publication and checkpoint consistency.
- Verification: migration fixture verifies preserved identity/snapshot rows, version-0 backup contents and no repeated backup; immutability regression rejects altered history. Revisit before the next schema version. Extends D-015 rather than replacing SQLite.
## D-053 — Strict JSONL input without trusting selection metadata

- Date/status: 2026-10-18, accepted.
- Problem/evidence: rechecked public starter calls for JSONL batches. Existing CLI read every file as CSV, treating JSON objects as invalid organisation numbers. Eleven of twelve new cases failed; empty input already worked.
- Decision: auto-detect .jsonl, allow explicit --input-format, require strict objects with string organisation_number, preserve exact supplied strings and existing occurrence mapping. Ignore other metadata for identity/configuration. Validate the full container before opening a repository; malformed containers fail without acquisition, while invalid identifier strings produce canonical terminal errors.
- Implementation/application: cli._read_batch_inputs, duplicate-key/non-finite JSON hooks and batch option. Applies to new batch invocations and batch --resume input parsing; runner checkpoint/budget semantics remain unchanged. CSV/TXT retains D-048 behavior.
- Why/alternatives: numeric coercion can alter identifiers; aliases guess an undocumented schema; streaming research before validating the container can leave a partial run for malformed input. Additional universe fields are useful for later sampling, not proof of current company facts. No stack/dependency change is needed.
- Tradeoffs/limits: input strings are collected in memory, as before; no hard input-size guarantee or gzip input. Local output remains whole JSON rather than starter JSONL. Public eligible universe is available/hash-verified, but private batch, frozen identity snapshot, formal output schema, duplicate policy and numeric limits remain unconfirmed. This does not claim organizer acceptance.
- Verification: tests/unit/test_jsonl_input.py covers occurrence mapping, invalid identifiers, untrusted configuration, malformed/non-object/non-string/duplicate/non-finite input, explicit format, BOM/separators and empty input; related CLI/input/result/cardinality suites. See docs/verification.md for measured results. Revisit when organizer input/schema changes or bounded streaming ingestion is needed. Extends D-048.
