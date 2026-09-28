# Entity Resolution

## Canonical identity
The official Brønnøysund Register entry for the given `organisation_number` is the canonical identity.

## Matching signals
- Organisation number (exact)
- Legal name (normalized: lowercase, remove form suffixes)
- Registered address
- Municipality
- Industry/NACE
- Website domain
- Status (active/dissolved)

## Classification
- `VERIFIED`: Exact org number match or exact name + address match.
- `LIKELY`: Strong name overlap + address/municipality match.
- `AMBIGUOUS`: Partial overlap without contradiction.
- `REJECTED`: Contradictory identity signals (e.g., different org number, different legal entity).
