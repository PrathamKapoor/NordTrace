"""Public starter JSONL input compatibility; simulated outcomes are not live research."""

import json

import pytest
from click.testing import CliRunner

from nordtrace.cli import cli
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome

ORG = "982463718"


def test_jsonl_batch_preserves_identifiers_and_occurrences_without_trusting_other_fields(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "input.db"))
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        assert self.budget.configuration.max_requests != 999999
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr("nordtrace.engine.runner.ResearchPipeline.research_company", research)
    supplied = [ORG, "NO 982 463 718 MVA", "bad", "bad", ""]
    records = [{"organisation_number": value, "name": "UNTRUSTED NAME", "website": "file:///untrusted",
                "run_configuration": {"max_requests": 999999}} for value in supplied]
    source = tmp_path / "companies.jsonl"
    source.write_text("\n" + "\n\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8-sig")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["batch", str(source), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert calls == [ORG]
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [item["supplied"] for item in payload["inputs"]] == supplied
    assert [item["result_key"] for item in payload["inputs"]] == [ORG, ORG, "bad", "bad", ""]
    assert [item["index"] for item in payload["inputs"]] == list(range(5))
    assert payload["completion"] == {"complete": True, "input_count": 5, "result_count": 3}
    assert all(item["company"] is None for item in payload["results"])
    assert payload["request_count"] == 0


@pytest.mark.parametrize("record", [
    '{"organisation_number": 982463718}', '{"organisation_number": null}',
    '{"organisation_number": true}', '{}', '[]', '"982463718"',
    '{"organisation_number":"982463718","organisation_number":"958973306"}',
    '{"organisation_number":"982463718","extra":NaN}',
    '{"organisation_number":"982463718","extra":1e999}',
    '{"organisation_number":"\\ud800"}',
    '{"organisation_number":',
])
def test_invalid_jsonl_container_fails_before_any_research(tmp_path, monkeypatch, record):
    calls = []
    monkeypatch.setattr("nordtrace.cli._repo", lambda: calls.append("repository opened"))
    source = tmp_path / "invalid.jsonl"
    source.write_text(json.dumps({"organisation_number": ORG}) + "\n" + record + "\n", encoding="utf-8")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["batch", str(source), "--output", str(output)])
    assert result.exit_code != 0
    assert "JSONL line 2" in result.output
    assert calls == [] and not output.exists()


def test_explicit_jsonl_format_works_with_an_external_filename(tmp_path, monkeypatch):
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "explicit.db"))
    source = tmp_path / "organizer-input.txt"
    source.write_text('{"organisation_number":"bad"}\n', encoding="utf-8")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, [
        "batch", str(source), "--input-format", "jsonl", "--output", str(output),
    ])
    assert result.exit_code == 2, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["inputs"] == [{"index": 0, "supplied": "bad", "result_key": "bad"}]
    assert payload["results"][0]["errors"][0]["code"] == "invalid_organisation_number"


def test_empty_jsonl_is_an_input_error_before_repository_access(tmp_path, monkeypatch):
    source = tmp_path / "empty.jsonl"
    source.write_text("\n\n", encoding="utf-8-sig")
    calls = []
    monkeypatch.setattr("nordtrace.cli._repo", lambda: calls.append("repository opened"))
    result = CliRunner().invoke(cli, ["batch", str(source)])
    assert result.exit_code == 2 and "Nothing to research" in result.output
    assert calls == []


def test_paired_unicode_escapes_remain_an_invalid_identifier_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "unicode.db"))
    source = tmp_path / "unicode.jsonl"
    source.write_text('{"organisation_number":"\\ud83d\\ude00"}\n', encoding="utf-8")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["batch", str(source), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert json.loads(output.read_text(encoding="utf-8"))["inputs"][0]["supplied"] == "\U0001f600"
