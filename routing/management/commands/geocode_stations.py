"""
geocode_stations — populates latitude/longitude on FuelStation records.

Strategy
--------
Groups stations by unique (city, state) pair and geocodes *once per pair*,
then bulk-updates every station in that city. This keeps Nominatim calls to
a minimum (one per unique city, not one per station).

Usage
-----
    # Geocode the first 200 unique city/state pairs (safe, ~3-4 minutes)
    python manage.py geocode_stations --limit 200

    # Geocode everything (3,898 pairs, ~65 minutes — run overnight)
    python manage.py geocode_stations

    # Faster delay if using your own Nominatim instance
    python manage.py geocode_stations --delay 0.5
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Count

from routing.models import FuelStation
from routing.services.geocoding import GeocodingService


class Command(BaseCommand):
    help = "Geocode FuelStation records via Nominatim (groups by city/state to minimise API calls)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of city/state pairs to geocode in this run (default: all).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.1,
            help="Seconds to wait between Nominatim requests (default: 1.1 to respect rate limit).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            default=False,
            help="Re-geocode stations that already have coordinates.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        delay = options["delay"]
        overwrite = options["overwrite"]

        svc = GeocodingService()

        # Build ordered list of (city, state) pairs — busiest cities first
        # so partial runs still cover the most stations
        qs = FuelStation.objects

        if not overwrite:
            qs = qs.filter(latitude__isnull=True)

        city_pairs = (
            qs.values("city", "state")
            .annotate(n=Count("id"))
            .order_by("-n")  # most-represented cities first
        )

        if limit:
            city_pairs = city_pairs[:limit]

        total_pairs = len(city_pairs)
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nGeocoding {total_pairs} unique city/state pairs "
                f"({'all' if not limit else f'limit={limit}'}) — "
                f"delay={delay}s per request\n"
            )
        )

        geocoded_stations = 0
        skipped = 0
        failed_pairs = []

        for i, row in enumerate(city_pairs, start=1):
            city  = row["city"]
            state = row["state"]
            count = row["n"]
            query = f"{city}, {state}, USA"

            lat, lon = svc.get_coordinates(query)

            if lat is not None and lon is not None:
                updated = FuelStation.objects.filter(
                    city=city,
                    state=state,
                ).update(latitude=lat, longitude=lon)
                geocoded_stations += updated
                self.stdout.write(
                    f"[{i:>4}/{total_pairs}] OK  {city}, {state:<2}  "
                    f"-> {lat:.5f}, {lon:.5f}  ({updated} stations)"
                )
            else:
                skipped += count
                failed_pairs.append(f"{city}, {state}")
                self.stdout.write(
                    self.style.WARNING(
                        f"[{i:>4}/{total_pairs}] FAIL  {city}, {state}  -- geocoding failed"
                    )
                )

            # Respect Nominatim's 1 req/sec usage policy
            # (GeocodingService caches hits, so cached cities are instant)
            time.sleep(delay)

        # Summary
        self.stdout.write("\n" + "─" * 60)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done!  {geocoded_stations} stations now have coordinates."
            )
        )
        if failed_pairs:
            self.stdout.write(
                self.style.WARNING(f"{len(failed_pairs)} cities failed: {', '.join(failed_pairs[:10])}" +
                                   (" …" if len(failed_pairs) > 10 else ""))
            )
        self.stdout.write(
            "Run again without --limit to geocode remaining pairs.\n"
        )
