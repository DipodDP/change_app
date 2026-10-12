# Change

Finds the cheapest way to convert currency through chains of exchanges you have
actually made, rather than through published market rates.

You record real conversions — what you handed over, what you got back, and
optionally which bank did it. The effective rate (commission already inside)
falls out of the two amounts. Change then treats each exchange as an edge in a
graph and finds every chain between two currencies, ranked by what you would
actually end up with.

## Example

Given these recorded exchanges:

| Spent | Received | Bank | |
|---|---|---|---|
| 60 000 RUB | 2 140.43 BYN | Белинвестбанк | |
| 100 BYN | 28.84 EUR | Приорбанк | |
| 28.84 EUR | 28.70 EUR | Приорбанк → OTP | transfer |
| 14.02 EUR | 5 000 HUF | OTP | |
| 100 BYN | 33.26 USD | Freedom | |
| 33.26 USD | 32.60 USD | Freedom → Wise | transfer |
| 7.34 USD | 2 200 HUF | Wise | |

Comparing 100 BYN → HUF:

| Route | Payout | |
|---|---|---|
| BYN → EUR → HUF, via Приорбанк and OTP | **10 235.38 HUF** | best rate |
| BYN → USD → HUF, via Freedom and Wise | 9 771.12 HUF | +4.54% |

The euro route wins by 464.26 HUF per 100 BYN. RUB → HUF chains automatically
through BYN without being entered as a route.

Money only chains where it actually sits: a balance at one bank cannot be spent
at another. The two transfer rows are what carry the funds between banks, and
without them these are seven unrelated conversions with no route between them.

## Running it

Dependencies are managed with [uv](https://docs.astral.sh/uv/); `uv run`
creates and syncs the environment automatically, so there is no activate step.

    uv run python manage.py migrate
    uv run python manage.py createsuperuser        # for /admin/
    uv run python manage.py runserver

Then open http://127.0.0.1:8000.

Translations are compiled artifacts and are not committed. Build them once:

    msgfmt -o locale/ru/LC_MESSAGES/django.mo locale/ru/LC_MESSAGES/django.po
    msgfmt -o locale/en/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po

(`uv run python manage.py compilemessages` also works, but on some setups it
only walks Django's own catalogs.)

To serve it on a LAN or tailnet, bind all interfaces and add the address to
`ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` in `config/settings.py`:

    uv run python manage.py runserver 0.0.0.0:8000

## Tests

    uv run python manage.py test exchanges

## Notes

- **Money** is rounded to 2 decimal places with banker's rounding
  (`ROUND_HALF_EVEN`) everywhere — see `exchanges/money.py`. Rates keep more
  precision, since a sub-unit rate would collapse to `0.01` at money precision.
- **Rates are historical.** They come from conversions you already made, so they
  answer "which way was cheaper" — not "what will it cost right now".
- **Routes** can be found automatically (graph search over all recorded
  exchanges) or saved by hand and named, because which bank performed a
  conversion is not derivable from the currency pair.
- **Languages**: English and Russian, switchable in the header.
