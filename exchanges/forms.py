from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django.contrib.auth.forms import AuthenticationForm

from .models import Currency, Exchange
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
            "made_on",
        ]
        labels = {
            "spent_amount": _("I spent"),
            "spent_currency": _("Spent currency"),
            "received_amount": _("I received"),
            "received_currency": _("Received currency"),
            "provider": _("Bank or service"),
            "received_provider": _("Money ends up at"),
            "made_on": _("Date"),
        }
        widgets = {
            "made_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
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
        self.fields["made_on"].required = False

    def clean_made_on(self):
        # A cleared date means the same as an untouched one: it happened today.
        return self.cleaned_data.get("made_on") or timezone.localdate()


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


class StyledLoginForm(StyledFormMixin, AuthenticationForm):
    """Django's login form wearing the app's input styling."""
