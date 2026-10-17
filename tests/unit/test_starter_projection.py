"""Illustrative public starter projection, not private grader acceptance."""

import asyncio
import hashlib
import json
import zipfile

import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyProfile, Fact, ResearchMetadata
from nordtrace.core.repository import Repository
from nordtrace.engine.runner import BatchRunner


def test_mapping_preserves_zero_qualifiers_and_never_promotes_registered_website():
    from nordtrace.core.export import _starter_example

    # Projection arithmetic only. Constructed claims do not establish factual support.
    from nordtrace.core.models import EvidenceRecord, JsonPointerLocator, SourceRecord

    source = SourceRecord(source_id="src", source_type="registry", url="https://data.brreg.no/entity",
                          final_url="https://data.brreg.no/entity", content_hash="a" * 64)
    evidence = EvidenceRecord(evidence_id="ev", source_id="src", evidence_text='Display value, not a quote',
                              locator=JsonPointerLocator(pointer="/amount", raw_value=0))
    facts = [Fact(org_number="982463718", category=category, field=field, value=value,
                  normalized_value=value, unit=unit, currency=currency, reporting_period=period,
                  source_id="src", evidence_id="ev", subject_scope="legal_entity", status="PUBLISHED")
             for category, field, value, unit, currency, period in [
                 ("identity", "website", "https://example.no", None, None, None),
                 ("financials", "revenue", 0, "thousands", "EUR", "2025"),
             ]]
    profile = CompanyProfile(run_id="r", organisation_number="982463718", status="available",
                             facts=facts, sources=[source], evidence=[evidence],
                             research_metadata=ResearchMetadata(request_count=99, estimated_cost_usd=3))
    payload = _starter_example(profile)
    assert payload["run"]["terminal_status"] == "completed"
    assert payload["availability"] == "available"
    assert payload["claims"][0]["field"] == "registered_website"
    revenue = payload["claims"][1]
    assert (revenue["value"], revenue["unit"], revenue["currency"], revenue["reporting_period"],
            revenue["subject_scope"]) == (0, "thousands", "EUR", "2025", "legal_entity")
    assert revenue["evidence_ids"] == ["ev"]
    assert payload["evidence"][0]["claim_span"] is None
    assert payload["evidence"][0]["locator"]["raw_value"] == 0
    assert payload["evidence"][0]["display_text"] == "Display value, not a quote"
    assert payload["operations"]["requests"] is None  # 99 was a cumulative counter, not entity usage.
    assert payload["operations"]["third_party_cost_usd"] is None


@pytest.mark.parametrize("state", [
    "available", "not_available", "blocked", "not_applicable", "ambiguous", "failed",
])
def test_projection_preserves_actual_availability_and_does_not_invent_claims(state):
    from nordtrace.core.export import _starter_example

    payload = _starter_example(CompanyProfile(run_id="r", organisation_number="bad", status=state))
    assert payload["availability"] == state
    assert payload["claims"] == []
    assert payload["run"]["terminal_status"] == ("failed" if state == "failed" else "completed")


@pytest.mark.parametrize("mutation", ["invented_claim", "zero_to_false"])
def test_bundle_projection_is_derived_and_tampering_cannot_change_it(tmp_path, mutation):
    from nordtrace.core.export import export_run, verify_bundle

    repo = Repository(tmp_path / "projection.db")
    run = asyncio.run(BatchRunner(repo, BudgetManager(max_requests=0)).run_batch(["bad", "bad"]))
    output = tmp_path / "audit.zip"
    manifest = export_run(repo, run.run_id, output)
    repo.close()
    info = manifest["projections"]["starter-example-v1"]
    with zipfile.ZipFile(output) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    projection = json.loads(entries[info["path"]])
    assert projection["organisation_number"] == "bad"
    assert projection["availability"] == "not_applicable"
    assert projection["errors"][0]["code"] == "invalid_organisation_number"
    assert len(entries[info["path"]].splitlines()) == 1
    if mutation == "invented_claim":
        projection["claims"] = [{"field": "invented", "value": 99}]
    else:
        assert projection["research_metadata"]["run_configuration"]["max_requests"] == 0
        projection["research_metadata"]["run_configuration"]["max_requests"] = False
    entries[info["path"]] = (json.dumps(projection) + "\n").encode()
    changed_hash = hashlib.sha256(entries[info["path"]]).hexdigest()
    manifest["projections"]["starter-example-v1"]["sha256"] = changed_hash
    entries["manifest.json"] = json.dumps(manifest).encode()
    modified = tmp_path / "modified.zip"
    with zipfile.ZipFile(modified, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    with pytest.raises(ValueError, match="projection"):
        verify_bundle(modified)
