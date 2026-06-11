import hashlib
import logging
from typing import Optional, Tuple

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

class GeocodingService:
    """
    A service to geocode addresses or city names using the free Nominatim API.
    It uses Django's caching framework to avoid redundant API calls.
    """

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "FuelRouterAssessment/1.0 (testuser12345@gmail.com)"
    CACHE_TIMEOUT = 60 * 60 * 24 * 30  # 30 days

    def get_coordinates(self, query: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get the latitude and longitude for a given search query.

        Args:
            query (str): The address, city, or location to search for.

        Returns:
            Tuple[Optional[float], Optional[float]]: A tuple containing (latitude, longitude)
            or (None, None) if the geocoding failed or returned no results.
        """
        if not query or not query.strip():
            return None, None

        query = query.strip()
        
        # Create a safe cache key by hashing the query
        query_hash = hashlib.md5(query.lower().encode('utf-8')).hexdigest()
        cache_key = f"geocode_{query_hash}"

        # Check cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Not in cache, call Nominatim
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "addressdetails": 0,
            # We can optionally limit to US if we want, but letting the query dictate is fine
            "countrycodes": "us" 
        }
        
        headers = {
            "User-Agent": self.USER_AGENT
        }

        try:
            response = requests.get(
                self.NOMINATIM_URL, 
                params=params, 
                headers=headers, 
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data and len(data) > 0:
                result = data[0]
                lat = float(result.get("lat"))
                lon = float(result.get("lon"))
                coords = (lat, lon)
                
                # Cache the successful result
                cache.set(cache_key, coords, self.CACHE_TIMEOUT)
                return coords
            else:
                # Cache the empty result for a shorter time to prevent hammering the API for bad queries
                cache.set(cache_key, (None, None), 60 * 60) # 1 hour
                return None, None

        except requests.RequestException as e:
            logger.error(f"Geocoding API request failed for query '{query}': {e}")
            return None, None
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Error parsing geocoding response for query '{query}': {e}")
            return None, None
