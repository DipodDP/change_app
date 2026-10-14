from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Rates are derived from the user's own amounts, so precision matters more than
# range: HUF-per-BYN sits near 100 while BYN-per-HUF sits near 0.01.
RATE_DP = Decimal("0.00000001")


class Currency(models.TextChoices):
    """Currencies a route can pass through.

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
        """Units of received currency per one unit of spent currency."""
        return (self.received_amount / self.spent_amount).quantize(RATE_DP)


class Route(models.Model):
    """A user-curated chain of exchanges, named for the providers involved.

    Kept alongside automatic path-finding because which bank performed the
    conversion is not derivable from the currency pair alone.
    """

    name = models.CharField(_("name"), max_length=120)
    steps = models.ManyToManyField(Exchange, through="RouteStep", related_name="routes")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routes",
        verbose_name=_("owner"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("route")
        verbose_name_plural = _("routes")

    def __str__(self):
        return self.name

    def ordered_steps(self):
        return [s.exchange for s in self.route_steps.select_related("exchange")]


class RouteStep(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="route_steps")
    exchange = models.ForeignKey(Exchange, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        unique_together = [("route", "position")]
