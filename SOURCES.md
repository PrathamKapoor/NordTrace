# Public eligible-universe selection — 2026-10-18

Builderr's public signalpost-company-universe-2025.jsonl.gz is used only to select reproducible eligible inputs, never as an independently verified identity or company-fact source. The supplied official frozen registry snapshot/private batch remain separate and unavailable. Original compressed/uncompressed hashes match the public contract; see docs/evaluator-contract.md. Underlying official registry attribution remains Brønnøysundregistrene; distribution/normalization is Builderr Signalpost. No starter code was copied and no MIT licence is asserted over downloaded data. Generated selections/manifests are local audit artifacts, ignored by Git; source-specific rights continue to govern any later distribution. Sampling has no source/network/model client and records no factual accuracy or official score. Zero observed workload socket connections during the actual100/1000 selections is an operational measurement, not source licence proof.

# Current source record — 2026-10-17

Documentation recheck2026-10-17: [Builderr source policy](https://www.builderr.ai/starter-briefs/signalpost-sources.md) was fetched again with identical bytes (SHA256f080470ab29d5c6da243d812e35d0ae0aa3d35f5871d62dfef90422df1b8f630; ignored data/contracts/source-policy-recheck-20261017.txt). It permits verified company-owned structured data for business description, with exact subject attribution and access restrictions; this is not a blanket storage licence or independent sentiment basis. [Schema.org Organization](https://schema.org/Organization) and [taxID](https://schema.org/taxID) primary definitions were inspected for a future locator-backed extractor. No external website claim support is enabled by this documentation check; ownership/terms, exact anchor/locator and scope verification still require implementation and tests.

The source list below records historical adapter access, not current release coverage. Production publication requires retained snapshots and supported locators. Atomic registry identity and parent-verified registered subunit predicates have converted support rules; other source candidates remain withheld. See docs/implementation-tracker.md and docs/verification.md.

Registered subunits use the public /enhetsregisteret/api/underenheter endpoint, explicit overordnetEnhet, bounded constructed pages and beliggenhetsadresse. A 2026-10-17 schema inspection retained source src_3dff13585680033d in ignored data/source-inspection/brreg-branches.db (one request). A subsequent limited live profile retained identity plus three registered subunits using four requests, independently counted at the transport boundary, with zero declared API cost. Its profile/database/manifest remain ignored under data/verification-runs/subunits-1792192132208554000. This is not a real100-company smoke report or population accuracy measurement.

Source-rights decision for these public registry records: the official Enhetsregisteret documentation identifies NLOD2.0; the [current licence text](https://data.norge.no/nlod/en/2.0) was checked2026-10-17. It permits reuse subject to its conditions, requires source/licence attribution and identification of modifications, and excludes some personal/third-party/protected information. NordTrace normalizes selected fields and retains local audit snapshots; software MIT does not replace this data licence. Attribution: contains NLOD2.0 data distributed by Brønnøysundregistrene, normalized by NordTrace. This permission does not establish a processing basis for every personal datum. Personal-data minimization/retention, source-specific website/PDF rights and inactive-vacancy retention remain unfinished; public data artifacts are not automatically authorized for publication. No authenticated NAV feed, paid search/API, OCR weights or private dataset was accessed.

Enhetsregisteret primary documentation version 2.0.0 was retrieved 2026-10-17 at https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html. It declares Norwegian Licence for Open Government Data (NLOD) 2.0; the code's MIT licence does not relicense registry/company data. Retained documentation hash: dd857144bf1a5efcd91c86b54a68eb3657f70e4e7f3d4edd77324d5aa1a4fd3b. Raw copy is local ignored data/contracts/enhetsregisteret-docs.html. Source-specific personal-data retention and all external source terms remain under review. No authenticated personal-identifier registry endpoints are used.

# Historical sources (access reported 2026-09-29/30)

## Tier 0 — Official Registry (live-verified)
- Brreg Enhetsregisteret: `data.brreg.no/enhetsregisteret/api/enheter/{orgnr}` — identity, form, status, address, NACE, capital, employees
- Brreg Roller: `.../enheter/{orgnr}/roller` — board/management roles
- Brreg Underenheter: `.../underenheter?overordnetEnhet=` — branch units
- Brreg Regnskap: `data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` — annual accounts (revenue, result, assets, equity, liabilities, currency, period)
- Brreg Updates: `.../oppdateringer/enheter` — cursor-paged change feed

Note: `hent-regnskap` paths are 404; the working path is `/regnskapsregisteret/regnskap/`.

## Tier 1 — Official Company Documents (live-verified)
- Company official website (`/om`, `/kontakt`, `/produkter`, `/karriere`, `/nyheter`)
- Annual report PDFs (text-based; scanned PDFs honestly reported as extraction-failed)

## Tier 2 — Norwegian Public Sector (live-verified)
- NAV Arbeidsplassen: `arbeidsplassen.nav.no/stillinger/api/search?q=` — job postings (employer names have no orgnr → entity verification via name/municipality)

## Tier 3 — Reputable Business Information
- Not implemented (no keyless provider; document as optional integration)

## Tier 4 — Discovery Sources
- Not implemented as a search engine; registry search (`?navn=`) serves discovery needs
# Acquisition policy update — 2026-10-16

Website discovery, internal pages and PDF retrieval apply robots through the counted gateway. Successful robots rules are enforced; 404/410 permit access; other errors, refusal and unavailable robots deny it. This is a conservative local policy, not a claim that robots alone grants storage or redistribution rights. Company/registry source rights and retention still need field-specific review.

Redirects are manual and every permitted hop is charged and checked. Connections use validated public IPs with the original Host/TLS identity and separate pools for each original origin. Environment proxies are disabled. Compressed responses are refused before decoding to enforce memory bounds; normal requests ask for identity encoding. Cache hits retain original retrieval timestamps and are labelled. Actual TLS/network behavior, bounded DNS and model transport require further verification; no optional model integration is claimed to use this boundary yet.
