"""Entity resolution: deterministic identity matching + publication firewall.

Signals (deterministic, no LLM involvement):
  - organisation number contradiction (explicit/labelled subject identifier)
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
  - contradictory subject identifiers reject before positive identity shortcuts
  - incidental numbers and explicitly labelled customer mentions are not subject IDs
  - independently identified legal subjects may share one registrable domain
  - when signals are weak we prefer AMBIGUOUS (treated as "unknown") over wrong-company
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

import tldextract

from nordtrace.core.models import CompanyIdentity, MatchVerdict
from nordtrace.core.orgnr import normalize_orgnr, validate_orgnr

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
_ORGNR_RE = re.compile(r"(?<![0-9])([0-9]{9}|[0-9]{3}(?:[\s.\-][0-9]{3}){2})(?![0-9])")
_LABELLED_ID = re.compile(
    r"(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|vat(?:\s*(?:id|number))?)"
    r"\s*[:#]?\s*(?:NO\s*)?([0-9]{9}|[0-9]{3}(?:[\s.\-][0-9]{3}){2})(?![0-9])", re.I
)
_MENTION_ROLE = re.compile(r"\b(customer|client|kunde|supplier|leverandør)\b", re.I)
_PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


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
    """Registrable hostname using bundled PSL data, with all network fetching disabled."""
    if not host:
        return ""
    if "://" in host or "/" in host:
        raise ValueError("registrable_domain requires a hostname")
    parsed = _PSL(host.lower().rstrip("."))
    return parsed.top_domain_under_public_suffix or host.lower().rstrip(".")


def extract_orgnrs(text: str, exclude: Optional[str] = None) -> List[str]:
    """Checksum-valid whole/grouped identifier candidates; context is evaluated separately."""
    if not text:
        return []
    found = _ORGNR_RE.findall(text)
    values = [normalize_orgnr(number) for number in found if validate_orgnr(number).valid]
    return list(dict.fromkeys(number for number in values if number != exclude))


def subject_orgnrs(text: str) -> List[str]:
    """Conservative labelled subject IDs; explicitly marked customer mentions are data.

    This deliberately leaves unclassified mentions unresolved rather than treating
    arbitrary financial/telephone digits as document identity.
    """
    found = []
    for match in _LABELLED_ID.finditer(text):
        context = re.split(r"[.!?;\n]", text[max(0, match.start() - 120):match.start()])[-1]
        if _MENTION_ROLE.search(context):
            continue
        parsed = validate_orgnr(match[1])
        if parsed.valid:
            found.append(parsed.value)
    return list(dict.fromkeys(found))


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
    if ta <= tb or tb <= ta:
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
        self.known_domains: Dict[str, set[str]] = {
            domain: {org} for domain, org in (known_domains or {}).items()
        }

    def register_verified_domain(self, domain: str, org_number: str) -> None:
        if domain:
            self.known_domains.setdefault(registrable_domain(domain_of(domain)), set()).add(org_number)

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
        subject_ids = subject_orgnrs(candidate_text)
        explicit_orgnr = normalize_orgnr(candidate_orgnr) if candidate_orgnr else None
        orgnrs_in_text = [number for number in subject_ids if number != target.organisation_number]
        if explicit_orgnr and explicit_orgnr != target.organisation_number:
            orgnrs_in_text.append(explicit_orgnr)
        if orgnrs_in_text:
            sig.orgnr_contradiction = True
            sig.foreign_orgnr = orgnrs_in_text[0]
            return MatchResult(
                verdict=MatchVerdict.REJECTED.value,
                signals=sig,
                reason=f"candidate carries foreign organisation number {orgnrs_in_text[0]}",
                score=-1.0,
            )
        if explicit_orgnr == target.organisation_number or target.organisation_number in subject_ids:
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
                if owner and target.organisation_number not in owner and not sig.orgnr_match:
                    sig.domain_conflict = True
        if cand_host:
            owner = self.known_domains.get(registrable_domain(cand_host))
            if owner and target.organisation_number not in owner and not sig.orgnr_match:
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
