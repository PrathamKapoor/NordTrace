"""Evidence-grounded synthesis: summary generated ONLY from verified facts.

Deterministic template builder; no model is invoked.
Unknowns describe verification outcomes, never presumed absence of business facts.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional

from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import ChangeRecord, CompanyIdentity, Coverage, Fact


def build_summary(
    identity: CompanyIdentity,
    ledger: FactLedger,
    coverage: Coverage,
    changes: List[ChangeRecord],
    *, previous_run_id: Optional[str] = None,
) -> str:
    parts: List[str] = []
    org = identity.organisation_number
    conflicts = ledger.conflicting_facts(org)

    # 1. what the company does
    desc = _latest(ledger, org, "business_description", "description")
    verified_name = _latest(ledger, org, "identity", "legal_name")
    if verified_name is None:
        parts.append(f"Organisation {org} (legal name unresolved)")
    else:
        parts.append(f"{verified_name.value} (orgnr {org}) {_cite(verified_name)}")
    if desc is not None and getattr(desc, "value", None):
        parts.append(f"What it does: {desc.value} {_cite(desc)}")
    else:
        parts.append(f"What it does: {_availability_text(coverage.get('business_description'))}.")

    # 2. main business areas
    ind_f = _latest(ledger, org, "identity", "industry_description")
    ind = ind_f.value if ind_f is not None else None
    ind_code = _latest(ledger, org, "identity", "industry_code")
    if ind_f is not None and ind:
        parts.append(f"Industry: {ind} {_cite(ind_f)}"
                     + (f" ({ind_code.value} {_cite(ind_code)})" if ind_code is not None else ""))
    else:
        parts.append("Industry: not verified in this run.")

    # 3. scale / financials — only verified facts
    rev = _latest(ledger, org, "financials", "revenue")
    res = _latest(ledger, org, "financials", "operating_result")
    ar = _latest(ledger, org, "financials", "annual_result")
    eq = _latest(ledger, org, "financials", "equity")
    emp = _latest(ledger, org, "identity", "employee_count")
    financials = [(label, fact) for label, fact in (
        ("revenue", rev), ("operating result", res), ("annual result", ar), ("equity", eq),
    ) if fact is not None]
    fin_parts = []
    for label, fact in financials:
        amount = _financial_text(fact)
        if amount is not None:
            fin_parts.append(f"{label} {amount} {_cite(fact)}")
    if fin_parts:
        parts.append("Financials: " + "; ".join(fin_parts) + ".")
        if len(fin_parts) != len(financials):
            parts.append("Some monetary observations could not be safely rendered and are withheld.")
    elif financials:
        parts.append("Financials: monetary values could not be safely rendered.")
    else:
        parts.append(f"Financials: {_availability_text(coverage.get('financials'))}.")
    if emp:
        parts.append(f"Registered employees: {_fmt(emp)}. {_cite(emp)}")

    branches = [fact for fact in ledger.published_facts(org)
                if fact.category == "locations" and fact.field == "branch"
                and isinstance(fact.value, dict) and fact.value.get("parent_orgnr") == org
                and isinstance(fact.value.get("name"), str) and fact.value.get("name")
                and fact.value.get("orgnr") == fact.item_key and fact.item_key]
    if branches:
        items = []
        for branch in sorted(branches, key=lambda fact: fact.item_key or "")[:3]:
            value = branch.value
            if not isinstance(value, dict):
                continue
            text = f"{value['name']} (orgnr {value['orgnr']})"
            address = " ".join(part for key in ("physical_address", "postal_code", "postal_area")
                               if isinstance(part := value.get(key), str) and part)
            if address:
                text += f", {address}"
            for key, label in (("closure_date", "closed"), ("deleted_date", "deleted")):
                if value.get(key):
                    text += f", {label} {value[key]}"
            items.append(f"{text} {_cite(branch)}")
        parts.append("Registered subunits observed: " + "; ".join(items) + ".")
        if len(branches) > 3:
            parts.append("Additional verified subunit observations appear in the profile.")

    # 4. people/roles
    roles = _role_facts(ledger, org)
    if roles:
        role_str = ", ".join(f"{fact.value['name']} ({fact.value.get('role', fact.field)}) {_cite(fact)}"
                             for fact in roles[:5] if isinstance(fact.value, dict))
        parts.append(f"Key roles: {role_str}.")
    else:
        parts.append(f"Key roles: {_availability_text(coverage.get('leadership'))}.")

    # 5. recent activity
    acts = _activity_facts(ledger, org)
    if acts:
        act_str = "; ".join(acts[:3])
        parts.append(f"Activity observations: {act_str}.")
    else:
        parts.append(f"Recent activity: {_availability_text(coverage.get('recent_activity'))}.")

    # 6. meaningful changes
    sig = [c for c in changes if c.change_type in ("CHANGED", "RETRACTED")]
    new = [c for c in changes if c.change_type == "NEW"]
    if previous_run_id is None:
        if ledger.published_facts(org):
            parts.append("Changes: first verified observations; no earlier run is available for comparison.")
        else:
            parts.append("Changes: no verified observations available for comparison.")
    elif sig:
        ch_str = "; ".join(_change_text(c) for c in sig[:4])
        parts.append(f"Changes in verified observations: {ch_str}.")
    else:
        parts.append("Changes: no material changes established among comparable verified observations.")
    if previous_run_id is not None and new:
        new_str = "; ".join(_change_text(c) for c in new[:4])
        parts.append(f"Newly verified observations: {new_str}.")

    # 7. unknowns
    unknowns = unknowns_for_coverage(coverage)
    if unknowns:
        parts.append("Unknowns: " + "; ".join(unknowns) + ".")
    if conflicts:
        parts.append("Some sources disagree. Disputed values are withheld; their evidence remains available.")

    return " ".join(parts)


def _latest(ledger: FactLedger, org: str, category: str, field: str) -> Optional[Fact]:
    """Latest fact for a slot regardless of reporting_period (latest run wins)."""
    cur = ledger.current_values(org)
    best = None
    for f in cur.values():
        if f.category == category and f.field == field:
            if best is None or (f.reporting_period or "") > (best.reporting_period or ""):
                best = f
    return best


def _cite(fact: Fact) -> str:
    return f"[{fact.claim_id}]"


def _fmt(fact: Fact) -> str:
    v = fact.value
    if isinstance(v, (int, float)):
        s = f"{v:,.0f}".replace(",", " ")
        if fact.currency:
            return f"{fact.currency} {s}"
        return s
    return str(v)


def _financial_text(fact: Fact) -> Optional[str]:
    """Render existing claim values without rounding, scaling or scope inference."""
    scopes = {"legal_entity": "legal entity", "group": "group", "branch": "branch", "brand": "brand"}
    if (not fact.currency or len(fact.currency) != 3 or not fact.currency.isascii()
            or not fact.currency.isalpha() or not fact.currency.isupper()
            or not fact.unit or not fact.unit.strip()
            or not fact.reporting_period or not fact.reporting_period.strip()
            or fact.subject_scope not in scopes
            or isinstance(fact.value, bool) or not isinstance(fact.value, (int, float, Decimal, str))):
        return None
    try:
        value = Decimal(str(fact.value))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    # Bound fixed-point expansion (e.g. 1e-999999) without silently rounding it.
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or max(1, value.adjusted() + 1) + max(0, -exponent) > 256:
        return None
    number = format(value, ",f").replace(",", " ")
    return (f"{fact.currency} {number} (unit: {fact.unit}; period: {fact.reporting_period}; "
            f"{scopes[fact.subject_scope]})")


def _change_text(change: ChangeRecord) -> str:
    if change.category == "financials":
        # ChangeRecord has no old/new currency or unit. Never print an amount
        # whose qualifiers would be invented or borrowed from the current fact.
        text = (f"{change.field}: {change.change_type.lower()} monetary observation; "
                "inspect qualified evidence")
    elif change.change_type == "NEW":
        text = f"{change.field}: {_short(change.current_value)}"
    elif change.previous_value is not None:
        text = f"{change.field}: {_short(change.previous_value)} → {_short(change.current_value)}"
    else:
        text = f"{change.field}: new ({_short(change.current_value)})"
    return text + (f" [{change.claim_id}]" if change.claim_id else "")


def _role_facts(ledger: FactLedger, org: str) -> List[Fact]:
    cur = ledger.current_values(org)
    out = []
    for _, f in sorted(cur.items()):
        if f.category == "leadership" and isinstance(f.value, dict) and f.value.get("name"):
            out.append(f)
    return out


def _activity_facts(ledger: FactLedger, org: str) -> List[str]:
    cur = ledger.current_values(org)
    out = []
    for _, f in sorted(cur.items()):
        if f.category == "recent_activity":
            v = f.value
            if isinstance(v, dict):
                date = v.get("date") or v.get("registered") or ""
                out.append(f"{v.get('event', f.field)}" + (f" ({date})" if date else "") + f" {_cite(f)}")
            else:
                out.append(str(v) + f" {_cite(f)}")
    return out


def _short(v) -> str:
    s = str(v)
    return s[:40] + ("…" if len(s) > 40 else "")


def _availability_text(state: str) -> str:
    return {
        "not_found": "not verified in this run",
        "not_available": "no supported observation available",
        "blocked": "verification blocked",
        "ambiguous": "evidence unresolved or conflicting",
        "failed": "verification failed",
        "not_applicable": "not applicable",
    }.get(state, "not verified in this run")


def unknowns_for_coverage(coverage: Coverage) -> List[str]:
    """One vocabulary for final canonical unknowns and the deterministic brief."""
    labels = {
        "financials": "Annual accounts",
        "leadership": "Board/management roles",
        "products_services": "Products/services",
        "jobs": "Job postings",
        "recent_activity": "Recent public activity",
        "business_description": "Business description",
        "locations": "Location details",
        "website": "Company website",
    }
    return [f"{label} ({_availability_text(coverage.get(category))})"
            for category, label in labels.items() if coverage.get(category) != "found"]
