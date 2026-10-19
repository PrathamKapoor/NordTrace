"""Exact source-number diagnostics; no implied monetary units or publication rule."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from nordtrace.core.evidence import decode_source_json


@dataclass(frozen=True)
class JsonNumber:
    """Distinguish an actual JSON numeric token from strings and booleans."""

    lexeme: str

    def __post_init__(self) -> None:
        if len(self.lexeme) > 256:
            raise ValueError("financial JSON number token capacity exceeded")

    def decimal_text(self) -> str:
        try:
            value = Decimal(self.lexeme)
        except InvalidOperation as error:
            raise ValueError("unsupported financial JSON number") from error
        # Local supported range, not a Brreg schema assertion. Bound before
        # fixed-point formatting so a tiny exponent token cannot expand memory.
        exponent = value.as_tuple().exponent
        if (not value.is_finite() or not isinstance(exponent, int)
                or abs(exponent) > 36 or value.adjusted() > 35
                or len(value.as_tuple().digits) > 48 or exponent < -12):
            raise ValueError("financial source number outside supported exact range")
        return format(value, "f")


def parse_accounts_json(body: bytes) -> Any:
    """Keep all number lexemes internally; never inject Decimal into generic DTOs."""
    return decode_source_json(body, parse_float=JsonNumber, parse_int=JsonNumber)
