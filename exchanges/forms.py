from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import formats, timezone
from django.utils.translation import gettext_lazy as _

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Currency, Exchange
from .suggestions import currency_choices, latest_conversion


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


class AmountField(forms.DecimalField):
    """A decimal that also takes a comma and grouping spaces.

    A phone keypad in a Russian region types 28,84, and people copy 1 000.00
    from a receipt. Both mean one number; refusing them fails the user at the
    counter for a formatting choice, not a mistake.
    """

    widget = forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off", "class": "num"})

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        return super().to_python(value)


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
        field_classes = {"spent_amount": AmountField, "received_amount": AmountField}
        widgets = {
            # Text in the page's own date format: a date input draws the
            # browser's locale instead, so an English browser showed mm/dd/yyyy
            # on the Russian page. The template pairs it with a calendar button
            # that borrows the browser's picker. No inputmode: a numeric keypad
            # has no dot to type 05.03.2026 with.
            "made_on": forms.DateInput(
                attrs={"autocomplete": "off", "class": "num",
                       "placeholder": _("YYYY-MM-DD")}
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
            # Both selects would otherwise open on the same currency, which is
            # a transfer: the form would describe the rare case by default.
            # The direction of the user's latest conversion is the likely next
            # one; with none yet, the most common pair.
            if not self.is_bound and not self.instance.pk:
                latest = latest_conversion(exchanges)
                spent, received = (
                    (latest.spent_currency, latest.received_currency)
                    if latest
                    else (Currency.USD, Currency.EUR)
                )
                self.initial.setdefault("spent_currency", spent)
                self.initial.setdefault("received_currency", received)
        self.fields["made_on"].required = False
        # A route only continues at the bank holding the money; an unnamed one
        # would chain to every bank and invent routes. The model stays blank
        # for rows saved before this.
        self.fields["provider"].required = True
        # The calendar writes its pick back in the format the field shows.
        self.fields["made_on"].widget.attrs["data-format"] = formats.get_format(
            "DATE_INPUT_FORMATS"
        )[0]

    def clean_made_on(self):
        # A cleared date means the same as an untouched one: it happened today.
        made_on = self.cleaned_data.get("made_on") or timezone.localdate()
        # A rate is a conversion already made. The server keeps UTC, so one
        # day of slack lets a traveller east of it record their own today.
        if made_on > timezone.localdate() + timedelta(days=1):
            raise forms.ValidationError(_("The date cannot be in the future."))
        return made_on


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
    amount = AmountField(
        label=_("Amount"),
        min_value=Decimal("0.01"),
        max_digits=18,
        decimal_places=2,
        initial=Decimal("100"),
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
    """Django's login form wearing the app's input styling.

    The account's username is its email, stored lowercase, so the field asks
    for an email and folds case before Django looks the account up.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        username = self.fields["username"]
        username.label = _("Email")
        username.widget.input_type = "email"
        username.widget.attrs["autocomplete"] = "email"

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class RegisterForm(StyledFormMixin, UserCreationForm):
    """An email and a password. The email doubles as the username, so the
    stock sign-in works unchanged."""

    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("email",)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
