"""Money helpers. Amounts are always `Decimal` quantized to the penny, never float."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PENNY = Decimal("0.01")
CURRENCY_SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}


def quantize(value: Decimal) -> Decimal:
    """Round to 2 decimal places, half up (the usual accounting convention)."""
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def to_money(value: object) -> Decimal | None:
    """Parse an amount into a 2dp Decimal.

    Accepts Decimal, int, float (converted via `str` so 1243.5 stays exact) and text such as
    "1,234.50", "£1,234.50" or "(100.00)" (brackets mean negative, as in accounting exports).
    Blank values return None. Anything else unreadable raises ValueError.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Not a valid amount: {value!r}")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        text = re.sub(r"[£$€,\s]", "", text)
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"Not a valid amount: {value!r}") from None
        if negative:
            number = -number
    else:
        raise ValueError(f"Not a valid amount: {value!r}")
    if not number.is_finite():
        raise ValueError(f"Not a valid amount: {value!r}")
    return quantize(number)


def format_money(amount: Decimal | None, currency: str | None = "GBP") -> str:
    """Format for workpaper text: £1,234.50, €3,200.00, CHF 1,000.00, -£9.00."""
    if amount is None:
        return "amount unknown"
    code = (currency or "GBP").upper()
    sign = "-" if amount < 0 else ""
    digits = f"{abs(quantize(amount)):,.2f}"
    symbol = CURRENCY_SYMBOLS.get(code)
    return f"{sign}{symbol}{digits}" if symbol else f"{sign}{code} {digits}"
