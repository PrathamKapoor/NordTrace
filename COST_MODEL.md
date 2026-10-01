# Cost Model (actual)

## Tracking
Every LLM call is tracked by:
- Provider/model (`settings.llm_model`, default `gpt-4o-mini`)
- Input/output tokens (from API usage)
- Estimated cost (USD) via configurable price table (`LLM_PRICE_INPUT_PER_M`, `LLM_PRICE_OUTPUT_PER_M`)
- Request count

## Limits
- Global declared API cost: $10.00 (`MAX_API_COST_USD`)
- Budget gate: `CostBudget.can_afford()` prevents expensive calls when insufficient budget remains.
- All measured results in this project used **$0.00** (deterministic extraction only — LLM disabled without key).

## Optimization strategy
- Registry lookups (free) are preferred over LLM extraction.
- Structured extraction (registry JSON, PDF key-lines) is deterministic.
- LLM is optional: only for messy/unstructured page extraction or synthesis polish.
