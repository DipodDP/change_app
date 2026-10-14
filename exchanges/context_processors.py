from django.conf import settings

from .models import Exchange

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
    """The header's reset control needs to know whether anything is stored.

    Scoped to the signed-in account: the control toggles between loading demo
    data and wiping the ledger, so an unscoped check would offer a brand-new
    user the destroy label for someone else's data.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"has_exchanges": False}
    return {"has_exchanges": Exchange.objects.filter(owner=user).exists()}
