"""Durable refresh order and old support cannot be manufactured by migration."""

import asyncio
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import (
    CompanyProfile,
    EvidenceRecord,
    Fact,
    ResearchMetadata,
    ResearchRun,
    SourceRecord,
    utcnow,
)
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def test_schema5_upgrade_preserves_envelopes_without_inventing_order(tmp_path):
    path = tmp_path / "ordering-upgrade.db"
    repo = Repository(path)
    old = ResearchRun(companies=[ORG], started_at="2026-01-01T00:00:00+00:00")
    repo.create_run(old)
    profile = CompanyProfile(
        run_id=old.run_id, organisation_number=ORG,
        research_metadata=ResearchMetadata(completed_at="2026-01-01T01:00:00+00:00"),
    )
    repo.save_result(profile)
    payload = repo.conn.execute("SELECT payload_json FROM company_results").fetchone()[0]
    repo.conn.execute("DROP TABLE history_order")
    repo.conn.execute("PRAGMA user_version=5")
    repo.conn.commit()
    repo.close()
    upgraded = Repository(path)
    assert upgraded.conn.execute("SELECT payload_json FROM company_results").fetchone()[0] == payload
    assert upgraded.conn.execute("SELECT count(*) FROM history_order").fetchone()[0] == 0
    assert upgraded.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    current = ResearchRun(companies=[ORG], started_at="2026-02-01T00:00:00+00:00")
    upgraded.create_run(current)
    assert upgraded.previous_result(ORG, current.run_id).run_id == old.run_id
    upgraded.close()
    backups = list(tmp_path.glob("ordering-upgrade.db.pre-v6-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 5
        assert backup.execute("SELECT payload_json FROM company_results").fetchone()[0] == payload


def test_unbacked_prior_publication_cannot_be_promoted_to_last_known(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "unbacked.db")
    old = ResearchRun(companies=[ORG], started_at="2026-01-01T00:00:00+00:00")
    repo.create_run(old)
    source = SourceRecord(org_number=ORG, access_status="success", source_type="registry", authority_tier=0)
    evidence = EvidenceRecord(
        source_id=source.source_id, org_number=ORG, entity_verdict="VERIFIED", evidence_text="TARGET AS",
    )
    fact = Fact(
        org_number=ORG, category="identity", field="legal_name",
        value="TARGET AS", normalized_value="TARGET AS",
        source_id=source.source_id, evidence_id=evidence.evidence_id, run_id=old.run_id,
        status="PUBLISHED", entity_verdict="VERIFIED", subject_scope="legal_entity",
    )
    repo.save_result(CompanyProfile(
        run_id=old.run_id, organisation_number=ORG, facts=[fact], evidence=[evidence], sources=[source],
    ))
    current = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(current)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=1))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(403)
        ))
        try:
            return await pipeline.research_company(ORG, current.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.last_known == [] and outcome.facts == [] and outcome.changes == []
    assert any("failed support revalidation" in unknown for unknown in outcome.unknowns)
    assert repo.get_result(old.run_id, ORG).facts[0].status == "PUBLISHED"  # History is not rewritten.
    repo.close()


@pytest.mark.parametrize("status", ["CONFLICT", "FAILED", "EXTRACTED", "SOURCE_UNAVAILABLE"])
def test_current_fact_collection_cannot_publish_noncurrent_observations(status):
    source = SourceRecord(org_number=ORG, access_status="success")
    evidence = EvidenceRecord(source_id=source.source_id, org_number=ORG, evidence_text="Fixture")
    fact = Fact(
        org_number=ORG, category="identity", field="legal_name", value="Fixture",
        source_id=source.source_id, evidence_id=evidence.evidence_id, status=status,
    )
    with pytest.raises(ValidationError, match="published facts"):
        CompanyProfile(
            run_id="fixture", organisation_number=ORG, facts=[fact], sources=[source], evidence=[evidence],
        )
