"""
FuelOptimizer — finds the cheapest fuel stations at each required stop along a route.

Algorithm
---------
1. Given route waypoints (spaced ~400 miles apart), use a greedy algorithm to
   identify the minimum set of stops where refuelling is REQUIRED given the
   vehicle's maximum range (default 500 miles).

2. At each required stop, query the database for the cheapest FuelStation
   within ``search_radius_miles`` (default 10 miles).

3. The database query uses a bounding-box ORM pre-filter for speed, then
   annotates candidates with the exact Haversine distance via Django ORM
   math functions (Sin, Cos, ASin, Radians, Sqrt, Power).
   No external API calls are made.

Notes
-----
The FuelStation rows must have ``latitude`` and ``longitude`` populated
before this service returns results. Use a geocoding step to fill those
fields after loading from the CSV.
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from django.db.models import ExpressionWrapper, FloatField, F, Value
from django.db.models.functions import ASin, Cos, Power, Radians, Sin, Sqrt

from routing.models import FuelStation
from routing.services.routing import Waypoint

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

EARTH_RADIUS_MILES = 3_958.8          # mean radius of Earth in miles
MILES_PER_DEGREE_LAT = 69.0          # approximate, constant across latitudes
DEFAULT_MAX_RANGE_MILES = 500.0
DEFAULT_SEARCH_RADIUS_MILES = 10.0


# ──────────────────────────────────────────────────────────────────────────────
# Return type
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class StationRecommendation:
    """A fuel station recommended as a stop along the route."""

    station_id: int
    station_name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    price_per_gallon: float            # USD per gallon
    distance_from_waypoint_miles: float  # off-route distance to this station
    waypoint_distance_miles: float     # cumulative route distance of this fuel stop


# ──────────────────────────────────────────────────────────────────────────────
# Main class
# ──────────────────────────────────────────────────────────────────────────────


class FuelOptimizer:
    """
    Recommends the cheapest fuel stations along a driving route.

    Parameters
    ----------
    max_range_miles:
        Maximum distance the vehicle can travel on a full tank (default 500 mi).
    search_radius_miles:
        Radius around each required fuel stop to search for stations (default 10 mi).

    Usage
    -----
    ::

        from routing.services.routing import RoutingService
        from routing.services.optimizer import FuelOptimizer

        route  = RoutingService().get_route(
            start=(41.8781, -87.6298),   # Chicago
            end=(34.0522, -118.2437),    # Los Angeles
        )
        stops = FuelOptimizer().optimize(route.waypoints, route.distance_miles)

        for s in stops:
            print(f"{s.waypoint_distance_miles:.0f} mi  {s.station_name}  ${s.price_per_gallon:.3f}/gal")
    """

    def __init__(
        self,
        max_range_miles: float = DEFAULT_MAX_RANGE_MILES,
        search_radius_miles: float = DEFAULT_SEARCH_RADIUS_MILES,
    ) -> None:
        self.max_range_miles = max_range_miles
        self.search_radius_miles = search_radius_miles

    # ── Public ────────────────────────────────────────────────────────────────

    def optimize(
        self,
        waypoints: List[Waypoint],
        total_route_miles: float,
    ) -> List[StationRecommendation]:
        """
        Return an ordered list of recommended fuel stations, one per required stop.

        Parameters
        ----------
        waypoints:
            Intermediate route waypoints from ``RoutingService.get_route()``,
            each spaced ~400 miles apart.
        total_route_miles:
            Total length of the route in miles (used to evaluate the last leg).

        Returns
        -------
        List of ``StationRecommendation`` objects in route order (earliest stop
        first).  If no station with coordinates exists within the search radius
        of a required stop, that stop is omitted with a warning printed to
        stdout.
        """
        required_stops = self._identify_required_stops(waypoints, total_route_miles)
        recommendations: List[StationRecommendation] = []

        for stop_wp in required_stops:
            rec = self._find_cheapest_station(
                lat=stop_wp.lat,
                lon=stop_wp.lng,
                waypoint_distance_miles=stop_wp.distance_miles,
            )
            if rec is not None:
                recommendations.append(rec)
            else:
                print(
                    f"[FuelOptimizer] WARNING: no station with coordinates found "
                    f"within {self.search_radius_miles} miles of waypoint at "
                    f"{stop_wp.distance_miles:.0f} mi "
                    f"(lat={stop_wp.lat}, lng={stop_wp.lng}). "
                    f"Populate FuelStation.latitude/longitude via geocoding."
                )

        return recommendations

    # ── Private helpers ───────────────────────────────────────────────────────

    def _identify_required_stops(
        self,
        waypoints: List[Waypoint],
        total_route_miles: float,
    ) -> List[Waypoint]:
        """
        Greedy algorithm to find the minimum set of waypoints where refuelling
        is mandatory.

        Rules
        -----
        * The vehicle departs with a full tank (max_range_miles available).
        * At each waypoint, check whether the *next* checkpoint (waypoint or
          destination) is reachable without refuelling from the last stop.
        * If not, this waypoint is added to the required-stop list and
          becomes the new "last refuel" position.
        """
        if not waypoints:
            return []

        required: List[Waypoint] = []
        last_refuel_miles = 0.0  # full tank at route start

        for i, wp in enumerate(waypoints):
            # Distance of the next checkpoint (next waypoint or final destination)
            if i + 1 < len(waypoints):
                next_checkpoint = waypoints[i + 1].distance_miles
            else:
                next_checkpoint = total_route_miles

            # Cannot reach next checkpoint from last refuel → must stop here
            if next_checkpoint - last_refuel_miles > self.max_range_miles:
                required.append(wp)
                last_refuel_miles = wp.distance_miles

        return required

    def _find_cheapest_station(
        self,
        lat: float,
        lon: float,
        waypoint_distance_miles: float,
    ) -> Optional[StationRecommendation]:
        """
        Query the DB for the cheapest FuelStation within ``search_radius_miles``
        of (lat, lon).

        Implementation
        ~~~~~~~~~~~~~~
        1. **Bounding-box pre-filter** (ORM ``__range`` lookups) eliminates the
           vast majority of the table without any trig.  One degree of latitude
           ≈ 69 miles; longitude varies with cos(lat).

        2. **Annotated Haversine queryset**: the surviving candidates are
           annotated with the exact great-circle distance (in miles) using
           Django ORM math functions — ``Sin``, ``Cos``, ``Radians``, ``ASin``,
           ``Sqrt``, ``Power``.  This runs entirely inside the database engine
           (SQLite in dev, Postgres in prod).  No external calls.

           Formula:
               a = sin²(Δlat/2) + cos(lat_ref) · cos(lat_db) · sin²(Δlon/2)
               d = 2 · R · asin(√a)

        3. The result is **ordered by price_per_gallon ASC, distance_miles ASC**
           so the single cheapest station within radius is retrieved with
           ``.first()``.

        Returns ``None`` if no geocoded station exists within the radius.
        """
        cos_ref_lat = math.cos(math.radians(lat))

        # Degree deltas for the bounding box
        lat_delta = self.search_radius_miles / MILES_PER_DEGREE_LAT
        lon_delta = (
            self.search_radius_miles / (MILES_PER_DEGREE_LAT * cos_ref_lat)
            if cos_ref_lat > 1e-9
            else 360.0
        )

        # Reference point in radians (evaluated once in Python, not per-row in SQL)
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)

        # ── Build the Haversine distance annotation ───────────────────────────
        # Each sub-expression is wrapped explicitly so Django knows the output type.

        # Δlat / 2  and  Δlon / 2  (in radians)
        half_dlat = ExpressionWrapper(
            (Radians(F("latitude")) - Value(lat_rad)) / Value(2.0),
            output_field=FloatField(),
        )
        half_dlon = ExpressionWrapper(
            (Radians(F("longitude")) - Value(lon_rad)) / Value(2.0),
            output_field=FloatField(),
        )

        # a = sin²(Δlat/2) + cos(lat_ref) · cos(lat_db) · sin²(Δlon/2)
        a_expr = ExpressionWrapper(
            Power(Sin(half_dlat), 2)
            + Value(cos_ref_lat) * Cos(Radians(F("latitude"))) * Power(Sin(half_dlon), 2),
            output_field=FloatField(),
        )

        # d = 2 · R · asin(√a)   [miles]
        distance_expr = ExpressionWrapper(
            Value(2.0 * EARTH_RADIUS_MILES) * ASin(Sqrt(a_expr)),
            output_field=FloatField(),
        )

        # ── Execute the query ─────────────────────────────────────────────────
        best = (
            FuelStation.objects
            # Only consider rows with geocoordinates
            .filter(latitude__isnull=False, longitude__isnull=False)
            # Fast bounding-box pre-filter
            .filter(
                latitude__range=(lat - lat_delta, lat + lat_delta),
                longitude__range=(lon - lon_delta, lon + lon_delta),
            )
            # Exact Haversine distance annotation
            .annotate(distance_miles=distance_expr)
            # Exact radius filter
            .filter(distance_miles__lte=self.search_radius_miles)
            # Cheapest first; ties broken by proximity
            .order_by("price_per_gallon", "distance_miles")
            .first()
        )

        if best is None:
            return None

        return StationRecommendation(
            station_id=best.id,
            station_name=best.station_name,
            address=best.address,
            city=best.city,
            state=best.state,
            latitude=best.latitude,
            longitude=best.longitude,
            price_per_gallon=float(best.price_per_gallon),
            distance_from_waypoint_miles=round(best.distance_miles, 3),
            waypoint_distance_miles=waypoint_distance_miles,
        )
