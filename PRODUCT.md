# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Expats, migrants, and frequent travellers who move money between currencies
often enough that the spread matters. Anyone can sign up; accounts are private
(every Exchange carries an `owner`), and a new user arrives with no
data at all.

Two genuine usage scenes, both first-class:

- **Phone, at the counter.** Checking which route pays out more, or logging a
  conversion moments after making it. Fast scanning, large tap targets.
- **Desktop, reviewing later.** Entering a backlog of records and comparing
  routes at leisure. Density and table readability.

Interface is available in English and Russian, switchable in the header.

## Product Purpose

Change finds the cheapest way to convert currency through chains of exchanges
the user has actually made, rather than through published market rates. Success
is the user picking the better route and knowing by how much it wins.

## Positioning

Rates are derived from the user's own completed conversions — two amounts in,
effective rate out, commission already baked in — not from a market feed. This
answers "which way was cheaper for me" rather than "what is the mid-market rate",
which a rate-aggregator cannot truthfully claim. Recorded exchanges form a graph,
so chains the user never explicitly entered (RUB → HUF via BYN) are found
automatically.

## Operating Context

- Record an exchange: spent amount + currency, received amount + currency,
  optional provider (the bank that did it) and destination provider (for
  transfers that move money between banks).
- Compare: pick source and target currency, get every chain ranked by payout,
  with the shortfall against the winner shown as a percentage.
- Clear all (header, only when data exists) wipes the account after a
  confirmation page. There is no demo dataset: an empty account explains the
  three steps and asks for a first real exchange.
- The dashboard opens on the last comparison run on this device (session),
  while it still routes; otherwise on the newest conversion.

## Capabilities and Constraints

- Django, server-rendered templates, one hand-written stylesheet
  (`static/css/app.css`); no JS framework, no build step.
- **Rates are historical.** They come from conversions already made and are not
  live quotes. Nothing in the product may imply otherwise.
- Money rounds to 2 decimal places with banker's rounding (`ROUND_HALF_EVEN`);
  rates keep 8 decimal places, because a sub-unit rate collapses to `0.01` at
  money precision.
- 30 currencies, ordered by usage; labels are the symbol where one is in common
  use and the code otherwise, and the picker shows both.
- Terminology: *exchange* (one conversion performed), *route* (a chain of exchanges found by Compare),
  *provider* (the bank), *payout* (what you end up with), *rate* (received per
  unit spent).
- Routes stay within a single bank unless an exchange records a destination
  provider.

## Brand Commitments

Name: **Change**. Existing identity is an incumbent implementation rather than a
user-declared constraint: dark OLED ground, amber for money and trust, violet for
actions, Fira Sans / Fira Code. Whether to preserve or replace it is undecided —
see Evidence.

## Evidence on Hand

- Real worked example in `README.md` (BYN → HUF via EUR beats via USD by 316.37
  HUF per 100 BYN) — genuine, safe to use in docs and tests, never as
  data loaded into an account.
- No testimonials, customers, benchmarks, pricing, press, or logo assets exist.
  Future work must not invent them.

## Product Principles

1. **Your numbers, not the market's.** Every figure shown traces back to a
   conversion the user actually made.
2. **The comparison is the product.** Ranking routes and naming the gap between
   them outranks any other screen.
3. **Honest about being historical.** Never let a rate read as a live quote.
4. **Legible at the counter and at the desk.** Neither usage scene is the
   degraded one.
5. **Empty is the normal first state.** A new account has no data; the app must
   still explain itself.

## Accessibility & Inclusion

No formal standard has been set. The incumbent stylesheet already works to
WCAG AA contrast (secondary text documented at 6.9:1 on the ground) and uses a
44px minimum tap target, so AA is the working floor. Bilingual EN/RU means copy
and layout must tolerate roughly 30% string growth.

## Open Decisions

- Visual scope (refine the incumbent world vs. replace it) is deliberately
  undecided; the user chose to audit first.
- No accessibility standard formally committed beyond the AA floor above.
