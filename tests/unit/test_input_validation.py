"""Input records and explicit schema versions cannot silently disappear/downgrade."""

import json

import click
import pytest
from click.testing import CliRunner

from nordtrace.cli import _read_csv, cli
from nordtrace.validate import validate_result


@pytest.mark.parametrize("body, expected", [
    ("orgbad\n12345\n", ["orgbad", "12345"]),
    ("orgnr\norgbad\norgnr\n12345\n", ["orgbad", "orgnr", "12345"]),
    ("12345\norgbad\n", ["12345", "orgbad"]),
    ("organisasjonsnummer,navn\n12345,Fixture\n", ["12345"]),
    ("organisation_number\n12345\n", ["12345"]),
    ("organisation_number,navn\n\n,Empty input\n\"\"\n12345,Fixture\n", ["", "", "12345"]),
    ("\nORGNR\norgbad\n", ["orgbad"]),
])
def test_csv_header_is_exact_first_record_and_invalid_records_survive(tmp_path, body, expected):
    source = tmp_path / "inputs.csv"
    source.write_text(body, encoding="utf-8-sig")
    assert _read_csv(str(source)) == expected


@pytest.mark.parametrize("body", [b'orgnr\n"unterminated\n12345\n', b"orgnr\n\xff\n"])
def test_malformed_csv_fails_before_research(tmp_path, monkeypatch, body):
    source = tmp_path / "malformed.csv"
    source.write_bytes(body)
    calls = []
    monkeypatch.setattr("nordtrace.cli._repo", lambda: calls.append("opened repository"))
    result = CliRunner().invoke(cli, ["batch", str(source)])
    assert result.exit_code != 0
    assert "Cannot read company input" in result.output
    assert calls == []
    with pytest.raises(click.ClickException):
        _read_csv(str(source))


def test_cli_preserves_every_invalid_csv_record_in_export(tmp_path, monkeypatch):
    from nordtrace.core.repository import Repository

    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "inputs.db"))
    source = tmp_path / "inputs.csv"
    source.write_text('orgnr\norgbad\norgnr\n""\norgbad\n', encoding="utf-8")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["batch", str(source), "--output", str(output)])
    assert result.exit_code == 2, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [item["supplied"] for item in payload["inputs"]] == ["orgbad", "orgnr", "", "orgbad"]
    assert [item["index"] for item in payload["inputs"]] == [0, 1, 2, 3]
    assert {item["organisation_number"] for item in payload["results"]} == {"orgbad", "orgnr", ""}
    assert all(item["status"] == "not_applicable" for item in payload["results"])
    assert payload["completion"] == {"complete": True, "input_count": 4, "result_count": 3}
    assert payload["request_count"] == 0


@pytest.mark.parametrize("version", ["9.9", "1.0", None, 1.1, True, {}, []])
def test_explicit_unknown_schema_cannot_use_legacy_validation(version):
    data = {
        "schema_version": version, "run_id": "fixture", "organisation_number": "982463718",
        "status": "available", "facts": [],
    }
    assert any("unsupported schema_version" in error for error in validate_result(data))


def test_unversioned_legacy_and_current_schema_remain_distinct_supported_paths():
    from nordtrace.core.models import CompanyProfile

    assert validate_result({
        "run_id": "legacy", "organisation_number": "982463718", "status": "not_available",
    }) == []
    profile = CompanyProfile(run_id="current", organisation_number="982463718", status="not_available")
    assert validate_result(profile.model_dump(mode="json")) == []


@pytest.mark.parametrize("data", [None, [], "fixture", 123, True])
def test_non_object_result_is_a_validation_error(data):
    assert validate_result(data) == ["result must be a JSON object"]
