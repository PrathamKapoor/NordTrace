# Registry-only live smoke baseline — 2026-10-18

This is a real public-source research run, with complete canonical profiles and retained evidence. It establishes a bounded operational baseline, **not release readiness, independent accuracy, external recall or an official score**. A known summary defect described below remains in these immutable baseline results.

Revision: `8a90719b6a29fcb837ce77dc046842e3751c8ea7`, clean source checkout at launch. Run: `run_12a3ebe30a508b22`. Acquisition/report interval: 2026-10-18T07:33:06Z–07:36:50Z. Windows/Python3.12.5, frozen dependencies. No concurrent regression suite or paid/model/API-key acquisition ran during this measurement.

## Inputs and configuration

The fixed development sample contains100 unique eligible-universe identifiers. Seed: `nordtrace-eligible-evaluation-2026-10-18`. Selection is balanced over metadata strata, not a weighted population estimate or held-out accuracy evaluation;38/41 strata are represented. Source universe has411160 records. Its metadata/cutoff is not a current identity reference; live official Brreg responses anchored this local run. No organizer-supplied frozen identity snapshot or official private batch/limits were available.

Input: `data/evaluation-samples/universe-2025-1792273061419623400/100/development.jsonl`, SHA256 `199aa0e94b3d9c7af7c211c7752d071aa38be4614e6216173c717a44fcfd1180`. Selection/source hashes and omissions remain in that directory's manifest.

```powershell
.venv/Scripts/python.exe -m nordtrace.cli smoke data/evaluation-samples/universe-2025-1792273061419623400/100/development.jsonl --live --output data/verification-runs/registry-100-8a90719 --max-requests 2000 --max-runtime-sec 900 --per-company-sec 30 --finalization-reserve-sec 20 --concurrency 4
.venv/Scripts/python.exe -m nordtrace.cli verify-bundle data/verification-runs/registry-100-8a90719/evidence.zip
```

Use a new output directory when reproducing; existing destinations are refused. These are explicit **local** limits, not confirmed competition allowances. Allowed origin: `https://data.brreg.no`; websites/PDFs excluded, NAV disabled, model key disabled, API-cost allowance zero. Public acquisition strips server cookies. Effective settings and full input mapping are retained.

## Observed results

| Measure | Result |
|---|---:|
| Supplied inputs / unique complete envelopes |100 /100|
| Available terminal envelopes / supported legal identities |100 /100|
| Supported logical claims / published observations |1087 /1087|
| Snapshot/locator support checks |1087 passed,0 failed|
| Companies with supported registry identity / subunit locations |100 /90|
| Companies with unavailable supported location observations |10|
| Published external claims / financial claims |0 /0|
| Financial family unresolved / failed |85 /15|
| Leadership without supported published observations |100|
| Website / hiring family blocked |100 /100|
| Charged reservations / independently observed HTTP dispatches |430 /430|
| Unresolved request reservations |0|
| Successful / failed gateway transport outcomes |385 /45|
| Retry operations (included in430) |30|
| Successful retained captures / retained body bytes |385 /1264043|
| End-to-end observed duration |224.094s|
| Research/report duration before export |219.956s|
| Company duration p50 / p95 |8.047s /12.594s|
| Declared third-party API/model cost |USD0|
| Command exit code |0|

The15 failed financial families exhausted three HTTP500 attempts each; these45 failed operations and30 retries are counted. All385 successful operations have retained captures. No failed family is interpreted as a removed business fact. Available company status describes completed exact identity research, not complete information across families.

Transport counts observe asynchronous HTTPX dispatch below the pinned gateway transport, including errors; they exclude DNS/TCP packets and cache hits. All430 dispatches used the permitted Brreg origin. Company quantiles use nearest-rank recorded durations and exclude queue waits. End-to-end timing includes support validation, export and offline verification, stopping before final manifest writing. Synchronous operations remain cooperatively rather than hard deadline bounded. Recorded costs are zero because no paid/authenticated/model integration was enabled; infrastructure costs and an independent billing statement are not measured.

## Evidence and limitations

Artifacts remain ignored/local under `data/verification-runs/registry-100-8a90719/`: retained input, research.db, results.json, report.json, transport.json, evidence.zip and manifest.json. The complete ZIP reverified offline after completion, and every outer artifact hash was independently recomputed from stored files. Hashes:

| Artifact | SHA256 |
|---|---|
| results.json |`fc5c17db9f13a96489d63ba8b81e0c5d201a6b4cac891bd14a49aa181db9b3ca`|
| report.json |`d0610f778109963d7664d657516c6829dbbf19c58f445b096d96f60c2246c43f`|
| transport.json |`4439eca57f19a973e45706cbb517deb5cc1ae612fb886499e308a7514161d986`|
| evidence.zip |`f4715fcfa4034f7726b25f7aafb5b67dcc4128580dd13ea12bd5d6613cca6967`|

Support validation establishes snapshot/locator/value consistency under current deterministic rules. It is not an independently adjudicated accuracy reference. Exact-company precision, wrong-company publications, claim recall, financial exact match, uncertainty intervals, held-out gains and feature ablations are **unmeasured**. Withheld financial candidates are not positive financial accuracy results. The earlier synthetic100/1000 cardinality ZIPs and metadata selections remain different artifacts.

Known baseline summary defect: acquired-but-withheld accounts can be described as “not publicly available”; leadership/activity/website wording also confuses unsupported observations with source absence. Canonical family states above remain explicit. Unknowns are computed before final refresh coverage, so they can disagree with the envelope. First observations are also described as changes since a previous run. These deficiencies mean complete evidence-backed claim output does not establish fully grounded briefs. Preserve these baseline bytes; correct new synthesis separately and evaluate the correction without rewriting history.

Superseding implementation record (2026-10-18,D-068): new outcomes now build unknowns after final refresh and use explicit verification-state wording. The baseline files above remain unchanged. This correction has deterministic production fixtures; no new live100 comparison or accuracy gain is implied. First-observation wording and complete claim-reference synthesis remain unfinished.

Further implementation record (2026-10-18,D-069): new briefs distinguish first observations, newly verified information and changed comparable observations. This corrects the new-output first-run wording left open at D-068; the frozen baseline still contains its original text. Claim-reference synthesis remains unfinished; no repeated live measurement is claimed.

Earlier preflight at0d207ae failed after one entity response because a server session cookie was refused on the next request: independent1/gateway2, exit1, partial retained result. D-067 fixed cookie replay. Separate corrected first-input preflight at8a90719 succeeded in3.094s with four matching operations and a verified ZIP. Both artifacts are retained; no failed attempt is hidden or counted as the100-company run.

Source attribution: contains NLOD2.0 registry data distributed by Brønnøysundregistrene, normalized by NordTrace. Raw roles/company captures remain local; software MIT does not relicense them. Privacy/retention and redistribution review remain unfinished, and no artifact has been remotely published. This baseline does not compare external coverage against a repaired extractor or satisfy the broader release gates.
