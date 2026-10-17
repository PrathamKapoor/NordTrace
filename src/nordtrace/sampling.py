"""Offline, reproducible sample selection; source metadata is never verified fact."""

from __future__ import annotations

import gzip
import hashlib
import heapq
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from nordtrace.core.contracts import write_bytes_atomic, write_json_atomic
from nordtrace.core.models import utcnow
from nordtrace.core.orgnr import validate_orgnr

PUBLIC_SHA256 = "1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384"
PUBLIC_UNCOMPRESSED_SHA256 = "b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838"
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _rank(seed: str, purpose: str, value: str) -> int:
    return int.from_bytes(hashlib.sha256(_json([seed, purpose, value])).digest(), "big")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            total += len(block)
            if total > MAX_COMPRESSED_BYTES:
                raise ValueError("compressed universe capacity exceeded")
            digest.update(block)
    return digest.hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _stratum(row: dict) -> str:
    employees = row.get("employees")
    band = ("unknown" if type(employees) is not int or employees < 0 else "metadata_zero" if employees == 0
            else "1_9" if employees < 10 else "10_49" if employees < 50 else "50_plus")
    website = ("recorded" if isinstance(row.get("website"), str) and row["website"].strip()
               else "none_recorded")
    label = str(row.get("industry_label") or "").casefold()
    code = str(row.get("industry_code") or "")
    industry = ("holding_metadata" if "holding" in label else "64_66_metadata"
                if code[:2] in ("64", "65", "66") else "other")
    form = "AS_metadata" if row.get("legal_form") == "AS" else "other_form"
    return "|".join((form, band, website, industry))


def _rows(path: Path, maximum: int, digest: Any) -> Iterator[tuple[int, str, str, dict]]:
    total = 0
    with gzip.open(path, "rb") as source:
        line_number = 0
        while line := source.readline(MAX_LINE_BYTES + 1):
            line_number += 1
            total += len(line)
            if len(line) > MAX_LINE_BYTES or total > maximum:
                raise ValueError("uncompressed universe capacity exceeded")
            digest.update(line)
            if not line.strip():
                continue
            try:
                row = json.loads(line.decode("utf-8-sig" if line_number == 1 else "utf-8"),
                                 object_pairs_hook=_object, parse_constant=_constant, parse_float=_number)
                if not isinstance(row, dict) or not isinstance(row.get("organisation_number"), str):
                    raise ValueError("missing string organisation_number")
                org = validate_orgnr(row["organisation_number"])
                if not org.valid:
                    raise ValueError("invalid organisation number")
                _json(row)  # Reject unpaired surrogate metadata before any selection/export.
            except (ValueError, RecursionError) as error:
                raise ValueError(f"invalid universe JSONL line {line_number}") from error
            yield line_number, org.value, _stratum(row), row


def sample_universe(
    source: str | Path, output: str | Path, *, seed: str, development_size: int = 100,
    held_out_size: int = 100, expected_sha256: str = PUBLIC_SHA256,
    expected_uncompressed_sha256: str = PUBLIC_UNCOMPRESSED_SHA256,
    max_uncompressed_bytes: int = 256 * 1024 * 1024,
) -> dict:
    """Balanced stratified SHA-256 selection, without replacement or live acquisition.

    Two streaming passes retain IDs plus only the requested selected rows. Rare
    strata are oversampled deliberately; these are not population accuracy weights.
    """
    source, destination = Path(source), Path(output)
    if os.path.lexists(destination):
        raise FileExistsError(f"sample destination already exists: {destination}")
    if (not isinstance(seed, str) or not seed
            or any(type(n) is not int or n < 0 for n in (development_size, held_out_size))
            or development_size + held_out_size == 0
            or type(max_uncompressed_bytes) is not int or max_uncompressed_bytes <= 0):
        raise ValueError("nonempty seed, nonnegative split sizes and positive capacity are required")
    compressed_hash = _file_hash(source)
    if compressed_hash != expected_sha256.lower():
        raise ValueError("compressed universe hash differs from expected source")
    population: Counter[str] = Counter()
    partitions: dict[str, Counter[str]] = {"development": Counter(), "held_out": Counter()}
    seen = set()
    first_digest = hashlib.sha256()
    for _, org, key, _ in _rows(source, max_uncompressed_bytes, first_digest):
        if org in seen:
            raise ValueError("duplicate organisation number in universe")
        seen.add(org)
        population[key] += 1
        split = "development" if _rank(seed, "partition", org) % 2 == 0 else "held_out"
        partitions[split][key] += 1
    count = len(seen)
    del seen
    if first_digest.hexdigest() != expected_uncompressed_sha256.lower():
        raise ValueError("uncompressed universe hash differs from expected source")
    if development_size + held_out_size > count:
        raise ValueError("requested disjoint samples exceed universe population")
    keys = sorted(population, key=lambda key: (_rank(seed, "stratum-order", key), key))
    allocation: dict[str, Counter[str]] = {"development": Counter(), "held_out": Counter()}
    remaining = {"development": development_size, "held_out": held_out_size}
    for split in allocation:
        if remaining[split] > sum(partitions[split].values()):
            raise ValueError("requested sample exceeds fixed partition population")
        while remaining[split]:
            for key in keys:
                if remaining[split] and allocation[split][key] < partitions[split][key]:
                    allocation[split][key] += 1
                    remaining[split] -= 1
    heaps: dict[tuple[str, str], list] = {(split, key): [] for split in allocation for key in keys}
    second_digest = hashlib.sha256()
    for line_number, org, key, row in _rows(source, max_uncompressed_bytes, second_digest):
        if key not in population:
            raise ValueError("universe changed during sampling")
        split = "development" if _rank(seed, "partition", org) % 2 == 0 else "held_out"
        capacity = allocation[split][key]
        if not capacity:
            continue
        item = (-_rank(seed, "selection", org), org, line_number, row)
        heap = heaps[split, key]
        if len(heap) < capacity:
            heapq.heappush(heap, item)
        else:
            heapq.heappushpop(heap, item)
    if second_digest.digest() != first_digest.digest() or _file_hash(source) != compressed_hash:
        raise ValueError("universe changed during sampling")
    selected: dict[str, list] = {"development": [], "held_out": []}
    for (split, _key), heap in heaps.items():
        selected[split].extend(sorted(heap, key=lambda item: (-item[0], item[1])))
    if {item[1] for item in selected["development"]} & {item[1] for item in selected["held_out"]}:
        raise ValueError("split overlap")
    manifest: dict[str, Any] = {
        "format": "nordtrace-samples-v1", "algorithm": "balanced-strata-sha256-v1", "seed": seed,
        "created_at": utcnow().isoformat(), "source_file": source.name,
        "source_sha256": compressed_hash, "source_uncompressed_sha256": first_digest.hexdigest(),
        "source_record_count": count, "source_cutoff": None,
        "source_url": ("https://www.builderr.ai/signalpost-company-universe-2025.jsonl.gz"
                       if compressed_hash == PUBLIC_SHA256 else None),
        "metadata_only": True, "independent_accuracy": "not_measured",
        "partition_policy": "SHA256(seed, partition, normalized orgnr) parity, stable across sample sizes",
        "partition_populations": {split: sum(values.values()) for split, values in partitions.items()},
        "limitations": ["Source fields are selection metadata, not current verified business facts",
                        "Balanced rare-stratum oversampling is not a population recall estimate",
                        "Singleton strata cannot occur in both disjoint samples",
                        "Official supplied evaluation batch and frozen identity snapshot are separate"],
        "strata": [{"key": key, "population": population[key],
                    "partition_populations": {split: partitions[split][key] for split in partitions},
                    **{split: allocation[split][key] for split in allocation}} for key in sorted(keys)],
        "splits": {}, "completion": {"complete": True},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(destination.name + ".lock")
    with lock.open("x", encoding="utf-8") as lock_handle:
        try:
            if os.path.lexists(destination):
                raise FileExistsError(f"sample destination already exists: {destination}")
            with tempfile.TemporaryDirectory(prefix=destination.name + ".", suffix=".partial",
                                             dir=destination.parent) as directory:
                staging = Path(directory).resolve()
                if staging.parent != destination.parent.resolve():
                    raise ValueError("sample staging directory outside intended parent")
                for split, items in selected.items():
                    items.sort(key=lambda item: (_rank(seed, split + "-output", item[1]), item[1]))
                    body = b"".join(_json(item[3]) + b"\n" for item in items)
                    path = split + ".jsonl"
                    write_bytes_atomic(staging / path, body)
                    manifest["splits"][split] = {
                        "path": path, "count": len(items), "sha256": hashlib.sha256(body).hexdigest(),
                        "organisation_numbers": [item[1] for item in items],
                        "source_lines": [item[2] for item in items],
                        "unrepresented_strata": [key for key in keys if not allocation[split][key]],
                    }
                write_json_atomic(staging / "manifest.json", manifest)
                # Reserve the final namespace exclusively on every platform. Renaming
                # a directory can replace a concurrent empty directory on POSIX.
                destination.mkdir()
                for name in ("development.jsonl", "held_out.jsonl", "manifest.json"):
                    os.link(staging / name, destination / name)
        finally:
            # Only our exclusively created lock is retired; existing output is never deleted.
            lock_handle.close()  # Windows cannot unlink an open lock file.
            lock.unlink()
    return manifest
