"""Suggestions built from what the user has already stored.

The wireframe leans on recall over typing: bank names come back as chips,
and the user's own currencies sit at the top of every picker.
"""

from dataclasses import dataclass
from typing import Iterable

from .models import Currency, Exchange

DEFAULT_BANK_LIMIT = 6


@dataclass(frozen=True)
class BankPick:
    name: str
    count: int

    @property
    def label(self) -> str:
        """Repeat use is worth showing; a single use speaks for itself."""
        return f"{self.name} · {self.count}" if self.count > 1 else self.name


def bank_suggestions(
    exchanges: Iterable[Exchange],
    typed: str = "",
    order: str = "frequent",
    limit: int = DEFAULT_BANK_LIMIT,
    show_counts: bool = True,
    exclude: str | Iterable[str] = "",
) -> list[BankPick]:
    """Previously-used bank names.

    `typed` narrows the list to matches as the user types. `exclude` drops a
    name — or several — without narrowing anything else: for a prefilled edit
    form, where the record's own bank is redundant but the others are still
    useful, and for the destination field, where the source bank would
    describe a transfer that goes nowhere.
    """
    # Recency is judged by created_at rather than iteration order, since the
    # queryset's own ordering is newest-first and would invert "last seen".
    stats: dict[str, dict] = {}
    for exchange in exchanges:
        stamp = getattr(exchange, "created_at", None) or 0
        # A bank the user has moved money *into* is as real as one they have
        # spent from, and on a transfer it is the only place that name appears.
        # Counting both ends means a destination typed once comes back as a
        # chip everywhere a bank is asked for.
        for field in (exchange.provider, exchange.received_provider):
            name = (field or "").strip()
            if not name:
                continue
            entry = stats.setdefault(name, {"name": name, "count": 0, "last": stamp})
            entry["count"] += 1
            if stamp and stamp > entry["last"]:
                entry["last"] = stamp

    needle = typed.strip().lower()
    names = [exclude] if isinstance(exclude, str) else list(exclude)
    skip = {n.strip().lower() for n in names if n and n.strip()}
    picks = [
        e
        for e in stats.values()
        # Whatever is already in the field is noise if offered back.
        if e["name"].lower() != needle
        and e["name"].lower() not in skip
        and (not needle or needle in e["name"].lower())
    ]

    if order == "recent":
        picks.sort(key=lambda e: e["last"], reverse=True)
    else:
        picks.sort(key=lambda e: (-e["count"], e["name"].lower()))

    return [
        BankPick(name=e["name"], count=e["count"] if show_counts else 1)
        for e in picks[:limit]
    ]


def currency_choices(exchanges: Iterable[Exchange]) -> list[tuple[str, str]]:
    """Currency options with the user's own currencies floated to the top.

    The catalog is long enough that scanning it is a chore, and all but a few
    entries are dead weight for any one person. Ordering by how often a code
    appears in their own records puts the working set within reach; everything
    untouched keeps its alphabetical order so it stays predictable to hunt for.
    """
    counts: dict[str, int] = {}
    for exchange in exchanges:
        for code in (exchange.spent_currency, exchange.received_currency):
            if code:
                counts[code] = counts.get(code, 0) + 1

    labels = dict(Currency.choices)
    # Ties break alphabetically, so a fresh currency does not jump around as
    # unrelated rows are added.
    ordered = sorted(labels, key=lambda code: (-counts.get(code, 0), code))
    # The bare symbol is enough on a result row but not in a list this long,
    # where ¥ is two different currencies; the code disambiguates.
    return [
        (code, code if labels[code] == code else f"{code} · {labels[code]}")
        for code in ordered
    ]
