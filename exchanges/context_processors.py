from .models import Exchange


def ledger(request):
    """The header's reset control needs to know whether anything is stored."""
    return {"has_exchanges": Exchange.objects.exists()}
