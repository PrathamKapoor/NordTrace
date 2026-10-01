# Limitations (actual, verified)

- **Annual accounts**: latest filed year via public regnskapsregisteret endpoint; custom-layout filers (banks, insurers) may be unavailable → `not_available`, never fabricated.
- **PDF extraction**: works on text-based PDFs (verified on a real 42-page report); scanned/image-based PDFs are honestly reported as extraction-failed (no OCR fallback implemented).
- **Job employer verification**: NAV postings carry employer names without orgnr → name/municipality-based matching; ambiguous postings rejected, not merged.
- **Website discovery**: registry `hjemmeside` field primary; companies without a registered website get conservative name-derived candidates that must pass identity verification or are rejected.
- **No general news search**: no keyless provider implemented; "recent activity" comes from dated registry signals only (registrations, capital changes, status events).
- **LLM**: disabled without `LLM_API_KEY`; deterministic extraction is primary ($0.00 cost in all measured results). With a key, responses are schema-validated and cost-tracked.
- **Roles availability**: some registry entries return empty rollegrupper (role data restricted for some company forms) → leadership reported as not available.
- **`hent-regnskap` paths**: 404; the working path is `/regnskapsregisteret/regnskap/{orgnr}`.
- **NAV rate limits**: 429s observed at ~15 companies in quick succession; retry/backoff handles it; batch concurrency should stay modest.
