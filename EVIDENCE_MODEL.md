# Evidence Model

Every `Fact` must reference exactly one `Evidence`.
Every `Evidence` must reference exactly one `Source`.

## Fields
- `evidence_id`: Unique identifier
- `source_id`: Parent source
- `url`: Source URL (optional for PDFs or internal records)
- `source_title`: Human-readable source name
- `evidence_text`: Snippet / extracted text
- `page_section`: Page or section within source
- `content_hash`: SHA-256 of retrieved content (for snapshot comparison)
- `entity_match_details`: Structured identity match results (VERIFIED, LIKELY, AMBIGUOUS, REJECTED)
- `entity_confidence`: Final identity match classification

## Publication rule
Only facts with `entity_confidence` in (`VERIFIED`, `LIKELY`) and a non-empty `evidence_text` can reach `PUBLISHED` status.
Facts where identity is `REJECTED` are never published; the rejection is recorded in the firewall log.
