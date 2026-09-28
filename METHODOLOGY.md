# Methodology

## Identity Resolution
1. Validate organisation number format and checksum.
2. Query Brønnøysund Register (Tier 0).
3. Build canonical identity from official registry response.
4. Confirm entity with multiple signals (name, address, org form, status).

## Evidence Pipeline
1. Discover permitted sources.
2. Fetch source content through RequestManager (budget-tracked).
3. Compute content hash for snapshots.
4. Extract candidate facts (structured + LLM-assisted where unstructured).
5. Validate identity match on candidate source (firewall).
6. Attach evidence metadata.
7. Publish only if verified.

## Change Detection
- Compare previous profile facts with new facts by `fact_id` and `normalized_value`.
- Detect new, changed, retracted, or unchanged facts.
- Preserve historical versions.
