"""Synthetic public-universe shape; no research or independent accuracy labels."""

import gzip
import hashlib
import json
from itertools import islice

import pytest

from nordtrace.core.orgnr import validate_orgnr


def records(size=80):
    ids = list(islice((str(value) for value in range(900000000, 900010000)
                       if validate_orgnr(str(value)).valid), size))
    return [{"organisation_number": org, "name": "SYNTHETIC FIXTURE", "legal_form": "AS" if i % 3 else "ANS",
             "employees": [None, 0, 2, 12, 60][i % 5], "website": "https://example.no" if i % 2 else "",
             "industry_code": "64.200" if i % 4 == 0 else "62.010",
             "industry_label": "Holding metadata" if i % 4 == 0 else "Other metadata"}
            for i, org in enumerate(ids)]


def supplied(tmp_path, rows, filename="universe.gz"):
    body = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    archive = gzip.compress(body, mtime=0)
    path = tmp_path / filename
    path.write_bytes(archive)
    return path, {"expected_sha256": hashlib.sha256(archive).hexdigest(),
                  "expected_uncompressed_sha256": hashlib.sha256(body).hexdigest()}


def test_seeded_samples_are_disjoint_reproducible_and_do_not_treat_unknown_as_zero(tmp_path):
    from nordtrace.sampling import sample_universe

    source, hashes = supplied(tmp_path, records())
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = sample_universe(source, first, seed="fixture-seed", development_size=10,
                               held_out_size=10, **hashes)
    sample_universe(source, second, seed="fixture-seed", development_size=10, held_out_size=10, **hashes)
    assert manifest["source_record_count"] == 80
    chosen = []
    for split in ("development", "held_out"):
        info = manifest["splits"][split]
        body = (first / info["path"]).read_bytes()
        assert len(body.splitlines()) == info["count"] == 10
        assert hashlib.sha256(body).hexdigest() == info["sha256"]
        assert body == (second / info["path"]).read_bytes()
        chosen.append({row["organisation_number"] for row in map(json.loads, body.splitlines())})
    assert not chosen[0] & chosen[1]
    keys = [item["key"] for item in manifest["strata"]]
    assert any("unknown" in key for key in keys) and any("metadata_zero" in key for key in keys)
    assert manifest["independent_accuracy"] == "not_measured"
    assert manifest["completion"]["complete"] is True


def test_selection_is_independent_of_source_record_order(tmp_path):
    from nordtrace.sampling import sample_universe

    rows = records()
    for name, items in (("forward", rows), ("backward", rows[::-1])):
        source, hashes = supplied(tmp_path, items, name + ".gz")
        sample_universe(source, tmp_path / name, seed="fixed", development_size=10,
                        held_out_size=10, **hashes)
    for filename in ("development.jsonl", "held_out.jsonl"):
        forward, backward = tmp_path / "forward" / filename, tmp_path / "backward" / filename
        assert forward.read_bytes() == backward.read_bytes()


def test_larger_samples_never_move_a_held_out_company_into_development(tmp_path):
    from nordtrace.sampling import sample_universe

    rows = records()
    template = rows[0]
    rows = [{**template, "organisation_number": row["organisation_number"]} for row in rows]
    source, hashes = supplied(tmp_path, rows)
    chosen = {"development": set(), "held_out": set()}
    previous = {}
    for size in (5, 20):
        output = tmp_path / str(size)
        manifest = sample_universe(source, output, seed="stable-partition", development_size=size,
                                   held_out_size=size, **hashes)
        for split, info in manifest["splits"].items():
            values = set(info["organisation_numbers"])
            assert previous.get(split, set()) <= values
            previous[split] = values
            chosen[split].update(values)
    assert not chosen["development"] & chosen["held_out"]


@pytest.mark.parametrize("defect", ["wrong_hash", "duplicate", "invalid_org", "capacity", "too_many"])
def test_sampling_refuses_invalid_inputs_without_a_complete_artifact(tmp_path, defect):
    from nordtrace.sampling import sample_universe

    rows = records()
    if defect == "duplicate":
        rows.append(rows[0])
    if defect == "invalid_org":
        rows[0]["organisation_number"] = "123456789"
    source, hashes = supplied(tmp_path, rows)
    if defect == "wrong_hash":
        hashes["expected_sha256"] = "0" * 64
    kwargs = {"max_uncompressed_bytes": 5} if defect == "capacity" else {}
    output = tmp_path / "samples"
    with pytest.raises(ValueError):
        sample_universe(source, output, seed="fixture", development_size=100 if defect == "too_many" else 10,
                        held_out_size=10, **hashes, **kwargs)
    assert not output.exists()


def test_existing_sample_directory_is_preserved(tmp_path):
    from nordtrace.sampling import sample_universe

    source, hashes = supplied(tmp_path, records())
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        sample_universe(source, output, seed="fixture", development_size=10, held_out_size=10, **hashes)
    assert (output / "user.txt").read_text(encoding="utf-8") == "preserve"


def test_cli_sampling_is_offline_and_generated_jsonl_is_accepted_by_batch(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import _read_batch_inputs, cli

    source, hashes = supplied(tmp_path, records())
    output = tmp_path / "samples"
    monkeypatch.setattr("nordtrace.cli._repo", lambda: pytest.fail("sampling opened repository"))
    result = CliRunner().invoke(cli, [
        "sample-universe", str(source), "--output", str(output), "--seed", "fixture",
        "--development-size", "10", "--held-out-size", "10",
        "--expected-sha256", hashes["expected_sha256"],
        "--expected-uncompressed-sha256", hashes["expected_uncompressed_sha256"],
    ])
    assert result.exit_code == 0, result.output
    assert len(_read_batch_inputs(str(output / "development.jsonl"))) == 10
    assert (output / "manifest.json").exists()


def test_concurrent_destination_creation_is_never_replaced(tmp_path, monkeypatch):
    from nordtrace.sampling import sample_universe

    source, hashes = supplied(tmp_path, records())
    output = tmp_path / "samples"
    from nordtrace.sampling import write_json_atomic

    def concurrent(path, payload):
        write_json_atomic(path, payload)
        output.mkdir()  # A concurrent user creates an empty directory immediately before publication.

    monkeypatch.setattr("nordtrace.sampling.write_json_atomic", concurrent)
    with pytest.raises(FileExistsError):
        sample_universe(source, output, seed="fixture", development_size=10, held_out_size=10, **hashes)
    assert output.is_dir() and list(output.iterdir()) == []


def test_failed_publication_has_no_completion_manifest(tmp_path, monkeypatch):
    from nordtrace.sampling import sample_universe

    source, hashes = supplied(tmp_path, records())
    output = tmp_path / "samples"
    original_link = __import__("os").link

    def fail(source, destination):
        if str(destination).endswith("held_out.jsonl"):
            raise OSError("injected publication failure")
        return original_link(source, destination)

    monkeypatch.setattr("nordtrace.sampling.os.link", fail)
    with pytest.raises(OSError, match="publication failure"):
        sample_universe(source, output, seed="fixture", development_size=10, held_out_size=10, **hashes)
    assert not (output / "manifest.json").exists()
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("record", [
    '{}', '[]', '{"organisation_number":900000006}',
    '{"organisation_number":"900000006","organisation_number":"900000014"}',
    '{"organisation_number":"900000006","extra":NaN}',
    '{"organisation_number":"900000006","extra":1e999}',
    '{"organisation_number":"900000006","name":"\\ud800"}',
])
def test_malformed_universe_is_not_silently_filtered(tmp_path, record):
    from nordtrace.sampling import sample_universe

    body = (record + "\n").encode()
    archive = gzip.compress(body, mtime=0)
    path = tmp_path / "invalid.gz"
    path.write_bytes(archive)
    output = tmp_path / "samples"
    with pytest.raises(ValueError, match="JSONL line 1"):
        sample_universe(path, output, seed="fixture", development_size=1, held_out_size=0,
                        expected_sha256=hashlib.sha256(archive).hexdigest(),
                        expected_uncompressed_sha256=hashlib.sha256(body).hexdigest())
    assert not output.exists()


@pytest.mark.parametrize("bound", ["line", "compressed", "uncompressed_hash"])
def test_all_source_integrity_bounds_fail_before_output(tmp_path, monkeypatch, bound):
    from nordtrace.sampling import sample_universe

    source, hashes = supplied(tmp_path, records())
    if bound == "line":
        monkeypatch.setattr("nordtrace.sampling.MAX_LINE_BYTES", 20)
    elif bound == "compressed":
        monkeypatch.setattr("nordtrace.sampling.MAX_COMPRESSED_BYTES", 20)
    else:
        hashes["expected_uncompressed_sha256"] = "0" * 64
    output = tmp_path / "samples"
    with pytest.raises(ValueError):
        sample_universe(source, output, seed="fixture", development_size=10, held_out_size=10, **hashes)
    assert not output.exists()
