from django.conf import settings

from .views import owned_exchanges

STYLESHEET = settings.BASE_DIR / "static" / "css" / "app.css"


def stylesheet_version(request):
    """The stylesheet's mtime, appended to its URL.

    The dev server sends no cache-busting name, so a browser can keep an old
    app.css next to a new page — after the fonts moved in-house that left
    Russian in a system face until a hard reload. A new URL per edit means a
    changed stylesheet is always fetched.
    """
    return {"stylesheet_v": int(STYLESHEET.stat().st_mtime)}


def ledger(request):
    """The header's Clear all appears only when there is something to clear.

    Scoped like every other read — the account, or this browser signed out:
    an unscoped check would offer a newcomer the destroy control for someone
    else's data.
    """
    if not hasattr(request, "user") or not hasattr(request, "session"):
        return {"has_exchanges": False}
    return {"has_exchanges": owned_exchanges(request).exists()}
