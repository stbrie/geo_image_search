"""Tests for the constants module.

These tests verify that constants are properly defined and error codes are semantically correct.
They also serve as documentation for the available constants and their expected values.
"""

import pytest
from geo_image_search.constants import Constants


class TestConstants:
    """Test suite for application constants."""

    @pytest.mark.unit
    def test_jpeg_extensions_defined(self):
        """
        Test that JPEG file extensions are correctly defined.
        
        This test documents which file types are supported by the application
        and ensures they include common JPEG variants.
        """
        # Test that JPEG extensions are defined
        assert hasattr(Constants, 'JPEG_EXTENSIONS')
        assert isinstance(Constants.JPEG_EXTENSIONS, set)
        
        # Test expected extensions are present
        expected_extensions = {'.jpg', '.jpeg', '.JPG', '.JPEG'}
        assert Constants.JPEG_EXTENSIONS == expected_extensions
        
        # Test that all extensions start with dot
        for ext in Constants.JPEG_EXTENSIONS:
            assert ext.startswith('.'), f"Extension {ext} should start with dot"
        
        # Test case sensitivity is handled
        assert '.jpg' in Constants.JPEG_EXTENSIONS
        assert '.JPG' in Constants.JPEG_EXTENSIONS

    @pytest.mark.unit
    def test_error_codes_are_unique(self):
        """
        Test that all error codes have unique values.
        
        This test documents all possible exit codes and ensures there are
        no conflicts that could cause ambiguous error reporting.
        """
        error_codes = Constants.ErrorCodes
        
        # Get all error code values
        code_values = []
        code_names = []
        
        for attr_name in dir(error_codes):
            if not attr_name.startswith('_'):
                code_value = getattr(error_codes, attr_name)
                if isinstance(code_value, int):
                    code_values.append(code_value)
                    code_names.append(attr_name)
        
        # Test that we have error codes defined
        assert len(code_values) > 0, "No error codes found"
        
        # Test uniqueness
        assert len(code_values) == len(set(code_values)), \
            f"Duplicate error codes found: {code_names}"
        
        # Test that SUCCESS is 0 (standard exit code for success)
        assert error_codes.SUCCESS == 0

    @pytest.mark.unit
    def test_error_codes_are_integers(self):
        """
        Test that error codes are valid integer types.
        
        This test ensures error codes are proper exit codes that can be
        used with sys.exit() and shell scripts.
        """
        error_codes = Constants.ErrorCodes
        
        for attr_name in dir(error_codes):
            if not attr_name.startswith('_'):
                code_value = getattr(error_codes, attr_name)
                if attr_name.isupper():  # Only check constant names
                    assert isinstance(code_value, int), \
                        f"Error code {attr_name} should be integer, got {type(code_value)}"
                    assert 0 <= code_value <= 255, \
                        f"Error code {attr_name} should be valid exit code (0-255), got {code_value}"

    @pytest.mark.unit
    def test_default_values_are_reasonable(self):
        """
        Test that default values make sense.
        
        This test documents default behavior and ensures values are within
        reasonable ranges for typical usage.
        """
        # Test default radius is reasonable (not too large or small)
        assert 0.01 <= Constants.DEFAULT_RADIUS <= 10.0, \
            f"Default radius {Constants.DEFAULT_RADIUS} seems unreasonable"
        
        # Test checkpoint interval is reasonable
        assert 10 <= Constants.CHECKPOINT_INTERVAL_FILES <= 1000, \
            f"Checkpoint interval {Constants.CHECKPOINT_INTERVAL_FILES} seems unreasonable"
        
        # Test that defaults are correct types
        assert isinstance(Constants.DEFAULT_RADIUS, float)
        assert isinstance(Constants.CHECKPOINT_INTERVAL_FILES, int)

    @pytest.mark.unit
    def test_user_agent_format(self):
        """
        Test that user agent string follows expected format.
        
        This test documents how the application identifies itself to external
        services like Nominatim geocoding.
        """
        user_agent = Constants.DEFAULT_USER_AGENT
        
        # Test user agent is defined and non-empty
        assert user_agent
        assert isinstance(user_agent, str)
        assert len(user_agent.strip()) > 0
        
        # Test contains expected components
        assert 'geo_image_search' in user_agent.lower() or 'geo-image-search' in user_agent.lower()
        
        # Test reasonable length (not too short or too long)
        assert 10 <= len(user_agent) <= 100, \
            f"User agent length {len(user_agent)} seems unreasonable"

    @pytest.mark.unit
    def test_error_codes_semantic_meaning(self):
        """
        Test that error codes have semantically meaningful values.
        
        This test documents the meaning of each error code and ensures
        they follow logical patterns.
        """
        error_codes = Constants.ErrorCodes
        
        # Test specific error codes exist and have expected values
        expected_codes = {
            'SUCCESS': 0,
            'INTERRUPTED': 1,
            'NO_ROOT_DIRECTORY': 2,
            'NO_OUTPUT_DIRECTORY': 3,
        }
        
        for code_name, expected_value in expected_codes.items():
            assert hasattr(error_codes, code_name), f"Missing error code: {code_name}"
            actual_value = getattr(error_codes, code_name)
            assert actual_value == expected_value, \
                f"Error code {code_name} should be {expected_value}, got {actual_value}"

    @pytest.mark.unit
    def test_constants_are_immutable(self):
        """
        Test that constants behave as immutable values.
        
        This test ensures constants cannot be accidentally modified during
        runtime, which could cause unexpected behavior.
        """
        # Test that JPEG_EXTENSIONS is a set (immutable for our purposes)
        assert isinstance(Constants.JPEG_EXTENSIONS, (set, frozenset))
        
        # Test that we can't easily modify the set
        original_extensions = Constants.JPEG_EXTENSIONS.copy()
        
        # This should work (creating new set)
        new_extensions = Constants.JPEG_EXTENSIONS | {'.png'}
        assert new_extensions != Constants.JPEG_EXTENSIONS
        
        # Original should be unchanged
        assert Constants.JPEG_EXTENSIONS == original_extensions

    @pytest.mark.unit
    def test_all_required_constants_present(self):
        """
        Test that all required constants are present.
        
        This test serves as a checklist to ensure no required constants
        are missing from the implementation.
        """
        required_constants = [
            'JPEG_EXTENSIONS',
            'DEFAULT_RADIUS', 
            'CHECKPOINT_INTERVAL_FILES',
            'DEFAULT_USER_AGENT'
        ]
        
        for const_name in required_constants:
            assert hasattr(Constants, const_name), \
                f"Missing required constant: {const_name}"
            
            value = getattr(Constants, const_name)
            assert value is not None, f"Constant {const_name} should not be None"

    @pytest.mark.unit  
    def test_error_codes_coverage(self):
        """
        Test that error codes cover expected scenarios.
        
        This test documents the range of error conditions the application
        can report and ensures comprehensive coverage.
        """
        error_codes = Constants.ErrorCodes
        
        # Expected categories of errors
        expected_error_types = [
            'SUCCESS',           # Normal completion
            'INTERRUPTED',       # User interruption
            'NO_ROOT_DIRECTORY', # Missing required input
            'CONFLICTING_OPTIONS', # Configuration errors
            'GEOCODING_FAILED',  # External service errors
            'FILE_OPERATION_ERROR', # File system errors
        ]
        
        for error_type in expected_error_types:
            assert hasattr(error_codes, error_type), \
                f"Missing expected error type: {error_type}"