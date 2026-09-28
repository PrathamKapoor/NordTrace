# Cost Model

## Provider tracking
Every LLM/extraction call is tracked by:
- Provider (`openai`, `local`, etc.)
- Model name (`gpt-4o-mini`, etc.)
- Input tokens
- Output tokens
- Estimated cost (USD)
- Request count

## Limits
- Global declared API cost: $10.00
- Per-run tracking: `budget.cost.total_used`
- Per-request tracking: `budget.cost.by_provider`, `budget.cost.by_model`
- Budget gate: `budget.can_start_expensive()` prevents expensive operations when cost < $0.50 remains.

## Optimization strategy
- Registry lookups (free) are preferred over LLM extraction.
- Structured extraction is preferred over LLM synthesis.
- LLM is only used for messy/unstructured pages or complex conflict resolution.
