"""Logical claim identity is independent of values and observation UUIDs."""

import pytest

from nordtrace.core.changes import detect_changes
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord

ORG = "982463718"


def vacancy(item, title="Engineer", org=ORG):
    return Fact(
        org_number=org, category="jobs", field="job_posting", item_key=item, subject_scope="legal_entity",
        value={"title": title, "vacancy_id": item}, normalized_value=title,
        source_id="source", evidence_id="evidence", entity_verdict="VERIFIED", status="PUBLISHED",
    )


def test_repeated_observations_keep_logical_identity_without_using_value():
    first = vacancy("nav:123")
    replay = vacancy("nav:123")
    updated = vacancy("nav:123", title="Senior engineer")
    assert first.fact_id != replay.fact_id  # Historical observation IDs remain immutable.
    assert first.claim_id == replay.claim_id == updated.claim_id
    assert first.observation_id == first.fact_id
    assert {change.change_type for change in detect_changes(ORG, "run2", [first], [replay])} == {"UNCHANGED"}
    changes = detect_changes(ORG, "run3", [replay], [updated])
    assert len(changes) == 1 and changes[0].change_type == "CHANGED"
    assert changes[0].claim_id == first.claim_id
    assert changes[0].item_key == "nav:123"


def test_distinct_items_subjects_scopes_and_periods_have_distinct_identity():
    first = vacancy("nav:123")
    others = [
        vacancy("nav:124"), vacancy("nav:123", org="958973306"),
        first.model_copy(update={"subject_scope": "group"}),
        first.model_copy(update={"reporting_period": "FY2024"}),
    ]
    assert len({first.claim_id, *(item.claim_id for item in others)}) == 5
    # Delimiters within an item/field cannot collide with another tuple.
    a = first.model_copy(update={"field": "job|posting", "item_key": "x"})
    b = first.model_copy(update={"field": "job", "item_key": "posting|x"})
    assert a.fact_key() != b.fact_key()
    # Opaque source identifiers must not collide through UTF-8 replacement.
    assert vacancy("nav:\ud800").claim_id != vacancy("nav:\ud801").claim_id


def test_distinct_vacancies_coexist_without_fact_slot_conflicts():
    # This tests the collection-key layer only, not source support/NAV access.
    ledger = FactLedger()
    ledger.add_source(SourceRecord(source_id="source", org_number=ORG, access_status="success"))
    ledger.add_evidence(EvidenceRecord(
        evidence_id="evidence", source_id="source", evidence_text="Fixture roles", org_number=ORG,
        entity_verdict="VERIFIED",
    ))
    assert ledger.add_fact(vacancy("nav:123", "Engineer")).status == "PUBLISHED"
    assert ledger.add_fact(vacancy("nav:124", "Designer")).status == "PUBLISHED"
    assert len(ledger.published_facts()) == 2


def test_identical_claim_from_same_snapshot_is_idempotent_within_ledger():
    ledger = FactLedger()
    ledger.add_source(SourceRecord(
        source_id="source", org_number=ORG, access_status="success", content_hash="fixture-body-hash",
    ))
    ledger.add_evidence(EvidenceRecord(
        evidence_id="evidence", source_id="source", evidence_text="Fixture roles", org_number=ORG,
        entity_verdict="VERIFIED",
    ))
    first = vacancy("nav:123")
    replay = vacancy("nav:123")
    ledger.add_fact(first)
    retained = ledger.add_fact(replay)
    assert len(ledger.published_facts()) == 1
    assert retained.fact_id == first.fact_id
    assert replay.status == "DUPLICATE"


def test_same_fact_instance_replay_cannot_unpublish_the_retained_observation():
    ledger = FactLedger()
    source = SourceRecord(
        source_id="source", org_number=ORG, access_status="success", content_hash="same fixture snapshot",
    )
    evidence = EvidenceRecord(
        source_id=source.source_id, evidence_text="Fixture job", org_number=ORG, entity_verdict="VERIFIED",
    )
    fact = vacancy("nav:123")
    ledger.add_fact(fact, evidence, source)
    assert len(ledger.published_facts()) == 1
    ledger.add_fact(fact, evidence, source)
    assert len(ledger.published_facts()) == 1
    assert fact.status == "PUBLISHED"


def test_production_identical_snapshot_replay_has_stable_claims_and_no_false_changes(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import ResearchRun, utcnow
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "replay.db")

    def respond(request):
        if str(request.url).endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "TARGET AS"})
        return httpx.Response(404)

    async def execute():
        outcomes = []
        for _ in range(2):
            run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
            repo.create_run(run)
            pipeline = ResearchPipeline(repo, BudgetManager(max_requests=20))
            pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            try:
                outcomes.append(await pipeline.research_company(ORG, run.run_id))
            finally:
                await pipeline.aclose()
        return outcomes

    first, replay = asyncio.run(execute())
    assert first.facts and replay.facts
    assert [fact.claim_id for fact in first.facts] == [fact.claim_id for fact in replay.facts]
    assert first.facts[0].observation_id != replay.facts[0].observation_id
    assert {change.change_type for change in replay.changes} == {"UNCHANGED"}
    assert repo.conn.execute("SELECT count(*) FROM snapshot_blobs").fetchone()[0] == 1
    changes = repo.get_changes(ORG)
    assert all(change.claim_id == first.facts[0].claim_id for change in changes)
    assert all(change.subject_scope == "legal_entity" for change in changes)
    repo.close()


def test_repository_keeps_latest_observation_for_each_collection_item(tmp_path):
    from nordtrace.core.models import CompanyIdentity, ResearchRun
    from nordtrace.core.repository import Repository

    repo = Repository(tmp_path / "items.db")
    older = ResearchRun(companies=[ORG], started_at="2026-01-01T00:00:00+00:00")
    newer = ResearchRun(companies=[ORG], started_at="2026-02-01T00:00:00+00:00")
    current = ResearchRun(companies=[ORG], started_at="2026-03-01T00:00:00+00:00")
    for run in (older, newer, current):
        repo.create_run(run)
    repo.upsert_company(CompanyIdentity(organisation_number=ORG, legal_name="TARGET AS"), older.run_id)
    for run, items in [(older, [vacancy("nav:123"), vacancy("nav:124", "Designer")]),
                       (newer, [vacancy("nav:123", "Senior engineer")])]:
        source = SourceRecord(org_number=ORG, access_status="success")
        evidence = EvidenceRecord(source_id=source.source_id, org_number=ORG, evidence_text="Storage fixture")
        repo.insert_sources_bulk([source], run.run_id, ORG)
        repo.insert_evidence(evidence)
        for fact in items:
            fact.run_id = run.run_id
            fact.source_id = source.source_id
            fact.evidence_id = evidence.evidence_id
        repo.insert_facts_bulk(items)
    previous = repo.get_previous_facts(ORG, current.run_id)
    assert {fact.item_key: fact.value["title"] for fact in previous} == {
        "nav:123": "Senior engineer", "nav:124": "Designer",
    }
    assert repo.integrity_check()["duplicate_fact_slots_same_run"] == 0
    assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    repo.close()


def test_schema4_upgrade_preserves_history_and_adds_unknown_qualifiers(tmp_path):
    import sqlite3

    from nordtrace.core.models import ResearchRun
    from nordtrace.core.repository import Repository

    path = tmp_path / "upgrade4.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.conn.execute("ALTER TABLE facts DROP COLUMN item_key")
    repo.conn.execute("ALTER TABLE facts DROP COLUMN subject_scope")
    repo.conn.execute("ALTER TABLE changes DROP COLUMN change_json")
    repo.conn.execute("PRAGMA user_version=4")
    repo.conn.commit()
    repo.close()
    upgraded = Repository(path)
    assert upgraded.get_run(run.run_id).companies == [ORG]
    assert upgraded.conn.execute("PRAGMA user_version").fetchone()[0] == 6
    upgraded.close()
    backups = list(tmp_path.glob("upgrade4.db.pre-v5-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 4
    Repository(path).close()
    assert len(list(tmp_path.glob("upgrade4.db.pre-v5-*.bak"))) == 1


@pytest.mark.parametrize("changed", ["currency", "unit", "valid_to", "deadline"])
def test_assertion_changes_cannot_hide_behind_same_normalized_title(changed):
    before = vacancy("nav:123")
    if changed in ("currency", "unit"):
        before = before.model_copy(update={
            "category": "financials", "field": "revenue", "item_key": None,
            "value": 100, "normalized_value": 100, "currency": "NOK", "unit": "currency_units",
            "reporting_period": "FY2025",
        })
    changed_value = {"currency": "USD", "unit": "thousand_currency_units", "valid_to": "2026-12-01"}
    updates = {changed: changed_value[changed]} if changed != "deadline" else {
        "value": before.value | {"deadline": "2026-12-01"},
    }
    after = before.model_copy(update=updates)
    assert before.claim_id == after.claim_id
    changes = detect_changes(ORG, "changed", [before], [after])
    assert len(changes) == 1 and changes[0].change_type == "CHANGED"


def test_financial_diff_uses_exact_decimal_equality_without_float_epsilon():
    before = vacancy("fixture").model_copy(update={
        "category": "financials", "field": "revenue", "item_key": None,
        "value": 100.0, "normalized_value": 100.0, "currency": "NOK", "reporting_period": "FY2025",
    })
    after = before.model_copy(update={"value": 100.0000000001, "normalized_value": 100.0000000001})
    assert detect_changes(ORG, "changed", [before], [after])[0].change_type == "CHANGED"
    equivalent = before.model_copy(update={"value": 100, "normalized_value": 100})
    assert detect_changes(ORG, "same", [before], [equivalent])[0].change_type == "UNCHANGED"
