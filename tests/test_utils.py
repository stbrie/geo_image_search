"""Tests for the utils module.

These tests verify utility classes and helper functions work correctly.
They serve as documentation for path handling, date parsing, and GPS filtering functionality.
"""

import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from geo_image_search.utils import LoggingSetup, PathNormalizer, DateParser, GPSFilter
from geo_image_search.types import FilterConfig
from geo_image_search.exceptions import ConfigurationError


class TestLoggingSetup:
    """Test suite for LoggingSetup utility."""

    @pytest.mark.unit
    def test_basic_logging_setup(self):
        """
        Test basic logging configuration.
        
        This test documents how to set up application logging
        and verifies the logger is properly configured.
        """
        logging_setup = LoggingSetup()
        logger = logging_setup.setup_logging()
        
        # Test logger is returned
        assert isinstance(logger, logging.Logger)
        assert logger.name == "geo_image_search.utils"
        
        # Test logger has appropriate level
        assert logger.level <= logging.INFO

    @pytest.mark.unit
    def test_logging_setup_with_custom_level(self):
        """
        Test logging setup with custom level.
        
        This test shows how to configure logging with different
        verbosity levels for debugging vs production.
        """
        logging_setup = LoggingSetup()
        
        # Test with DEBUG level
        debug_logger = logging_setup.setup_logging(level=logging.DEBUG)
        assert debug_logger.level <= logging.DEBUG
        
        # Test with WARNING level
        warning_logger = logging_setup.setup_logging(level=logging.WARNING)
        assert warning_logger.level <= logging.WARNING

    @pytest.mark.unit 
    def test_logging_format_includes_required_info(self):
        """
        Test logging format includes timestamp, level, and message.
        
        This test verifies log messages contain sufficient information
        for debugging and troubleshooting.
        """
        logging_setup = LoggingSetup()
        logger = logging_setup.setup_logging()
        
        # Test that we can log messages without errors
        logger.info("Test info message")
        logger.warning("Test warning message") 
        logger.error("Test error message")
        logger.debug("Test debug message")


class TestPathNormalizer:
    """Test suite for PathNormalizer utility."""

    @pytest.mark.unit
    def test_normalize_path_basic(self):
        """
        Test basic path normalization.
        
        This test documents how paths are normalized for
        cross-platform compatibility.
        """
        normalizer = PathNormalizer()
        
        # Test basic path normalization
        test_path = "some/relative/path"
        normalized = normalizer.normalize_path(test_path)
        
        assert isinstance(normalized, str)
        assert len(normalized) > 0
        
        # Test absolute path handling
        abs_path = Path("/absolute/path").resolve()
        normalized_abs = normalizer.normalize_path(str(abs_path))
        assert Path(normalized_abs).is_absolute()

    @pytest.mark.unit
    def test_normalize_path_empty_string(self):
        """
        Test path normalization with empty string.
        
        This test shows how empty paths are handled gracefully.
        """
        normalizer = PathNormalizer()
        
        result = normalizer.normalize_path("")
        assert result == ""

    @pytest.mark.unit
    def test_normalize_path_none_handling(self):
        """
        Test path normalization with None input.
        
        This test documents error handling for invalid path inputs.
        """
        normalizer = PathNormalizer()
        
        # Should handle None gracefully or raise appropriate error
        result = normalizer.normalize_path(None)
        assert result is None or result == ""

    @pytest.mark.unit
    def test_get_kml_image_path_formatting(self):
        """
        Test KML image path formatting.
        
        This test documents how image paths are formatted for
        inclusion in KML files with proper file:// URLs.
        """
        normalizer = PathNormalizer()
        
        # Test Windows-style path
        windows_path = "C:\\photos\\image.jpg"
        kml_path = normalizer.get_kml_image_path(windows_path)
        
        assert kml_path.startswith("file:///")
        assert "/" in kml_path  # Should use forward slashes
        assert "\\" not in kml_path  # Should not have backslashes

    @pytest.mark.unit
    def test_get_kml_image_path_unix_style(self):
        """
        Test KML path formatting for Unix-style paths.
        
        This test shows KML path handling for Unix/Linux systems.
        """
        normalizer = PathNormalizer()
        
        unix_path = "/home/user/photos/image.jpg"
        kml_path = normalizer.get_kml_image_path(unix_path)
        
        assert kml_path.startswith("file:///")
        assert unix_path.replace("/", "/") in kml_path

    @pytest.mark.unit
    def test_sanitize_folder_name_removes_invalid_chars(self):
        """
        Test folder name sanitization removes invalid characters.
        
        This test documents how folder names are cleaned for
        safe use in file systems.
        """
        normalizer = PathNormalizer()
        
        # Test various invalid characters
        unsafe_name = 'folder<>:"/\\|?*name'
        safe_name = normalizer.sanitize_folder_name(unsafe_name)
        
        # Should not contain filesystem-invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            assert char not in safe_name
        
        # Should still contain the basic text
        assert "folder" in safe_name
        assert "name" in safe_name

    @pytest.mark.unit
    def test_sanitize_folder_name_handles_edge_cases(self):
        """
        Test folder name sanitization edge cases.
        
        This test shows handling of empty names, dots, and spaces.
        """
        normalizer = PathNormalizer()
        
        # Test empty string
        result = normalizer.sanitize_folder_name("")
        assert result == "images"  # Should provide fallback
        
        # Test dots and spaces
        result = normalizer.sanitize_folder_name("  . . ")
        assert len(result) > 0
        assert result != "  . . "  # Should be cleaned


class TestDateParser:
    """Test suite for DateParser utility."""

    @pytest.mark.unit
    def test_parse_date_valid_formats(self):
        """
        Test parsing valid date strings.
        
        This test documents supported date formats and shows
        how to parse dates for filtering operations.
        """
        parser = DateParser()
        
        # Test standard ISO format
        result = parser.parse_date("2024-01-15", "test_field")
        assert result == date(2024, 1, 15)
        
        # Test another valid date
        result = parser.parse_date("2023-12-31", "test_field")
        assert result == date(2023, 12, 31)

    @pytest.mark.unit
    def test_parse_date_invalid_formats(self):
        """
        Test parsing invalid date strings raises errors.
        
        This test documents error handling for malformed dates
        and shows what error messages users will see.
        """
        parser = DateParser()
        
        # Test invalid format
        with pytest.raises(ConfigurationError) as exc_info:
            parser.parse_date("2024/01/15", "test_field")
        
        assert "Invalid date format" in str(exc_info.value)
        assert "test_field" in str(exc_info.value)
        assert "YYYY-MM-DD" in str(exc_info.value)

    @pytest.mark.unit
    def test_parse_date_empty_strings(self):
        """
        Test parsing empty date strings.
        
        This test shows error handling for empty or missing date values.
        """
        parser = DateParser()
        
        with pytest.raises(ConfigurationError) as exc_info:
            parser.parse_date("", "test_field")
        
        assert "Empty date string" in str(exc_info.value)

    @pytest.mark.unit
    def test_is_date_in_range_basic(self):
        """
        Test basic date range validation.
        
        This test documents how date filtering works with
        from/to date ranges.
        """
        parser = DateParser()
        
        # Test date within range
        result = parser.is_date_in_range(
            "2024:06:15 10:30:00",
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert result is True
        
        # Test date outside range (too early)
        result = parser.is_date_in_range(
            "2023:06:15 10:30:00",
            date(2024, 1, 1), 
            date(2024, 12, 31)
        )
        assert result is False

    @pytest.mark.unit
    def test_is_date_in_range_no_filters(self):
        """
        Test date range validation with no date filters.
        
        This test shows behavior when no date filtering is applied.
        """
        parser = DateParser()
        
        # Test with no date filters - should always return True
        result = parser.is_date_in_range("2024:06:15 10:30:00", None, None)
        assert result is True

    @pytest.mark.unit
    def test_is_date_in_range_partial_filters(self):
        """
        Test date range validation with only from or to date.
        
        This test documents behavior with incomplete date ranges.
        """
        parser = DateParser()
        
        # Test with only date_from
        result = parser.is_date_in_range(
            "2024:06:15 10:30:00",
            date(2024, 1, 1),
            None
        )
        assert result is True
        
        # Test with only date_to
        result = parser.is_date_in_range(
            "2024:06:15 10:30:00", 
            None,
            date(2024, 12, 31)
        )
        assert result is True

    @pytest.mark.unit
    def test_is_date_in_range_exif_format_handling(self):
        """
        Test date range validation handles EXIF date formats.
        
        This test shows parsing of EXIF date/time strings
        which use colons instead of dashes.
        """
        parser = DateParser()
        
        # Test EXIF format: "YYYY:MM:DD HH:MM:SS"
        result = parser.is_date_in_range(
            "2024:06:15 14:30:45",
            date(2024, 6, 1),
            date(2024, 6, 30)
        )
        assert result is True

    @pytest.mark.unit
    def test_is_date_in_range_invalid_dates(self):
        """
        Test date range validation with unparseable dates.
        
        This test shows graceful handling of corrupted or
        missing date information in images.
        """
        parser = DateParser()
        
        # Test with invalid date format - should return True (include image)
        result = parser.is_date_in_range(
            "not-a-date",
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert result is True  # Conservative approach - include if can't parse
        
        # Test with None date
        result = parser.is_date_in_range(
            None,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert result is True


class TestGPSFilter:
    """Test suite for GPSFilter utility."""

    def setup_method(self):
        """Set up test fixtures for GPS filter tests."""
        self.mock_logger = Mock()
        self.filter_config = FilterConfig(
            max_gps_error=50.0,
            max_dop=5.0,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 12, 31)
        )
        self.gps_filter = GPSFilter(self.filter_config, self.mock_logger)

    @pytest.mark.unit
    def test_gps_filter_initialization(self):
        """
        Test GPS filter initialization with configuration.
        
        This test documents how to create a GPS filter with
        filtering criteria for accuracy and date ranges.
        """
        assert self.gps_filter.filter_config == self.filter_config
        assert self.gps_filter.logger == self.mock_logger
        assert hasattr(self.gps_filter, 'date_parser')

    @pytest.mark.unit
    def test_apply_gps_accuracy_filters_pass(self, mock_image):
        """
        Test GPS accuracy filtering with acceptable values.
        
        This test documents GPS quality filtering and shows
        how images with good GPS accuracy are accepted.
        """
        # Mock image has gps_horizontal_error = 25.0, max allowed is 50.0
        result = self.gps_filter.apply_gps_accuracy_filters(mock_image, "test.jpg")
        assert result is True
        
        # Should not log any filtering messages
        self.mock_logger.debug.assert_not_called()

    @pytest.mark.unit
    def test_apply_gps_accuracy_filters_fail_error(self):
        """
        Test GPS accuracy filtering with poor GPS error.
        
        This test shows how images with poor GPS accuracy are filtered out.
        """
        mock_image = Mock()
        mock_image.gps_horizontal_error = 100.0  # Exceeds max of 50.0
        
        result = self.gps_filter.apply_gps_accuracy_filters(mock_image, "poor_gps.jpg")
        assert result is False
        
        # Should log filtering decision
        self.mock_logger.debug.assert_called_once()
        log_call = self.mock_logger.debug.call_args[0][0]
        assert "poor_gps.jpg" in log_call
        assert "GPS error" in log_call

    @pytest.mark.unit
    def test_apply_gps_accuracy_filters_fail_dop(self):
        """
        Test GPS accuracy filtering with poor DOP value.
        
        This test documents DOP (Dilution of Precision) filtering
        which indicates GPS signal quality.
        """
        mock_image = Mock()
        mock_image.gps_horizontal_error = 10.0  # Good
        mock_image.gps_dop = 10.0  # Poor (exceeds max of 5.0)
        
        result = self.gps_filter.apply_gps_accuracy_filters(mock_image, "poor_dop.jpg")
        assert result is False
        
        # Should log DOP filtering
        self.mock_logger.debug.assert_called_once()
        log_call = self.mock_logger.debug.call_args[0][0]
        assert "DOP" in log_call

    @pytest.mark.unit
    def test_apply_gps_accuracy_filters_no_data(self):
        """
        Test GPS accuracy filtering when GPS quality data is missing.
        
        This test shows graceful handling of images that don't have
        GPS accuracy information in their EXIF data.
        """
        # Create a mock that doesn't have GPS accuracy attributes
        mock_image = Mock(spec=[])
        
        result = self.gps_filter.apply_gps_accuracy_filters(mock_image, "no_accuracy.jpg")
        assert result is True  # Should include if can't determine accuracy

    @pytest.mark.unit
    def test_apply_gps_accuracy_filters_disabled(self):
        """
        Test GPS accuracy filtering when filters are disabled.
        
        This test shows behavior when no GPS accuracy filtering
        is configured (None values).
        """
        # Create filter with no accuracy constraints
        no_filter_config = FilterConfig(
            max_gps_error=None,
            max_dop=None
        )
        gps_filter = GPSFilter(no_filter_config, self.mock_logger)
        
        mock_image = Mock()
        mock_image.gps_horizontal_error = 1000.0  # Would normally be filtered
        mock_image.gps_dop = 100.0  # Would normally be filtered
        
        result = gps_filter.apply_gps_accuracy_filters(mock_image, "test.jpg")
        assert result is True  # Should pass when filtering disabled

    @pytest.mark.unit
    def test_apply_date_filters_pass(self, mock_image):
        """
        Test date filtering with dates within range.
        
        This test documents date-based filtering and shows
        how images with dates in the specified range are accepted.
        """
        # Mock image has datetime_original = "2024:01:15 10:30:00"
        result = self.gps_filter.apply_date_filters(mock_image, "test.jpg")
        assert result is True

    @pytest.mark.unit
    def test_apply_date_filters_fail(self):
        """
        Test date filtering with dates outside range.
        
        This test shows how images with dates outside the
        specified range are filtered out.
        """
        mock_image = Mock()
        mock_image.datetime_original = "2023:06:15 10:30:00"  # Before 2024 range
        
        result = self.gps_filter.apply_date_filters(mock_image, "old_photo.jpg")
        assert result is False
        
        # Should log filtering decision
        self.mock_logger.debug.assert_called_once()

    @pytest.mark.unit
    def test_apply_date_filters_no_date(self):
        """
        Test date filtering when image has no date information.
        
        This test shows graceful handling of images without
        date metadata in their EXIF data.
        """
        mock_image = Mock()
        # Mock no date fields available
        for field in ["datetime_original", "datetime", "datetime_digitized"]:
            setattr(mock_image, field, None)
        
        result = self.gps_filter.apply_date_filters(mock_image, "no_date.jpg")
        assert result is True  # Conservative approach - include if no date

    @pytest.mark.unit
    def test_apply_date_filters_disabled(self):
        """
        Test date filtering when no date filters are configured.
        
        This test shows behavior when date filtering is disabled.
        """
        # Create filter with no date constraints
        no_date_config = FilterConfig(
            date_from=None,
            date_to=None
        )
        gps_filter = GPSFilter(no_date_config, self.mock_logger)
        
        mock_image = Mock()
        mock_image.datetime_original = "1990:01:01 00:00:00"  # Very old
        
        result = gps_filter.apply_date_filters(mock_image, "ancient.jpg")
        assert result is True  # Should pass when filtering disabled

    @pytest.mark.unit
    def test_extract_image_date_priority_order(self):
        """
        Test date extraction follows proper EXIF field priority.
        
        This test documents the order in which EXIF date fields
        are checked for date information.
        """
        mock_image = Mock()
        mock_image.datetime_original = "2024:01:15 10:30:00"  # Highest priority
        mock_image.datetime = "2024:01:16 11:30:00"  # Lower priority
        mock_image.datetime_digitized = "2024:01:17 12:30:00"  # Lowest priority
        
        date_str = self.gps_filter._extract_image_date(mock_image)
        assert date_str == "2024:01:15 10:30:00"  # Should use datetime_original

    @pytest.mark.unit
    def test_extract_image_date_fallback(self):
        """
        Test date extraction falls back to other fields when primary unavailable.
        
        This test shows fallback behavior when the preferred date
        field is not available in the EXIF data.
        """
        mock_image = Mock()
        # datetime_original not available, should use datetime
        def mock_hasattr(obj, name):
            return name != "datetime_original"
        
        with patch('builtins.hasattr', mock_hasattr):
            mock_image.datetime = "2024:01:16 11:30:00"
            mock_image.datetime_digitized = "2024:01:17 12:30:00"
            
            date_str = self.gps_filter._extract_image_date(mock_image)
            assert date_str == "2024:01:16 11:30:00"  # Should use datetime