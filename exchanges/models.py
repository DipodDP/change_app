from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _



class Currency(models.TextChoices):
    """Currencies an exchange can be made in.

    Labels are the symbol where one is in common use and the code otherwise,
    since a bare "лв" or "₼" is only a hint — the dropdown shows both.
    """

    AED = "AED", "د.إ"
    AMD = "AMD", "֏"
    AZN = "AZN", "₼"
    BGN = "BGN", "лв"
    BYN = "BYN", "BYN"
    CHF = "CHF", "CHF"
    CNY = "CNY", "¥"
    CZK = "CZK", "Kč"
    EUR = "EUR", "€"
    GBP = "GBP", "£"
    GEL = "GEL", "₾"
    HUF = "HUF", "Ft"
    ILS = "ILS", "₪"
    INR = "INR", "₹"
    JPY = "JPY", "¥"
    KGS = "KGS", "с"
    KZT = "KZT", "₸"
    MDL = "MDL", "L"
    NOK = "NOK", "kr"
    PLN = "PLN", "zł"
    RON = "RON", "lei"
    RSD = "RSD", "дин"
    RUB = "RUB", "₽"
    SEK = "SEK", "kr"
    THB = "THB", "฿"
    TRY = "TRY", "₺"
    UAH = "UAH", "₴"
    USD = "USD", "$"
    UZS = "UZS", "soʻm"
    VND = "VND", "₫"


class Exchange(models.Model):
    """One conversion the user actually performed.

    Stored as the two amounts rather than a rate: the user knows what they
    handed over and what they got back, and the effective rate (commission
    already baked in) falls out of the pair.
    """

    spent_amount = models.DecimalField(
        _("spent amount"),
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    spent_currency = models.CharField(
        _("spent currency"), max_length=3, choices=Currency.choices
    )
    received_amount = models.DecimalField(
        _("received amount"),
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    received_currency = models.CharField(
        _("received currency"), max_length=3, choices=Currency.choices
    )
    provider = models.CharField(_("provider"), max_length=80, blank=True)
    # Only a transfer needs this: money that leaves one bank and lands in
    # another. Blank means the funds stay where `provider` put them. Keeping it
    # a separate field means renaming a bank cannot sever the link the way a
    # convention buried in the provider string could.
    received_provider = models.CharField(
        _("destination provider"), max_length=80, blank=True
    )
    # Kept nullable and SET_NULL: a conversion you made is history, and losing
    # the account should not erase the record of it.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exchanges",
        verbose_name=_("owner"),
    )
    # A signed-out visitor's rows, keyed to their browser session until they
    # sign in and the rows move to the account. Never set alongside `owner`:
    # an ownerless row with no key is history from a deleted account.
    guest_key = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    # When the conversion happened, which is not when it was typed in: a
    # backlog entered later must not pass for the newest rate.
    made_on = models.DateField(_("date"), default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-made_on", "-created_at", "-pk"]
        verbose_name = _("exchange")
        verbose_name_plural = _("exchanges")

    def __str__(self):
        return (
            f"{self.spent_amount} {self.spent_currency} → "
            f"{self.received_amount} {self.received_currency}"
        )

    @property
    def rate(self) -> Decimal:
        """Units of received currency per one unit of spent currency.

        Unrounded: VND-per-USD sits near 0.00004, where 8 places keep only four
        digits and lose cents on the round trip. Display rounds, maths does not.
        """
        return self.received_amount / self.spent_amount
