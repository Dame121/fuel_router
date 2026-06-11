import hashlib
from django.core.cache import cache
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.services.geocoding import GeocodingService
from routing.services.optimizer import FuelOptimizer
from routing.services.routing import RoutingService


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(required=True, max_length=255)
    end = serializers.CharField(required=True, max_length=255)


class RouteAPIView(APIView):
    """
    POST /api/route/
    Accepts 'start' and 'end' location strings.
    Returns optimal route geometry and recommended fuel stops.
    """

    MPG = 10.0  # Assumed vehicle fuel efficiency

    def post(self, request, *args, **kwargs):
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        start_location = serializer.validated_data["start"]
        end_location = serializer.validated_data["end"]

        # 0. Check Cache
        norm_start = start_location.lower().strip()
        norm_end = end_location.lower().strip()
        cache_key = f"route_{hashlib.md5(f'{norm_start}_{norm_end}'.encode('utf-8')).hexdigest()}"

        cached_response = cache.get(cache_key)
        if cached_response:
            return Response(cached_response, status=status.HTTP_200_OK)

        # 1. Geocode locations
        geocoder = GeocodingService()
        
        start_coords = geocoder.get_coordinates(start_location)
        if start_coords == (None, None):
            return Response(
                {"error": f"Could not geocode start location: '{start_location}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        end_coords = geocoder.get_coordinates(end_location)
        if end_coords == (None, None):
            return Response(
                {"error": f"Could not geocode end location: '{end_location}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Call Routing Service
        routing_svc = RoutingService()
        try:
            route_result = routing_svc.get_route(start=start_coords, end=end_coords)
        except Exception as e:
            return Response(
                {"error": f"Failed to calculate route: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # 3. Run Fuel Optimizer
        optimizer = FuelOptimizer()
        fuel_stops = optimizer.optimize(
            waypoints=route_result.waypoints,
            total_route_miles=route_result.distance_miles,
        )

        # 4. Calculate Costs
        total_miles = route_result.distance_miles
        total_gallons = total_miles / self.MPG

        # Calculate average price from the actual stops if any, otherwise default or 0
        if fuel_stops:
            avg_price = sum(stop.price_per_gallon for stop in fuel_stops) / len(fuel_stops)
        else:
            avg_price = 0.0

        total_fuel_cost_usd = total_gallons * avg_price

        # 5. Format Output
        stops_output = []
        for stop in fuel_stops:
            stops_output.append({
                "station_name": stop.station_name,
                "address": stop.address,
                "city": stop.city,
                "state": stop.state,
                "price": stop.price_per_gallon,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
            })

        response_data = {
            "route_geometry": route_result.geometry,
            "fuel_stops": stops_output,
            "total_miles": round(total_miles, 2),
            "total_gallons": round(total_gallons, 2),
            "total_fuel_cost_usd": round(total_fuel_cost_usd, 2),
        }

        # Cache the successful response for 1 hour
        cache.set(cache_key, response_data, 60 * 60)

        return Response(response_data, status=status.HTTP_200_OK)
