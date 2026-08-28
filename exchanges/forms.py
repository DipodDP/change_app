from decimal import Decimal, InvalidOperation

from django import forms
from django.utils.translation import gettext_lazy as _

from django.contrib.auth.forms import AuthenticationForm

from .models import Currency, Exchange, Route
from .suggestions import currency_choices


class StyledFormMixin:
    """Apply the design-system input classes without repeating them per widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "select"
            elif isinstance(widget, forms.CheckboxInput):
                css = ""
            else:
                css = "input"
            if css:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {css}".strip()


class ExchangeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Exchange
        fields = [
            "spent_amount",
            "spent_currency",
            "received_amount",
            "received_currency",
            "provider",
            "received_provider",
        ]
        labels = {
            "spent_amount": _("I spent"),
            "spent_currency": _("Spent currency"),
            "received_amount": _("I received"),
            "received_currency": _("Received currency"),
            "provider": _("Bank or service"),
            "received_provider": _("Money ends up at"),
        }
        widgets = {
            "spent_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}
            ),
            "received_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}
            ),
            "provider": forms.TextInput(
                attrs={"placeholder": _("e.g. Prior, Wise, Revolut")}
            ),
            "received_provider": forms.TextInput(
                attrs={"placeholder": _("e.g. Prior")}
            ),
        }

    def __init__(self, *args, exchanges=None, **kwargs):
        # The catalog is long; the caller passes the user's own rows so the
        # currencies they actually deal in sit at the top of both selects.
        super().__init__(*args, **kwargs)
        if exchanges is not None:
            choices = currency_choices(exchanges)
            for name in ("spent_currency", "received_currency"):
                self.fields[name].choices = choices

    def clean(self):
        cleaned = super().clean()
        spent = cleaned.get("spent_currency")
        received = cleaned.get("received_currency")
        if spent and received:
            self._reject_if_it_breaks_routes(spent, received)
        return cleaned

    def _reject_if_it_breaks_routes(self, spent, received):
        """Refuse a currency change that would strand a saved route.

        A route is a chain: each step's received currency has to feed the next
        step's spent currency. Editing one leg's currencies can sever that link,
        and the route would then be permanently unusable with no way to repair
        it from the dashboard. Cheaper to stop here than to leave the wreckage.
        """
        if not self.instance.pk:
            return
        if (
            spent == self.instance.spent_currency
            and received == self.instance.received_currency
        ):
            return

        from .routing import chain_rate
        from .suggestions import affected_routes

        broken = []
        for item in affected_routes(self.instance):
            steps = item["steps"]
            # Stand in for the edited record so the chain is checked as it
            # would be after saving, without touching the database.
            probe = [
                Exchange(
                    spent_currency=spent if s.pk == self.instance.pk else s.spent_currency,
                    received_currency=(
                        received if s.pk == self.instance.pk else s.received_currency
                    ),
                    spent_amount=s.spent_amount,
                    received_amount=s.received_amount,
                )
                for s in steps
            ]
            try:
                chain_rate(probe)
            except ValueError:
                broken.append(item["route"].name)

        if broken:
            raise forms.ValidationError(
                _(
                    "This change would break the saved route %(names)s. "
                    "Edit or delete the route first."
                )
                % {"names": ", ".join(broken)}
            )


class CompareForm(StyledFormMixin, forms.Form):
    """The dashboard query: how much, from what, into what, which direction."""

    MODES = [
        ("send", _("I send")),
        ("get", _("I want to get")),
    ]

    mode = forms.ChoiceField(
        label=_("Direction"),
        choices=MODES,
        initial="send",
        required=False,
        widget=forms.RadioSelect,
    )
    amount = forms.DecimalField(
        label=_("Amount"),
        min_value=Decimal("0.01"),
        max_digits=18,
        decimal_places=2,
        initial=Decimal("100"),
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )
    base = forms.ChoiceField(
        label=_("From"), choices=Currency.choices, initial=Currency.BYN
    )
    target = forms.ChoiceField(
        label=_("To"), choices=Currency.choices, initial=Currency.HUF
    )

    def __init__(self, *args, exchanges=None, **kwargs):
        super().__init__(*args, **kwargs)
        if exchanges is not None:
            choices = currency_choices(exchanges)
            for name in ("base", "target"):
                self.fields[name].choices = choices

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("base") and cleaned.get("base") == cleaned.get("target"):
            raise forms.ValidationError(_("Pick two different currencies to compare."))
        return cleaned


class RouteForm(StyledFormMixin, forms.ModelForm):
    """A named chain the user curates by hand."""

    # Submitted by the chip builder as a comma-separated list of ids, so the
    # order the user clicked is preserved (a multi-select cannot express it).
    step_ids = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, owner=None, **kwargs):
        # Without an owner the form would validate against every user's
        # exchanges and happily build a route out of someone else's steps.
        self.owner = owner
        super().__init__(*args, **kwargs)
        self.fields["step_ids"].required = False

    def clean_step_ids(self):
        raw = (self.cleaned_data.get("step_ids") or "").strip()
        if not raw:
            raise forms.ValidationError(_("Add at least one exchange to the route."))
        try:
            pks = [int(x) for x in raw.split(",") if x]
        except ValueError:
            raise forms.ValidationError(_("Could not read the selected steps."))

        available = Exchange.objects.all()
        if self.owner is not None:
            available = available.filter(owner=self.owner)
        found = {e.pk: e for e in available.filter(pk__in=pks)}
        missing = [pk for pk in pks if pk not in found]
        if missing:
            raise forms.ValidationError(_("Some selected exchanges no longer exist."))

        steps = [found[pk] for pk in pks]
        for prev, nxt in zip(steps, steps[1:]):
            if prev.received_currency != nxt.spent_currency:
                raise forms.ValidationError(
                    _("These steps do not connect into a chain.")
                )
        self.ordered_steps = steps
        return raw

    class Meta:
        model = Route
        # The name is derived from the steps' banks by sync_route_names(), so
        # it is not an input; the form only collects the chain itself.
        fields = []


class StyledLoginForm(StyledFormMixin, AuthenticationForm):
    """Django's login form wearing the app's input styling."""
