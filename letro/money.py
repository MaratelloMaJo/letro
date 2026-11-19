"""Integer minor-unit money helpers.

All arithmetic is done with :class:`decimal.Decimal` and converted back to
integer minor units. Binary floats are never used for money.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from .constants import CURRENCY_DECIMALS


class MoneyError(ValueError):
    """Raised when a money value cannot be represented safely."""


def currency_decimals(currency: str) -> int:
    code = (currency or "").upper()
    if code not in CURRENCY_DECIMALS:
        raise MoneyError(f"unsupported currency: {code!r}")
    return CURRENCY_DECIMALS[code]


def parse_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MoneyError("money value must be a decimal string or number")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise MoneyError("empty money value")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError("invalid decimal value") from exc
    else:
        raise MoneyError("money value must be a decimal string or number")
    if not parsed.is_finite():
        raise MoneyError("money value must be finite")
    return parsed


def to_minor(value: object, currency: str) -> int:
    """Convert a major-unit value to integer minor units."""
    decimals = currency_decimals(currency)
    quant = Decimal(1).scaleb(-decimals)
    try:
        amount = parse_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"cannot convert value to {currency} minor units") from exc
    return int(amount.scaleb(decimals))


def from_minor(amount_minor: int, currency: str) -> Decimal:
    decimals = currency_decimals(currency)
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise MoneyError("minor units must be an integer")
    return Decimal(amount_minor).scaleb(-decimals)


def format_minor(amount_minor: int, currency: str) -> str:
    return str(from_minor(amount_minor, currency))


def convert_minor(
    amount_minor: int,
    rate: object,
    from_currency: str,
    to_currency: str,
) -> int:
    """Convert minor units with an explicit decimal rate, half-up."""
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
        raise MoneyError("amount_minor must be an integer")
    rate_dec = parse_decimal(rate)
    if rate_dec <= 0:
        raise MoneyError("FX rate must be positive")
    source = from_minor(amount_minor, from_currency)
    target = source * rate_dec
    return to_minor(target, to_currency)


def inverse_rate(rate: object) -> Decimal:
    rate_dec = parse_decimal(rate)
    if rate_dec <= 0:
        raise MoneyError("FX rate must be positive")
    return Decimal(1) / rate_dec
