"""
RoutingService — wraps the free OSRM demo API.

One call to /route/v1/driving returns:
  - full route geometry (GeoJSON LineString)
  - total distance in miles
  - waypoints sampled every ~400 miles along the route
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import requests

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving"
METERS_PER_MILE = 1_609.344
WAYPOINT_INTERVAL_MILES = 400.0
WAYPOINT_INTERVAL_METERS = WAYPOINT_INTERVAL_MILES * METERS_PER_MILE
REQUEST_TIMEOUT_SECONDS = 30


# ──────────────────────────────────────────────────────────────────────────────
# Return types
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Waypoint:
    """A geographic point sampled along the route."""
    lat: float
    lng: float
    distance_miles: float  # cumulative distance from the start


@dataclass
class RouteResult:
    """All routing data returned from a single OSRM call."""
    geometry: dict                    # GeoJSON LineString {"type": "LineString", "coordinates": [[lng, lat], ...]}
    distance_miles: float             # total route distance
    duration_seconds: float           # estimated travel time
    waypoints: List[Waypoint] = field(default_factory=list)  # sampled every ~400 mi


# ──────────────────────────────────────────────────────────────────────────────
# Haversine helper
# ──────────────────────────────────────────────────────────────────────────────


def _haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Return the great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ──────────────────────────────────────────────────────────────────────────────
# Waypoint sampler
# ──────────────────────────────────────────────────────────────────────────────


def _sample_waypoints(
    coordinates: List[List[float]],
    interval_meters: float = WAYPOINT_INTERVAL_METERS,
) -> List[Waypoint]:
    """
    Walk the route geometry and emit a Waypoint whenever the cumulative
    distance crosses a multiple of *interval_meters*.

    The start and end points are NOT included; only intermediate checkpoints.

    Parameters
    ----------
    coordinates:
        List of [longitude, latitude] pairs from the GeoJSON geometry.
    interval_meters:
        Spacing between sampled waypoints in metres.

    Returns
    -------
    List of Waypoint objects, each carrying cumulative distance in miles.
    """
    if len(coordinates) < 2:
        return []

    waypoints: List[Waypoint] = []
    cumulative_meters = 0.0
    next_threshold = interval_meters  # first waypoint at ~400 miles

    prev_lon, prev_lat = coordinates[0]

    for lon, lat in coordinates[1:]:
        segment = _haversine_meters(prev_lon, prev_lat, lon, lat)
        cumulative_meters += segment

        # Emit waypoints for every threshold we crossed in this segment
        while cumulative_meters >= next_threshold:
            # Interpolate the exact position at next_threshold
            overshoot = cumulative_meters - next_threshold
            fraction = 1.0 - (overshoot / segment) if segment > 0 else 1.0
            wp_lat = prev_lat + fraction * (lat - prev_lat)
            wp_lon = prev_lon + fraction * (lon - prev_lon)
            waypoints.append(
                Waypoint(
                    lat=round(wp_lat, 6),
                    lng=round(wp_lon, 6),
                    distance_miles=round(next_threshold / METERS_PER_MILE, 2),
                )
            )
            next_threshold += interval_meters

        prev_lon, prev_lat = lon, lat

    return waypoints


# ──────────────────────────────────────────────────────────────────────────────
# Public service class
# ──────────────────────────────────────────────────────────────────────────────


class RoutingService:
    """
    Thin wrapper around the OSRM demo routing API.

    Usage
    -----
    ::
        svc = RoutingService()
        result = svc.get_route(
            start=(41.8781, -87.6298),   # Chicago, IL
            end=(34.0522, -118.2437),    # Los Angeles, CA
        )
        print(result.distance_miles)
        print(len(result.waypoints))
    """

    def __init__(
        self,
        base_url: str = OSRM_BASE_URL,
        waypoint_interval_miles: float = WAYPOINT_INTERVAL_MILES,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.waypoint_interval_meters = waypoint_interval_miles * METERS_PER_MILE
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> RouteResult:
        """
        Fetch the fastest driving route between *start* and *end*.

        Parameters
        ----------
        start:
            ``(latitude, longitude)`` of the origin.
        end:
            ``(latitude, longitude)`` of the destination.

        Returns
        -------
        RouteResult
            Contains the GeoJSON geometry, total distance in miles,
            estimated duration in seconds, and intermediate waypoints
            spaced roughly every 400 miles.

        Raises
        ------
        ValueError
            If OSRM returns a non-OK status code in the JSON body.
        requests.RequestException
            On network or HTTP errors.
        """
        start_lat, start_lng = start
        end_lat, end_lng = end

        # OSRM expects coordinates as "longitude,latitude" pairs separated by ";"
        coords_str = f"{start_lng},{start_lat};{end_lng},{end_lat}"
        url = f"{self.base_url}/{coords_str}"

        params = {
            "overview": "full",       # return the full geometry (not simplified)
            "geometries": "geojson",  # GeoJSON LineString
            "steps": "false",         # no turn-by-turn steps
            "annotations": "false",   # no per-node metadata
        }

        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "Ok":
            raise ValueError(
                f"OSRM returned an error: {data.get('code')} — {data.get('message', 'unknown')}"
            )

        route = data["routes"][0]
        geometry: dict = route["geometry"]               # GeoJSON LineString
        distance_meters: float = route["distance"]       # metres
        duration_seconds: float = route["duration"]      # seconds

        distance_miles = distance_meters / METERS_PER_MILE

        waypoints = _sample_waypoints(
            coordinates=geometry["coordinates"],
            interval_meters=self.waypoint_interval_meters,
        )

        return RouteResult(
            geometry=geometry,
            distance_miles=round(distance_miles, 2),
            duration_seconds=round(duration_seconds, 1),
            waypoints=waypoints,
        )
