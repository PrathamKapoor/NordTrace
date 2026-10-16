# Current source record — 2026-10-17

The source list below records historical adapter access, not current live verification or working publication coverage. Production publication now requires retained snapshots and supported locators. Only atomic registry identity predicates currently have converted support rules; other source candidates are withheld pending conversion. See docs/implementation-tracker.md and docs/verification.md.

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
