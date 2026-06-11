from django.db import models


class FuelStation(models.Model):
    opis_truckstop_id = models.IntegerField(db_index=True)
    station_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    price_per_gallon = models.DecimalField(max_digits=8, decimal_places=5)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["state", "city", "station_name"]
        verbose_name = "Fuel Station"
        verbose_name_plural = "Fuel Stations"

    def __str__(self):
        return f"{self.station_name} – {self.city}, {self.state} (${self.price_per_gallon})"
