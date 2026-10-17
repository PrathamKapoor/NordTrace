"""Operational benchmark reporting is distinct from independent factual accuracy."""

import asyncio
import json

import pytest
from click.testing import CliRunner

from nordtrace.benchmark import BenchmarkHarness
from nordtrace.cli import cli
from nordtrace.core.models import CompanyIdentity
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline


def test_benchmark_requires_supplied_inputs_before_repository_access(monkeypatch):
    monkeypatch.setattr("nordtrace.cli._repo", lambda: pytest.fail("repository opened"))
    result = CliRunner().invoke(cli, ["benchmark"])
    assert result.exit_code == 2 and "--orgnr-file" in result.output


@pytest.mark.parametrize("conflict", ["input_output_alias", "input_changed_during_read"])
def test_benchmark_preserves_input_and_checks_provenance_before_research(tmp_path, monkeypatch, conflict):
    source = tmp_path / "sample.jsonl"
    source.write_text('{"organisation_number":"bad"}\n', encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr("nordtrace.cli._repo", lambda: pytest.fail("repository opened"))
    if conflict == "input_output_alias":
        output = source
    else:
        from nordtrace.cli import _read_batch_inputs

        def changed(path, input_format):
            records = _read_batch_inputs(path, input_format)
            source.write_text('{"organisation_number":"different"}\n', encoding="utf-8")
            return records

        monkeypatch.setattr("nordtrace.cli._read_batch_inputs", changed)
    result = CliRunner().invoke(cli, ["benchmark", "--orgnr-file", str(source), "--output", str(output)])
    assert result.exit_code != 0
    if conflict == "input_output_alias":
        assert "bad" in source.read_text(encoding="utf-8")
    assert not (tmp_path / "report.json").exists()


def test_legacy_brand_discovery_cannot_spend_an_unreported_allowance(tmp_path, monkeypatch):
    calls = []

    async def acquisition(*args, **kwargs):
        from nordtrace.core.models import SourceRecord

        calls.append("unreported discovery")
        return SourceRecord(access_status="failed")

    monkeypatch.setattr("nordtrace.core.request_gateway.RequestGateway.fetch", acquisition)
    repo = Repository(tmp_path / "discovery.db")
    try:
        with pytest.raises(ValueError, match="supplied"):
            asyncio.run(BenchmarkHarness(repo).fetch_live_companies())
        assert calls == []
        assert repo.list_runs() == []
    finally:
        repo.close()


def test_benchmark_completion_is_not_availability_or_entity_resolution(tmp_path, monkeypatch):
    async def research(self, org, run_id):
        if org == "982463718":
            # Even an available DTO is not a supported legal name without observations.
            return CompanyOutcome(org_number=org, terminal_state="available",
                                  identity=CompanyIdentity(organisation_number=org,
                                                           legal_name="UNSUPPORTED AS"))
        if org == "958973306":
            return CompanyOutcome(org_number=org, terminal_state="not_available")
        raise RuntimeError("fixture source failure")

    monkeypatch.setattr(ResearchPipeline, "research_company", research)
    repo = Repository(tmp_path / "metrics.db")
    try:
        report = asyncio.run(BenchmarkHarness(repo).evaluate_batch(
            ["NO 982 463 718 MVA", "958973306", "bad", "923609016", "982463718"],
        ))
        assert report["input_count"] == 5
        assert report["batch_size"] == report["completed"] == 4
        assert report["available"] == 1 and report["failed"] == 1
        assert report["entity_resolved"] == 0
        assert report["completion_rate"] == 1
        assert len(report["results"]) == 4
        assert [row["supplied"] for row in report["inputs"]][0] == "NO 982 463 718 MVA"
        assert report["independent_accuracy"]["measured"] is False
        assert report["independent_accuracy"]["exact_company_precision"] is None
        assert report["independent_accuracy"]["claim_recall"] is None
        assert report["run_id"]
        assert report["total_external_supported_claims"] == 0
    finally:
        repo.close()


@pytest.mark.parametrize("limit", [None, 5])
def test_benchmark_cli_preserves_jsonl_inputs_and_records_explicit_selection(tmp_path, monkeypatch, limit):
    source = tmp_path / "sample.jsonl"
    supplied = [f"invalid-{index}" for index in range(12)]
    source.write_text("\n".join(json.dumps({"organisation_number": value}) for value in supplied),
                      encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "cli.db"))
    args = ["benchmark", "--orgnr-file", str(source), "--output", str(output)]
    if limit is not None:
        args += ["--limit", str(limit)]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 2, result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    expected = 12 if limit is None else limit
    assert report["input_count"] == report["completed"] == expected
    assert [item["supplied"] for item in report["inputs"]] == supplied[:expected]
    assert report["selection"]["supplied_input_count"] == 12
    assert report["selection"]["excluded_input_indices"] == list(range(expected, 12))
    assert report["budgets"]["requests_used"] == 0
    assert report["entity_resolved"] == 0


@pytest.mark.parametrize("tamper", [False, True])
def test_benchmark_revalidates_real_pipeline_observations_and_separates_registry_counts(
    tmp_path, monkeypatch, tamper,
):
    import httpx

    from nordtrace.core.budget import BudgetManager
    from nordtrace.engine.runner import BatchRunner

    original_init = ResearchPipeline.__init__
    transport_calls = []

    def respond(request):
        transport_calls.append(str(request.url))
        if request.url.path.endswith("/enheter/982463718"):
            return httpx.Response(200, json={
                "organisasjonsnummer": "982463718", "navn": "METRIC FIXTURE AS", "antallAnsatte": 0,
            })
        return httpx.Response(404)

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(ResearchPipeline, "__init__", initialize)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    original_run = BatchRunner.run_batch

    async def after_publication(self, *args, **kwargs):
        run = await original_run(self, *args, **kwargs)
        if tamper:
            self.repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"tampered",))
            self.repo.conn.commit()
        return run

    monkeypatch.setattr(BatchRunner, "run_batch", after_publication)
    repo = Repository(tmp_path / "supported.db")
    try:
        report = asyncio.run(BenchmarkHarness(repo).evaluate_batch(
            ["982463718"], budget=BudgetManager(max_requests=100),
        ))
        assert report["completed"] == 1 and report["available"] == 1, report["results"]
        assert report["entity_resolved"] == (0 if tamper else 1)
        assert report["total_facts"] == 2
        assert report["total_supported_claims"] == (0 if tamper else 2)
        assert len(report["support_validation"]["failures"]) == (2 if tamper else 0)
        assert report["total_external_supported_claims"] == 0
        assert report["company_counts_by_external_supported_family"] == {}
        assert report["budgets"]["requests_used"] == len(transport_calls)
        assert report["independent_accuracy"]["measured"] is False
    finally:
        repo.close()


def test_cli_reports_exceeded_runtime_even_when_every_input_has_a_terminal_envelope(tmp_path, monkeypatch):
    from nordtrace.core.budget import BudgetManager

    original = BenchmarkHarness.evaluate_batch

    async def minimal_allowance(self, org_numbers):
        return await original(self, org_numbers, budget=BudgetManager(
            max_requests=0, max_runtime_sec=1e-9, max_cost=0,
        ))

    monkeypatch.setattr(BenchmarkHarness, "evaluate_batch", minimal_allowance)
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "deadline.db"))
    source = tmp_path / "input.csv"
    source.write_text("bad\n", encoding="utf-8")
    output = tmp_path / "report.json"
    result = CliRunner().invoke(cli, ["benchmark", "--orgnr-file", str(source), "--output", str(output)])
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["completed"] == 1 and report["failed"] == 0
    assert report["budgets"]["runtime_ok"] is False
    assert result.exit_code == 1


@pytest.mark.parametrize("corroboration", [False, True])
def test_logical_claim_counts_do_not_inflate_with_corroborating_observations(
    tmp_path, monkeypatch, corroboration,
):
    import httpx

    from nordtrace.adapters.brreg import BrregAdapter
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.request_gateway import RequestGateway

    original_init = ResearchPipeline.__init__
    original_finalize = ResearchPipeline._finalize_ledger
    sequence = []
    extra = {}

    def respond(request):
        if request.url.path.endswith("/enheter/982463718"):
            sequence.append(1)
            return httpx.Response(200, json={"organisasjonsnummer": "982463718", "navn": "FIXTURE AS",
                                            "unrelated_nonce": len(sequence)})
        return httpx.Response(404)

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        original_fetch = self.brreg.fetch_entity

        async def fetch(org, run_id):
            first = await original_fetch(org, run_id)
            if corroboration:
                gateway = RequestGateway(self.budget, repository=self.repo)
                gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                adapter = BrregAdapter(gateway, self.budget)
                try:
                    identity, source, _, hint = await adapter.fetch_entity(org, run_id)
                    assert hint == "found"
                    evidence, facts = adapter.identity_claims(identity, source, run_id)
                    extra[id(self)] = (source, evidence, facts)
                finally:
                    await gateway.aclose()
            return first

        self.brreg.fetch_entity = fetch

    def finalize(self, outcome, ledger, run_id, accounts_status):
        if id(self) in extra:
            source, evidence, facts = extra.pop(id(self))
            ledger.add_source(source)
            for item in evidence:
                ledger.add_evidence(item)
            for fact in facts:
                ledger.add_fact(fact)
        return original_finalize(self, outcome, ledger, run_id, accounts_status)

    monkeypatch.setattr(ResearchPipeline, "__init__", initialize)
    monkeypatch.setattr(ResearchPipeline, "_finalize_ledger", finalize)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "corroborated.db")
    try:
        report = asyncio.run(BenchmarkHarness(repo).evaluate_batch(
            ["982463718"], budget=BudgetManager(max_requests=100),
        ))
        canonical = repo.get_results(report["run_id"])[0]
        assert len(canonical.facts) == (2 if corroboration else 1)
        assert len({fact.claim_id for fact in canonical.facts}) == 1
        assert report["total_supported_claims"] == 1
        assert report["total_supported_observations"] == len(canonical.facts)
        assert report["support_validation"]["failures"] == []
    finally:
        repo.close()


def test_outage_inventory_does_not_claim_historical_sources_were_retrieved_now(tmp_path, monkeypatch):
    import httpx

    from nordtrace.core.budget import BudgetManager

    original_init = ResearchPipeline.__init__
    responses = []
    outage = False

    def respond(request):
        if request.url.path.endswith("/enheter/982463718"):
            status = 403 if outage else 200
            responses.append(status)
            return httpx.Response(status, json={"organisasjonsnummer": "982463718", "navn": "FIXTURE AS"})
        return httpx.Response(404)

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(ResearchPipeline, "__init__", initialize)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "outage.db")
    try:
        harness = BenchmarkHarness(repo)
        asyncio.run(harness.evaluate_batch(["982463718"], budget=BudgetManager(max_requests=100)))
        outage = True
        responses.clear()
        report = asyncio.run(harness.evaluate_batch(["982463718"], budget=BudgetManager(max_requests=100)))
        assert responses == [403]
        assert report["terminal_counts"] == {"blocked": 1}
        assert report["results"][0]["last_known_claims"] == 1
        assert report["results"][0]["retained_successful_source_records"] == 1
        assert report["results"][0]["last_known_source_records"] == 1
        assert "sources_retrieved" not in report["results"][0]
        assert report["budgets"]["requests_used"] == 1
    finally:
        repo.close()
