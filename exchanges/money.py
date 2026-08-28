"""Money formatting and rounding.

Every monetary figure the app shows is rounded to 2 decimal places using
banker's rounding (ROUND_HALF_EVEN): halves go to the nearest even digit, so
repeated rounding across many conversions does not drift upward the way
ROUND_HALF_UP does.
"""

from decimal import Decimal, ROUND_HALF_EVEN

MONEY_DP = Decimal("0.01")


def quantize_money(value) -> Decimal:
    """Round any numeric to 2dp, half-to-even."""
    if value is None:
        return None
    return Decimal(value).quantize(MONEY_DP, rounding=ROUND_HALF_EVEN)
