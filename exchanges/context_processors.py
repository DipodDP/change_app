from .models import Exchange


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
