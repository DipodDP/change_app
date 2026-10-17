# Change

English · [Русский](README.ru.md)

Change finds the cheapest way to convert currency using exchanges you have
already made, not published market rates.

For each conversion you record what you handed over, what you got back and
which bank did it. The two amounts give the effective rate with the commission
already included. Change treats every exchange as an edge in a graph, finds all
the chains between two currencies and ranks them by how much you end up with.

## Example

Say you have recorded these exchanges:

| Spent | Received | Bank | |
|---|---|---|---|
| 60 000 RUB | 2 140.43 BYN | Белинвестбанк | |
| 100 BYN | 28.84 EUR | Приорбанк | |
| 28.84 EUR | 28.70 EUR | Приорбанк → OTP | transfer |
| 14.02 EUR | 5 000 HUF | OTP | |
| 100 BYN | 33.26 USD | Freedom | |
| 33.26 USD | 32.60 USD | Freedom → Wise | transfer |
| 7.34 USD | 2 200 HUF | Wise | |

Comparing 100 BYN → HUF gives:

| Route | Payout | |
|---|---|---|
| BYN → EUR → HUF, via Приорбанк and OTP | **10 235.38 HUF** | best rate |
| BYN → USD → HUF, via Freedom and Wise | 9 771.12 HUF | −4.54% |

Going through euros pays 464.26 HUF more per 100 BYN. You never enter RUB → HUF
as a route; Change builds it through BYN on its own.

A chain only continues at the bank where the money is, because a balance at one
bank can't be spent at another. In the example the two transfer rows move the
money between banks. Without them you would have seven unrelated conversions and
no route at all. A cash deposit works the same way: record it as a transfer in
one currency from "Cash" to the bank.

## Accounts

You can use everything without signing in. Exchanges you record while signed
out belong to your browser, and they stay as long as it visits at least once
every 30 days. If you register with an email and password, they move into your
account. From then on they are kept permanently and you can open them on any
device.

## Running it

[uv](https://docs.astral.sh/uv/) manages the dependencies. `uv run` creates and
syncs the environment by itself, so you don't need to activate anything.

    uv run python manage.py migrate
    uv run python manage.py compilemessages -l ru -l en
    uv run python manage.py createsuperuser        # for /admin/
    uv run python manage.py runserver

Then open http://127.0.0.1:8000. The compiled translation files aren't in the
repository, which is why `compilemessages` is on the list.

To reach it from your LAN or tailnet, bind to all interfaces and list the
machine's addresses in `.env` (`DJANGO_ALLOWED_HOSTS=192.168.1.10,100.64.0.1`):

    uv run python manage.py runserver 0.0.0.0:8000

Signed-out exchanges stay in the database after their session expires until
something deletes them. Run this once a day:

    uv run python manage.py clearsessions && uv run python manage.py purge_guests

## Deploying

Change is a plain Django WSGI project (`config.wsgi:application`) that stores
its data in SQLite. Any host with Python 3.12 or newer can run it.

**1. Get the code.**

    git clone https://github.com/DipodDP/change_app.git
    cd change_app

**2. Configure.** Copy the example file and fill in your domain and a secret key.
You can generate the key with
`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.

    cp .env.example .env && chmod 600 .env

The site, the management commands and any scheduled jobs all read `.env`, so
they use the same secret key. The cleanup job needs that key to read sessions.
If a variable is also set in the real environment, that value wins. With
`DJANGO_DEBUG=0` the app won't start until you set a real key.

**3. Create the virtualenv.** Run this in the project directory:

    uv sync --frozen --python 3.13

It creates `.venv/` with the exact versions from `uv.lock`. Point your WSGI
server at that directory (`/path/to/change_app/.venv`). The `--python` flag
picks the interpreter when the server has several.

If the server doesn't have uv, install it with `pip install --user uv`. You can
also do without it:

    python3.13 -m venv .venv && .venv/bin/pip install "django==6.1"

In that case it's up to you to keep the Django version in line with `uv.lock`.

**4. Prepare.**

    .venv/bin/python manage.py migrate
    .venv/bin/python manage.py compilemessages -l ru -l en
    .venv/bin/python manage.py collectstatic --noinput
    .venv/bin/python manage.py createsuperuser

To keep your existing data, copy your `db.sqlite3` into the project directory
before you run `migrate`.

**5. Serve it.**

- Run `config.wsgi:application` with whatever WSGI server your host provides
  (Gunicorn, uWSGI, mod_wsgi or the platform's own). Use the project directory
  as the working directory and the Python in `.venv`.
- Serve `/static/` from the `staticfiles/` directory.
- Use HTTPS only and redirect plain HTTP to it. With `DJANGO_DEBUG=0` the
  session and CSRF cookies are only sent over HTTPS, so signing in won't work
  over HTTP.

**6. Schedule the cleanup** to run once a day, for example with cron:

    0 4 * * * cd /path/to/change_app && .venv/bin/python manage.py clearsessions && .venv/bin/python manage.py purge_guests

If it can't read the sessions, it stops without deleting anything.

**Updating** later:

    git pull && uv sync --frozen \
      && .venv/bin/python manage.py migrate \
      && .venv/bin/python manage.py compilemessages -l ru -l en \
      && .venv/bin/python manage.py collectstatic --noinput

Then restart the WSGI server.

## Tests

    uv run python manage.py test exchanges

## Notes

- **Money** is rounded to 2 decimal places with banker's rounding
  (`ROUND_HALF_EVEN`, see `exchanges/money.py`). Rates are never rounded in
  calculations, only when they are displayed.
- **Rates are historical.** They come from conversions you already made, so
  they tell you which way was cheaper, not what a conversion costs right now.
  Only the newest record for each currency pair and bank is used for routes.
  Older records stay in the list as history.
- **Routes** come from a graph search over all your recorded exchanges. A route
  stays within one bank unless a transfer moves the money. It can also end with
  a transfer, so "EUR in cash" and "EUR deposited at the bank" show up as
  separate options.
- **Languages**: English and Russian, switchable in the header.
