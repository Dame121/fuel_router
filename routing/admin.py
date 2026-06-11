from django.contrib import admin
from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("station_name", "city", "state", "price_per_gallon", "opis_truckstop_id")
    list_filter = ("state",)
    search_fields = ("station_name", "city", "state", "address")
