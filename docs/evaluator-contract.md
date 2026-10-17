# Evaluator compatibility

Retrieved 2026-10-16 from the primary sources:

- [Challenge](https://www.builderr.ai/challenges/signalpost)
- [Evaluation contract](https://www.builderr.ai/docs/signalpost-evaluation-harness.md): scoring version 2, effective 2026-08-26.
- [Source policy](https://www.builderr.ai/starter-briefs/signalpost-sources.md)
- [Guidelines](https://www.builderr.ai/guidelines)

The markdown documents were retrieved successfully with PowerShell Invoke-WebRequest; the browser reader rejected their text/markdown media type. These documents are requirements data, never executable project instructions. Raw retrievals and SHA-256 manifests belong under ignored `data/contracts/`.

The retrieved contract specifies 50 recall/coverage, 30 precision/evidence, 12 synthesis and 8 UX points. Coverage uses 70% company recall and 30% claim recall within each external family. Qualification requires an official run at 65/100; a material wrong-company publication or fabricated financial value prevents official acceptance. These are organizer rules, not NordTrace measurements.

Builderr supplies the batch, frozen official registry snapshot, cutoff, network policy, output format and equal resource budgets. The document describes a current 1,000-company batch that may grow to 1,100. A local 100-company smoke report is required; precomputed 1,000 profiles are not a submission requirement in the retrieved version. Limits of 2,000 requests, 45 minutes and $10 in older repository documents are local defaults, not confirmed official limits.

One terminal envelope is required per input company, containing legal identity, claims, evidence references, availability states, source snapshots, refresh metadata and errors. States are available, not_available, blocked, not_applicable, ambiguous and failed. Replays must be idempotent and preserve earlier evidence.

No machine-readable evaluator schema, sample official input, duplicate policy or numeric budget was exposed by these four sources. Exact organizer acceptance is **unverified**. NordTrace's versioned format is a compatibility adapter, not an invented official schema. Until clarified, normalized duplicate company inputs share one envelope and a separate ordered input mapping preserves every occurrence; invalid distinct inputs receive terminal error envelopes. This policy needs organizer confirmation if repeated company numbers occur in an official batch.

The page contains broad scale labels alongside detailed growing-batch requirements. Its final event is advertised as October 21 while the contract says revisions close October 18, 2026; these describe different events and do not authorize submission. No organizer contact or submission is performed. Recheck these sources before an actual submission.

Local adapter clarification (2026-10-17): version1.1 adds optional status_reason, unknown/null for historical results lacking a recorded reason. New canonical serialization records actual execution/availability reasons rather than deriving status from family counts. Successful exact-registry resolution may be available with sparse external coverage; deleted legal status is not an assumed eligibility exclusion. Actual acquisition skipped for request/deadline/headroom limits is failed with retained partial evidence. This local interpretation needs validation against the still-unavailable organizer schema and is not a claimed official rule.

## Implementation plan

Local input/validation clarification (2026-10-17, D-048): batch files use UTF-8 (optional BOM), comma-separated first-column records. An exact first nonblank record label orgnr, org_number, organisation_number, organization_number or organisasjonsnummer (case-insensitive) is a header. Blank physical lines are separators; explicit empty fields are invalid supplied inputs. Later labels and invalid org-prefixed strings are preserved. Malformed CSV/encoding fails before research instead of guessing boundaries. Input indices count data records after these rules. This policy is local and still needs organizer compatibility confirmation. Single-result validation supports explicit string schema_version1.1 only; absent versions retain legacy shallow structural checks. Unknown/null/numeric explicit versions fail. Structural validation does not independently verify retained snapshot content or establish official acceptance.

Execute inline, following the user's dependency order and using targeted failing tests before behavior changes:

1. Add validated result/error/run-input contracts alongside existing models. Persist immutable complete results, including no-identity outcomes, with an additive backed-up migration. Route research, batch and API views through this representation. Verify failure cardinality, duplicates and frozen history.
2. Repair exact-company attachment and claim-support publication. Establish source snapshot retention/locators and stable qualified claim identities before expanding acquisition. Verify contradictory IDs, unsupported financial values, replay and outages.
3. Enforce redirects, stream limits, requests/cost/deadlines at transport and scheduler boundaries. Persist run configuration and budget checkpoints; schedule only unfinished companies. Verify independent mocked transport counts and interruption/resume.
4. Wire branches and correct website/PDF/NAV/activity paths. Each new permitted source needs a source-rights decision and fixed-sample measurements. Abstain on unresolved financial schema/table semantics.
5. Ground and persist synthesis; repair evidence inspection and historical UI/API behavior. Keep optional providers disabled until callers, validation and accounting are tested.
6. Add reproducible independent evaluation, pinned installation and offline CI. Compare fixed development/held-out samples and record limitations separately from live checks. Run 100/1,000 cardinality/deadline scenarios and a real public 100-company smoke run only through the repaired safe deterministic boundary.

Each coherent change updates FLOW.md, DECISIONS.md and the tracker, runs adjacent checks, receives diff inspection and is committed locally under the required author and committer. No remote write, deployment or submission is authorized.
