"""Location-based searching and distance calculations."""

import logging

try:
    from geopy.distance import distance
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
except ImportError:
    distance = None
    Nominatim = None
    GeocoderTimedOut = Exception
    GeocoderServiceError = Exception

from .constants import Constants
from .exceptions import ConfigurationError, GPSDataError
from .types import SearchConfig


class LocationSearchEngine:
    """Handles location-based searching and distance calculations."""
    
    def __init__(self, search_config: SearchConfig, logger: logging.Logger):
        self.search_config = search_config
        self.logger = logger
        self.search_coords: tuple[float, float] | None = None
        
        if not Nominatim or not distance:
            raise ImportError("geopy library is required for location search. Install with: pip install geopy")
            
        self.geolocator = Nominatim(user_agent=Constants.DEFAULT_USER_AGENT)
        
    def initialize_search_location(self) -> None:
        """Initialize the search location from address or coordinates."""
        if self.search_config.address:
            try:
                location = self.geolocator.geocode(query=self.search_config.address)
                if location:
                    self.search_coords = (location.latitude, location.longitude)
                    self.logger.info(f"Nominatim address: {location.address}")
                    self.logger.info(f"Lat, Lon: {location.latitude}, {location.longitude}")
                else:
                    raise ConfigurationError("No location found from Nominatim")
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                raise ConfigurationError(f"Geocoding failed: {e}")
                
        elif self.search_config.latitude and self.search_config.longitude:
            try:
                location = self.geolocator.reverse(
                    query=f"{self.search_config.latitude}, {self.search_config.longitude}"
                )
                if location:
                    self.search_coords = (self.search_config.latitude, self.search_config.longitude)
                    self.logger.info(f"Reverse geocoded address: {location.address}")
                    self.logger.info(f"Lat, Lon: {self.search_config.latitude}, {self.search_config.longitude}")
                else:
                    raise ConfigurationError("Invalid coordinates provided")
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                raise ConfigurationError(f"Coordinate validation failed: {e}")
        else:
            raise ConfigurationError("Either address or coordinates must be provided")
    
    def calculate_distance_miles(self, image_coords: tuple[float, float]) -> float:
        """Calculate distance in miles between search coords and image coords."""
        if not self.search_coords:
            raise GPSDataError("Search coordinates not initialized")
        return distance(self.search_coords, image_coords).miles
    
    def is_within_radius(self, image_coords: tuple[float, float]) -> bool:
        """Check if image coordinates are within the search radius."""
        distance_miles = self.calculate_distance_miles(image_coords)
        return distance_miles <= self.search_config.radius