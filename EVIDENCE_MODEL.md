# Evidence Model (actual)

Every `Fact` references exactly one `Evidence`. Every `Evidence` references exactly one `Source`.

## Fields (implemented)
- `evidence_id`: unique identifier
- `source_id`: parent source
- `url`: source URL
- `source_title`: human-readable source name
- `evidence_text`: snippet / extracted text
- `page_or_section`: page number for PDFs, section for pages
- `content_hash`: SHA-256 of retrieved content (snapshot comparison)
- `entity_match_details`: structured identity match results
- `entity_verdict`: VERIFIED / LIKELY / AMBIGUOUS / REJECTED

## Publication rule (enforced by CitationValidator)
Only facts with `entity_verdict` in (VERIFIED, LIKELY), a successfully retrieved
source (`access_status=success`), existing evidence with non-empty text, and a
non-null value reach `PUBLISHED`. Financial facts must carry `currency`.
Everything else: FAILED / NOT_AVAILABLE. REJECTED entity facts are never published.
