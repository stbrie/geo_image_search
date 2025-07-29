"""Tests for the exceptions module.

These tests verify custom exception hierarchy and error handling.
They serve as documentation for the types of errors the application can encounter.
"""

import pytest
from geo_image_search.exceptions import (
    GeoImageSearchError, ConfigurationError, GPSDataError, FileOperationError
)


class TestExceptionHierarchy:
    """Test suite for exception inheritance and hierarchy."""

    @pytest.mark.unit
    def test_base_exception_exists(self):
        """
        Test that base exception class exists and is usable.
        
        This test documents the base exception type that all application
        errors inherit from, enabling comprehensive error handling.
        """
        # Test that we can create and raise the base exception
        with pytest.raises(GeoImageSearchError):
            raise GeoImageSearchError("Test error message")
        
        # Test that it's a proper Exception subclass
        assert issubclass(GeoImageSearchError, Exception)

    @pytest.mark.unit
    def test_exception_inheritance_chain(self):
        """
        Test that all custom exceptions inherit from base exception.
        
        This test documents the exception hierarchy and ensures all
        application errors can be caught with a single except clause.
        """
        # Test ConfigurationError inheritance
        assert issubclass(ConfigurationError, GeoImageSearchError)
        assert issubclass(ConfigurationError, Exception)
        
        # Test GPSDataError inheritance  
        assert issubclass(GPSDataError, GeoImageSearchError)
        assert issubclass(GPSDataError, Exception)
        
        # Test FileOperationError inheritance
        assert issubclass(FileOperationError, GeoImageSearchError)
        assert issubclass(FileOperationError, Exception)

    @pytest.mark.unit
    def test_can_catch_all_with_base_exception(self):
        """
        Test that base exception can catch all derived exceptions.
        
        This test demonstrates how to implement comprehensive error
        handling that catches all application-specific errors.
        """
        # Test catching ConfigurationError with base exception
        with pytest.raises(GeoImageSearchError):
            raise ConfigurationError("Configuration problem")
        
        # Test catching GPSDataError with base exception
        with pytest.raises(GeoImageSearchError):
            raise GPSDataError("GPS processing problem")
        
        # Test catching FileOperationError with base exception
        with pytest.raises(GeoImageSearchError):
            raise FileOperationError("File operation problem")


class TestConfigurationError:
    """Test suite for ConfigurationError scenarios."""

    @pytest.mark.unit
    def test_configuration_error_creation(self):
        """
        Test ConfigurationError creation and message handling.
        
        This test documents how configuration errors are created
        and what information they should contain.
        """
        error_message = "Invalid configuration: missing required field"
        
        with pytest.raises(ConfigurationError) as exc_info:
            raise ConfigurationError(error_message)
        
        assert str(exc_info.value) == error_message
        assert isinstance(exc_info.value, ConfigurationError)
        assert isinstance(exc_info.value, GeoImageSearchError)

    @pytest.mark.unit
    def test_configuration_error_scenarios(self):
        """
        Test various configuration error scenarios.
        
        This test documents the types of configuration problems
        that should raise ConfigurationError.
        """
        # Test missing required directory
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("Root directory not specified")
        
        # Test conflicting options
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("Cannot use --find-only with --sort-by-location")
        
        # Test invalid date format
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("Invalid date format: expected YYYY-MM-DD")
        
        # Test geocoding failure
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("Could not geocode address: service unavailable")

    @pytest.mark.unit
    def test_configuration_error_with_details(self):
        """
        Test ConfigurationError with detailed context.
        
        This test shows how to provide helpful error messages
        that include context about what went wrong.
        """
        field_name = "date_from"
        invalid_value = "not-a-date"
        
        error_msg = f"Invalid date format for {field_name}: {invalid_value}. Use YYYY-MM-DD"
        
        with pytest.raises(ConfigurationError) as exc_info:
            raise ConfigurationError(error_msg)
        
        error_str = str(exc_info.value)
        assert field_name in error_str
        assert invalid_value in error_str
        assert "YYYY-MM-DD" in error_str


class TestGPSDataError:
    """Test suite for GPSDataError scenarios."""

    @pytest.mark.unit
    def test_gps_data_error_creation(self):
        """
        Test GPSDataError creation and usage.
        
        This test documents how GPS processing errors are handled
        and what information they should convey.
        """
        error_message = "Invalid GPS coordinates in image EXIF data"
        
        with pytest.raises(GPSDataError) as exc_info:
            raise GPSDataError(error_message)
        
        assert str(exc_info.value) == error_message
        assert isinstance(exc_info.value, GPSDataError)
        assert isinstance(exc_info.value, GeoImageSearchError)

    @pytest.mark.unit
    def test_gps_data_error_scenarios(self):
        """
        Test various GPS data error scenarios.
        
        This test documents the types of GPS processing problems
        that should raise GPSDataError.
        """
        # Test missing GPS data
        with pytest.raises(GPSDataError):
            raise GPSDataError("Image contains no GPS information")
        
        # Test corrupted GPS data
        with pytest.raises(GPSDataError):
            raise GPSDataError("GPS coordinates are corrupted or invalid")
        
        # Test coordinate validation failure
        with pytest.raises(GPSDataError):
            raise GPSDataError("Latitude must be between -90 and 90 degrees")
        
        # Test search coordinates not initialized
        with pytest.raises(GPSDataError):
            raise GPSDataError("Search coordinates not initialized")

    @pytest.mark.unit
    def test_gps_data_error_with_filename(self):
        """
        Test GPSDataError with file context.
        
        This test shows how to provide file-specific error information
        for better debugging and user feedback.
        """
        filename = "vacation_photo.jpg"
        error_msg = f"Could not extract GPS data from {filename}: EXIF data corrupted"
        
        with pytest.raises(GPSDataError) as exc_info:
            raise GPSDataError(error_msg)
        
        error_str = str(exc_info.value)
        assert filename in error_str
        assert "GPS data" in error_str
        assert "EXIF" in error_str


class TestFileOperationError:
    """Test suite for FileOperationError scenarios."""

    @pytest.mark.unit
    def test_file_operation_error_creation(self):
        """
        Test FileOperationError creation and usage.
        
        This test documents how file system errors are handled
        and what information they should include.
        """
        error_message = "Could not write to output directory: permission denied"
        
        with pytest.raises(FileOperationError) as exc_info:
            raise FileOperationError(error_message)
        
        assert str(exc_info.value) == error_message
        assert isinstance(exc_info.value, FileOperationError)
        assert isinstance(exc_info.value, GeoImageSearchError)

    @pytest.mark.unit
    def test_file_operation_error_scenarios(self):
        """
        Test various file operation error scenarios.
        
        This test documents the types of file system problems
        that should raise FileOperationError.
        """
        # Test directory creation failure
        with pytest.raises(FileOperationError):
            raise FileOperationError("Could not create output directory: disk full")
        
        # Test file read failure
        with pytest.raises(FileOperationError):
            raise FileOperationError("Could not read image file: file not found")
        
        # Test file write failure
        with pytest.raises(FileOperationError):
            raise FileOperationError("Could not write CSV file: permission denied")
        
        # Test directory access failure
        with pytest.raises(FileOperationError):
            raise FileOperationError("Could not access root directory: permission denied")

    @pytest.mark.unit
    def test_file_operation_error_with_path(self):
        """
        Test FileOperationError with file path context.
        
        This test shows how to provide specific file path information
        in error messages for better troubleshooting.
        """
        file_path = "/restricted/directory/file.jpg"
        error_msg = f"Could not read file {file_path}: permission denied"
        
        with pytest.raises(FileOperationError) as exc_info:
            raise FileOperationError(error_msg)
        
        error_str = str(exc_info.value)
        assert file_path in error_str
        assert "permission denied" in error_str


class TestExceptionMessages:
    """Test suite for exception message quality and usefulness."""

    @pytest.mark.unit
    def test_exception_messages_are_helpful(self):
        """
        Test that exception messages provide actionable information.
        
        This test ensures error messages help users understand what
        went wrong and how to fix the problem.
        """
        # Test helpful configuration error
        config_error = ConfigurationError(
            "Root directory '/nonexistent/path' does not exist. "
            "Please specify a valid directory with -d/--root"
        )
        
        message = str(config_error)
        assert "/nonexistent/path" in message
        assert "does not exist" in message
        assert "-d/--root" in message  # Shows how to fix

    @pytest.mark.unit
    def test_exceptions_preserve_original_error_info(self):
        """
        Test that exceptions can wrap and preserve original error information.
        
        This test shows how to chain exceptions to preserve the full
        error context while providing application-specific error types.
        """
        original_error = OSError("No such file or directory")
        
        # Test chaining with 'from' clause
        with pytest.raises(FileOperationError) as exc_info:
            try:
                raise original_error
            except OSError as e:
                raise FileOperationError(f"File operation failed: {e}") from e
        
        # Test that original error info is preserved
        assert exc_info.value.__cause__ is original_error
        assert "No such file or directory" in str(exc_info.value)

    @pytest.mark.unit
    def test_exception_str_representation(self):
        """
        Test exception string representations are informative.
        
        This test ensures exceptions have clear string representations
        for logging, debugging, and user feedback.
        """
        exceptions_to_test = [
            ConfigurationError("Test configuration error"),
            GPSDataError("Test GPS data error"),
            FileOperationError("Test file operation error"),
            GeoImageSearchError("Test base error")
        ]
        
        for exc in exceptions_to_test:
            str_repr = str(exc)
            assert len(str_repr) > 0
            assert "Test" in str_repr
            assert "error" in str_repr.lower()

    @pytest.mark.unit
    def test_exceptions_support_empty_messages(self):
        """
        Test that exceptions handle empty or None messages gracefully.
        
        This test ensures exceptions don't break when created without
        detailed error messages.
        """
        # Test with empty string
        empty_error = ConfigurationError("")
        assert str(empty_error) == ""
        
        # Test with None (should not break)
        none_error = GPSDataError()
        str_repr = str(none_error)
        assert isinstance(str_repr, str)  # Should not raise exception


class TestExceptionUsagePatterns:
    """Test suite for common exception usage patterns."""

    @pytest.mark.unit
    def test_specific_exception_catching(self):
        """
        Test catching specific exception types.
        
        This test demonstrates how to handle specific error types
        differently in application code.
        """
        def raise_config_error():
            raise ConfigurationError("Config problem")
        
        def raise_gps_error():
            raise GPSDataError("GPS problem")
        
        # Test catching specific ConfigurationError
        with pytest.raises(ConfigurationError):
            raise_config_error()
        
        # Test catching specific GPSDataError
        with pytest.raises(GPSDataError):
            raise_gps_error()

    @pytest.mark.unit
    def test_generic_exception_catching(self):
        """
        Test catching all application exceptions generically.
        
        This test shows how to implement fallback error handling
        that catches any application-specific error.
        """
        def raise_various_errors(error_type):
            if error_type == "config":
                raise ConfigurationError("Config error")
            elif error_type == "gps":
                raise GPSDataError("GPS error")  
            elif error_type == "file":
                raise FileOperationError("File error")
        
        # Test that all can be caught with base exception
        for error_type in ["config", "gps", "file"]:
            with pytest.raises(GeoImageSearchError):
                raise_various_errors(error_type)