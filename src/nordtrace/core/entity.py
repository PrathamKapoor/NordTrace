"""Entity resolution: deterministic identity matching + publication firewall.

Signals (deterministic, no LLM involvement):
  - organisation number contradiction  (foreign 9-digit orgnr in candidate text)
  - normalised name similarity        (Norwegian legal-form suffixes stripped properly)
  - website domain match
  - municipality / address overlap
  - industry overlap
  - known-alias set                   (historical names)

Verdicts:
  VERIFIED   - orgnr matches, or name+strong corroboration
  LIKELY     - strong name match + at least one corroborating signal
  AMBIGUOUS  - partial signals, no contradiction
  REJECTED   - contradictory identity (foreign orgnr, conflicting name+domain, etc.)

Rules enforced:
  - a candidate showing a foreign organisation number is always REJECTED
  - a candidate whose domain belongs to a *different verified company* is REJECTED
  - when signals are weak we prefer AMBIGUOUS (treated as "unknown") over wrong-company
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from nordtrace.core.models import CompanyIdentity, MatchVerdict

_LEGAL_SUFFIXES = {
    # actual legal-form codes, not geographic/descriptive words
    "as",
    "asa",
    "a s",
    "nuf",
    "ks",
    "da",
    "ans",
    "ba",
    "enybf",
    "se",
    "sf",
    "fkf",
    "iks",
    "ktrf",
    "stiftelse",
}
_SUFFIX_RE = re.compile(
    r"\b(" + "|".join(sorted(_LEGAL_SUFFIXES, key=len, reverse=True)) + r")\b", re.IGNORECASE
)


# Regexes used for normalization and orgnr extraction from free text.
_WS_RE = re.compile(r"[^0-9a-zæøåäö]+")
_ORGNR_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")
_NON_ORGNR_NINE = re.compile(r"\b(19|20)\d{7}\b|\b\d{4}[-. ]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def normalize_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation; keep semantic core."""
    if not name:
        return ""
    s = name.lower()
    s = s.replace("&", " og ").replace("+", " og ")
    s = _SUFFIX_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return " ".join(s.split())


def domain_of(url_or_host: str) -> str:
    if not url_or_host:
        return ""
    v = url_or_host
    if "://" not in v:
        v = "http://" + v
    host = (urlparse(v).hostname or "").lower().strip(".")
    return host


def registrable_domain(host: str) -> str:
    """crude but effective: last two labels (no PSL vendored for hackathon scale)."""
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def extract_orgnrs(text: str, exclude: Optional[str] = None) -> List[str]:
    """All 9-digit orgnr-looking tokens, excluding dates/phone-like patterns and `exclude`."""
    if not text:
        return []
    cleaned = _NON_ORGNR_NINE.sub(" ", text)
    found = _ORGNR_RE.findall(cleaned)
    return list(dict.fromkeys(n for n in found if n != exclude))


def name_similarity(a: str, b: str) -> float:
    """Similarity in [0,1]: token overlap + prefix containment on normalized names."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb) / max(len(ta), len(tb))
    # containment: "telenor norge" ⊆ "telenor" style relationships
    if na in nb or nb in na:
        overlap = max(overlap, 0.85)
    return overlap


@dataclass
class MatchSignals:
    orgnr_match: bool = False
    orgnr_contradiction: bool = False
    foreign_orgnr: Optional[str] = None
    name_similarity: float = 0.0
    domain_match: bool = False
    domain_conflict: bool = False
    municipality_match: bool = False
    industry_match: bool = False
    alias_match: bool = False


@dataclass
class MatchResult:
    verdict: str = MatchVerdict.AMBIGUOUS.value
    signals: MatchSignals = field(default_factory=MatchSignals)
    reason: str = ""
    score: float = 0.0


class EntityResolver:
    """Deterministic candidate-vs-target matcher."""

    def __init__(self, known_domains: Optional[Dict[str, str]] = None):
        # domain -> orgnr, populated as companies are verified (wrong-domain guard)
        self.known_domains: Dict[str, str] = dict(known_domains or {})

    def register_verified_domain(self, domain: str, org_number: str) -> None:
        if domain:
            self.known_domains[registrable_domain(domain)] = org_number

    def evaluate(
        self,
        target: CompanyIdentity,
        *,
        candidate_text: str = "",
        candidate_name: Optional[str] = None,
        candidate_orgnr: Optional[str] = None,
        candidate_url: Optional[str] = None,
        candidate_municipality: Optional[str] = None,
        candidate_industry: Optional[str] = None,
    ) -> MatchResult:
        sig = MatchSignals()

        # -- 1. Organisation-number contradictions dominate everything --------
        orgnrs_in_text = extract_orgnrs(candidate_text, exclude=target.organisation_number)
        if candidate_orgnr and candidate_orgnr != target.organisation_number:
            orgnrs_in_text.append(candidate_orgnr)
        if orgnrs_in_text:
            sig.orgnr_contradiction = True
            sig.foreign_orgnr = orgnrs_in_text[0]
            return MatchResult(
                verdict=MatchVerdict.REJECTED.value,
                signals=sig,
                reason=f"candidate carries foreign organisation number {orgnrs_in_text[0]}",
                score=-1.0,
            )
        if candidate_orgnr == target.organisation_number or target.organisation_number in (
            candidate_text or ""
        ):
            sig.orgnr_match = True

        # -- 2. Name similarity -------------------------------------------------
        cand_name = candidate_name or ""
        if not cand_name and candidate_text:
            cand_name = _guess_name_from_text(candidate_text, target)
        sig.name_similarity = name_similarity(target.legal_name, cand_name)

        # -- 3. Domain signals ---------------------------------------------------
        cand_host = domain_of(candidate_url) if candidate_url else ""
        tgt_host = domain_of(target.website) if target.website else ""
        if cand_host and tgt_host:
            if registrable_domain(cand_host) == registrable_domain(tgt_host):
                sig.domain_match = True
            else:
                # candidate domain already verified as belonging to a different company?
                owner = self.known_domains.get(registrable_domain(cand_host))
                if owner and owner != target.organisation_number:
                    sig.domain_conflict = True
        if cand_host:
            owner = self.known_domains.get(registrable_domain(cand_host))
            if owner and owner != target.organisation_number:
                sig.domain_conflict = True

        # -- 4. Corroboration signals -------------------------------------------
        if candidate_municipality and target.municipality:
            sig.municipality_match = normalize_name(candidate_municipality) == normalize_name(
                target.municipality
            )
        if candidate_industry and target.industry_code:
            sig.industry_match = str(candidate_industry).strip() == str(target.industry_code).strip()

        # -- 5. Verdict ------------------------------------------------------------
        return self._verdict(sig, target)

    def _verdict(self, sig: MatchSignals, target: CompanyIdentity) -> MatchResult:
        score = 0.0
        if sig.domain_conflict:
            return MatchResult(
                MatchVerdict.REJECTED.value, sig, "candidate domain belongs to a different company", -1.0
            )
        if sig.orgnr_match:
            return MatchResult(MatchVerdict.VERIFIED.value, sig, "organisation number match", 1.0)
        score += sig.name_similarity * 2.0
        corroboration = sum([sig.domain_match, sig.municipality_match, sig.industry_match, sig.alias_match])
        score += corroboration * 0.5

        if sig.name_similarity >= 0.9 and corroboration >= 1:
            return MatchResult(
                MatchVerdict.VERIFIED.value, sig, "strong name + corroboration", min(1.0, score / 3)
            )
        if sig.name_similarity >= 0.7 and corroboration >= 1:
            return MatchResult(MatchVerdict.LIKELY.value, sig, "name match + one corroboration", score / 3)
        if sig.name_similarity >= 0.95 and corroboration == 0:
            # Same name, nothing corroborating → could be another entity with same name
            return MatchResult(MatchVerdict.AMBIGUOUS.value, sig, "name match without corroboration", 0.3)
        if 0.4 <= sig.name_similarity < 0.7 and corroboration >= 2:
            return MatchResult(
                MatchVerdict.LIKELY.value, sig, "partial name + strong corroboration", score / 3
            )
        if sig.name_similarity < 0.35:
            return MatchResult(
                MatchVerdict.REJECTED.value, sig, f"name dissimilar to {target.legal_name!r}", 0.0
            )
        return MatchResult(MatchVerdict.AMBIGUOUS.value, sig, "insufficient signals", 0.2)


def _guess_name_from_text(text: str, target: CompanyIdentity) -> str:
    """Extract the most plausible company-name mention from text: prefer exact
    target-name occurrences, else a token window around 'AS'-like markers."""
    t = target.legal_name
    if t and t.lower() in (text or "").lower():
        return t
    m = re.search(r"([A-ZÆØÅ][\wÆØÅæøå&.\- ]{2,60}?)\s+(?:AS|ASA|AB|NUF|KS|DA|ANS)\b", text or "")
    if m:
        return m.group(1)
    return text[:80] if text else ""


class PublicationFirewall:
    """Publication gate: every candidate fact passes identity + evidence validation
    before entering the ledger as PUBLISHED. Rejections are recorded for the trace."""

    def __init__(self, resolver: Optional[EntityResolver] = None):
        self.resolver = resolver or EntityResolver()
        self.rejected: List[Dict] = []

    def evaluate_candidate(
        self,
        target: CompanyIdentity,
        *,
        candidate_text: str = "",
        candidate_name: Optional[str] = None,
        candidate_orgnr: Optional[str] = None,
        candidate_url: Optional[str] = None,
        candidate_municipality: Optional[str] = None,
        candidate_industry: Optional[str] = None,
    ) -> MatchResult:
        result = self.resolver.evaluate(
            target,
            candidate_text=candidate_text,
            candidate_name=candidate_name,
            candidate_orgnr=candidate_orgnr,
            candidate_url=candidate_url,
            candidate_municipality=candidate_municipality,
            candidate_industry=candidate_industry,
        )
        if result.verdict == MatchVerdict.REJECTED.value:
            self.rejected.append(
                {
                    "reason": result.reason,
                    "signals": {
                        "foreign_orgnr": result.signals.foreign_orgnr,
                        "name_similarity": round(result.signals.name_similarity, 3),
                        "candidate_name": candidate_name,
                        "candidate_url": candidate_url,
                    },
                }
            )
        return result

    def may_publish(self, result: MatchResult) -> bool:
        return result.verdict in (MatchVerdict.VERIFIED.value, MatchVerdict.LIKELY.value)
