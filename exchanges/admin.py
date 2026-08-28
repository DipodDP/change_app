from django.contrib import admin

from .models import Exchange, Route, RouteStep


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


class RouteStepInline(admin.TabularInline):
    model = RouteStep
    extra = 1
    ordering = ("position",)


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    # Derived from the steps' banks by sync_route_names(); anything typed here
    # is overwritten on the next save, so it is shown but not editable.
    readonly_fields = ("name",)
    list_filter = ("owner",)
    search_fields = ("name", "owner__username")
    inlines = [RouteStepInline]
