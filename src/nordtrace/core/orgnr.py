"""Norwegian organisation number (organisasjonsnummer) utilities.

The organisasjonsnummer is a 9-digit number with a modulus-11 checksum
using weights [3, 2, 7, 6, 5, 4, 3, 2] applied to the first 8 digits.
The check digit is (11 - (weighted_sum % 11)) % 11; a result of 10 is invalid.

Note: a syntactically valid number is not necessarily a registered company.
Registry lookup is a separate, authoritative check performed by the Brreg adapter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)
_ORGNR_RE = re.compile(r"^\d{9}$")


@dataclass(frozen=True)
class OrgNrResult:
    value: str
    valid: bool
    reason: str


def normalize_orgnr(raw: str) -> str:
    """Strip whitespace, dashes, dots and OCR noise from raw input."""
    if raw is None:
        return ""
    return re.sub(r"[\s\-–—_.]", "", str(raw))


def _checksum_valid(digits: str) -> bool:
    try:
        total = sum(_WEIGHTS[i] * int(digits[i]) for i in range(8))
    except (IndexError, ValueError):
        return False
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False  # modulus-11 reserves 10 as invalid
    return check == int(digits[8])


def validate_orgnr(raw: str) -> OrgNrResult:
    """Validate format + checksum. Registration is checked separately at Brreg."""
    value = normalize_orgnr(raw)
    if not value:
        return OrgNrResult(value="", valid=False, reason="empty input")
    if not _ORGNR_RE.match(value):
        if value.isdigit():
            return OrgNrResult(value=value, valid=False, reason=f"expected 9 digits, got {len(value)}")
        return OrgNrResult(value=value, valid=False, reason="contains non-digit characters")
    if not _checksum_valid(value):
        return OrgNrResult(value=value, valid=False, reason="checksum failed (modulus 11)")
    return OrgNrResult(value=value, valid=True, reason="valid format and checksum")


def is_valid_orgnr(raw: str) -> bool:
    return validate_orgnr(raw).valid
