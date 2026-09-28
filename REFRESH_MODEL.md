# Refresh Model

## Snapshot mechanism
Every source stores a `content_hash`. On refresh:
- Same hash → unchanged source
- Different hash → re-extract facts

## Fact comparison
Compare previous `normalized_value` and `value` for each `fact_id`. Detect:
- `NEW`: Fact not present in previous profile
- `CHANGED`: Normalized value changed
- `RETRACTED`: Fact removed (source no longer available or evidence retracted)
- `UNCHANGED`: Same value, same source
- `CONFLICT`: Multiple sources with different values for same field

## Preservation
Historical profile versions are preserved by storing previous `profile_json` with timestamp. The current profile is rebuilt from current verified facts.
