# Methodology (actual, live-verified)

## Identity Resolution
1. Validate organisation number (format + modulus-11 checksum).
2. Query Brreg Enhetsregisteret (`/enheter/{orgnr}`) — live.
3. Parse real JSON into `CompanyIdentity` (name, form, status, address, NACE, capital, employees).
4. Roles via `/enheter/{orgnr}/roller`; accounts via `/regnskapsregisteret/regnskap/{orgnr}`; branches via `/underenheter`.

## Evidence Pipeline
1. Discover permitted sources (registry hjemmeside, regnskap, NAV jobs, branches).
2. Fetch through RequestGateway (budget-tracked, SSRF-guarded, robots-aware, cached with content hash).
3. Extract facts deterministically (registry JSON paths, PDF key-line extraction with page numbers).
4. Validate identity on every candidate source (signal-based resolver + publication firewall).
5. Validate citation chain (fact → evidence → source, deterministic).
6. Publish only if verified; conflicts exposed, never hidden; rejections logged.

## Financial Research
- Registry accounts (public regnskapsregisteret): revenue, operating result, annual result, assets, equity, liabilities — with currency + period from the source.
- PDF annual reports on company websites: text-based PDFs parsed with page-preserving extraction; scanned PDFs honestly reported as extraction-failed.
- Missing data reported as `not_available`; never fabricated. LLM disabled without key; financial extraction is deterministic regardless.

## Change Detection
- Fact slots: (category, field, reporting_period). Compare previous vs current per slot.
- NEW / CHANGED / RETRACTED / UNCHANGED / SOURCE_UNAVAILABLE with explanations.
- Previous profile facts preserved (history); refresh does not overwrite.
