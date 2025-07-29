"""Pytest configuration and shared fixtures for geo_image_search tests."""

import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock, MagicMock, PropertyMock
import pytest

from geo_image_search.types import (
    SearchConfig, DirectoryConfig, OutputConfig, FilterConfig,
    ProcessingConfig, FolderKMLConfig, ImageData
)
from geo_image_search.constants import Constants


# =============================================================================
# Test Configuration
# =============================================================================

@pytest.fixture(scope="session")
def test_data_dir():
    """Directory containing test data files."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    """Temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def sample_images_dir(test_data_dir):
    """Directory containing sample test images."""
    return test_data_dir / "sample_images"


# =============================================================================
# Configuration Fixtures
# =============================================================================

@pytest.fixture
def basic_search_config():
    """Basic search configuration for testing."""
    return SearchConfig(
        address="New York, NY",
        latitude=None,
        longitude=None,
        radius=1.0,
        far=False
    )


@pytest.fixture
def coordinate_search_config():
    """Coordinate-based search configuration."""
    return SearchConfig(
        address=None,
        latitude=40.7128,
        longitude=-74.0060,
        radius=0.5,
        far=False
    )


@pytest.fixture
def basic_directory_config(temp_dir):
    """Basic directory configuration for testing."""
    return DirectoryConfig(
        root=str(temp_dir / "images"),
        output_directory=str(temp_dir / "output"),
        find_only=False,
        sort_by_location=False
    )


@pytest.fixture
def basic_output_config():
    """Basic output configuration for testing."""
    return OutputConfig(
        save_addresses=False,
        export_kml=False,
        verbose=True
    )


@pytest.fixture
def basic_filter_config():
    """Basic filter configuration for testing."""
    return FilterConfig(
        max_gps_error=50.0,
        max_dop=5.0,
        date_from=date(2020, 1, 1),
        date_to=date(2024, 12, 31)
    )


@pytest.fixture
def basic_processing_config():
    """Basic processing configuration for testing."""
    return ProcessingConfig(resume=False)


@pytest.fixture
def basic_folder_kml_config(temp_dir):
    """Basic folder KML configuration for testing."""
    return FolderKMLConfig(
        folder_path=str(temp_dir / "photos"),
        output_kml_path=str(temp_dir / "output.kml"),
        recursive=True,
        verbose=True,
        date_from=None,
        date_to=None
    )


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_image_data():
    """Sample image data for testing."""
    return [
        ImageData(
            filename="photo1.jpg",
            path="/test/photos/photo1.jpg",
            latitude=40.7128,
            longitude=-74.0060,
            date_taken="2024:01:15 10:30:00"
        ),
        ImageData(
            filename="photo2.jpg",
            path="/test/photos/photo2.jpg",
            latitude=40.7589,
            longitude=-73.9851,
            date_taken="2024:01:16 14:45:00"
        ),
        ImageData(
            filename="photo3.jpg",
            path="/test/photos/photo3.jpg",
            latitude=40.6892,
            longitude=-74.0445,
            date_taken="2024:01:17 09:15:00"
        )
    ]


@pytest.fixture
def sample_toml_config():
    """Sample TOML configuration content."""
    return """# Test configuration file
[search]
address = "Test City, NY"
radius = 2.0
far = false

[directories]
root = "/test/images"
output_directory = "test_output"
find_only = false
sort_by_location = true

[output]
save_addresses = true
export_kml = true
verbose = true

[filters]
max_gps_error = 30.0
max_dop = 3.0
date_from = "2023-01-01"
date_to = "2024-12-31"

[processing]
resume = true

[folder_kml]
folder_path = "/test/photos"
output_kml_path = "test_photos.kml"
recursive = true
verbose = true
"""


@pytest.fixture
def sample_csv_data():
    """Sample CSV data for testing exports."""
    return [
        {
            "filename": "photo1.jpg",
            "path": "/test/photos/photo1.jpg",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "address": "New York, NY, USA"
        },
        {
            "filename": "photo2.jpg", 
            "path": "/test/photos/photo2.jpg",
            "latitude": "40.7589",
            "longitude": "-73.9851",
            "address": "Times Square, New York, NY, USA"
        }
    ]


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    logger = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    return logger


@pytest.fixture
def mock_geocoder():
    """Mock geocoder for testing location services."""
    geocoder = Mock()
    
    # Mock geocode method (address to coordinates)
    mock_location = Mock()
    mock_location.latitude = 40.7128
    mock_location.longitude = -74.0060
    mock_location.address = "New York, NY, USA"
    geocoder.geocode.return_value = mock_location
    
    # Mock reverse method (coordinates to address)  
    mock_reverse = Mock()
    mock_reverse.address = "New York, NY, USA"
    mock_reverse.raw = {
        'address': {
            'city': 'New York',
            'state': 'New York',
            'country': 'United States'
        }
    }
    geocoder.reverse.return_value = mock_reverse
    
    return geocoder


@pytest.fixture
def mock_image():
    """Mock image object for testing GPS extraction."""
    image = Mock()
    
    # GPS data
    image.gps_latitude = [40, 42, 46.08]  # 40°42'46.08"N
    image.gps_longitude = [74, 0, 21.6]   # 74°0'21.6"W
    image.gps_latitude_ref = "N"
    image.gps_longitude_ref = "W"
    
    # Date data
    image.datetime_original = "2024:01:15 10:30:00"
    image.datetime = "2024:01:15 10:30:00"
    
    # GPS quality data
    image.gps_horizontal_error = 25.0
    image.gps_dop = 2.5
    
    return image


@pytest.fixture
def mock_image_no_gps():
    """Mock image object without GPS data."""
    image = Mock()
    
    # Configure to not have GPS attributes - they should not exist
    del image.gps_latitude
    del image.gps_longitude
    del image.gps_latitude_ref  
    del image.gps_longitude_ref
    
    # Set valid datetime attribute
    image.datetime_original = "2024:01:15 10:30:00"
    
    return image


@pytest.fixture
def mock_path_normalizer():
    """Mock path normalizer for testing."""
    normalizer = Mock()
    normalizer.normalize_path.side_effect = lambda x: str(Path(x).resolve())
    normalizer.get_kml_image_path.side_effect = lambda x: f"file:///{x.replace('\\', '/')}"
    normalizer.sanitize_folder_name.side_effect = lambda x: x.replace(' ', '_').replace('/', '_')
    return normalizer


# =============================================================================
# File System Fixtures
# =============================================================================

@pytest.fixture
def sample_config_file(temp_dir, sample_toml_config):
    """Create a sample TOML configuration file."""
    config_file = temp_dir / "test_config.toml"
    config_file.write_text(sample_toml_config)
    return config_file


@pytest.fixture
def sample_checkpoint_data():
    """Sample checkpoint data for testing."""
    return {
        "processed_files": [
            "/test/photo1.jpg",
            "/test/photo2.jpg", 
            "/test/photo3.jpg"
        ],
        "total_files": 10,
        "timestamp": "2024-01-15T10:30:00"
    }


@pytest.fixture
def sample_checkpoint_file(temp_dir, sample_checkpoint_data):
    """Create a sample checkpoint file."""
    checkpoint_file = temp_dir / "geo_search_checkpoint.json"
    with open(checkpoint_file, 'w') as f:
        json.dump(sample_checkpoint_data, f, indent=2)
    return checkpoint_file


# =============================================================================
# Test Utilities
# =============================================================================

class TestUtils:
    """Utility functions for tests."""
    
    @staticmethod
    def create_sample_image_file(file_path: Path, has_gps: bool = True):
        """Create a sample image file for testing."""
        # Create a minimal JPEG-like file for testing
        # This is just for file system testing, not actual image processing
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'wb') as f:
            # Write minimal JPEG header
            f.write(b'\xff\xd8\xff\xe0')  # JPEG SOI and APP0 markers
            f.write(b'\x00\x10JFIF\x00\x01')  # JFIF header
            f.write(b'\x01\x01\x00\x00\x01\x00\x01\x00\x00')
            # Add some fake EXIF data if GPS requested
            if has_gps:
                f.write(b'EXIF_GPS_DATA_PLACEHOLDER')
            f.write(b'\xff\xd9')  # JPEG EOI marker
    
    @staticmethod
    def assert_csv_content(csv_file: Path, expected_data: List[Dict]):
        """Assert CSV file contains expected data."""
        import csv
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            actual_data = list(reader)
        
        assert len(actual_data) == len(expected_data)
        for actual, expected in zip(actual_data, expected_data):
            for key, value in expected.items():
                assert actual[key] == str(value)
    
    @staticmethod
    def assert_kml_contains_placemarks(kml_file: Path, expected_count: int):
        """Assert KML file contains expected number of placemarks."""
        content = kml_file.read_text()
        placemark_count = content.count('<Placemark>')
        assert placemark_count == expected_count, f"Expected {expected_count} placemarks, found {placemark_count}"
    
    @staticmethod
    def create_mock_args(**kwargs):
        """Create mock argument namespace for testing."""
        from argparse import Namespace
        defaults = {
            'address': None,
            'latitude': None,
            'longitude': None,
            'radius': 0.1,
            'far': False,
            'root': None,
            'output_directory': None,
            'find_only': False,
            'sort_by_location': False,
            'save_addresses': False,
            'export_kml': False,
            'verbose': False,
            'max_gps_error': None,
            'max_dop': None,
            'date_from': None,
            'date_to': None,
            'resume': False,
            'config': None,
            'create_config': None,
            'export_folder_kml': None,
            'output_kml': None,
            'no_recursive': False
        }
        defaults.update(kwargs)
        return Namespace(**defaults)


@pytest.fixture
def test_utils():
    """Test utilities fixture."""
    return TestUtils