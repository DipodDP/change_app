"""Suggestions built from what the user has already stored.

The wireframe leans on recall over typing: bank names come back as chips,
route names are proposed from the banks on the chosen steps, and the route
builder only offers steps that actually connect.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from .models import Currency, Exchange, Route
from .routing import chain_rate

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
    exclude: str = "",
) -> list[BankPick]:
    """Previously-used bank names.

    `typed` narrows the list to matches as the user types. `exclude` drops one
    name without narrowing anything else — for a prefilled edit form, where
    the record's own bank is redundant but the others are still useful.
    """
    # Recency is judged by created_at rather than iteration order, since the
    # queryset's own ordering is newest-first and would invert "last seen".
    stats: dict[str, dict] = {}
    for exchange in exchanges:
        name = (exchange.provider or "").strip()
        if not name:
            continue
        stamp = getattr(exchange, "created_at", None) or 0
        entry = stats.setdefault(name, {"name": name, "count": 0, "last": stamp})
        entry["count"] += 1
        if stamp and stamp > entry["last"]:
            entry["last"] = stamp

    needle = typed.strip().lower()
    skip = exclude.strip().lower()
    picks = [
        e
        for e in stats.values()
        # Whatever is already in the field is noise if offered back.
        if e["name"].lower() != needle
        and e["name"].lower() != skip
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


def route_name_suggestions(
    steps: Sequence[Exchange], taken: Sequence[str] = (), current: str = "", limit: int = 3
) -> list[str]:
    """Names built from the banks on the chosen steps, best guess first."""
    banks = [(s.provider or "").strip() for s in steps]
    banks = [b for b in banks if b]
    if not banks:
        return []

    ideas: list[str] = ["–".join(banks)]
    if len(banks) > 2:
        # A long chain reads better as its endpoints.
        ideas.append(f"{banks[0]}–{banks[-1]}")
    ideas.extend(banks)

    seen: set[str] = set()
    out: list[str] = []
    for idea in ideas:
        if idea in seen or idea == current or idea in taken:
            continue
        seen.add(idea)
        out.append(idea)
    return out[:limit]


def affected_routes(exchange: Exchange) -> list[dict]:
    """Saved routes that contain this exchange, with their through rate."""
    if not exchange.pk:
        return []

    out = []
    for route in Route.objects.filter(route_steps__exchange=exchange).distinct():
        steps = route.ordered_steps()
        try:
            rate = chain_rate(steps)
            broken = False
        except ValueError:
            rate = None
            broken = True
        out.append({"route": route, "rate": rate, "broken": broken, "steps": steps})
    return out


def split_candidates(
    exchanges: Iterable[Exchange], chosen: Sequence[Exchange]
) -> tuple[list[Exchange], list[Exchange]]:
    """Partition available steps into those that continue the chain and those that cannot."""
    chosen_pks = {e.pk for e in chosen}
    tail = chosen[-1].received_currency if chosen else None

    fits: list[Exchange] = []
    unfits: list[Exchange] = []
    for exchange in exchanges:
        if exchange.pk in chosen_pks:
            continue
        if tail is None or exchange.spent_currency == tail:
            fits.append(exchange)
        else:
            unfits.append(exchange)
    return fits, unfits


def name_from_steps(steps: Sequence[Exchange], disambiguate: bool = False) -> str:
    """The canonical name for a chain, derived from the banks on its steps.

    Consecutive duplicates collapse, so a chain done entirely at one bank reads
    as that bank rather than repeating it. With no banks recorded at all the
    currency path is the only meaningful label.
    """
    banks: list[str] = []
    for step in steps:
        name = (step.provider or "").strip()
        if name and (not banks or banks[-1] != name):
            banks.append(name)

    if banks:
        label = "–".join(banks)
        if disambiguate:
            # Same banks, different currencies: name the hops that differ.
            middle = [s.received_currency for s in steps[:-1]]
            if middle:
                label = f"{label} ({' → '.join(middle)})"
        return label

    if not steps:
        return ""
    path = [steps[0].spent_currency] + [s.received_currency for s in steps]
    return " → ".join(path)


def _scoped(owner):
    """Names collide only within one user's own list, so that is the scope."""
    routes = Route.objects.all()
    return routes if owner is None else routes.filter(owner=owner)


def repair_routes(owner=None) -> int:
    """Close the gaps a deleted step leaves behind.

    A cascaded RouteStep takes its position with it, so the survivors no longer
    start at 0 and no longer form a contiguous run. A route emptied entirely is
    dropped: the dashboard skips step-less routes, so leaving it would strand an
    invisible row the user cannot reach to delete.
    """
    removed = 0
    for route in _scoped(owner).prefetch_related("route_steps"):
        steps = list(route.route_steps.order_by("position", "pk"))
        if not steps:
            route.delete()
            removed += 1
            continue
        if [s.position for s in steps] == list(range(len(steps))):
            continue
        # Shift through a range that cannot collide with the existing rows,
        # since (route, position) is unique.
        offset = max(s.position for s in steps) + 1
        for shift, step in enumerate(steps):
            step.position = offset + shift
            step.save(update_fields=["position"])
        for position, step in enumerate(steps):
            step.position = position
            step.save(update_fields=["position"])
    return removed


def sync_route_names(exchange: Exchange | None = None, owner=None) -> list[Route]:
    """Recompute saved route names from the banks on their steps.

    Every route is considered, not just the ones containing `exchange`: a
    rename can create or resolve a collision with a route that does not share
    the edited step, and deciding that from stale sibling names leaves one
    route suffixed and the other not.
    """
    routes = []
    for route in _scoped(owner).prefetch_related("route_steps__exchange"):
        steps = route.ordered_steps()
        if steps:
            routes.append((route, steps, name_from_steps(steps)))

    counts: dict[str, int] = {}
    for _, _, name in routes:
        counts[name] = counts.get(name, 0) + 1

    # Same banks and same currency path: the hop suffix cannot separate them
    # either, so fall back to numbering in creation order.
    disambiguated: dict[str, int] = {}
    for _, steps, name in routes:
        if counts[name] > 1:
            long_name = name_from_steps(steps, disambiguate=True)
            disambiguated[long_name] = disambiguated.get(long_name, 0) + 1

    seen: dict[str, int] = {}
    changed = []
    for route, steps, name in routes:
        final = name
        if counts[name] > 1:
            final = name_from_steps(steps, disambiguate=True)
            if disambiguated.get(final, 0) > 1:
                seen[final] = seen.get(final, 0) + 1
                final = f"{final} #{seen[final]}"
        if final and final != route.name:
            route.name = final
            route.save(update_fields=["name"])
            changed.append(route)
    return changed


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
