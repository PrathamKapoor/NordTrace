# Sources (all verified live 2026-09-29/30)

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
