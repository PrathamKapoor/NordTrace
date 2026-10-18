"""Conservative refresh comparison against retained, revalidated observations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from nordtrace.core.changes import detect_changes
from nordtrace.core.ledger import CitationValidator
from nordtrace.core.models import FactStatus, RefreshOutcome, SourceRecord, utcnow
from nordtrace.core.repository import Repository

if TYPE_CHECKING:
    from nordtrace.engine.pipeline import CompanyOutcome


def source_family(source: SourceRecord) -> str:
    path = urlsplit(source.requested_url or source.url or "").path.rstrip("/")
    if source.source_type == "registry":
        if path.endswith("/roller"):
            return "leadership"
        if "/underenheter" in path:
            return "locations"
        return "identity"
    return {"registry_accounts": "financials", "company_document": "financials",
            "company_website": "website", "public_sector": "jobs",
            "job_board": "jobs"}.get(source.source_type, "other")


def apply_refresh(repo: Repository, outcome: CompanyOutcome, run_id: str) -> None:
    """Keep last-known support separate from new publication, including early failures.

    Only canonical earlier observations passing the current support gate qualify.
    Legacy existence-only PUBLISHED rows are deliberately not promoted.
    """
    now = utcnow().isoformat()
    current_sources = {source.source_id: source for source in outcome.sources}
    supported_sources = {fact.source_id for fact in outcome.facts}
    conflicting_sources = {fact.source_id for fact in outcome.conflicts}
    producer_outcomes = {item.source_id: item for item in outcome.refresh_outcomes if item.source_id}
    attempts = []
    for source in current_sources.values():
        if source.source_id in producer_outcomes:
            attempts.append(producer_outcomes[source.source_id])
            continue
        state = {"blocked": "blocked", "robots_denied": "blocked", "rate_limited": "blocked",
                 "not_found": "not_available",
                 "discovered": "not_available"}.get(source.access_status, "failed")
        if source.http_status in (404, 410):
            state = "not_available"
        reason = source.error_detail or f"Acquisition state: {source.access_status}."
        if source.access_status == "success":
            if source.source_id in conflicting_sources:
                state, reason = "ambiguous", "Supported observations disagree."
            elif source.source_id in supported_sources:
                state, reason = "available", "Supported observations acquired; completeness not established."
            elif outcome.error_code == "registry_failed" and source_family(source) == "identity":
                state, reason = "failed", "Registry response could not be parsed."
            else:
                state, reason = "not_available", "Body acquired; no supported observation accepted."
        attempts.append(RefreshOutcome.model_validate({
            "requested_url": source.requested_url or source.url or "", "family": source_family(source),
            "source_id": source.source_id, "state": state, "observed_at": now, "reason": reason,
        }))
    outcome.refresh_outcomes = attempts
    for attempt in attempts:
        if outcome.coverage.get(attempt.family) in (None, "not_found", "not_available"):
            outcome.coverage[attempt.family] = (
                "not_available" if attempt.state == "available" else attempt.state
            )
    previous = repo.previous_result(outcome.org_number, run_id)
    previous_facts = []
    if previous is not None:
        outcome.previous_run_id = previous.run_id
        previous_sources = {source.source_id: source for source in previous.sources}
        previous_evidence = {item.evidence_id: item for item in previous.evidence}
        validator = CitationValidator(previous_sources, previous_evidence, repo)
        current_keys = {fact.claim_id for fact in outcome.facts}
        evidence_ids = {item.evidence_id for item in outcome.evidence}
        attempted_urls = {attempt.requested_url for attempt in attempts}
        for fact in previous.facts + previous.last_known:
            valid, reason = validator.validate(fact)
            if not valid:
                outcome.unknowns.append(
                    f"Previous observation {fact.fact_id} failed support revalidation: {reason}"
                )
                continue
            previous_facts.append(fact)
            source = previous_sources[fact.source_id]
            evidence = previous_evidence[fact.evidence_id]
            if fact.source_id not in current_sources:
                outcome.sources.append(source)
                current_sources[fact.source_id] = source
            if fact.evidence_id not in evidence_ids:
                outcome.evidence.append(evidence)
                evidence_ids.add(fact.evidence_id)
            if fact.claim_id in current_keys:
                continue
            outcome.last_known.append(fact.model_copy(update={"status": FactStatus.SOURCE_UNAVAILABLE.value}))
            url = source.requested_url or source.url or ""
            if url not in attempted_urls:
                attempts.append(RefreshOutcome(
                    requested_url=url, family=source_family(source), state="not_available", observed_at=now,
                    reason="Previous source was not acquired in this run; disappearance not established.",
                ))
                attempted_urls.add(url)
    outcome.changes = detect_changes(outcome.org_number, run_id, previous_facts, outcome.facts)
    if outcome.last_known:
        outcome.unknowns.append(
            f"{len(outcome.last_known)} last-known observations were not reconfirmed; no removal established."
        )


def stale_notice(outcome: CompanyOutcome) -> str:
    if not outcome.last_known:
        return ""
    return (
        f"{len(outcome.last_known)} previously verified observations are last-known "
        "and were not reconfirmed. "
        "Their original verification times and supporting evidence remain available."
    )
