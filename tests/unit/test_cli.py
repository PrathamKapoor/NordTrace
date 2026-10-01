import json

import pytest
from click.testing import CliRunner

from nordtrace.cli import _read_csv, _result_json, cli
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyIdentity, utcnow


@pytest.fixture()
def runner():
    return CliRunner()


def test_cli_help(runner):
    res = runner.invoke(cli, ["--help"])
    assert res.exit_code == 0
    for cmd in ("research", "batch", "resume", "benchmark", "validate", "serve"):
        assert cmd in res.output


def test_read_csv_with_header(tmp_path):
    p = tmp_path / "companies.csv"
    p.write_text("orgnr,navn\n982463718,Telenor\n958973306,Salmar\n", encoding="utf-8")
    orgs = _read_csv(str(p))
    assert orgs == ["982463718", "958973306"]


def test_read_csv_without_header(tmp_path):
    p = tmp_path / "companies.txt"
    p.write_text("982463718\n958973306\n", encoding="utf-8")
    assert _read_csv(str(p)) == ["982463718", "958973306"]


def test_research_invalid_orgnr_exits(runner):
    res = runner.invoke(cli, ["research", "12345"])
    assert res.exit_code == 2
    assert "invalid" in res.output.lower()


def test_research_malformed_exits(runner):
    res = runner.invoke(cli, ["research", "abcdefghi"])
    assert res.exit_code == 2


def test_validate_good_result(runner, tmp_path):
    p = tmp_path / "result.json"
    p.write_text(
        json.dumps(
            {
                "run_id": "run_x",
                "organisation_number": "982463718",
                "status": "available",
                "facts": [],
                "changes": [],
                "research_metadata": {"request_count": 5, "estimated_cost_usd": 0.0},
            }
        ),
        encoding="utf-8",
    )
    res = runner.invoke(cli, ["validate", str(p)])
    assert res.exit_code == 0
    assert "passed" in res.output.lower()


def test_validate_missing_fields(runner, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    res = runner.invoke(cli, ["validate", str(p)])
    assert res.exit_code == 1
    assert "run_id" in res.output


def test_validate_bad_status(runner, tmp_path):
    p = tmp_path / "bad2.json"
    p.write_text(
        json.dumps({"run_id": "r", "organisation_number": "982463718", "status": "awesome"}), encoding="utf-8"
    )
    res = runner.invoke(cli, ["validate", str(p)])
    assert res.exit_code == 1
    assert "status" in res.output


def test_validate_negative_metadata(runner, tmp_path):
    p = tmp_path / "bad3.json"
    p.write_text(
        json.dumps(
            {
                "run_id": "r",
                "organisation_number": "982463718",
                "status": "available",
                "research_metadata": {"request_count": -5},
            }
        ),
        encoding="utf-8",
    )
    res = runner.invoke(cli, ["validate", str(p)])
    assert res.exit_code == 1


def test_result_json_structure():
    """_result_json produces schema-valid output."""

    class Outcome:
        org_number = "982463718"
        terminal_state = "available"
        identity = CompanyIdentity(organisation_number="982463718", legal_name="TELENOR ASA")
        facts = []
        evidence = []
        sources = []
        rejected = []
        changes = []
        summary = "test summary"
        unknowns = []
        coverage = {"identity": "found"}
        stages = ["validation"]
        error = None
        duration_sec = 1.5

    bm = BudgetManager()
    payload = _result_json(Outcome(), "run_x", bm, utcnow().isoformat())
    assert payload["organisation_number"] == "982463718"
    assert payload["status"] == "available"
    assert payload["research_metadata"]["request_count"] == 0
    assert "run_id" in payload


def test_batch_missing_file_exits(runner):
    res = runner.invoke(cli, ["batch", "no_such_file.csv"])
    assert res.exit_code != 0
