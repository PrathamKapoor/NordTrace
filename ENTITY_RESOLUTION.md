# Entity Resolution (actual, deterministic)

## Canonical identity
The official Brreg Enhetsregisteret entry for the given `organisation_number`.

## Matching signals (implemented, deterministic)
- Organisation number (exact match → VERIFIED)
- Foreign organisation number in candidate (→ REJECTED, dominates everything)
- Normalized name similarity (Norwegian legal-form suffixes stripped; geographic words kept)
- Website domain (registrable-domain match; domain owned by a different verified company → REJECTED)
- Municipality / address overlap
- Industry code match

## Classification thresholds
- VERIFIED: orgnr match, or name ≥0.9 + ≥1 corroboration
- LIKELY: name ≥0.7 + ≥1 corroboration, or partial name + ≥2 corroboration
- AMBIGUOUS: name ≥0.95 without corroboration; or insufficient signals (prefers UNKNOWN over wrong-company)
- REJECTED: foreign orgnr, domain conflict, or name <0.35 similarity

## Wrong-company firewall (PublicationFirewall)
Every candidate fact passes `evaluate_candidate`; REJECTED candidates are logged
with signals (foreign orgnr, name similarity, candidate URL) and are visible in
the UI. `may_publish` requires VERIFIED or LIKELY.
