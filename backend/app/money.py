"""Money handling. The rule: parse to integer cents once, at the edge, using
Decimal — then everything downstream is integer arithmetic. No floats touch a
dollar amount anywhere in the app.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class MoneyParseError(ValueError):
    """Raised when a raw amount string can't be understood as money."""


def parse_to_cents(raw: str) -> int:
    """Convert a human/bank amount string to signed integer cents.

    Handles: '$1,234.56', '(45.00)' as negative, '  -12.5 ', '1000'.
    Accounting-style parentheses mean a negative amount.
    """
    if raw is None:
        raise MoneyParseError("amount is missing")

    s = str(raw).strip()
    if not s:
        raise MoneyParseError("amount is empty")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    try:
        dollars = Decimal(s)
    except InvalidOperation as exc:
        raise MoneyParseError(f"could not parse amount: {raw!r}") from exc

    cents = int((dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -cents if negative else cents


def format_cents(cents: int) -> str:
    """Render integer cents as a plain dollar string, e.g. -1234 -> '-12.34'."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"
