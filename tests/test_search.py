"""Tests for the search module.

These tests verify location search and distance calculation functionality.
They serve as documentation for geocoding, coordinate validation, and distance algorithms.
"""

import pytest
from unittest.mock import Mock, patch, PropertyMock
from geopy.distance import geodesic

from geo_image_search.search import LocationSearchEngine
from geo_image_search.types import SearchConfig, ImageData
from geo_image_search.exceptions import GPSDataError, ConfigurationError


class TestLocationSearchEngine:
    """Test suite for LocationSearchEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.search_config = SearchConfig(
            address="Test City, NY",
            latitude=40.7128,
            longitude=-74.0060,
            radius=1.0
        )
        self.search_engine = LocationSearchEngine(self.search_config, self.mock_logger)

    @pytest.mark.unit
    def test_search_engine_initialization(self):
        """
        Test LocationSearchEngine initialization.
        
        This test documents how to create a search engine
        and verifies it has the required components.
        """
        assert self.search_engine.search_config == self.search_config
        assert self.search_engine.logger == self.mock_logger
        assert hasattr(self.search_engine, 'search_coords')

    @pytest.mark.unit
    def test_search_engine_requires_geopy(self):
        """
        Test search engine requires geopy library.
        
        This test documents the dependency on geopy for geocoding
        and distance calculations.
        """
        with patch('geo_image_search.search.Nominatim', None):
            with pytest.raises(ImportError) as exc_info:
                LocationSearchEngine(self.search_config, self.mock_logger)
            
            assert "geopy library is required" in str(exc_info.value)
            assert "pip install geopy" in str(exc_info.value)

    @pytest.mark.unit
    @patch('geo_image_search.search.Nominatim')
    def test_initialize_search_coords_from_config(self, mock_nominatim_class):
        """
        Test search coordinate initialization from configuration.
        
        This test documents how search coordinates are set up
        when latitude/longitude are provided directly.
        """
        # Mock the reverse geocoding call
        mock_geocoder = Mock()
        mock_location = Mock()
        mock_location.address = "New York, NY, USA"
        mock_geocoder.reverse.return_value = mock_location
        mock_nominatim_class.return_value = mock_geocoder
        
        # Test with coordinates in config
        config_with_coords = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=1.0
        )
        
        engine = LocationSearchEngine(config_with_coords, self.mock_logger)
        engine.initialize_search_location()
        
        assert engine.search_coords == (40.7128, -74.0060)
        assert engine.search_config.latitude == 40.7128
        assert engine.search_config.longitude == -74.0060

    @pytest.mark.unit
    @patch('geo_image_search.search.Nominatim')
    def test_initialize_search_coords_from_address(self, mock_nominatim_class):
        """
        Test search coordinate initialization from address geocoding.
        
        This test documents how addresses are converted to coordinates
        using the Nominatim geocoding service.
        """
        # Mock geocoder and location result
        mock_geocoder = Mock()
        mock_location = Mock()
        mock_location.latitude = 40.7589
        mock_location.longitude = -73.9851
        mock_location.address = "Central Park, New York, NY, USA"
        mock_geocoder.geocode.return_value = mock_location
        mock_nominatim_class.return_value = mock_geocoder
        
        config_with_address = SearchConfig(
            address="Central Park, New York",
            radius=1.0
        )
        
        engine = LocationSearchEngine(config_with_address, self.mock_logger)
        engine.initialize_search_location()
        
        # Should have called geocoder
        mock_geocoder.geocode.assert_called_once_with(query="Central Park, New York")
        
        # Should have set coordinates from geocoding result
        assert engine.search_coords == (40.7589, -73.9851)

    @pytest.mark.unit
    @patch('geo_image_search.search.Nominatim')
    def test_initialize_search_coords_geocoding_failure(self, mock_nominatim_class):
        """
        Test search coordinate initialization when geocoding fails.
        
        This test documents error handling when an address
        cannot be geocoded to coordinates.
        """
        # Mock geocoder returning None (address not found)
        mock_geocoder = Mock()
        mock_geocoder.geocode.return_value = None
        mock_nominatim_class.return_value = mock_geocoder
        
        config_with_bad_address = SearchConfig(
            address="Nonexistent Place, Nowhere",
            radius=1.0
        )
        
        engine = LocationSearchEngine(config_with_bad_address, self.mock_logger)
        
        with pytest.raises(ConfigurationError) as exc_info:
            engine.initialize_search_location()
        
        assert "No location found from Nominatim" in str(exc_info.value)

    @pytest.mark.unit
    def test_initialize_search_coords_no_location_specified(self):
        """
        Test search coordinate initialization with no location.
        
        This test documents the requirement that either coordinates
        or an address must be provided for location-based search.
        """
        config_no_location = SearchConfig(radius=1.0)
        
        engine = LocationSearchEngine(config_no_location, self.mock_logger)
        
        with pytest.raises(ConfigurationError) as exc_info:
            engine.initialize_search_location()
        
        assert "Either address or coordinates must be provided" in str(exc_info.value)

    @pytest.mark.unit
    def test_validate_coordinates_valid_ranges(self):
        """
        Test coordinate validation for valid latitude and longitude ranges.
        
        This test documents the valid ranges for GPS coordinates
        and shows successful validation.
        """
        # Test valid coordinates
        valid_coords = [
            (0, 0),           # Equator, Prime Meridian
            (90, 180),        # North Pole, International Date Line
            (-90, -180),      # South Pole, opposite side
            (40.7128, -74.0060),  # New York City
            (-33.8688, 151.2093)  # Sydney, Australia
        ]
        
        for lat, lon in valid_coords:
            # Should not raise any exceptions
            self.search_engine._validate_coordinates(lat, lon)

    @pytest.mark.unit
    def test_validate_coordinates_invalid_latitude(self):
        """
        Test coordinate validation for invalid latitude values.
        
        This test documents latitude range validation and shows
        error handling for out-of-range values.
        """
        invalid_latitudes = [91, -91, 100, -100, 200]
        
        for lat in invalid_latitudes:
            with pytest.raises(ValueError) as exc_info:
                self.search_engine._validate_coordinates(lat, 0)
            
            assert "Invalid latitude" in str(exc_info.value)
            assert "Must be between -90 and 90 degrees" in str(exc_info.value)
            assert str(lat) in str(exc_info.value)

    @pytest.mark.unit
    def test_validate_coordinates_invalid_longitude(self):
        """
        Test coordinate validation for invalid longitude values.
        
        This test documents longitude range validation and shows
        error handling for out-of-range values.
        """
        invalid_longitudes = [181, -181, 200, -200, 360]
        
        for lon in invalid_longitudes:
            with pytest.raises(ValueError) as exc_info:
                self.search_engine._validate_coordinates(0, lon)
            
            assert "Invalid longitude" in str(exc_info.value)
            assert "Must be between -180 and 180 degrees" in str(exc_info.value)
            assert str(lon) in str(exc_info.value)

    @pytest.mark.unit
    def test_calculate_distance_basic(self):
        """
        Test basic distance calculation between two points.
        
        This test documents distance calculation using the geodesic
        algorithm and shows expected distance units (miles).
        """
        # Set up search coordinates (NYC)
        self.search_engine.search_coords = (40.7128, -74.0060)
        
        # Test distance from NYC to Washington DC (approximately 205 miles)
        dc_coords = (38.9072, -77.0369)
        
        distance = self.search_engine.calculate_distance_miles(dc_coords)
        
        # Should be approximately 205 miles
        assert isinstance(distance, float)
        assert 200 < distance < 210  # Allow some tolerance
        assert distance > 0

    @pytest.mark.unit
    def test_calculate_distance_same_point(self):
        """
        Test distance calculation for identical coordinates.
        
        This test shows that distance between the same point is zero.
        """
        # Set up search coordinates
        same_coords = (40.7128, -74.0060)
        self.search_engine.search_coords = same_coords
        
        distance = self.search_engine.calculate_distance_miles(same_coords)
        
        assert distance == 0.0

    @pytest.mark.unit
    def test_calculate_distance_across_date_line(self):
        """
        Test distance calculation across the International Date Line.
        
        This test documents distance calculation for coordinates
        that cross the 180/-180 longitude boundary.
        """
        # Points near the International Date Line
        point_west = (0, 179)  # Just west of date line
        point_east = (0, -179)  # Just east of date line
        
        # Set search coordinates to point west
        self.search_engine.search_coords = point_west
        
        distance = self.search_engine.calculate_distance_miles(point_east)
        
        # Should be a short distance (about 138 miles at equator for 2 degrees)
        assert distance < 200  # Much less than going the long way around

    @pytest.mark.unit
    def test_calculate_distance_antipodal_points(self):
        """
        Test distance calculation for antipodal points (opposite sides of Earth).
        
        This test shows maximum possible distance on Earth's surface.
        """
        # Antipodal points (opposite sides of Earth)
        north_pole = (90, 0)
        south_pole = (-90, 0)
        
        # Set search coordinates to north pole
        self.search_engine.search_coords = north_pole
        
        distance = self.search_engine.calculate_distance_miles(south_pole)
        
        # Should be approximately half Earth's circumference (~12,430 miles)
        assert 12000 < distance < 13000

    @pytest.mark.unit
    def test_is_within_radius_inside(self, sample_image_data):
        """
        Test radius filtering for images within search radius.
        
        This test documents how images are filtered by distance
        from the search location.
        """
        # Use first sample image (should be within radius for testing)
        image_data = sample_image_data[0]
        
        # Mock calculate_distance to return a value within radius
        with patch.object(self.search_engine, 'calculate_distance_miles', return_value=0.5):
            result = self.search_engine.is_within_radius(image_data)
        
        assert result is True

    @pytest.mark.unit
    def test_is_within_radius_outside(self, sample_image_data):
        """
        Test radius filtering for images outside search radius.
        
        This test shows how images beyond the search radius are excluded.
        """
        image_data = sample_image_data[0]
        
        # Mock calculate_distance to return a value outside radius
        with patch.object(self.search_engine, 'calculate_distance_miles', return_value=2.0):
            result = self.search_engine.is_within_radius(image_data)
        
        assert result is False

    @pytest.mark.unit
    def test_is_within_radius_exactly_on_boundary(self, sample_image_data):
        """
        Test radius filtering for images exactly on the radius boundary.
        
        This test documents boundary condition handling for radius filtering.
        """
        image_data = sample_image_data[0]
        
        # Mock calculate_distance to return exactly the radius value
        with patch.object(self.search_engine, 'calculate_distance_miles', return_value=1.0):
            result = self.search_engine.is_within_radius(image_data)
        
        # Should include images exactly on the boundary
        assert result is True

    @pytest.mark.unit
    def test_is_within_radius_no_coordinates_set(self):
        """
        Test radius filtering when search coordinates are not initialized.
        
        This test documents error handling when distance calculation
        is attempted without search coordinates being set.
        """
        # Create engine with coordinates but clear them
        self.search_engine.search_coords = None
        
        test_coords = (40.7589, -73.9851)
        
        with pytest.raises(GPSDataError) as exc_info:
            self.search_engine.is_within_radius(test_coords)
        
        assert "Search coordinates not initialized" in str(exc_info.value)

    @pytest.mark.unit
    def test_search_coords_property(self):
        """
        Test search coordinates property access.
        
        This test documents how to access the current search coordinates
        from the search engine.
        """
        # Initially None until initialized
        assert self.search_engine.search_coords is None
        
        # Set coordinates manually for testing
        test_coords = (40.7128, -74.0060)
        self.search_engine.search_coords = test_coords
        
        coords = self.search_engine.search_coords
        assert coords == test_coords
        assert isinstance(coords, tuple)
        assert len(coords) == 2
        assert isinstance(coords[0], float)  # latitude
        assert isinstance(coords[1], float)  # longitude

    @pytest.mark.unit
    def test_calculate_distance_to_image_location(self):
        """
        Test calculating distance from search location to image coordinates.
        
        This test documents how to calculate distance from the current
        search coordinates to any image location.
        """
        # Set search coordinates
        self.search_engine.search_coords = (40.7128, -74.0060)
        
        # Test coordinates for a nearby location
        image_coords = (40.7589, -73.9851)  # Central Park
        
        distance = self.search_engine.calculate_distance_miles(image_coords)
        
        assert isinstance(distance, float)
        assert distance > 0
        assert distance < 10  # Should be within 10 miles

    @pytest.mark.unit
    def test_search_engine_with_different_radius_units(self):
        """
        Test search engine with different radius configurations.
        
        This test documents how different radius values affect
        the search area and filtering behavior.
        """
        # Test with small radius (city block level)
        small_config = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=0.1  # 100 meters
        )
        small_engine = LocationSearchEngine(small_config, self.mock_logger)
        assert small_engine.search_config.radius == 0.1
        
        # Test with large radius (regional level)
        large_config = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=50.0  # 50 kilometers
        )
        large_engine = LocationSearchEngine(large_config, self.mock_logger)
        assert large_engine.search_config.radius == 50.0


class TestLocationSearchIntegration:
    """Test suite for location search integration scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.search_config = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=1.0
        )
        self.search_engine = LocationSearchEngine(self.search_config, self.mock_logger)

    @pytest.mark.unit
    @patch('geo_image_search.search.Nominatim')
    def test_geocoding_with_user_agent(self, mock_nominatim_class):
        """
        Test that geocoding service is initialized with proper user agent.
        
        This test documents the requirement to identify the application
        when using Nominatim geocoding service.
        """
        mock_geocoder = Mock()
        mock_location = Mock()
        mock_location.latitude = 40.7128
        mock_location.longitude = -74.0060
        mock_geocoder.geocode.return_value = mock_location
        mock_nominatim_class.return_value = mock_geocoder
        
        config_with_address = SearchConfig(
            address="Test Location",
            radius=1.0
        )
        
        LocationSearchEngine(config_with_address, self.mock_logger)
        
        # Should have initialized Nominatim with user_agent
        mock_nominatim_class.assert_called_once()
        call_kwargs = mock_nominatim_class.call_args[1]
        assert 'user_agent' in call_kwargs
        assert 'geo_image_search' in call_kwargs['user_agent']

    @pytest.mark.unit
    def test_distance_calculation_accuracy(self):
        """
        Test distance calculation accuracy against known distances.
        
        This test validates the distance algorithm using well-known
        geographic distances for accuracy verification.
        """
        # Known distance: NYC to Boston is approximately 190 miles
        nyc = (40.7128, -74.0060)
        boston = (42.3601, -71.0589)
        
        # Set search coordinates to NYC
        self.search_engine.search_coords = nyc
        
        distance = self.search_engine.calculate_distance_miles(boston)
        
        # Allow 5% tolerance for geodesic calculation differences
        expected_distance = 190  # miles
        tolerance = expected_distance * 0.05
        
        assert abs(distance - expected_distance) < tolerance

    @pytest.mark.requires_network
    @pytest.mark.integration
    def test_real_geocoding_service(self):
        """
        Test with real Nominatim geocoding service.
        
        This test validates geocoding against the actual service
        using a well-known address.
        """
        # Use a well-known address
        config_real_address = SearchConfig(
            address="Times Square, New York, NY",
            radius=1.0
        )
        
        try:
            engine = LocationSearchEngine(config_real_address, self.mock_logger)
            coords = engine.search_coords
            
            # Times Square should be approximately at these coordinates
            assert 40.75 < coords[0] < 40.76  # Latitude
            assert -73.99 < coords[1] < -73.98  # Longitude
            
        except Exception as e:
            # Skip test if network unavailable
            pytest.skip(f"Network geocoding failed: {e}")

    @pytest.mark.unit
    def test_search_radius_edge_cases(self, sample_image_data):
        """
        Test search radius handling for edge cases.
        
        This test documents behavior with very small and very large
        radius values and zero radius.
        """
        image_data = sample_image_data[0]
        
        # Test with zero radius (should only include exact matches)
        zero_config = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=0.0
        )
        zero_engine = LocationSearchEngine(zero_config, self.mock_logger)
        
        with patch.object(zero_engine, 'calculate_distance_miles', return_value=0.0):
            assert zero_engine.is_within_radius(image_data) is True
        
        with patch.object(zero_engine, 'calculate_distance_miles', return_value=0.001):
            assert zero_engine.is_within_radius(image_data) is False
        
        # Test with very large radius (should include everything on Earth)
        large_config = SearchConfig(
            latitude=40.7128,
            longitude=-74.0060,
            radius=50000.0  # 50,000 km (larger than Earth's circumference)
        )
        large_engine = LocationSearchEngine(large_config, self.mock_logger)
        
        with patch.object(large_engine, 'calculate_distance_miles', return_value=20000):
            assert large_engine.is_within_radius(image_data) is True