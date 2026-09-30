"""Evidence-grounded synthesis: summary generated ONLY from verified facts.

Deterministic template builder; optional LLM polish behind strict grounding.
Unknowns are listed explicitly ("Not publicly available") instead of guessed.
"""
from __future__ import annotations

from typing import List, Optional

from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import ChangeRecord, CompanyIdentity, Coverage, Fact, FactStatus


def build_summary(
    identity: CompanyIdentity,
    ledger: FactLedger,
    coverage: Coverage,
    changes: List[ChangeRecord],
) -> str:
    parts: List[str] = []
    org = identity.organisation_number

    # 1. what the company does
    desc = _latest(ledger, org, "business_description", "description")
    parts.append(f"{identity.legal_name} (orgnr {org})")
    if desc is not None and getattr(desc, "value", None):
        parts.append(f"What it does: {desc.value}")
    elif isinstance(desc, str):
        parts.append(f"What it does: {desc}")
    else:
        parts.append("What it does: business description not available from permitted sources.")

    # 2. main business areas
    ind_f = _latest(ledger, org, "identity", "industry_description")
    ind = (ind_f.value if ind_f is not None and getattr(ind_f, "value", None) else None) or identity.industry_description
    if ind:
        parts.append(f"Industry: {ind}"
                     + (f" ({identity.industry_code})" if identity.industry_code else ""))
    else:
        parts.append("Industry: not available.")

    # 3. scale / financials — only verified facts
    rev = _latest(ledger, org, "financials", "revenue")
    res = _latest(ledger, org, "financials", "operating_result")
    ar = _latest(ledger, org, "financials", "annual_result")
    eq = _latest(ledger, org, "financials", "equity")
    emp = _latest(ledger, org, "identity", "employee_count")
    if rev or res or ar or eq:
        fin_parts = []
        if rev:
            fin_parts.append(f"revenue {_fmt(rev)}")
        if res:
            fin_parts.append(f"operating result {_fmt(res)}")
        if ar:
            fin_parts.append(f"annual result {_fmt(ar)}")
        if eq:
            fin_parts.append(f"equity {_fmt(eq)}")
        period = rev.reporting_period if rev else None
        parts.append(f"Financials ({period or 'latest reported'}): " + ", ".join(fin_parts) + ".")
    else:
        parts.append("Financials: not publicly available via permitted sources.")
    if emp:
        parts.append(f"Registered employees: {_fmt(emp)}.")

    # 4. people/roles
    roles = _role_facts(ledger, org)
    if roles:
        role_str = ", ".join(f"{name} ({role})" for role, name in roles[:5])
        parts.append(f"Key roles: {role_str}.")
    else:
        parts.append("Key roles: not available from registry roles data.")

    # 5. recent activity
    acts = _activity_facts(ledger, org)
    if acts:
        act_str = "; ".join(acts[:3])
        parts.append(f"Recent registry activity: {act_str}.")
    else:
        parts.append("Recent activity: no dated public events found.")

    # 6. meaningful changes
    sig = [c for c in changes if c.change_type in ("CHANGED", "NEW", "RETRACTED")]
    if sig:
        ch_str = "; ".join(
            f"{c.field}: {_short(c.previous_value)} → {_short(c.current_value)}" if c.previous_value is not None
            else f"{c.field}: new ({_short(c.current_value)})"
            for c in sig[:4]
        )
        parts.append(f"Changes since previous run: {ch_str}.")
    else:
        parts.append("Changes: first research run or no changes detected.")

    # 7. unknowns
    unknowns = _unknown_list(coverage)
    if unknowns:
        parts.append("Unknowns: " + "; ".join(unknowns) + ".")

    return " ".join(parts)


def _latest(ledger: FactLedger, org: str, category: str, field: str) -> Optional[Fact]:
    """Latest fact for a slot regardless of reporting_period (latest run wins)."""
    cur = ledger.current_values(org)
    best = None
    prefix = f"{category}|{field}|"
    for k, f in cur.items():
        if k.startswith(prefix):
            if best is None or (f.reporting_period or "") > (best.reporting_period or ""):
                best = f
    return best


def _fmt(fact: Fact) -> str:
    v = fact.value
    if isinstance(v, (int, float)):
        s = f"{v:,.0f}".replace(",", " ")
        if fact.currency:
            return f"{fact.currency} {s}"
        return s
    return str(v)


def _role_facts(ledger: FactLedger, org: str) -> List[tuple]:
    cur = ledger.current_values(org)
    out = []
    for k, f in sorted(cur.items()):
        if f.category == "leadership" and isinstance(f.value, dict) and f.value.get("name"):
            role = f.value.get("role", k.split("|")[1])
            out.append((role, f.value["name"]))
    return out


def _activity_facts(ledger: FactLedger, org: str) -> List[str]:
    cur = ledger.current_values(org)
    out = []
    for k, f in sorted(cur.items()):
        if f.category == "recent_activity":
            v = f.value
            if isinstance(v, dict):
                date = v.get("date") or v.get("registered") or ""
                out.append(f"{v.get('event', k.split('|')[1])}" + (f" ({date})" if date else ""))
            else:
                out.append(str(v)[:80])
    return out


def _short(v) -> str:
    s = str(v)
    return s[:40] + ("…" if len(s) > 40 else "")


def _unknown_list(coverage: Coverage) -> List[str]:
    labels = {
        "financials": "annual accounts not publicly available",
        "leadership": "board/management roles not available",
        "products_services": "products/services sections not available",
        "jobs": "no job postings found",
        "recent_activity": "no dated public events found",
        "business_description": "business description not available",
        "locations": "location details not available",
    }
    return [labels[cat] for cat in labels if coverage.get(cat) in ("not_available", "not_found", "blocked")]
