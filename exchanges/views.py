from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .forms import CompareForm, ExchangeForm
from .models import Currency, Exchange
from .routing import GET, SEND, blocked_chain, compare, group_options, latest_per_lane
from .suggestions import bank_suggestions

SYMBOL = dict(Currency.choices)

# The last comparison run on this device, kept in the session so the
# dashboard reopens on it. Stored with the amount as a string: the session is
# JSON, and a float would round the money.
LAST_COMPARE = "last_compare"


def opening_query(request, exchanges):
    """What the dashboard asks before the user does.

    Their last comparison on this device, while it still has a route — a
    remembered question that now ends on "no route" is the dashboard failing,
    not the user asking. Otherwise their newest conversion, which is certain
    to route. An empty account has no question to ask at all.
    """
    last = request.session.get(LAST_COMPARE)
    if last:
        query = {**last, "amount": Decimal(last["amount"])}
        if compare(exchanges, query["base"], query["target"], query["amount"], mode=query["mode"]):
            return query
    latest = next(
        (e for e in exchanges if e.spent_currency != e.received_currency), None
    )
    if latest:
        return {
            "amount": Decimal("100"),
            "base": latest.spent_currency,
            "target": latest.received_currency,
            "mode": SEND,
        }
    return None


def owned_exchanges(request):
    """Only what this user recorded. Ownership is the whole access model."""
    return Exchange.objects.filter(owner=request.user)


@login_required
def dashboard(request):
    exchanges = list(owned_exchanges(request))

    query = None
    if request.GET:
        form = CompareForm(request.GET, exchanges=exchanges)
        if form.is_valid():
            query = dict(form.cleaned_data)
            query["mode"] = query.get("mode") or SEND
            request.session[LAST_COMPARE] = {
                **query, "amount": str(query["amount"])
            }
    else:
        query = opening_query(request, exchanges)
        form = CompareForm(exchanges=exchanges, initial=query or {})

    results = []
    groups = []
    blocked = None
    if query and exchanges:
        results = compare(
            exchanges,
            query["base"],
            query["target"],
            query["amount"],
            mode=query["mode"],
        )
        groups = group_options(results)
        # Nothing found does not mean nothing is possible. If the chain exists
        # and only the bank changes mid-route, the empty state can say so.
        if not results:
            blocked = blocked_chain(exchanges, query["base"], query["target"])

    return render(
        request,
        "exchanges/dashboard.html",
        {
            "form": form,
            "query": query,
            "results": results,
            "groups": groups,
            "exchanges": exchanges,
            # Older records in a lane are history: listed, but not routed.
            "current": {e.pk for e in latest_per_lane(exchanges)},
            "blocked": blocked,
            "symbols": SYMBOL,
            "is_get_mode": bool(query and query["mode"] == GET),
        },
    )


def _exchange_context(request, form, instance=None):
    # `typed` narrows the list as the user types, so it only applies to what
    # was actually submitted. A record's saved provider is not "typing": using
    # it would filter the list down to that one name and then drop it as an
    # exact match, leaving the edit form with no suggestions at all. There we
    # only exclude the record's own bank, keeping the rest on offer.
    if request.method == "POST":
        typed, exclude = request.POST.get("provider", ""), ""
        # The source bank is where the money already is, so offering it as the
        # destination would describe a transfer that goes nowhere.
        dest_typed = request.POST.get("received_provider", "")
        dest_exclude = request.POST.get("provider", "")
    else:
        typed, exclude = "", (instance.provider if instance else "")
        dest_typed = ""
        # Same reasoning as `exclude` above, for the other end: the record's
        # own destination is already in the field, and its source bank is
        # where the money is leaving from.
        dest_exclude = (
            [instance.provider, instance.received_provider] if instance else []
        )

    # Matching currencies mean a transfer, which is the only kind of row with a
    # second bank. Decided here so the field is already open when an existing
    # transfer is edited, rather than flashing in once scripts run.
    if request.method == "POST":
        shows_destination = request.POST.get("spent_currency") == request.POST.get(
            "received_currency"
        )
    else:
        shows_destination = bool(
            instance and instance.spent_currency == instance.received_currency
        )

    return {
        "form": form,
        "is_edit": instance is not None,
        "exchange": instance,
        "is_transfer": shows_destination,
        "bank_picks": bank_suggestions(
            owned_exchanges(request), typed=typed, exclude=exclude
        ),
        "destination_picks": bank_suggestions(
            owned_exchanges(request), typed=dest_typed, exclude=dest_exclude
        ),
    }


@login_required
def exchange_create(request):
    form = ExchangeForm(request.POST or None, exchanges=owned_exchanges(request))
    if request.method == "POST" and form.is_valid():
        exchange = form.save(commit=False)
        exchange.owner = request.user
        exchange.save()
        messages.success(request, _("Exchange recorded."))
        return redirect(reverse("dashboard"))
    return render(
        request, "exchanges/exchange_form.html", _exchange_context(request, form)
    )


@login_required
def exchange_edit(request, pk):
    exchange = get_object_or_404(owned_exchanges(request), pk=pk)
    form = ExchangeForm(
        request.POST or None, instance=exchange, exchanges=owned_exchanges(request)
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Exchange updated."))
        return redirect(reverse("dashboard"))
    return render(
        request,
        "exchanges/exchange_form.html",
        _exchange_context(request, form, instance=exchange),
    )


@login_required
def exchange_delete(request, pk):
    exchange = get_object_or_404(owned_exchanges(request), pk=pk)
    if request.method == "POST":
        exchange.delete()
        messages.success(request, _("Exchange deleted."))
        return redirect(reverse("dashboard"))
    return render(request, "exchanges/confirm_delete.html", {"object": exchange})


@login_required
def reset_data(request):
    """Clear all — wipe every exchange this user owns.

    It removes everything with no undo and no export, so it goes through the
    same confirmation a single deletion already gets — asking less for the
    larger loss would be exactly backwards.
    """
    exchanges = owned_exchanges(request)
    if not exchanges.exists():
        return redirect(reverse("dashboard"))

    if request.method == "POST" and request.POST.get("confirm"):
        count = exchanges.count()
        exchanges.delete()
        text = ngettext(
            "Cleared %(count)d exchange.",
            "Cleared %(count)d exchanges.",
            count,
        )
        messages.success(request, text % {"count": count})
        return redirect(reverse("dashboard"))
    return render(
        request,
        "exchanges/confirm_reset.html",
        {"exchange_count": exchanges.count()},
    )
