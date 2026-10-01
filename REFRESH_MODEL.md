# Refresh Model (actual)

## Snapshot mechanism
Every source stores a `content_hash` (SHA-256 of retrieved content). On refresh:
- Same hash → unchanged source (cached response reused within TTL)
- Different hash → re-extract facts

## Fact comparison (implemented in `core/changes.py`)
Compare previous vs current per fact slot (category, field, reporting_period). Detect:
- `NEW`: fact not present in previous profile
- `CHANGED`: normalized value changed
- `RETRACTED`: fact present previously but not found in this run
- `UNCHANGED`: same value, same source
- `SOURCE_UNAVAILABLE`: source unavailable in this run; previous value retained but marked unverified

## Preservation
Historical facts preserved by run — `repo.get_previous_facts` returns latest
published facts from earlier runs; changes reference both previous and current
source ids. Refresh does not overwrite history.

## Verified behavior (live)
Same company researched twice → 23 UNCHANGED facts detected; change types
NEW/CHANGED/RETRACTED/SOURCE_UNAVAILABLE/UNCHANGED all unit-tested.
