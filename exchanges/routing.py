"""Path-finding over recorded exchanges.

Each exchange is a directed edge between two currencies whose weight is the
effective rate the user actually got. The cheapest way to convert A into B is
then the chain of edges with the greatest product of rates — enumerated in
full rather than by Dijkstra, because a realistic ledger has a handful of
currencies and the user wants to see every option ranked, not just the winner.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from .models import Exchange
from .money import quantize_money

# A chain longer than this is almost certainly noise rather than a real plan,
# and the bound keeps enumeration cheap.
MAX_LEGS = 5

QUANT_RATE = Decimal("0.00000001")
QUANT_PCT = Decimal("0.01")


@dataclass(frozen=True)
class Leg:
    exchange: Exchange

    @property
    def rate(self) -> Decimal:
        return self.exchange.rate


@dataclass(frozen=True)
class Path:
    legs: tuple[Leg, ...]

    @property
    def rate(self) -> Decimal:
        return chain_rate([leg.exchange for leg in self.legs])

    @property
    def currencies(self) -> list[str]:
        first = self.legs[0].exchange.spent_currency
        return [first] + [leg.exchange.received_currency for leg in self.legs]

    @property
    def providers(self) -> list[str]:
        return [leg.exchange.provider for leg in self.legs if leg.exchange.provider]


# "send" = I hand over `amount` of base, how much target comes back?
# "get"  = I want `amount` of target, how much base does it cost?
SEND = "send"
GET = "get"


@dataclass(frozen=True)
class Option:
    """One way to get from the base currency to the target, priced.

    In send mode `payout` is target received (more is better); in get mode it
    is base spent (less is better). `shortfall` is always the gap to the best
    option, expressed in whichever currency `payout` is denominated in.
    """

    path: Path
    payout: Decimal
    penalty_pct: Decimal
    shortfall: Decimal
    is_best: bool
    mode: str = SEND

    @property
    def rate(self) -> Decimal:
        return self.path.rate

    @property
    def cost_rate(self) -> Decimal:
        """What one unit of the target costs in base currency.

        The inverse of `rate`, for get mode: someone asking "what does 100 USD
        cost?" is thinking in BYN per dollar, not dollars per BYN.
        """
        if not self.path.rate:
            return Decimal(0)
        return (Decimal(1) / self.path.rate).quantize(QUANT_RATE)

    @property
    def legs(self) -> tuple[Leg, ...]:
        return self.path.legs


def provider_ends(exchange: Exchange) -> tuple[str, str]:
    """Where an exchange takes funds from, and where it leaves them.

    Only a transfer names a second bank; for a plain conversion the money ends
    up at the same place it started.
    """
    src = (exchange.provider or "").strip()
    dst = (exchange.received_provider or "").strip()
    return src, dst or src


def is_transfer(exchange: Exchange) -> bool:
    """A move within one currency rather than a conversion.

    Keyed on the currencies, not the name: a bank moving money between its own
    accounts is as much a transfer as one crossing between two banks, and both
    can charge for it.
    """
    return exchange.spent_currency == exchange.received_currency


def chain_rate(exchanges: Sequence[Exchange]) -> Decimal:
    """Compound rate across a connected chain of exchanges."""
    if not exchanges:
        raise ValueError("a chain needs at least one exchange")

    total = Decimal(1)
    for prev, nxt in zip(exchanges, exchanges[1:]):
        if prev.received_currency != nxt.spent_currency:
            raise ValueError(
                f"chain is broken: {prev.received_currency} does not feed "
                f"{nxt.spent_currency}"
            )
        # Same currency is not the same money: a balance at one bank cannot be
        # spent at another without a transfer nobody recorded. A leg with no
        # provider is unknown rather than contradictory, so it passes.
        held_by = provider_ends(prev)[1]
        spent_by = provider_ends(nxt)[0]
        if held_by and spent_by and held_by != spent_by:
            raise ValueError(
                f"chain is broken: {prev.received_currency} is held at "
                f"{held_by}, not {spent_by}"
            )
    for exchange in exchanges:
        total *= exchange.rate
    return total.quantize(QUANT_RATE)


def best_paths(
    exchanges: Iterable[Exchange], base: str, target: str, max_legs: int = MAX_LEGS
) -> list[Path]:
    """Every chain from base to target, best rate first.

    A currency is never visited twice, so cycles cannot produce endless walks.

    A chain may only continue where the money actually is: USD at one bank is a
    different account from USD at another, and no transfer between them is
    known unless the user recorded one. So each leg must start at the provider
    the previous leg paid out to. An exchange with no provider recorded is
    treated as connecting freely — nothing is known either way, and refusing to
    chain it would make every unlabelled record useless.
    """
    if base == target:
        return []

    edges: dict[str, list[Exchange]] = {}
    for exchange in exchanges:
        edges.setdefault(exchange.spent_currency, []).append(exchange)

    found: list[Path] = []

    def continues(exchange: Exchange, holder: str | None) -> bool:
        """Can funds held at `holder` be spent on this exchange?

        Mirrors the same-provider rule chain_rate enforces, applied while
        walking so an impossible branch is never explored in the first place.
        """
        if holder is None:
            return True
        here = provider_ends(exchange)[0]
        return not here or here == holder

    def walk(
        currency: str,
        visited: tuple[str, ...],
        legs: tuple[Leg, ...],
        holder: str | None,
    ) -> None:
        if len(legs) >= max_legs:
            return
        for exchange in edges.get(currency, ()):
            if not continues(exchange, holder):
                continue
            # A transfer moves funds that are already somewhere. With no holder
            # established there is nothing to move, and taking it would only
            # duplicate the chain that starts at the destination bank outright.
            if holder is None and is_transfer(exchange):
                continue
            nxt = exchange.received_currency
            if nxt in visited and not is_transfer(exchange):
                continue
            extended = legs + (Leg(exchange),)
            if nxt == target:
                found.append(Path(extended))
                # Reaching the target ends this branch: continuing would only
                # add a detour that leaves and re-enters the target currency.
                continue
            # The payout now sits wherever this exchange was made. An
            # unrecorded provider leaves that unknown, which frees the next
            # leg rather than pinning it to the bank two hops back.
            walk(nxt, visited + (nxt,), extended, provider_ends(exchange)[1] or None)

    walk(base, (base,), (), None)
    found.sort(key=lambda p: p.rate, reverse=True)
    return found


def compare(
    exchanges: Iterable[Exchange],
    base: str,
    target: str,
    amount: Decimal,
    max_legs: int = MAX_LEGS,
    mode: str = SEND,
) -> list[Option]:
    """Rank every route from base to target for a concrete amount.

    Ranking flips with the mode: sending, the best route yields the most
    target; getting, the best route costs the least base.
    """
    paths = best_paths(exchanges, base, target, max_legs=max_legs)
    if not paths:
        return []

    # Round to 2dp (half-to-even) before comparing, so the figures the user
    # sees are the same ones the ranking and the gap are computed from.
    if mode == GET:
        priced = [(path, quantize_money(amount / path.rate)) for path in paths]
        priced.sort(key=lambda pair: pair[1])          # cheapest cost first
    else:
        priced = [(path, quantize_money(amount * path.rate)) for path in paths]
        priced.sort(key=lambda pair: pair[1], reverse=True)  # biggest payout first

    best_payout = priced[0][1]

    options: list[Option] = []
    for index, (path, payout) in enumerate(priced):
        # Always a non-negative distance from the best option.
        shortfall = quantize_money(abs(payout - best_payout))
        penalty = (
            (shortfall / best_payout * 100).quantize(QUANT_PCT)
            if best_payout
            else Decimal("0.00")
        )
        options.append(
            Option(
                path=path,
                payout=payout,
                penalty_pct=penalty,
                shortfall=shortfall,
                is_best=index == 0,
                mode=mode,
            )
        )
    return options


@dataclass(frozen=True)
class Group:
    """Options that begin with the same exchange, drawn under one heading."""

    options: list[Option]
    shared_step: Exchange | None = None

    @property
    def shared(self) -> bool:
        return self.shared_step is not None and len(self.options) > 1


def group_options(options: Sequence[Option]) -> list[Group]:
    """Collapse a common opening step so the fork is what stands out.

    Order is preserved: the best option stays first, and a group takes the
    position of its best member.
    """
    groups: list[Group] = []
    buckets: dict[int, list[Option]] = {}
    order: list[int] = []

    for option in options:
        key = option.legs[0].exchange.pk
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(option)

    for key in order:
        bucket = buckets[key]
        first_step = bucket[0].legs[0].exchange
        groups.append(
            Group(options=bucket, shared_step=first_step if len(bucket) > 1 else None)
        )
    return groups


def blocked_chain(
    exchanges: Iterable[Exchange], base: str, target: str, max_legs: int = MAX_LEGS
) -> dict | None:
    """The first chain the provider rule rejected, or None.

    Only meaningful once best_paths has come back empty. It re-walks with the
    rule lifted: if a chain appears, the currencies were always connected and
    the money simply cannot get from one bank to the next, so the fix is a
    transfer rather than another conversion. Returns the joint that broke —
    the currency held and the two banks either side of it — so the empty state
    can name the actual obstacle instead of guessing.
    """
    rows = list(exchanges)
    if base == target:
        return None

    edges: dict[str, list[Exchange]] = {}
    for exchange in rows:
        edges.setdefault(exchange.spent_currency, []).append(exchange)

    found: list[tuple[Exchange, Exchange]] = []

    def walk(
        currency: str, visited: tuple[str, ...], legs: tuple[Exchange, ...]
    ) -> None:
        if found or len(legs) >= max_legs:
            return
        for exchange in edges.get(currency, ()):
            nxt = exchange.received_currency
            if nxt in visited:
                continue
            chain = legs + (exchange,)
            if nxt == target:
                broken = _first_broken_joint(chain)
                if broken:
                    found.append(broken)
                    return
                continue
            walk(nxt, visited + (nxt,), chain)
            if found:
                return

    walk(base, (base,), ())
    if not found:
        return None

    left, right = found[0]
    return {
        "currency": left.received_currency,
        "from_provider": provider_ends(left)[1],
        "to_provider": provider_ends(right)[0],
    }


def _first_broken_joint(chain: tuple[Exchange, ...]) -> tuple[Exchange, Exchange] | None:
    """The first pair in a chain where funds change hands between banks."""
    for left, right in zip(chain, chain[1:]):
        holder = provider_ends(left)[1]
        here = provider_ends(right)[0]
        if holder and here and here != holder:
            return left, right
    return None
