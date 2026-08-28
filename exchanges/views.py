from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .forms import CompareForm, ExchangeForm, RouteForm
from .models import Currency, Exchange, Route, RouteStep
from .routing import GET, SEND, chain_rate, compare, group_options
from .suggestions import (
    affected_routes,
    bank_suggestions,
    name_from_steps,
    repair_routes,
    split_candidates,
    sync_route_names,
)

SYMBOL = dict(Currency.choices)

SEED = [
    ("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
    ("100", Currency.BYN, "28.84", Currency.EUR, "Приорбанк"),
    ("14.02", Currency.EUR, "5000", Currency.HUF, "OTP"),
    ("100", Currency.BYN, "33.26", Currency.USD, "Freedom"),
    ("7.34", Currency.USD, "2200", Currency.HUF, "Wise"),
]


def owned_exchanges(request):
    """Only what this user recorded. Ownership is the whole access model."""
    return Exchange.objects.filter(owner=request.user)


def owned_routes(request):
    return Route.objects.filter(owner=request.user)


@login_required
def dashboard(request):
    exchanges = list(owned_exchanges(request))
    form = CompareForm(request.GET or None, exchanges=exchanges)

    query = None
    if request.GET and form.is_valid():
        query = dict(form.cleaned_data)
        query["mode"] = query.get("mode") or SEND
    elif not request.GET:
        query = {
            "amount": Decimal("100"),
            "base": Currency.BYN,
            "target": Currency.HUF,
            "mode": SEND,
        }

    results = []
    groups = []
    if query and exchanges:
        results = compare(
            exchanges,
            query["base"],
            query["target"],
            query["amount"],
            mode=query["mode"],
        )
        groups = group_options(results)

    saved = []
    for route in owned_routes(request).prefetch_related("route_steps__exchange"):
        steps = route.ordered_steps()
        if not steps:
            continue
        try:
            rate = chain_rate(steps)
            broken = False
        except ValueError:
            rate = None
            broken = True
        saved.append(
            {
                "route": route,
                "steps": steps,
                "rate": rate,
                "broken": broken,
                "from_currency": steps[0].spent_currency,
                "to_currency": steps[-1].received_currency,
            }
        )

    # «в N маршрутах» — how much each recorded exchange is actually relied on
    usage = {e.pk: e.routes.count() for e in exchanges}
    rows = [{"exchange": e, "used": usage.get(e.pk, 0)} for e in exchanges]

    return render(
        request,
        "exchanges/dashboard.html",
        {
            "form": form,
            "query": query,
            "results": results,
            "groups": groups,
            "rows": rows,
            "exchanges": exchanges,
            "saved_routes": saved,
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
    else:
        typed, exclude = "", (instance.provider if instance else "")

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
        "affected": affected_routes(instance) if instance else [],
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
        # A route named after its banks is stale as soon as one of them changes.
        renamed = sync_route_names(exchange, owner=request.user)
        messages.success(request, _("Exchange updated."))
        if renamed:
            messages.success(
                request,
                _("Renamed %(names)s to match the new bank.")
                % {"names": ", ".join(r.name for r in renamed)},
            )
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
        # The cascade takes the RouteStep but leaves the route holding a gap in
        # its positions, a stale bank name, or nothing at all.
        dropped = repair_routes(owner=request.user)
        sync_route_names(owner=request.user)
        messages.success(request, _("Exchange deleted."))
        if dropped:
            messages.success(
                request,
                ngettext(
                    "%(count)d route had no steps left and was removed.",
                    "%(count)d routes had no steps left and were removed.",
                    dropped,
                )
                % {"count": dropped},
            )
        return redirect(reverse("dashboard"))
    return render(request, "exchanges/confirm_delete.html", {"object": exchange})


def _route_context(request, form, chosen, instance=None):
    fits, unfits = split_candidates(owned_exchanges(request), chosen)
    return {
        "form": form,
        "route": instance,
        "chosen": chosen,
        "step_ids": ",".join(str(e.pk) for e in chosen),
        "fitting": fits,
        "not_fitting": unfits,
        "tail": chosen[-1].received_currency if chosen else None,
        "derived_name": name_from_steps(chosen) if chosen else "",
        # A chain assembled from a rejected submission may not connect; show no
        # rate rather than crashing, the form error explains why.
        "through_rate": _safe_chain_rate(chosen),
    }


def _safe_chain_rate(steps):
    if not steps:
        return None
    try:
        return chain_rate(steps)
    except ValueError:
        return None


def _chosen_from(request):
    raw = request.POST.get("step_ids", "") or request.GET.get("step_ids", "")
    pks = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    found = {e.pk: e for e in owned_exchanges(request).filter(pk__in=pks)}
    return [found[pk] for pk in pks if pk in found]


def _save_route(request, form, chosen, instance=None):
    """Persist a route and its ordered steps, then resync every name."""
    route = instance or Route()
    if instance is None:
        route.owner = request.user
    # The name is derived, so a placeholder is enough until sync runs.
    route.name = route.name or _("Unnamed route")
    route.save()

    # Replace wholesale: positions must match the submitted order exactly.
    route.route_steps.all().delete()
    for position, exchange in enumerate(form.ordered_steps):
        RouteStep.objects.create(route=route, exchange=exchange, position=position)

    sync_route_names(owner=request.user)
    return route


@login_required
def route_create(request):
    chosen = _chosen_from(request)

    # The chip builder posts back to refine the chain before saving.
    if request.method == "POST" and request.POST.get("action") in {"add", "remove"}:
        return render(
            request,
            "exchanges/route_form.html",
            _route_context(request, RouteForm(owner=request.user), chosen),
        )

    form = RouteForm(request.POST or None, owner=request.user)
    if request.method == "POST" and form.is_valid():
        _save_route(request, form, chosen)
        messages.success(request, _("Route saved."))
        return redirect(reverse("dashboard"))

    return render(
        request, "exchanges/route_form.html", _route_context(request, form, chosen)
    )


@login_required
def route_edit(request, pk):
    route = get_object_or_404(owned_routes(request), pk=pk)
    # On first view the chain comes from the route; afterwards from the builder.
    chosen = _chosen_from(request) if request.method == "POST" else route.ordered_steps()

    if request.method == "POST" and request.POST.get("action") in {"add", "remove"}:
        return render(
            request,
            "exchanges/route_form.html",
            _route_context(
                request, RouteForm(instance=route, owner=request.user), chosen, instance=route
            ),
        )

    form = RouteForm(request.POST or None, instance=route, owner=request.user)
    if request.method == "POST" and form.is_valid():
        _save_route(request, form, chosen, instance=route)
        messages.success(request, _("Route updated."))
        return redirect(reverse("dashboard"))

    if request.method == "POST":
        # Rejected edit: show the submitted chain with its error, keep the saved
        # steps untouched in the database.
        return render(
            request,
            "exchanges/route_form.html",
            _route_context(request, form, chosen, instance=route),
        )

    return render(
        request,
        "exchanges/route_form.html",
        _route_context(request, form, chosen, instance=route),
    )


@login_required
def route_delete(request, pk):
    route = get_object_or_404(owned_routes(request), pk=pk)
    if request.method == "POST":
        route.delete()
        messages.success(request, _("Route deleted."))
        return redirect(reverse("dashboard"))
    return render(request, "exchanges/confirm_delete.html", {"object": route})


@login_required
def reset_data(request):
    """«очистить» / «демо-данные» — wipe, or reload the worked example."""
    if request.method != "POST":
        return redirect(reverse("dashboard"))

    if owned_exchanges(request).exists():
        owned_routes(request).delete()
        owned_exchanges(request).delete()
        messages.success(request, _("All exchanges cleared."))
    else:
        owner = request.user
        for spent, sc, received, rc, provider in SEED:
            Exchange.objects.create(
                spent_amount=Decimal(spent),
                spent_currency=sc,
                received_amount=Decimal(received),
                received_currency=rc,
                provider=provider,
                owner=owner,
            )
        messages.success(request, _("Demo data loaded."))
    return redirect(reverse("dashboard"))
