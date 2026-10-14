from django.contrib import admin

from .models import Exchange


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    list_display = (
        "spent_amount",
        "spent_currency",
        "received_amount",
        "received_currency",
        "provider",
        "effective_rate",
        "owner",
    )
    list_filter = ("owner", "spent_currency", "received_currency", "provider")
    search_fields = ("provider", "owner__username")

    @admin.display(description="rate")
    def effective_rate(self, obj):
        return f"1 {obj.spent_currency} = {obj.rate.normalize()} {obj.received_currency}"
