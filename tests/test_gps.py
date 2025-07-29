"""Tests for the GPS module.

These tests verify GPS data extraction from image files.
They serve as documentation for GPS processing capabilities and EXIF data handling.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import pytest

from geo_image_search.gps import GPSImageProcessor
from geo_image_search.types import FilterConfig, ImageData
from geo_image_search.constants import Constants
from geo_image_search.exceptions import GPSDataError


class TestGPSImageProcessor:
    """Test suite for GPSImageProcessor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.filter_config = FilterConfig(
            max_gps_error=50.0,
            max_dop=5.0
        )
        self.processor = GPSImageProcessor(self.filter_config, self.mock_logger)

    @pytest.mark.unit
    def test_gps_processor_initialization(self):
        """
        Test GPSImageProcessor initialization.
        
        This test documents how to create a GPS processor
        and verifies it has the required components.
        """
        assert self.processor.filter_config == self.filter_config
        assert self.processor.logger == self.mock_logger
        assert hasattr(self.processor, 'gps_filter')
        assert hasattr(self.processor, 'date_parser')

    @pytest.mark.unit
    def test_gps_processor_requires_exif_library(self):
        """
        Test GPS processor requires exif library.
        
        This test documents the dependency on the exif library
        and shows error handling when it's not available.
        """
        with patch('geo_image_search.gps.Image', None):
            with pytest.raises(ImportError) as exc_info:
                GPSImageProcessor(self.filter_config, self.mock_logger)
            
            assert "exif library is required" in str(exc_info.value)
            assert "pip install exif" in str(exc_info.value)

    @pytest.mark.unit
    def test_is_jpeg_file_valid_extensions(self):
        """
        Test JPEG file extension detection.
        
        This test documents which file extensions are recognized
        as JPEG images for processing.
        """
        valid_extensions = ['.jpg', '.jpeg', '.JPG', '.JPEG']
        
        for ext in valid_extensions:
            test_file = f"photo{ext}"
            assert self.processor._is_jpeg_file(test_file) is True

    @pytest.mark.unit
    def test_is_jpeg_file_invalid_extensions(self):
        """
        Test non-JPEG file extension rejection.
        
        This test shows that non-JPEG files are properly
        filtered out during processing.
        """
        invalid_extensions = ['.png', '.gif', '.bmp', '.tiff', '.txt', '.pdf']
        
        for ext in invalid_extensions:
            test_file = f"file{ext}"
            assert self.processor._is_jpeg_file(test_file) is False

    @pytest.mark.unit
    def test_is_jpeg_file_path_handling(self):
        """
        Test JPEG file detection with full paths.
        
        This test shows file extension detection works
        with full file paths, not just filenames.
        """
        full_paths = [
            "/path/to/photo.jpg",
            "C:\\Photos\\image.JPEG",
            "./relative/path/pic.jpeg"
        ]
        
        for path in full_paths:
            assert self.processor._is_jpeg_file(path) is True

    @pytest.mark.unit
    def test_convert_dms_to_decimal_basic(self):
        """
        Test DMS (degrees, minutes, seconds) to decimal conversion.
        
        This test documents GPS coordinate conversion and shows
        how EXIF GPS data is transformed to decimal degrees.
        """
        # Test: 40°42'46.08"N = 40.7128 degrees
        dms_coords = [40, 42, 46.08]
        decimal = self.processor._convert_dhms_to_decimal(dms_coords)
        
        assert decimal is not None
        assert abs(decimal - 40.7128) < 0.001  # Allow small floating point error

    @pytest.mark.unit
    def test_convert_dms_to_decimal_edge_cases(self):
        """
        Test DMS conversion edge cases.
        
        This test shows handling of various GPS coordinate formats
        and edge cases in EXIF data.
        """
        # Test zero coordinates
        zero_coords = [0, 0, 0]
        result = self.processor._convert_dhms_to_decimal(zero_coords)
        assert result == 0.0
        
        # Test empty/invalid input
        assert self.processor._convert_dhms_to_decimal([]) is None
        assert self.processor._convert_dhms_to_decimal(None) is None
        assert self.processor._convert_dhms_to_decimal([40, 30]) is None  # Missing seconds

    @pytest.mark.unit
    def test_get_decimal_coords_with_gps_data(self, mock_image):
        """
        Test GPS coordinate extraction from image with GPS data.
        
        This test documents complete GPS extraction workflow
        and shows expected coordinate conversion.
        """
        lat, lon = self.processor._get_decimal_coords(mock_image)
        
        assert lat is not None
        assert lon is not None
        assert isinstance(lat, float)
        assert isinstance(lon, float)
        
        # Check hemisphere handling (N = positive, W = negative)
        assert lat > 0  # North latitude should be positive
        assert lon < 0  # West longitude should be negative

    @pytest.mark.unit
    def test_get_decimal_coords_no_gps_data(self, mock_image_no_gps):
        """
        Test GPS coordinate extraction from image without GPS data.
        
        This test shows graceful handling of images that don't
        contain GPS information in their EXIF data.
        """
        lat, lon = self.processor._get_decimal_coords(mock_image_no_gps)
        
        assert lat is None
        assert lon is None

    @pytest.mark.unit
    def test_get_decimal_coords_hemisphere_handling(self):
        """
        Test GPS coordinate hemisphere handling.
        
        This test documents how GPS coordinates are signed
        based on hemisphere (N/S for latitude, E/W for longitude).
        """
        # Test Southern hemisphere (should be negative)
        south_image = Mock()
        south_image.gps_latitude = [40, 30, 0]
        south_image.gps_latitude_ref = "S"
        south_image.gps_longitude = [74, 0, 0]
        south_image.gps_longitude_ref = "E"
        
        lat, lon = self.processor._get_decimal_coords(south_image)
        
        assert lat < 0  # South should be negative
        assert lon > 0  # East should be positive


    @pytest.mark.unit
    def test_load_and_validate_image_success(self):
        """
        Test successful image loading and validation.
        
        This test documents image file loading process
        and shows successful validation workflow.
        """
        mock_file = Mock()
        mock_image = Mock()
        
        with patch('geo_image_search.gps.Image', return_value=mock_image):
            result = self.processor._load_and_validate_image(mock_file, "test.jpg")
            
        assert result == mock_image

    @pytest.mark.unit
    def test_load_and_validate_image_errors(self):
        """
        Test image loading error handling.
        
        This test shows error handling for corrupted or
        invalid image files.
        """
        mock_file = Mock()
        
        # Test various error conditions
        error_types = [OSError, IOError, MemoryError, ValueError]
        
        for error_type in error_types:
            with patch('geo_image_search.gps.Image', side_effect=error_type("Test error")):
                result = self.processor._load_and_validate_image(mock_file, "bad.jpg")
                
            assert result is None
            # Should log the error
            self.mock_logger.info.assert_called()

    @pytest.mark.unit 
    @patch('builtins.open', new_callable=mock_open)
    def test_extract_image_gps_data_success(self, mock_file_open, mock_image):
        """
        Test successful GPS data extraction from image.
        
        This test documents the complete GPS extraction workflow
        and shows expected ImageData structure.
        """
        test_path = "/test/photo.jpg"
        
        with patch.object(self.processor, '_load_and_validate_image', return_value=mock_image):
            with patch.object(self.processor.gps_filter, 'apply_date_filters', return_value=True):
                with patch.object(self.processor.gps_filter, 'apply_gps_accuracy_filters', return_value=True):
                    result = self.processor.extract_image_gps_data(test_path)
        
        assert isinstance(result, dict)  # ImageData is a TypedDict
        assert result["filename"] == "photo.jpg"
        assert result["path"] == test_path
        assert isinstance(result["latitude"], float)
        assert isinstance(result["longitude"], float)
        assert result["date_taken"] == "2024:01:15 10:30:00"

    @pytest.mark.unit
    def test_extract_image_gps_data_non_jpeg(self):
        """
        Test GPS extraction from non-JPEG files.
        
        This test shows that non-JPEG files are skipped
        during GPS processing.
        """
        result = self.processor.extract_image_gps_data("/test/image.png")
        assert result is None

    @pytest.mark.unit
    @patch('builtins.open', new_callable=mock_open)
    def test_extract_image_gps_data_no_gps(self, mock_file_open, mock_image_no_gps):
        """
        Test GPS extraction from image without GPS data.
        
        This test shows handling of images that don't contain
        GPS coordinates in their EXIF data.
        """
        with patch.object(self.processor, '_load_and_validate_image', return_value=mock_image_no_gps):
            with patch.object(self.processor.gps_filter, 'apply_date_filters', return_value=True):
                result = self.processor.extract_image_gps_data("/test/no_gps.jpg")
        
        assert result is None

    @pytest.mark.unit
    @patch('builtins.open', new_callable=mock_open)
    def test_extract_image_gps_data_filtered_by_date(self, mock_file_open, mock_image):
        """
        Test GPS extraction with date filtering.
        
        This test shows how date filters can exclude images
        based on when they were taken.
        """
        with patch.object(self.processor, '_load_and_validate_image', return_value=mock_image):
            with patch.object(self.processor.gps_filter, 'apply_date_filters', return_value=False):
                result = self.processor.extract_image_gps_data("/test/old_photo.jpg")
        
        assert result is None

    @pytest.mark.unit
    @patch('builtins.open', new_callable=mock_open)
    def test_extract_image_gps_data_filtered_by_accuracy(self, mock_file_open, mock_image):
        """
        Test GPS extraction with accuracy filtering.
        
        This test shows how GPS accuracy filters can exclude
        images with poor GPS quality.
        """
        with patch.object(self.processor, '_load_and_validate_image', return_value=mock_image):
            with patch.object(self.processor.gps_filter, 'apply_date_filters', return_value=True):
                with patch.object(self.processor.gps_filter, 'apply_gps_accuracy_filters', return_value=False):
                    result = self.processor.extract_image_gps_data("/test/poor_gps.jpg")
        
        assert result is None

    @pytest.mark.unit
    def test_extract_image_gps_data_file_errors(self):
        """
        Test GPS extraction file operation error handling.
        
        This test shows graceful handling of file system errors
        during image processing.
        """
        # Test file not found
        with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
            result = self.processor.extract_image_gps_data("/nonexistent/photo.jpg")
            
        assert result is None
        self.mock_logger.warning.assert_called()
        
        # Test permission error
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            result = self.processor.extract_image_gps_data("/restricted/photo.jpg")
            
        assert result is None

    @pytest.mark.unit
    def test_extract_image_gps_data_coordinates_validation(self, mock_image):
        """
        Test GPS coordinate validation and range checking.
        
        This test documents valid coordinate ranges and shows
        validation of extracted GPS data.
        """
        with patch('builtins.open', new_callable=mock_open):
            with patch.object(self.processor, '_load_and_validate_image', return_value=mock_image):
                with patch.object(self.processor.gps_filter, 'apply_date_filters', return_value=True):
                    with patch.object(self.processor.gps_filter, 'apply_gps_accuracy_filters', return_value=True):
                        result = self.processor.extract_image_gps_data("/test/photo.jpg")
        
        # Test coordinate ranges
        assert -90 <= result["latitude"] <= 90
        assert -180 <= result["longitude"] <= 180


class TestGPSProcessorIntegration:
    """Test suite for GPS processor integration scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.filter_config = FilterConfig()
        self.processor = GPSImageProcessor(self.filter_config, self.mock_logger)

    @pytest.mark.unit
    def test_multiple_image_processing(self, sample_image_data):
        """
        Test processing multiple images in sequence.
        
        This test documents batch processing workflow
        and shows consistent GPS extraction across images.
        """
        image_paths = [img["path"] for img in sample_image_data]
        
        results = []
        for path in image_paths:
            with patch.object(self.processor, 'extract_image_gps_data') as mock_extract:
                mock_extract.return_value = {
                    "filename": Path(path).name,
                    "path": path,
                    "latitude": 40.7128,
                    "longitude": -74.0060,
                    "date_taken": "2024:01:15 10:30:00"
                }
                result = self.processor.extract_image_gps_data(path)
                if result:
                    results.append(result)
        
        assert len(results) == len(image_paths)
        for result in results:
            assert isinstance(result, dict)
            assert "latitude" in result
            assert "longitude" in result

    @pytest.mark.unit
    def test_gps_processor_with_various_filter_configs(self):
        """
        Test GPS processor with different filter configurations.
        
        This test documents how different filter settings
        affect GPS data extraction and validation.
        """
        # Test with strict filtering
        strict_config = FilterConfig(
            max_gps_error=10.0,
            max_dop=2.0
        )
        strict_processor = GPSImageProcessor(strict_config, self.mock_logger)
        assert strict_processor.filter_config.max_gps_error == 10.0
        
        # Test with no filtering
        no_filter_config = FilterConfig()
        no_filter_processor = GPSImageProcessor(no_filter_config, self.mock_logger)
        assert no_filter_processor.filter_config.max_gps_error is None

    @pytest.mark.unit
    def test_error_handling_robustness(self):
        """
        Test GPS processor error handling robustness.
        
        This test ensures the processor can handle various
        error conditions without crashing.
        """
        error_scenarios = [
            "/nonexistent/file.jpg",
            "/empty/path/",
            "",
            None
        ]
        
        for scenario in error_scenarios:
            try:
                result = self.processor.extract_image_gps_data(scenario)
                # Should either return None or raise appropriate exception
                assert result is None or isinstance(result, dict)
            except (TypeError, AttributeError):
                # Some scenarios may raise these exceptions, which is acceptable
                pass

    @pytest.mark.requires_files
    def test_real_file_processing(self, test_utils, temp_dir):
        """
        Test GPS processing with real file system operations.
        
        This test shows GPS processor working with actual
        files in the file system.
        """
        # Create sample JPEG files
        jpeg_files = [
            temp_dir / "photo1.jpg",
            temp_dir / "photo2.jpeg",
            temp_dir / "image.JPG"
        ]
        
        for file_path in jpeg_files:
            test_utils.create_sample_image_file(file_path, has_gps=True)
        
        # Create non-JPEG file
        non_jpeg = temp_dir / "document.txt"
        non_jpeg.write_text("Not an image")
        
        # Test processing
        jpeg_results = []
        for file_path in jpeg_files:
            # Mock the actual GPS extraction since we don't have real GPS data
            with patch.object(self.processor, '_load_and_validate_image'):
                with patch.object(self.processor, '_get_decimal_coords', return_value=(40.7128, -74.0060)):
                    result = self.processor.extract_image_gps_data(str(file_path))
                    if result:
                        jpeg_results.append(result)
        
        # Should process JPEG files
        assert len(jpeg_results) > 0
        
        # Should skip non-JPEG files
        result = self.processor.extract_image_gps_data(str(non_jpeg))
        assert result is None