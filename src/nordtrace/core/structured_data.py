"""Restricted literal Schema.org candidates, without JSON-LD processing or IO.

Returned locations are extraction diagnostics, NOT publication-support locators.
No context, script, reference or instruction in input is fetched or executed.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from nordtrace.core.orgnr import validate_orgnr

_CONTEXTS = {"https://schema.org", "https://schema.org/", "http://schema.org", "http://schema.org/"}
_TYPES = {"Organization", "Corporation"}
_ORG_LABELS = {"orgnr", "org.nr", "org.nr.", "organisasjonsnummer", "norwegian organisation number"}
MAX_SCRIPTS = 32
MAX_SCRIPT_CHARS = 65536
MAX_NODES = 128


def _check_nesting(raw: str) -> None:
    """Bound JSON container depth before decoding, ignoring string contents."""
    depth = 0
    quoted = False
    escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("JSON nesting capacity exceeded")
        elif char in "]}":
            depth -= 1


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _literal_type(value: Any, permitted: set[str]) -> bool:
    types = value if isinstance(value, list) else [value]
    return bool(types) and all(isinstance(item, str) and item in permitted for item in types)


def _nodes(document: Any) -> list[tuple[dict, str, Any]]:
    roots = list(enumerate(document)) if isinstance(document, list) else [(None, document)]
    result = []
    for index, root in roots:
        if not isinstance(root, dict):
            raise ValueError("unsupported JSON root")
        pointer = "" if index is None else f"/{index}"
        context = root.get("@context")
        if context is not None and (not isinstance(context, str) or context not in _CONTEXTS):
            raise ValueError("unsupported root literal context")
        if "@type" in root:
            result.append((root, pointer, context))
        if "@graph" in root:
            graph = root["@graph"]
            if not isinstance(graph, list):
                raise ValueError("graph must be a literal array")
            for child_index, node in enumerate(graph):
                if not isinstance(node, dict):
                    raise ValueError("graph item must be an object")
                result.append((node, f"{pointer}/@graph/{child_index}", context))
        if len(result) > MAX_NODES or len(roots) > MAX_NODES:
            raise ValueError("structured node capacity exceeded")
    return result


def _identity_paths(node: dict, org: str, legal_name: str, pointer: str) -> tuple[str, list[str]]:
    name_key = "legalName" if "legalName" in node else "name"
    name = node.get(name_key)
    if (not isinstance(name, str) or " ".join(name.split()).casefold()
            != " ".join(legal_name.split()).casefold() or not legal_name.strip()):
        raise ValueError("exact legal name not established")
    identifiers = []
    if "vatID" in node:
        vat = node["vatID"]
        if not isinstance(vat, str) or not re.match(r"^NO\s*[0-9]", vat.strip(), re.I):
            raise ValueError("Norwegian VAT country prefix missing")
        parsed = validate_orgnr(vat)
        if not parsed.valid or parsed.value != org:
            raise ValueError("VAT subject differs or is invalid")
        identifiers.append(pointer + "/vatID")
    values = node.get("identifier", [])
    values = values if isinstance(values, list) else [values]
    if len(values) > 16:
        raise ValueError("identifier capacity exceeded")
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            continue  # Generic strings/numbers are not Norwegian identifier evidence.
        label = item.get("propertyID")
        if not isinstance(label, str) or " ".join(label.split()).casefold() not in _ORG_LABELS:
            continue
        if ("@context" in item and (
                not isinstance(item["@context"], str) or item["@context"] not in _CONTEXTS)
                or not _literal_type(item.get("@type"), {"PropertyValue"})):
            raise ValueError("unsupported identifier vocabulary/type")
        value = item.get("value")
        identifier_org = validate_orgnr(value) if isinstance(value, str) else None
        if identifier_org is None or not identifier_org.valid or identifier_org.value != org:
            raise ValueError("labelled organisation subject differs or is invalid")
        suffix = f"/{index}" if isinstance(node.get("identifier"), list) else ""
        identifiers.append(pointer + "/identifier" + suffix + "/value")
    if not identifiers:
        raise ValueError("explicit Norwegian identifier not established")
    return pointer + "/" + name_key, identifiers


def organization_descriptions(
    soup: BeautifulSoup, org_number: str, legal_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find bounded top-level/graph literals; preserve competing assertions.

    Context aliases, remote contexts, nested references, TextObjects and expanded
    IRIs are deliberately unsupported. A candidate does not prove source rights,
    website attachment, statement truth, scope or official identity provenance.
    """
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    scripts = soup.find_all("script")
    if len(scripts) > MAX_SCRIPTS:
        return [], [{"reason": "structured script capacity exceeded"}]
    org = validate_orgnr(org_number)
    if not org.valid:
        return [], [{"reason": "invalid target organisation number"}]
    for script_index, script in enumerate(scripts):
        if str(script.get("type", "")).strip().lower() != "application/ld+json":
            continue
        try:
            if script.has_attr("src"):
                raise ValueError("external script is not embedded data")
            raw = script.string
            if raw is None or len(raw) > MAX_SCRIPT_CHARS:
                raise ValueError("structured script missing or too large")
            _check_nesting(str(raw))
            document = json.loads(str(raw), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
            nodes = _nodes(document)
        except (ValueError, RecursionError) as error:
            rejected.append({"script_index": script_index,
                             "reason": type(error).__name__ + ": " + str(error)})
            continue
        for node, pointer, inherited_context in nodes:
            try:
                context = node.get("@context", inherited_context)
                if not isinstance(context, str) or context not in _CONTEXTS:
                    raise ValueError("unsupported literal context")
                if not _literal_type(node.get("@type"), _TYPES):
                    raise ValueError("unsupported literal organization type")
                name_pointer, identifier_pointers = _identity_paths(node, org.value, legal_name, pointer)
                description = node.get("description")
                if (not isinstance(description, str) or not description.strip() or len(description) > 4000
                        or any(ord(char) < 32 and char not in "\t\r\n" for char in description)):
                    raise ValueError("description must be a bounded nonempty literal text")
                if any(0xD800 <= ord(char) <= 0xDFFF for char in description):
                    raise ValueError("description contains invalid Unicode scalar")
                candidates.append({
                    "version": "schema-org-literal-v1", "script_index": script_index,
                    "pointer": pointer + "/description", "raw_value": description,
                    "name_pointer": name_pointer, "identifier_pointers": identifier_pointers,
                })
            except ValueError as error:
                rejected.append({"script_index": script_index, "pointer": pointer, "reason": str(error)})
    return candidates, rejected
