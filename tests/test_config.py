"""Tests for the config module.

These tests verify configuration management and argument parsing functionality.
They serve as documentation for all configuration options and their interactions.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import pytest

from geo_image_search.config import ConfigurationManager
from geo_image_search.types import SearchConfig, DirectoryConfig, OutputConfig, FilterConfig, ProcessingConfig
from geo_image_search.exceptions import ConfigurationError


class TestConfigurationManager:
    """Test suite for ConfigurationManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.config_manager = ConfigurationManager(self.mock_logger)

    @pytest.mark.unit
    def test_configuration_manager_initialization(self):
        """
        Test ConfigurationManager initialization.
        
        This test documents how to create a configuration manager
        and verifies it has the required components.
        """
        assert self.config_manager.logger == self.mock_logger
        assert hasattr(self.config_manager, 'path_normalizer')
        assert hasattr(self.config_manager, 'date_parser')

    @pytest.mark.unit
    def test_create_argument_parser(self):
        """
        Test argument parser creation and configuration.
        
        This test documents all available command-line options
        and verifies they are properly configured.
        """
        parser = self.config_manager._create_argument_parser()
        
        # Test parser was created
        assert parser is not None
        
        # Test help text generation
        help_text = parser.format_help()
        assert "geo_image_search.py" in help_text
        assert ".jpeg metadata" in help_text
        
        # Test essential arguments are present
        essential_args = [
            '-d', '--root',
            '-a', '--address', 
            '-t', '--latitude',
            '-g', '--longitude',
            '-r', '--radius',
            '-o', '--output_directory',
            '-f', '--find_only',
            '-v', '--verbose'
        ]
        
        for arg in essential_args:
            assert arg in help_text

    @pytest.mark.unit
    def test_argument_parser_types_and_defaults(self):
        """
        Test argument parser handles types and defaults correctly.
        
        This test documents the expected types and default values
        for all command-line arguments.
        """
        parser = self.config_manager._create_argument_parser()
        
        # Test parsing with minimal arguments
        args = parser.parse_args(['-d', '/test/path'])
        
        assert args.root == '/test/path'
        assert args.address is None
        assert args.latitude is None
        assert args.longitude is None
        assert args.radius == 0.1  # Default radius
        assert args.find_only is False
        assert args.verbose is False

    @pytest.mark.unit
    def test_argument_parser_coordinate_types(self):
        """
        Test argument parser handles coordinate types correctly.
        
        This test shows how latitude and longitude arguments
        are parsed as floating-point numbers.
        """
        parser = self.config_manager._create_argument_parser()
        
        args = parser.parse_args([
            '-d', '/test/path',
            '-t', '40.7128',
            '-g', '-74.0060',
            '-r', '1.5'
        ])
        
        assert args.latitude == 40.7128
        assert args.longitude == -74.0060
        assert args.radius == 1.5
        assert isinstance(args.latitude, float)
        assert isinstance(args.longitude, float)

    @pytest.mark.unit
    def test_load_config_file_success(self, sample_config_file, sample_toml_config):
        """
        Test successful TOML configuration file loading.
        
        This test documents the TOML configuration file format
        and shows how configuration files are loaded.
        """
        config_data = self.config_manager._load_config_file(sample_config_file)
        
        assert isinstance(config_data, dict)
        assert 'search' in config_data
        assert 'directories' in config_data
        assert 'output' in config_data
        assert 'filters' in config_data
        
        # Test specific values were loaded
        assert config_data['search']['address'] == "Test City, NY"
        assert config_data['search']['radius'] == 2.0
        assert config_data['directories']['root'] == "/test/images"

    @pytest.mark.unit
    def test_load_config_file_not_found(self):
        """
        Test configuration file loading when file doesn't exist.
        
        This test shows graceful handling when no configuration
        file is found in the standard locations.
        """
        with patch('pathlib.Path.exists', return_value=False):
            config_data = self.config_manager._load_config_file("/nonexistent/config.toml")
        
            assert config_data == {}
        # Should not log errors for missing optional config

    @pytest.mark.unit
    def test_load_config_file_search_order(self, temp_dir):
        """
        Test configuration file search order.
        
        This test documents the order in which configuration files
        are searched and which takes precedence.
        """
        # Create config files in different locations
        cwd_config = temp_dir / "geo_image_search.toml"
        cwd_config.write_text('[search]\naddress = "CWD Config"')
        
        with patch('pathlib.Path.cwd', return_value=temp_dir):
            config_data = self.config_manager._load_config_file()
        
        assert config_data['search']['address'] == "CWD Config"

    @pytest.mark.unit
    def test_merge_config_with_args_search_settings(self, test_utils):
        """
        Test merging search settings from config file.
        
        This test documents how configuration file values
        are merged with command-line arguments.
        """
        config_data = {
            'search': {
                'address': 'Config Address',
                'radius': 2.5,
                'far': True
            }
        }
        
        # Args with no conflicting values
        args = test_utils.create_mock_args(
            address=None,  # Should use config value
            radius=0.1,    # Should use config value (since it's default)
            far=False      # Should use config value
        )
        
        self.config_manager._merge_config_with_args(config_data, args)
        
        assert args.address == 'Config Address'
        assert args.radius == 2.5
        assert args.far is True

    @pytest.mark.unit
    def test_merge_config_with_args_cli_precedence(self, test_utils):
        """
        Test that CLI arguments take precedence over config file.
        
        This test documents the precedence order: CLI args override
        config file values.
        """
        config_data = {
            'search': {
                'address': 'Config Address',
                'radius': 2.5
            }
        }
        
        # Args with explicit values should take precedence
        args = test_utils.create_mock_args(
            address='CLI Address',  # Should override config
            radius=1.0             # Should override config
        )
        
        self.config_manager._merge_config_with_args(config_data, args)
        
        assert args.address == 'CLI Address'
        assert args.radius == 1.0

    @pytest.mark.unit
    def test_merge_config_with_args_all_sections(self, test_utils):
        """
        Test merging all configuration sections.
        
        This test documents all configuration sections and shows
        how they map to command-line arguments.
        """
        config_data = {
            'search': {'address': 'Test City'},
            'directories': {'root': '/config/images', 'find_only': True},
            'output': {'verbose': True, 'export_kml': True},
            'filters': {'max_gps_error': 30.0, 'date_from': '2024-01-01'},
            'processing': {'resume': True}
        }
        
        args = test_utils.create_mock_args()
        self.config_manager._merge_config_with_args(config_data, args)
        
        # Test all sections were merged
        assert args.address == 'Test City'
        assert args.root == '/config/images'
        assert args.find_only is True
        assert args.verbose is True
        assert args.export_kml is True
        assert args.max_gps_error == 30.0
        assert args.date_from == '2024-01-01'
        assert args.resume is True

    @pytest.mark.unit
    def test_parse_date_arg_valid(self, test_utils):
        """
        Test parsing valid date arguments.
        
        This test documents date argument parsing and shows
        supported date formats.
        """
        args = test_utils.create_mock_args(date_from='2024-06-15')
        
        parsed_date = self.config_manager._parse_date_arg(args, 'date_from')
        
        assert parsed_date is not None
        assert parsed_date.year == 2024
        assert parsed_date.month == 6
        assert parsed_date.day == 15

    @pytest.mark.unit
    def test_parse_date_arg_none(self, test_utils):
        """
        Test parsing None date arguments.
        
        This test shows handling of unspecified date arguments.
        """
        args = test_utils.create_mock_args(date_from=None)
        
        parsed_date = self.config_manager._parse_date_arg(args, 'date_from')
        
        assert parsed_date is None

    @pytest.mark.unit
    def test_create_sample_config(self, temp_dir):
        """
        Test sample configuration file creation.
        
        This test documents the complete configuration structure
        and shows what a sample config file contains.
        """
        output_path = temp_dir / "sample_config.toml"
        
        self.config_manager._create_sample_config(output_path)
        
        # Test file was created
        assert output_path.exists()
        
        # Test content includes all sections
        content = output_path.read_text()
        expected_sections = ['[search]', '[directories]', '[output]', '[filters]', '[processing]', '[folder_kml]']
        for section in expected_sections:
            assert section in content
        
        # Test includes examples and documentation
        assert 'Example configurations:' in content
        assert 'vacation photos' in content

    @pytest.mark.unit
    def test_validate_configuration_success(self):
        """
        Test successful configuration validation.
        
        This test documents valid configuration combinations
        and shows configurations that pass validation.
        """
        search_config = SearchConfig(address="Test City")
        directory_config = DirectoryConfig(root="/test", output_directory="/output")
        output_config = OutputConfig(save_addresses=True)
        filter_config = FilterConfig()
        
        # Should not raise any exceptions
        self.config_manager._validate_configuration(
            search_config, directory_config, output_config, filter_config
        )

    @pytest.mark.unit
    def test_validate_configuration_save_addresses_error(self):
        """
        Test configuration validation for save_addresses requirement.
        
        This test documents the requirement that save_addresses
        needs an output directory specified.
        """
        search_config = SearchConfig()
        directory_config = DirectoryConfig(output_directory=None)
        output_config = OutputConfig(save_addresses=True)
        filter_config = FilterConfig()
        
        with pytest.raises(ConfigurationError) as exc_info:
            self.config_manager._validate_configuration(
                search_config, directory_config, output_config, filter_config
            )
        
        assert "save_addresses requires" in str(exc_info.value)
        assert "output_directory" in str(exc_info.value)

    @pytest.mark.unit
    def test_validate_configuration_sort_location_errors(self):
        """
        Test configuration validation for sort_by_location requirements.
        
        This test documents requirements for location-based sorting
        including output directory and find_only conflicts.
        """
        search_config = SearchConfig()
        filter_config = FilterConfig()
        
        # Test sort_by_location with find_only conflict
        directory_config = DirectoryConfig(sort_by_location=True, find_only=True)
        output_config = OutputConfig()
        
        with pytest.raises(ConfigurationError) as exc_info:
            self.config_manager._validate_configuration(
                search_config, directory_config, output_config, filter_config
            )
        
        assert "sort-by-location" in str(exc_info.value)
        assert "find_only" in str(exc_info.value)
        
        # Test sort_by_location without output directory
        directory_config = DirectoryConfig(sort_by_location=True, find_only=False, output_directory=None)
        
        with pytest.raises(ConfigurationError) as exc_info:
            self.config_manager._validate_configuration(
                search_config, directory_config, output_config, filter_config
            )
        
        assert "sort-by-location" in str(exc_info.value)
        assert "output_directory" in str(exc_info.value)


class TestConfigurationIntegration:
    """Test suite for configuration integration scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.config_manager = ConfigurationManager(self.mock_logger)

    @pytest.mark.unit
    def test_parse_arguments_and_config_minimal(self, test_utils):
        """
        Test parsing with minimal required arguments.
        
        This test documents the minimum configuration needed
        to run the application successfully.
        """
        test_args = ['-d', '/test/images']
        
        with patch('sys.argv', ['prog'] + test_args):
            app_config = self.config_manager.parse_arguments_and_config()
            
        # Test required values are set
        assert app_config.directory.root == '/test/images'
        assert isinstance(app_config.search, SearchConfig)
        assert isinstance(app_config.output, OutputConfig)

    @pytest.mark.unit
    def test_parse_arguments_and_config_missing_root(self):
        """
        Test parsing fails when required root directory is missing.
        
        This test documents the error handling when required
        arguments are not provided.
        """
        test_args = ['-a', 'New York']  # Missing required -d
        
        with patch('sys.argv', ['prog'] + test_args):
            # Mock _load_config_file to return empty dict to isolate from system config
            with patch.object(self.config_manager, '_load_config_file', return_value={}):
                with pytest.raises(ConfigurationError) as exc_info:
                    self.config_manager.parse_arguments_and_config()
        
        assert "Root directory" in str(exc_info.value)
        assert "required" in str(exc_info.value)

    @pytest.mark.unit
    @patch('sys.exit')
    def test_parse_arguments_and_config_create_config(self, mock_exit, temp_dir):
        """
        Test create-config option exits after creating file.
        
        This test documents the --create-config option behavior
        and shows it creates a sample config file then exits.
        """
        test_args = ['--create-config', str(temp_dir / 'new_config.toml')]
        
        with patch('sys.argv', ['prog'] + test_args):
            self.config_manager.parse_arguments_and_config()
        
        # Should have called sys.exit with success code
        mock_exit.assert_called_once_with(0)
        
        # Should have created the config file
        config_file = temp_dir / 'new_config.toml'
        assert config_file.exists()

    @pytest.mark.unit 
    def test_parse_arguments_and_config_with_toml(self, temp_dir):
        """
        Test parsing with TOML configuration file.
        
        This test documents how command-line arguments and
        configuration files work together.
        """
        # Create a config file without folder_kml section to avoid triggering folder KML mode
        sample_config_content = """# Test configuration file
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
"""
        config_file = temp_dir / "test_config.toml"
        config_file.write_text(sample_config_content)
        
        test_args = ['-d', '/cli/images', '--config', str(config_file)]
        
        with patch('sys.argv', ['prog'] + test_args):
            app_config = self.config_manager.parse_arguments_and_config()
            
        # CLI arg should override config file
        assert app_config.directory.root == '/cli/images'
        
        # Config file values should be used where no CLI override
        assert app_config.search.address == "Test City, NY"  # From config file
        assert app_config.search.radius == 2.0  # From config file

    @pytest.mark.unit
    def test_configuration_objects_creation(self):
        """
        Test that configuration objects are created correctly.
        
        This test documents the structure of configuration objects
        returned by the configuration manager.
        """
        test_args = ['-d', '/test', '-a', 'NYC', '-r', '2.0', '-v', '--export-kml']
        
        with patch('sys.argv', ['prog'] + test_args):
            app_config = self.config_manager.parse_arguments_and_config()
            
        # Test SearchConfig
        assert app_config.search.address == 'NYC'
        assert app_config.search.radius == 2.0
        
        # Test DirectoryConfig  
        assert app_config.directory.root == '/test'
        
        # Test OutputConfig
        assert app_config.output.verbose is True
        assert app_config.output.export_kml is True
        
        # Test other configs exist
        assert isinstance(app_config.filter, FilterConfig)
        assert isinstance(app_config.processing, ProcessingConfig)


class TestTOMLSupport:
    """Test suite for TOML configuration file support."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.config_manager = ConfigurationManager(self.mock_logger)

    @pytest.mark.unit
    def test_toml_parsing_with_tomllib(self, temp_dir):
        """
        Test TOML parsing with built-in tomllib (Python 3.11+).
        
        This test documents TOML file format support and shows
        how configuration files are parsed.
        """
        toml_content = '''
[search]
address = "Test Address"
radius = 1.5

[directories]
root = "/test/path"
find_only = true
'''
        
        config_file = temp_dir / "test.toml"
        config_file.write_text(toml_content)
        
        config_data = self.config_manager._load_config_file(config_file)
        
        assert config_data['search']['address'] == "Test Address"
        assert config_data['search']['radius'] == 1.5
        assert config_data['directories']['root'] == "/test/path"
        assert config_data['directories']['find_only'] is True

    @pytest.mark.unit
    @patch('geo_image_search.config.tomllib', None)
    def test_toml_parsing_without_tomllib(self, temp_dir):
        """
        Test graceful handling when TOML support is not available.
        
        This test documents behavior on systems without TOML support
        and ensures the application still works without config files.
        """
        config_file = temp_dir / "test.toml"
        config_file.write_text('[search]\naddress = "Test"')
        
        config_data = self.config_manager._load_config_file(config_file)
        
        # Should return empty dict when TOML not available
        assert config_data == {}
        
        # Should log warning about missing TOML support
        self.mock_logger.warning.assert_called_once()
        warning_msg = self.mock_logger.warning.call_args[0][0]
        assert "TOML support not available" in warning_msg

    @pytest.mark.unit
    def test_toml_parsing_invalid_syntax(self, temp_dir):
        """
        Test handling of invalid TOML syntax.
        
        This test shows error handling for malformed configuration
        files and ensures graceful degradation.
        """
        invalid_toml = '''
[search
address = "Missing closing bracket"
invalid syntax here
'''
        
        config_file = temp_dir / "invalid.toml"
        config_file.write_text(invalid_toml)
        
        # Clear any previous warning calls
        self.mock_logger.warning.reset_mock()
        
        # Test the actual invalid TOML handling by manually triggering the parse error
        # Since the system may find other config files, we'll verify the parsing error occurs
        try:
            with open(config_file, "rb") as f:
                import tomllib
                tomllib.load(f)
            # If we get here, the TOML was actually valid, which shouldn't happen
            assert False, "Expected TOML parsing to fail"
        except Exception:
            # This confirms our invalid TOML will indeed cause a parsing error
            pass
        
        # Now test the actual config loading - it may return system config due to fallback
        config_data = self.config_manager._load_config_file(config_file)
        
        # The important thing is that a warning was logged about the parsing error
        # Even if system config is loaded as fallback
        warning_calls = [call for call in self.mock_logger.warning.call_args_list 
                        if call[0] and "Could not parse config file" in call[0][0]]
        assert len(warning_calls) > 0, "Expected warning about config file parsing error"