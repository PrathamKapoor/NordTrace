"""Atomic portable canonical JSONL bundles, not an official evaluator schema."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nordtrace.core.budget import request_telemetry_snapshot
from nordtrace.core.contracts import map_inputs, project_identity
from nordtrace.core.evidence import SnapshotReader, verify_capture_metadata
from nordtrace.core.ledger import CitationValidator
from nordtrace.core.models import CompanyProfile, RunBudgetState, SourceRecord, utcnow
from nordtrace.core.repository import Repository

DEFAULT_MAX_BYTES = 256 * 1024 * 1024  # Local uncompressed export capacity, not a run budget.


class BundleOperations(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    scope: Literal["whole_run"]
    accounting_state: Literal["recorded", "unavailable"]
    requests: int | None = Field(ge=0)
    estimated_cost_usd: float | None = Field(ge=0)
    budget: RunBudgetState | None
    observed_at: str
    finalized_run: bool
    started_at: str | None
    completed_at: str | None

    @model_validator(mode="after")
    def accounting_is_explicit(self) -> BundleOperations:
        from datetime import datetime

        if datetime.fromisoformat(self.observed_at).tzinfo is None:
            raise ValueError("accounting observation time must include a timezone")
        values = (self.requests, self.estimated_cost_usd, self.budget)
        if self.accounting_state == "recorded" and any(value is None for value in values):
            raise ValueError("recorded accounting requires totals and original budget")
        if self.accounting_state == "unavailable" and any(value is not None for value in values):
            raise ValueError("unavailable accounting must not invent totals or limits")
        if self.finalized_run and self.completed_at is None:
            raise ValueError("finalized accounting requires recorded completion time")
        if self.budget is not None and self.requests is not None:
            telemetry = self.budget.telemetry
            for field in ("successful", "failed", "unstarted_reservations", "retries"):
                value = telemetry.get(field, 0)
                if type(value) is not int or value < 0:
                    raise ValueError("request outcome counters must be nonnegative integers")
            expected = request_telemetry_snapshot(
                telemetry, self.requests, self.budget.configuration.max_requests,
            )
            if telemetry != expected or expected["unresolved_reservations"] < 0:
                raise ValueError("request accounting counters disagree")
        return self


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def _validate_result(result: CompanyProfile, reader: SnapshotReader) -> None:
    if result.company != project_identity(result.company, result.conflicts, result.facts):
        raise ValueError("structured identity is not supported by published observations")
    validator = CitationValidator(
        {source.source_id: source for source in result.sources},
        {item.evidence_id: item for item in result.evidence}, reader,
    )
    for fact in result.facts + result.conflicts + result.last_known:
        valid, reason = validator.validate(fact)
        if not valid:
            raise ValueError(f"claim support failed: {reason}")


def _validate_mapping(inputs: list[dict], keys: list[str]) -> None:
    expected = [item.model_dump() for item in map_inputs([item["supplied"] for item in inputs])]
    if inputs != expected or len(keys) != len(set(keys)):
        raise ValueError("invalid ordered input mapping")
    if list(dict.fromkeys(item["result_key"] for item in inputs)) != keys:
        raise ValueError("input mapping does not correspond exactly to results")


def export_run(
    repo: Repository, run_id: str, output: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict:
    """Publish one exclusive artifact only after every result and capture validates.

    Rows and blobs are read one at a time; the limit counts uncompressed payloads.
    A failed export leaves durable research untouched and no complete-looking artifact.
    """
    destination = Path(output)
    if destination.exists():
        raise FileExistsError(f"export destination already exists: {destination}")
    if max_bytes <= 0:
        raise ValueError("export capacity must be positive")
    run = repo.get_run(run_id)
    if run is None:
        raise ValueError("run not found")
    inputs = repo.get_run_inputs(run_id)
    _validate_mapping(inputs, run.companies)
    try:
        state, requests, cost = repo.get_run_budget(run_id)
    except ValueError as error:
        if str(error) != "original run budget is unavailable":
            raise  # Corrupt recorded budgets must remain observable.
        state, requests, cost = None, None, None
    if state is not None and requests is not None:
        state = state.model_copy(update={"telemetry": request_telemetry_snapshot(
            state.telemetry, requests, state.configuration.max_requests,
        )})
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    total = 0

    def charge(body: bytes) -> bytes:
        nonlocal total
        total += len(body)
        if total > max_bytes:
            raise ValueError("export capacity exceeded")
        return body

    try:
        with os.fdopen(fd, "w+b") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as archive:
                digest = hashlib.sha256()
                sources: dict[str, SourceRecord] = {}
                with archive.open("results.jsonl", "w", force_zip64=True) as results:
                    for key in run.companies:
                        result = repo.get_result(run_id, key)
                        if result is None or result.run_id != run_id or result.organisation_number != key:
                            raise ValueError("incomplete run: missing or mismatched canonical result")
                        _validate_result(result, repo)
                        body = charge(_json(result.model_dump(mode="json")))
                        results.write(body)
                        digest.update(body)
                        for source in result.sources:
                            if source.access_status == "success":
                                previous = sources.get(source.source_id)
                                if previous is not None and previous != source:
                                    raise ValueError("source ID has conflicting metadata")
                                sources[source.source_id] = source
                captures = {}
                written = set()
                for source_id, expected in sources.items():
                    captured, body = repo.read_capture(source_id)
                    verify_capture_metadata(captured, expected)
                    path = f"objects/{captured.content_hash}.bin"
                    if path not in written:
                        archive.writestr(path, charge(body))
                        written.add(path)
                    captures[source_id] = {"path": path, "bytes": len(body),
                                           "source": captured.model_dump(mode="json")}
                schema = charge(_json(CompanyProfile.model_json_schema()))
                archive.writestr("result-schema.json", schema)
                manifest = {
                    "format": "nordtrace-audit-bundle-v1", "result_schema": "nordtrace-1.1",
                    "run_id": run_id, "run_state": run.state, "inputs": inputs,
                    "schema_sha256": hashlib.sha256(schema).hexdigest(),
                    "results_sha256": digest.hexdigest(), "captures": captures,
                    "completion": {"complete": True, "input_count": len(inputs),
                                   "result_count": len(run.companies)},
                    "operations": {"scope": "whole_run", "requests": requests,
                                   "observed_at": utcnow().isoformat(),
                                   "finalized_run": run.completed_at is not None and run.state != "running",
                                   "accounting_state": "recorded" if state else "unavailable",
                                   "estimated_cost_usd": cost,
                                   "budget": state.model_dump(mode="json") if state else None,
                                   "started_at": run.started_at, "completed_at": run.completed_at},
                    "limitations": ["Local canonical format; official organizer acceptance unverified",
                                    "Costs are recorded estimates, not independently billed amounts",
                                    "Source rights are source-specific; intended for local audit"],
                }
                BundleOperations.model_validate(manifest["operations"])
                archive.writestr("manifest.json", charge(_json(manifest)))
            handle.flush()
            os.fsync(handle.fileno())
        # Same-directory hard link publishes atomically and refuses concurrent/existing outputs.
        os.link(temporary, destination)
        return manifest
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _BundleReader:
    def __init__(self, archive: zipfile.ZipFile, captures: dict):
        self.archive = archive
        self.captures = captures

    def read_capture(self, source_id: str) -> tuple[SourceRecord, bytes]:
        item = self.captures[source_id]
        source = SourceRecord.model_validate(item["source"])
        if (source.source_id != source_id or not source.content_hash
                or not re.fullmatch(r"[0-9a-f]{64}", source.content_hash)
                or item["path"] != f"objects/{source.content_hash}.bin"):
            raise ValueError("snapshot integrity metadata invalid")
        body = self.archive.read(item["path"])
        if (hashlib.sha256(body).hexdigest() != source.content_hash or len(body) != item["bytes"]
                or source.snapshot_representation != "http-response-body-v1"):
            raise ValueError("snapshot integrity failure")
        return source, body


def verify_bundle(output: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """Check portable bytes, reference graph and current deterministic support offline.

    Never extracts archive paths or follows URLs. This establishes internal support,
    not independent source truth, rights or authenticity of an unsigned artifact.
    """
    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or sum(item.file_size for item in infos) > max_bytes:
            raise ValueError("bundle capacity or duplicate-member integrity failure")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != "nordtrace-audit-bundle-v1":
            raise ValueError("unsupported bundle format")
        if manifest.get("result_schema") != "nordtrace-1.1":
            raise ValueError("unsupported bundle result schema")
        BundleOperations.model_validate(manifest["operations"])
        schema = archive.read("result-schema.json")
        if (hashlib.sha256(schema).hexdigest() != manifest["schema_sha256"]
                or json.loads(schema) != CompanyProfile.model_json_schema()):
            raise ValueError("bundle schema integrity differs from installed local schema")
        reader = _BundleReader(archive, manifest["captures"])
        for source_id in manifest["captures"]:
            reader.read_capture(source_id)
        digest = hashlib.sha256()
        keys = []
        with archive.open("results.jsonl") as results:
            for line in results:
                digest.update(line)
                result = CompanyProfile.model_validate_json(line)
                if result.run_id != manifest["run_id"]:
                    raise ValueError("result run differs from manifest")
                _validate_result(result, reader)
                keys.append(result.organisation_number)
                for source in result.sources:
                    if source.access_status == "success":
                        captured, _ = reader.read_capture(source.source_id)
                        verify_capture_metadata(captured, source)
        if digest.hexdigest() != manifest["results_sha256"]:
            raise ValueError("results integrity failure")
        _validate_mapping(manifest["inputs"], keys)
        if manifest["completion"] != {"complete": True, "input_count": len(manifest["inputs"]),
                                      "result_count": len(keys)}:
            raise ValueError("incomplete manifest")
        allowed = {"results.jsonl", "result-schema.json", "manifest.json"}
        allowed.update(item["path"] for item in manifest["captures"].values())
        if set(names) != allowed:
            raise ValueError("unexpected or missing bundle member")
        return manifest
