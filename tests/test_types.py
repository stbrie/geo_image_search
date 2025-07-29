"""Tests for the types module.

These tests validate dataclass definitions and type structures.
They serve as documentation for the data structures used throughout the application.
"""

import pytest
from datetime import date
from geo_image_search.types import (
    ImageData, SearchConfig, DirectoryConfig, OutputConfig,
    FilterConfig, ProcessingConfig, FolderKMLConfig
)


class TestImageData:
    """Test suite for ImageData TypedDict."""

    @pytest.mark.unit
    def test_image_data_creation(self):
        """
        Test ImageData can be created with all fields.
        
        This test documents the structure of image data throughout the application
        and shows how to create valid ImageData objects.
        """
        # Test complete ImageData creation
        image_data = ImageData(
            filename="test.jpg",
            path="/path/to/test.jpg", 
            latitude=40.7128,
            longitude=-74.0060,
            date_taken="2024:01:15 10:30:00"
        )
        
        # Test all fields are accessible
        assert image_data["filename"] == "test.jpg"
        assert image_data["path"] == "/path/to/test.jpg"
        assert image_data["latitude"] == 40.7128
        assert image_data["longitude"] == -74.0060
        assert image_data["date_taken"] == "2024:01:15 10:30:00"

    @pytest.mark.unit
    def test_image_data_with_none_date(self):
        """
        Test ImageData handles None date_taken field.
        
        This test shows that image data can handle missing date information,
        which is common when EXIF data is incomplete.
        """
        image_data = ImageData(
            filename="no_date.jpg",
            path="/path/to/no_date.jpg",
            latitude=40.7128,
            longitude=-74.0060,
            date_taken=None
        )
        
        assert image_data["date_taken"] is None
        assert image_data["filename"] == "no_date.jpg"


class TestSearchConfig:
    """Test suite for SearchConfig dataclass."""

    @pytest.mark.unit
    def test_search_config_address_mode(self):
        """
        Test SearchConfig with address-based search.
        
        This test documents how to configure address-based searches
        and shows the expected field values.
        """
        config = SearchConfig(
            address="New York, NY",
            latitude=None,
            longitude=None,
            radius=1.5,
            far=False
        )
        
        assert config.address == "New York, NY"
        assert config.latitude is None
        assert config.longitude is None
        assert config.radius == 1.5
        assert config.far is False

    @pytest.mark.unit
    def test_search_config_coordinate_mode(self):
        """
        Test SearchConfig with coordinate-based search.
        
        This test documents how to configure coordinate-based searches
        with latitude and longitude values.
        """
        config = SearchConfig(
            address=None,
            latitude=40.7128,
            longitude=-74.0060,
            radius=0.5,
            far=True
        )
        
        assert config.address is None
        assert config.latitude == 40.7128
        assert config.longitude == -74.0060
        assert config.radius == 0.5
        assert config.far is True

    @pytest.mark.unit
    def test_search_config_defaults(self):
        """
        Test SearchConfig default values.
        
        This test documents the default search behavior when no
        explicit values are provided.
        """
        config = SearchConfig()
        
        assert config.address is None
        assert config.latitude is None
        assert config.longitude is None
        assert config.radius == 0.1  # Default radius
        assert config.far is False

    @pytest.mark.unit
    def test_search_config_dataclass_behavior(self):
        """
        Test SearchConfig behaves as expected dataclass.
        
        This test verifies dataclass functionality like equality,
        representation, and field access.
        """
        config1 = SearchConfig(address="Test City", radius=1.0)
        config2 = SearchConfig(address="Test City", radius=1.0)
        config3 = SearchConfig(address="Other City", radius=1.0)
        
        # Test equality
        assert config1 == config2
        assert config1 != config3
        
        # Test repr
        repr_str = repr(config1)
        assert "SearchConfig" in repr_str
        assert "Test City" in repr_str


class TestDirectoryConfig:
    """Test suite for DirectoryConfig dataclass."""

    @pytest.mark.unit
    def test_directory_config_basic(self):
        """
        Test basic DirectoryConfig creation.
        
        This test documents directory configuration options
        for controlling input and output locations.
        """
        config = DirectoryConfig(
            root="/path/to/images",
            output_directory="/path/to/output",
            find_only=False,
            sort_by_location=True
        )
        
        assert config.root == "/path/to/images"
        assert config.output_directory == "/path/to/output"
        assert config.find_only is False
        assert config.sort_by_location is True

    @pytest.mark.unit
    def test_directory_config_find_only_mode(self):
        """
        Test DirectoryConfig for find-only mode.
        
        This test shows how to configure the application to only
        find images without copying them.
        """
        config = DirectoryConfig(
            root="/path/to/images",
            output_directory=None,
            find_only=True,
            sort_by_location=False
        )
        
        assert config.find_only is True
        assert config.output_directory is None


class TestFilterConfig:
    """Test suite for FilterConfig dataclass."""

    @pytest.mark.unit
    def test_filter_config_complete(self):
        """
        Test FilterConfig with all filtering options.
        
        This test documents all available filtering options
        for GPS accuracy and date ranges.
        """
        config = FilterConfig(
            max_gps_error=50.0,
            max_dop=5.0,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 12, 31)
        )
        
        assert config.max_gps_error == 50.0
        assert config.max_dop == 5.0
        assert config.date_from == date(2024, 1, 1)
        assert config.date_to == date(2024, 12, 31)

    @pytest.mark.unit
    def test_filter_config_no_filtering(self):
        """
        Test FilterConfig with no filtering enabled.
        
        This test shows the default behavior when no filtering
        is applied to the search results.
        """
        config = FilterConfig()
        
        assert config.max_gps_error is None
        assert config.max_dop is None
        assert config.date_from is None
        assert config.date_to is None

    @pytest.mark.unit
    def test_filter_config_date_only(self):
        """
        Test FilterConfig with only date filtering.
        
        This test demonstrates how to filter images by date
        without GPS accuracy constraints.
        """
        config = FilterConfig(
            date_from=date(2024, 6, 1),
            date_to=date(2024, 8, 31)
        )
        
        assert config.date_from == date(2024, 6, 1)
        assert config.date_to == date(2024, 8, 31)
        assert config.max_gps_error is None
        assert config.max_dop is None


class TestOutputConfig:
    """Test suite for OutputConfig dataclass."""

    @pytest.mark.unit
    def test_output_config_all_exports(self):
        """
        Test OutputConfig with all export options enabled.
        
        This test documents available export formats and
        output configuration options.
        """
        config = OutputConfig(
            save_addresses=True,
            export_kml=True,
            verbose=True
        )
        
        assert config.save_addresses is True
        assert config.export_kml is True
        assert config.verbose is True

    @pytest.mark.unit
    def test_output_config_minimal(self):
        """
        Test OutputConfig with minimal output.
        
        This test shows quiet operation mode with no exports.
        """
        config = OutputConfig()
        
        assert config.save_addresses is False
        assert config.export_kml is False
        assert config.verbose is False


class TestProcessingConfig:
    """Test suite for ProcessingConfig dataclass."""

    @pytest.mark.unit
    def test_processing_config_resume_enabled(self):
        """
        Test ProcessingConfig with resume functionality.
        
        This test documents how to enable checkpoint-based
        resume functionality for large searches.
        """
        config = ProcessingConfig(resume=True)
        
        assert config.resume is True

    @pytest.mark.unit
    def test_processing_config_defaults(self):
        """
        Test ProcessingConfig default behavior.
        
        This test shows default processing configuration
        without resume functionality.
        """
        config = ProcessingConfig()
        
        assert config.resume is False


class TestFolderKMLConfig:
    """Test suite for FolderKMLConfig dataclass."""

    @pytest.mark.unit
    def test_folder_kml_config_complete(self):
        """
        Test FolderKMLConfig with all options.
        
        This test documents folder KML export configuration
        including all available options.
        """
        config = FolderKMLConfig(
            folder_path="/path/to/photos",
            output_kml_path="/path/to/output.kml",
            recursive=True,
            verbose=True,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 12, 31)
        )
        
        assert config.folder_path == "/path/to/photos"
        assert config.output_kml_path == "/path/to/output.kml"
        assert config.recursive is True
        assert config.verbose is True
        assert config.date_from == date(2024, 1, 1)
        assert config.date_to == date(2024, 12, 31)

    @pytest.mark.unit
    def test_folder_kml_config_defaults(self):
        """
        Test FolderKMLConfig default values.
        
        This test documents default behavior for folder KML export
        when optional parameters are not specified.
        """
        config = FolderKMLConfig()
        
        assert config.folder_path is None
        assert config.output_kml_path is None
        assert config.recursive is True
        assert config.verbose is False
        assert config.date_from is None
        assert config.date_to is None

    @pytest.mark.unit
    def test_folder_kml_config_non_recursive(self):
        """
        Test FolderKMLConfig for non-recursive scanning.
        
        This test shows how to configure folder scanning to only
        process files in the specified directory without subdirectories.
        """
        config = FolderKMLConfig(
            folder_path="/path/to/photos",
            recursive=False
        )
        
        assert config.recursive is False
        assert config.folder_path == "/path/to/photos"


class TestDataclassIntegration:
    """Test suite for dataclass integration and compatibility."""

    @pytest.mark.unit
    def test_config_objects_are_serializable(self):
        """
        Test that config objects can be serialized.
        
        This test ensures configuration objects can be converted
        to dictionaries for logging, debugging, or storage.
        """
        from dataclasses import asdict
        
        config = SearchConfig(
            address="Test City",
            radius=1.0,
            far=True
        )
        
        config_dict = asdict(config)
        assert isinstance(config_dict, dict)
        assert config_dict["address"] == "Test City"
        assert config_dict["radius"] == 1.0
        assert config_dict["far"] is True

    @pytest.mark.unit
    def test_config_objects_support_field_access(self):
        """
        Test that config objects support both attribute and dict-style access.
        
        This test verifies config objects are easy to work with in various
        contexts throughout the application.
        """
        config = DirectoryConfig(
            root="/test/path",
            find_only=True
        )
        
        # Test attribute access
        assert config.root == "/test/path"
        assert config.find_only is True
        
        # Test that we can iterate over fields
        field_names = list(config.__dataclass_fields__.keys())
        assert "root" in field_names
        assert "find_only" in field_names

    @pytest.mark.unit
    def test_type_annotations_are_preserved(self):
        """
        Test that type annotations are preserved in dataclasses.
        
        This test ensures type information is available for IDE support
        and runtime type checking.
        """
        # Test SearchConfig annotations
        annotations = SearchConfig.__annotations__
        assert 'address' in annotations
        assert 'radius' in annotations
        
        # Test FilterConfig date annotations
        filter_annotations = FilterConfig.__annotations__
        assert 'date_from' in filter_annotations
        assert 'date_to' in filter_annotations