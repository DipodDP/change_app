from decimal import Decimal, ROUND_HALF_EVEN

from django import template

from ..models import Currency
from ..money import quantize_money

register = template.Library()

SYMBOL = dict(Currency.choices)

# Non-breaking space, so an amount never wraps across the separator.
GROUP_SEP = " "


@register.filter
def symbol(code):
    """ISO code -> the sign people actually recognise."""
    return SYMBOL.get(code, code)


@register.filter
def money(value):
    """Always 2dp with banker's rounding, thousands grouped."""
    if value is None:
        return "—"
    try:
        q = quantize_money(value)
    except (TypeError, ValueError, ArithmeticError):
        return "—"
    whole, _, frac = str(abs(q)).partition(".")
    grouped = f"{int(whole):,}".replace(",", GROUP_SEP)
    sign = "-" if q < 0 else ""
    return f"{sign}{grouped}.{frac}"


@register.filter
def rate(value):
    """A rate is not a money amount: keep enough precision to stay meaningful.

    Sub-unit rates are shown to at most 5 decimal places, with trailing zeros
    trimmed. A rate small enough that 5 places would round it away (or to
    nothing) falls back to 5 significant digits, so a real number never
    displays as 0.
    """
    if value is None:
        return "—"
    v = Decimal(value)
    if v >= 100:
        return money(v)
    if v >= 1:
        return _trim(v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))

    # Below 0.001 there are fewer than 3 meaningful digits left at 5 decimal
    # places (0.00008642 -> 0.00009), so switch to significant digits and keep
    # the rate readable at any magnitude.
    if v != 0 and abs(v) < Decimal("0.001"):
        return _trim(Decimal(f"{v:.5g}"))
    return _trim(v.quantize(Decimal("0.00001"), rounding=ROUND_HALF_EVEN))


def _trim(v: Decimal) -> str:
    """Render without exponent or trailing zeros ('0.2884', not '0.28840')."""
    s = f"{v:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s
