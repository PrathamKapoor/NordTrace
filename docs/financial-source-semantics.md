# Financial source semantics

Status: 2026-10-20 local (2026-10-19 UTC retrieval), decision D-086. This is the authoritative field-level record of which monetary semantics are established and which publication cases remain blocked. It supersedes the "units unknown" blocker recorded under D-084/D-085 only for the six structured predicates listed below.

## Sources checked

| Reference | What it establishes | Retrieved / retained |
|---|---|---|
| Altinn RR-0002 form page, Norwegian, [info.altinn.no/skjemaoversikt/bronnoysundregistrene/arsregnskap/](https://info.altinn.no/skjemaoversikt/bronnoysundregistrene/arsregnskap/) | Under "Valør": *"Du må velge om tallene rapporteres i hele tall, tusen eller million. Angir du tusen eller million, multipliseres tallene med hhv. 1 000 eller 1 000 000 når Regnskapsregisteret mottar skjemasettet."* Notes share the same currency and denomination. *"Hovedregelen er at valuta skal være Norske kroner."* | 2026-10-19T20:06Z, HTTP 200, SHA-256 `c69a9c1a21c5853d20a5c5eba35d839877dc964e699dde5a5d95fd442ace433e`, 92,129 bytes |
| Same page, English, [info.altinn.no/en/forms-overview/…/annual-accounts/](https://info.altinn.no/en/forms-overview/bronnoysund-register-centre/annual-accounts/) | Same rule: figures given as thousands/millions "are multiplied by 1,000 or 1,000,000, as applicable, when the Register of Company Accounts receives the forms." | same time, SHA-256 `e2bc75a2d7b01b41cb6570a82c25f3d24b81eea4d6e658dbac30693148cb1f22`, 91,176 bytes |
| Official OpenAPI, [data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs), version 1.1.16 | Monetary fields are `type: number` with no denomination/multiplier field. `id` is a system-generated int32. Explicit `valuta`, `regnskapstype` SELSKAP/KONSERN, `regnskapsperiode` fraDato/tilDato, `avviklingsregnskap` boolean. No ordering, latest or amendment semantics. | SHA-256 `c6b99a196249d22b494a26341a9b7f84d15388ebbb989bce63dcbcb55c59dac5`, unchanged from the 2026-10-19 copy |
| Key-figure specification listed as the official catalogue distribution, `regnskapsregister.json` 1.0.2 (brreg GitHub) | Describes the open part as "nøkkeltall fra sist innsendte årsregnskap". No unit text. | SHA-256 `df304273dd787ae2ca84d344d381a7a9eff0f33016bba7a835176653ef7195dc` |
| Official catalogue entry, [data.norge.no dataset 7c87f169…](https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret), publisher Registerenheten i Brønnøysund, updated 2025-10-09 | *"Den åpne delen inneholder nøkkeltall fra sist innsendte årsregnskap"*. Temporary R&D API that "vil ikke bli videreutviklet eller vedlikeholdt, og kan bli lagt ned uten varsel". NLOD 2.0 on the key-figure distribution. No unit or amendment text. | Browser read only; no raw hash |
| Service documentation and archived README (rechecked) | 10-year register retention and "last accounting year" preview scope. No unit or amendment text. | Browser read only |

Raw copies are retained locally (ignored) in `data/contracts/accounts-semantics-20261020/`. Documentation reads are engineering reads, separate from company-run request accounting.

## Matrix

All six predicates share one endpoint, `GET https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` (OpenAPI 1.1.16, `application/json`), and one support rule, `brreg-account-amount-v1`, locator kind `json_number` (result schema 1.3).

| Predicate | Source path under the record | Meaning (source line item) |
|---|---|---|
| `total_operating_revenue` | `resultatregnskapResultat/driftsresultat/driftsinntekter/sumDriftsinntekter` | Sum driftsinntekter (total operating revenue, including other operating income, not only sales) |
| `operating_result` | `resultatregnskapResultat/driftsresultat/driftsresultat` | Driftsresultat (operating result) |
| `annual_result` | `resultatregnskapResultat/aarsresultat` | Årsresultat (result for the year) |
| `total_assets` | `eiendeler/sumEiendeler` | Sum eiendeler |
| `equity` | `egenkapitalGjeld/egenkapital/sumEgenkapital` | Sum egenkapital |
| `total_liabilities` | `egenkapitalGjeld/gjeldOversikt/sumGjeld` | Sum gjeld |

Shared qualifiers, all resolved independently from the retained bytes by the validator:

| Qualifier | Basis | Status |
|---|---|---|
| Raw representation | Exact JSON number lexeme (e.g. `696480.00`), never a binary float. Canonical value: fixed-point decimal string with no exponent, no trailing fractional zeros and no `-0` (`696480`, `-12.5`, `0`). | established |
| Currency | The record's own `valuta`, which must be three uppercase letters. NOK is never assumed; EUR or any other declared code is carried through. | established |
| Unit / multiplier | Multiplier 1 (`currency_unit_x1`): whole units of `valuta`. Basis: the RR-0002 denomination rule (thousands/millions multiplied at receipt) plus the absence of any denomination field in the API. | established as a two-document inference; see limits |
| Full period | `regnskapsperiode` fraDato/tilDato, both strict ISO dates, start ≤ end. | established |
| Legal scope | `regnskapstype` = `SELSKAP` and `virksomhet.organisasjonsnummer` = the exact target. KONSERN is a different claim and is withheld. | established for SELSKAP; group unsupported |
| Statement basis | `avviklingsregnskap` must be literally `false`. Liquidation-basis or undeclared records are withheld. | established |
| Filing identity | `id` (int32) and optional `journalnr` are carried in the locator and display as qualifiers. | established as identification only |
| Supersession / precedence | **Not documented.** The catalogue's "sist innsendte årsregnskap" does not match observed behaviour: one live call returned three SELSKAP records for 2023, 2024 and 2025. So it cannot serve as a current-filing guarantee. | unsupported; handled by abstention |

## Publication cases

| Case | Outcome |
|---|---|
| Exactly one SELSKAP record (or exact duplicate representations) for a full period, valid metadata, `avviklingsregnskap: false` | Publish each present numeric predicate for that period, scoped to that filing's ID. No "latest", "current" or "supersedes" claim. |
| Several records with different periods | Each period publishes independently (a new period is a NEW claim). The brief shows the most recent period of each predicate, labelled with that period. |
| Two or more distinct SELSKAP records for one period | That period's amounts are withheld. Other periods are unaffected. The reason is recorded on the source. |
| A target-subject record whose period cannot be resolved | Every period is withheld, because it could compete with any of them. |
| Missing/invalid currency, ID, period, scope; foreign subject; `avviklingsregnskap` true/null/absent | Withheld; diagnostic candidates only. |
| Field absent, null, string, boolean, container, or outside the exact supported range | No claim for that field; other fields in the record are unaffected. |
| Same period, different value on a later refresh | Same claim ID, CHANGED. The brief points to qualified evidence rather than printing unqualified old/new amounts. |
| Source outage | Prior supported amounts become last-known; they are never retracted. |
| KONSERN statements | Unsupported (group scope is not available in the open API per the catalogue; no group predicate exists). |
| PDF statements (`aarsregnskap/kopi` or company documents) | Still diagnostic-only; the structured rule does not apply to PDFs. |

## Limits and revisit conditions

- The unit rule chains two official documents. The filing channel says the register normalizes denomination at receipt; the API is the register's key-figure service and exposes no denomination. No provider sentence says in so many words that "API amounts are whole units of valuta". Revisit immediately if the API adds a denomination field, or if any provider text or an official statement copy contradicts this.
- The Altinn page carries no date. Applying it to every period the open API returns assumes the rule held when those statements were received. Older statements outside the current open window have not been examined.
- Amounts identify a filing; they do not establish approval, audit status or freshness, and they say nothing about filings the API did not return.
- Agreement between the JSON and the official CSV comes from one provider and is not independent validation. Neither is the equity + liabilities ≈ assets sanity check on a real record, which only checks field semantics. No held-out accuracy has been measured.
- Source-specific redistribution rights over account content remain unresolved. The NLOD statement on the catalogue applies to the key-figure distribution and is recorded, but is not treated as a blanket grant for raw captures or PDFs.
