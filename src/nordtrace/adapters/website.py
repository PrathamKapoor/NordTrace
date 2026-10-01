"""Website discovery + focused crawler.

Pipeline: registry hjemmeside → validated domain → page classification →
focused crawl (about/contact/products/careers/news priority) → entity
verification of each page → facts (description, contact, locations, careers).

Security: robots respected, SSRF-guarded via gateway, page-count and size
limits, crawled content treated as UNTRUSTED DATA (never instructions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.entity import EntityResolver, MatchResult, normalize_name, registrable_domain
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    MatchVerdict,
    SourceRecord,
    SourceType,
    utcnow,
)
from nordtrace.core.request_gateway import RequestGateway

# Page classification ---------------------------------------------------------

_PRIORITY_PATHS = [
    # keyword in first 2 path segments, checked in priority order
    (("jobb", "karriere", "careers", "jobs", "vacancies", "ledige-stillinger"), "CAREERS", 75),
    (("presse", "media", "news", "nyheter", "aktuelt", "presserom"), "NEWS", 70),
    (("ledelse", "management", "styret", "board", "governance"), "LEADERSHIP", 65),
    (("investor", "finans", "rapporter", "reports", "ir"), "FINANCIAL", 70),
    (("kontakt", "contact"), "CONTACT", 75),
    (("produkter", "products"), "PRODUCT", 80),
    (("tjenester", "services", "losninger", "solutions"), "SERVICE", 80),
    (("om-oss", "om", "about", "selskapet", "company", "histoire"), "ABOUT", 85),
]

_JUNK_RE = re.compile(
    r"/(privacy|cookies?|gdpr|terms|legal|imprint|wp-admin|wp-content|wp-includes|"
    r"feed|xmlrpc|login|cart|checkout|category|tag|author|page/\d+)"
    r"|\.((css|js|jpg|jpeg|png|gif|svg|webp|ico|woff2?|ttf|mp4|zip)(\?.*)?)$", re.IGNORECASE
)


def classify_url(url: str) -> Tuple[str, int]:
    """(page_type, priority) from path keywords in the first two segments."""
    path = (urlsplit(url).path or "/").lower().strip("/")
    if path == "":
        return "HOME", 60
    if _JUNK_RE.search("/" + path):
        return "OTHER", 0
    segments = [s for s in path.split("/") if s][:2]
    for keywords, ptype, prio in _PRIORITY_PATHS:
        for seg in segments:
            if seg in keywords:
                return ptype, prio
            # compound segments like 'jobb-i-telenor' or 'om-oss'
            parts = re.split(r"[-_]", seg)
            if any(k in parts for k in keywords):
                return ptype, prio
            # prefix matches like 'jobbitelenor'
            if any(seg.startswith(k) and len(seg) <= len(k) + 12 for k in keywords):
                return ptype, prio
    return "OTHER", 20

@dataclass
class CrawledPage:
    url: str
    page_type: str
    title: Optional[str]
    text: str
    source: SourceRecord
    links: List[str]
    pdf_links: List[str]


class WebsiteAdapter:
    """Discovers + crawls the company's own website (Tier 1)."""

    source_type = SourceType.COMPANY_WEBSITE.value
    authority_tier = 1

    def __init__(self, gateway: RequestGateway, budget: BudgetManager, resolver: EntityResolver):
        self.gateway = gateway
        self.budget = budget
        self.resolver = resolver

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _soup_text(soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript", "header nav", "footer"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text)[:20000]

    @staticmethod
    def _extract_links(soup: BeautifulSoup, base_url: str, domain: str) -> Tuple[List[str], List[str]]:
        internal, pdfs = [], []
        reg = registrable_domain(domain)
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full = urljoin(base_url, href)
            if not full.startswith("http"):
                continue
            host = (urlsplit(full).hostname or "").lower()
            if registrable_domain(host) == reg:
                internal.append(full.split("#")[0])
            if full.lower().endswith(".pdf") or "/pdf" in full.lower():
                pdfs.append(full)
        return list(dict.fromkeys(internal))[:40], list(dict.fromkeys(pdfs))[:5]

    # ------------------------------------------------------------ discovery
    def candidate_urls(self, identity: CompanyIdentity) -> List[Dict]:
        """Website candidates with reasons; registry hjemmeside first, then
        name-derived guesses (validated by crawling + entity match)."""
        cands: List[Dict] = []
        if identity.website:
            cands.append({"url": identity.website, "reason": "registry hjemmeside", "confidence": 0.9})
        # name-derived guesses are deliberately conservative (.no/.com)
        core = normalize_name(identity.legal_name).split()
        if core:
            base = "-".join(core[:2]).replace(" ", "-")
            for tld in ("no", "com"):
                cands.append({"url": f"https://www.{base}.{tld}", "reason": f"name-derived .{tld}", "confidence": 0.3})
        seen = set()
        out = []
        for c in cands:
            k = c["url"].rstrip("/")
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    # ------------------------------------------------------------ verification
    def verify_site_homepage(self, identity: CompanyIdentity, page_text: str, url: str) -> Tuple[bool, str]:
        """A homepage belongs to the company if text mentions the legal name
        (or the registry orgnr) — deterministic, no LLM."""
        text_l = (page_text or "").lower()
        if identity.organisation_number in (page_text or ""):
            return True, "orgnr present on page"
        if normalize_name(identity.legal_name) and normalize_name(identity.legal_name) in text_l:
            return True, "legal name present on page"
        # fallback: strong brand token match (>=0.85 name similarity)
        match = self.resolver.evaluate(identity, candidate_text=page_text[:4000], candidate_url=url)
        if match.verdict in (MatchVerdict.VERIFIED.value, MatchVerdict.LIKELY.value):
            return True, f"resolver {match.verdict}: {match.reason}"
        return False, f"no identity confirmation on page (resolver: {match.verdict})"

    # ------------------------------------------------------------ crawl
    async def crawl(
        self, identity: CompanyIdentity, run_id: str
    ) -> Tuple[List[EvidenceRecord], List[Fact], List[SourceRecord], List[Dict], Dict[str, str]]:
        """Focused crawl. Returns (evidences, facts, sources, rejected, coverage_updates).

        coverage_updates maps CoverageCategory -> CategoryState string.
        """
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        sources: List[SourceRecord] = []
        rejected: List[Dict] = []
        cov: Dict[str, str] = {}

        # ---- 1. discover the canonical homepage --------------------------
        home_url: Optional[str] = None
        home_text: Optional[str] = None
        for cand in self.candidate_urls(identity):
            if self.budget.requests.remaining() < 6:
                break
            src = await self.gateway.fetch(
                cand["url"], stage="website_discovery", company=identity.organisation_number,
                source_type=self.source_type, authority_tier=self.authority_tier,
            )
            sources.append(src)
            if src.access_status != "success":
                rejected.append({"url": cand["url"], "reason": f"fetch failed ({src.access_status}: {src.error_detail})"})
                continue
            text = self._soup_text(BeautifulSoup(self.gateway.get_content(src.url).text, "lxml"))
            ok, why = self.verify_site_homepage(identity, text, src.url)
            if ok:
                home_url, home_text = src.url, text
                self.resolver.register_verified_domain(registrable_domain(src.url), identity.organisation_number)
                break
            rejected.append({"url": cand["url"], "reason": f"identity not confirmed: {why}"})

        if not home_url:
            cov["business_description"] = "not_available"
            return evidences, facts, sources, rejected, cov

        # homepage fact: business_description from meta/home text
        now = utcnow().isoformat()
        ev_home = EvidenceRecord(
            source_id=next(s.source_id for s in sources if s.url == home_url),
            url=home_url,
            source_title="Official website (homepage)",
            source_type=self.source_type,
            authority_tier=self.authority_tier,
            retrieved_at=now,
            evidence_text=home_text[:600],
            content_hash=next(s.content_hash for s in sources if s.url == home_url),
            entity_verdict=MatchVerdict.LIKELY.value,
            org_number=identity.organisation_number,
            entity_match_details={"homepage": home_url},
        )
        evidences.append(ev_home)
        desc = _meta_description(BeautifulSoup(self.gateway.get_content(home_url).text, "lxml")) or home_text[:400]
        facts.append(Fact(
            org_number=identity.organisation_number, run_id=run_id, category="business_description",
            field="description", value=desc[:1200], normalized_value=desc[:300],
            source_id=ev_home.source_id, evidence_id=ev_home.evidence_id,
            retrieved_at=now, entity_verdict=MatchVerdict.LIKELY.value,
            fact_confidence=0.8, status=FactStatus.PUBLISHED.value,
        ))
        cov["business_description"] = "found"

        # ---- 2. focused crawl from homepage links ------------------------
        soup = BeautifulSoup(self.gateway.get_content(home_url).text, "lxml")
        links, pdf_links = self._extract_links(soup, home_url, urlsplit(home_url).hostname or "")
        scored: Dict[str, int] = {}
        for link in links:
            ptype, prio = classify_url(link)
            if prio == 0:
                continue
            scored[link] = prio
        ordered = sorted(scored.items(), key=lambda kv: -kv[1])
        crawled_pages = 0
        for link, _prio in ordered:
            if crawled_pages >= settings.max_pages_per_company:
                break
            if self.budget.requests.remaining() < 4:
                break
            if link == home_url:
                continue
            src = await self.gateway.fetch(
                link, stage="website_crawl", company=identity.organisation_number,
                source_type=self.source_type, authority_tier=self.authority_tier,
                respect_robots=True,
                allowed_domains=[registrable_domain(urlsplit(home_url).hostname or "")],
            )
            sources.append(src)
            if src.access_status != "success":
                continue
            crawled_pages += 1
            page_text = self._soup_text(BeautifulSoup(self.gateway.get_content(src.url).text, "lxml"))
            ptype, _ = classify_url(link)
            # Pages under the verified company domain: domain corroboration is strong.
            # Still run the resolver to catch explicit foreign-orgnr contradictions.
            match = self.resolver.evaluate(identity, candidate_text=page_text[:4000], candidate_url=link)
            if match.verdict == MatchVerdict.REJECTED.value:
                rejected.append({"url": link, "reason": f"rejected: {match.reason}"})
                continue
            if match.verdict == MatchVerdict.AMBIGUOUS.value and link != home_url:
                match = MatchResult("LIKELY", match.signals, "same verified company domain", 0.5)

            ev = EvidenceRecord(
                source_id=src.source_id, url=src.url,
                source_title=f"Official website ({ptype.lower()})",
                source_type=self.source_type, authority_tier=self.authority_tier,
                retrieved_at=now, evidence_text=page_text[:600],
                content_hash=src.content_hash, entity_verdict=match.verdict,
                org_number=identity.organisation_number,
                entity_match_details={"page_type": ptype},
            )
            evidences.append(ev)

            if ptype == "CONTACT":
                contact = _extract_contact(page_text, link)
                if contact:
                    facts.append(Fact(
                        org_number=identity.organisation_number, run_id=run_id,
                        category="locations", field="contact",
                        value=contact, normalized_value=str(contact)[:200],
                        source_id=src.source_id, evidence_id=ev.evidence_id,
                        retrieved_at=now, entity_verdict=match.verdict,
                        fact_confidence=0.85, status=FactStatus.PUBLISHED.value,
                    ))
                    cov["locations"] = "found"
            elif ptype == "CAREERS":
                cov["jobs"] = cov.get("jobs") or "found"
                facts.append(Fact(
                    org_number=identity.organisation_number, run_id=run_id,
                    category="jobs", field="careers_page",
                    value={"url": link, "summary": page_text[:300]},
                    normalized_value=link, source_id=src.source_id,
                    evidence_id=ev.evidence_id, retrieved_at=now,
                    entity_verdict=match.verdict, fact_confidence=0.8,
                    status=FactStatus.PUBLISHED.value,
                ))
            elif ptype in ("PRODUCT", "SERVICE"):
                cov["products_services"] = "found"
                facts.append(Fact(
                    org_number=identity.organisation_number, run_id=run_id,
                    category="products_services", field="offering",
                    value={"url": link, "title": _page_title(BeautifulSoup(self.gateway.get_content(src.url).text, "lxml")), "summary": page_text[:400]},
                    normalized_value=link, source_id=src.source_id,
                    evidence_id=ev.evidence_id, retrieved_at=now,
                    entity_verdict=match.verdict, fact_confidence=0.85,
                    status=FactStatus.PUBLISHED.value,
                ))
            elif ptype == "NEWS":
                cov["recent_activity"] = cov.get("recent_activity") or "found"
                facts.append(Fact(
                    org_number=identity.organisation_number, run_id=run_id,
                    category="recent_activity", field="news_page",
                    value={"url": link, "summary": page_text[:300]},
                    normalized_value=link, source_id=src.source_id,
                    evidence_id=ev.evidence_id, retrieved_at=now,
                    entity_verdict=match.verdict, fact_confidence=0.7,
                    status=FactStatus.PUBLISHED.value,
                ))
            elif ptype == "LEADERSHIP":
                people = _extract_names(page_text)
                if people:
                    cov["leadership"] = "found"
                    for pname, prole in people[:6]:
                        evp = EvidenceRecord(
                            source_id=src.source_id, url=src.url,
                            source_title="Official website (leadership)",
                            source_type=self.source_type, authority_tier=self.authority_tier,
                            retrieved_at=now, evidence_text=f"{pname} — {prole}",
                            content_hash=src.content_hash, entity_verdict=match.verdict,
                            org_number=identity.organisation_number,
                            entity_match_details={"page_type": "LEADERSHIP"},
                        )
                        evidences.append(evp)
                        facts.append(Fact(
                            org_number=identity.organisation_number, run_id=run_id,
                            category="leadership", field="role:web",
                            value={"name": pname, "role": prole},
                            normalized_value=f"{prole}:{pname}",
                            source_id=src.source_id, evidence_id=evp.evidence_id,
                            retrieved_at=now, entity_verdict=match.verdict,
                            fact_confidence=0.8, status=FactStatus.PUBLISHED.value,
                        ))

        # PDF discovery note (documents themselves go through the PDF pipeline)
        for pdf_url in pdf_links:
            sources.append(SourceRecord(
                url=pdf_url, source_type=SourceType.COMPANY_DOCUMENT.value,
                authority_tier=1, access_status="success", org_number=identity.organisation_number,
                retrieved_at=now, title="discovered PDF",
            ))

        return evidences, facts, sources, rejected, cov


def _meta_description(soup: BeautifulSoup) -> Optional[str]:
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if meta and meta.get("content"):
        return re.sub(r"\s+", " ", meta["content"]).strip()[:600]
    return None


def _page_title(soup: BeautifulSoup) -> Optional[str]:
    t = soup.title.string if soup.title else None
    return re.sub(r"\s+", " ", t).strip()[:120] if t else None


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+47[\s-]?)?\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}(?:[\s-]?\d{2})?|(?:\+47[\s-]?)?\d{3}[\s-]?\d{2}[\s-]?\d{3}")
_ADDR_RE = re.compile(r"\b[A-ZÆØÅ][\wæøå-]+(?:veien|gata|gaten|street|road|vei|allé|all)\s*\d+[A-Za-z]?\b")


def _extract_contact(text: str, url: str) -> Optional[Dict]:
    emails = _EMAIL_RE.findall(text)[:3]
    phones = _PHONE_RE.findall(text)[:3]
    addrs = _ADDR_RE.findall(text)[:3]
    if not (emails or phones or addrs):
        return None
    return {"url": url, "emails": emails, "phones": phones, "addresses": addrs}


_ROLE_PATTERNS = [
    (re.compile(r"(konserndirektør|administrerende direktør|adm\. dir\.|CEO)\s*[:\-]?\s*([A-ZÆØÅ][\wæøå.\- ]{2,50})", re.I), "CEO"),
    (re.compile(r"(daglig leder)\s*[:\-]?\s*([A-ZÆØÅ][\wæøå.\- ]{2,50})", re.I), "daglig leder"),
    (re.compile(r"(styreleder|chair)\s*[:\-]?\s*([A-ZÆØÅ][\wæøå.\- ]{2,50})", re.I), "styreleder"),
    (re.compile(r"(CFO|finansdirektør)\s*[:\-]?\s*([A-ZÆØÅ][\wæøå.\- ]{2,50})", re.I), "CFO"),
    (re.compile(r"(CTO|teknologidirektør)\s*[:\-]?\s*([A-ZÆØÅ][\wæøå.\- ]{2,50})", re.I), "CTO"),
]


def _extract_names(text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for pat, label in _ROLE_PATTERNS:
        for m in pat.finditer(text):
            name = m.group(2).strip().rstrip(".,;")
            if 2 <= len(name.split()) <= 5 and not any(w == "og" for w in name.split()):
                out.append((name, label))
    return out[:8]
