"""New knowledge is not evidence that a company changed."""
import asyncio

import httpx

from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import ChangeRecord, CompanyIdentity, Coverage, ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.core.synthesis import build_summary
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def test_first_profile_and_identical_refresh_do_not_share_a_change_description(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "changes.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    name = "FIRST FIXTURE AS"
    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": name})
        return httpx.Response(404)
    async def execute():
        run = ResearchRun(companies=[ORG])
        repo.create_run(run)
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30,
                                    allowed_source_origins=["https://data.brreg.no"]))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
            return repo.get_result(run.run_id, ORG)
        finally:
            await pipeline.aclose()
    try:
        initial = asyncio.run(execute())
        assert initial.previous_run_id is None
        assert "first verified observations" in initial.summary.lower()
        assert "changes since previous run" not in initial.summary.lower()
        repeated = asyncio.run(execute())
        assert repeated.previous_run_id == initial.run_id
        assert not any(c.change_type in ("NEW", "CHANGED", "RETRACTED") for c in repeated.changes)
        unchanged = "no material changes established among comparable verified observations"
        assert unchanged in repeated.summary.lower()
        assert "first" not in repeated.summary.lower().replace(name.lower(), "")
        name = "RENAMED FIXTURE AS"
        changed = asyncio.run(execute())
        assert changed.previous_run_id == repeated.run_id
        assert "Changes in verified observations: legal_name:" in changed.summary
        assert any(c.change_type == "CHANGED" and c.field == "legal_name" for c in changed.changes)
        assert repo.get_result(initial.run_id, ORG).model_dump() == initial.model_dump()
    finally:
        repo.close()


def test_newly_supported_field_is_new_knowledge_instead_of_a_business_change():
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    observation = ChangeRecord(
        org_number=ORG, run_id="current", change_type="NEW", field="industry_description",
        category="identity", current_value="Fixture manufacturing",
    )
    summary = build_summary(identity, FactLedger(), Coverage(), [observation], previous_run_id="previous")
    assert "Newly verified observations: industry_description:" in summary
    assert "Changes in verified observations: industry_description:" not in summary


def test_previous_run_with_only_outage_cannot_establish_no_business_changes():
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    unavailable = ChangeRecord(
        org_number=ORG, run_id="current", change_type="SOURCE_UNAVAILABLE", field="legal_name",
        category="identity", previous_value="FIXTURE AS",
    )
    summary = build_summary(identity, FactLedger(), Coverage(), [unavailable], previous_run_id="previous")
    assert "no material changes established among comparable verified observations" in summary.lower()
    assert "no business changes" not in summary.lower()
    assert "first research" not in summary.lower()


def test_empty_verified_ledger_does_not_claim_a_first_verified_observation():
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    summary = build_summary(identity, FactLedger(), Coverage(), [])
    assert "no verified observations available for comparison" in summary.lower()
    assert "first verified observations" not in summary.lower()
