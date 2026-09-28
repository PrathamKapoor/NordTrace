# Limitations

- Brønnøysund Register API may return partial data; full historical records may require manual verification.
- PDF extraction depends on text-based PDFs; scanned/image-based documents require OCR fallback which is approximate.
- LLM extraction is bounded by cost budget ($10) and token limits; complex pages may fail extraction.
- External APIs (financial registries) are accessed within timeout/retry limits; temporary outages cause degraded profiles but do not fabricate data.
- Job and news sources depend on public availability; absence of information is reported as `not_available`, not fabricated.
