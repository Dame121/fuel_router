import csv
import os
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from routing.models import FuelStation


class Command(BaseCommand):
    help = (
        "Load fuel station prices from a CSV file into the FuelStation model. "
        "Expected columns: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            nargs="?",
            default=os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "fuel-prices-for-be-assessment.csv",
            ),
            help="Path to the CSV file (defaults to fuel-prices-for-be-assessment.csv in the project root).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of records per bulk_create batch (default: 500).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing FuelStation records before loading.",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_file"]
        batch_size = options["batch_size"]

        if not os.path.isfile(csv_path):
            raise CommandError(f"CSV file not found: {csv_path}")

        if options["clear"]:
            deleted, _ = FuelStation.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing FuelStation records."))

        stations = []
        skipped = 0
        loaded = 0

        self.stdout.write(f"Reading CSV: {csv_path}")

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for line_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    rack_id_raw = row.get("Rack ID", "").strip()
                    rack_id = int(rack_id_raw) if rack_id_raw else None
                    price = Decimal(row["Retail Price"].strip())

                    station = FuelStation(
                        opis_truckstop_id=opis_id,
                        station_name=row["Truckstop Name"].strip(),
                        address=row["Address"].strip(),
                        city=row["City"].strip(),
                        state=row["State"].strip(),
                        rack_id=rack_id,
                        price_per_gallon=price,
                        # latitude/longitude left null — populate later via geocoding
                    )
                    stations.append(station)

                except (ValueError, KeyError, InvalidOperation) as exc:
                    self.stderr.write(self.style.ERROR(f"  Skipping row {line_num}: {exc} → {dict(row)}"))
                    skipped += 1
                    continue

                # Flush batch
                if len(stations) >= batch_size:
                    FuelStation.objects.bulk_create(stations)
                    loaded += len(stations)
                    self.stdout.write(f"  Inserted {loaded} records so far…")
                    stations = []

        # Insert remaining records
        if stations:
            FuelStation.objects.bulk_create(stations)
            loaded += len(stations)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Loaded {loaded} fuel station records. Skipped {skipped} bad rows."
            )
        )
