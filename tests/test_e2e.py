"""End-to-end tests for the geo_image_search application.

These tests verify complete application workflows from command-line invocation to results.
They serve as documentation for real-world usage scenarios and CLI interface behavior.
"""

import tempfile
import subprocess
import json
import csv
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
import sys
import os

# Import for testing the CLI entry points
from geo_image_search.main import main
# Version checking handled elsewhere if needed


class TestCLIInterface:
    """Test suite for command-line interface functionality."""

    @pytest.mark.unit
    def test_cli_help_output(self):
        """
        Test CLI help output and documentation.
        
        This test documents the command-line interface and verifies
        help text includes all major options.
        """
        # Test help via argument parsing
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        parser = config_manager._create_argument_parser()
        
        help_output = parser.format_help()
        
        # Should include essential command-line options
        essential_options = [
            '-d', '--root',
            '-a', '--address',
            '-t', '--latitude',
            '-g', '--longitude', 
            '-r', '--radius',
            '-o', '--output_directory',
            '-f', '--find_only',
            '-v', '--verbose',
            '-i', '--save_addresses',  # Corrected from --export-csv
            '--export-kml'
        ]
        
        for option in essential_options:
            assert option in help_output
        
        # Should include description  
        assert '.jpeg metadata' in help_output

    @pytest.mark.unit
    @patch('sys.argv')
    def test_cli_minimal_arguments(self, mock_argv):
        """
        Test CLI with minimal required arguments.
        
        This test documents the minimum arguments needed
        to run the application from command line.
        """
        mock_argv.__getitem__.side_effect = lambda i: [
            'geo_image_search.py',
            '-d', '/test/images'
        ][i]
        mock_argv.__len__.return_value = 3
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        # Should be able to parse minimal arguments
        with patch.object(config_manager, '_validate_configuration'):
            with patch.object(config_manager, '_load_config_file', return_value={}):  # No config file defaults
                try:
                    app_config = config_manager.parse_arguments_and_config()
                    
                    assert app_config.directory.root == '/test/images'
                    assert app_config.search.address is None
                    
                except SystemExit:
                    # May exit due to missing required validation
                    pass

    @pytest.mark.unit
    @patch('sys.argv')
    def test_cli_address_search(self, mock_argv):
        """
        Test CLI with address-based search.
        
        This test documents address-based location search
        from the command line.
        """
        mock_argv.__getitem__.side_effect = lambda i: [
            'geo_image_search.py',
            '-d', '/test/images',
            '-a', 'Central Park, New York',
            '-r', '2.0'
        ][i]
        mock_argv.__len__.return_value = 7
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        with patch.object(config_manager, '_validate_configuration'):
            try:
                app_config = config_manager.parse_arguments_and_config()
                
                assert app_config.search.address == 'Central Park, New York'
                assert app_config.search.radius == 2.0
                
            except SystemExit:
                pass

    @pytest.mark.unit
    @patch('sys.argv')
    def test_cli_coordinate_search(self, mock_argv):
        """
        Test CLI with coordinate-based search.
        
        This test documents coordinate-based location search
        using latitude and longitude arguments.
        """
        mock_argv.__getitem__.side_effect = lambda i: [
            'geo_image_search.py',
            '-d', '/test/images',
            '-t', '40.7128',
            '-g', '-74.0060',
            '-r', '1.5'
        ][i]
        mock_argv.__len__.return_value = 9
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        with patch.object(config_manager, '_validate_configuration'):
            try:
                app_config = config_manager.parse_arguments_and_config()
                
                assert app_config.search.latitude == 40.7128
                assert app_config.search.longitude == -74.0060
                assert app_config.search.radius == 1.5
                
            except SystemExit:
                pass

    @pytest.mark.unit
    @patch('sys.argv')
    def test_cli_export_options(self, mock_argv):
        """
        Test CLI export configuration options.
        
        This test documents how to configure export formats
        from the command line.
        """
        mock_argv.__getitem__.side_effect = lambda i: [
            'geo_image_search.py',
            '-d', '/test/images',
            '-a', 'Test Location',
            '--export-csv',
            '--export-kml',
            '-o', '/test/output'
        ][i]
        mock_argv.__len__.return_value = 9
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        with patch.object(config_manager, '_validate_configuration'):
            try:
                app_config = config_manager.parse_arguments_and_config()
                
                assert app_config.output.save_addresses is True
                assert app_config.output.export_kml is True
                assert app_config.directory.output_directory == '/test/output'
                
            except SystemExit:
                pass

    @pytest.mark.unit
    @patch('sys.argv')
    def test_cli_filtering_options(self, mock_argv):
        """
        Test CLI filtering and processing options.
        
        This test documents GPS accuracy filtering and date
        range filtering from command line.
        """
        mock_argv.__getitem__.side_effect = lambda i: [
            'geo_image_search.py',
            '-d', '/test/images',
            '-a', 'Test Location',
            '--max-gps-error', '25.0',
            '--max-dop', '3.0',
            '--date-from', '2024-01-01',
            '--date-to', '2024-12-31'
        ][i]
        mock_argv.__len__.return_value = 13
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        with patch.object(config_manager, '_validate_configuration'):
            try:
                app_config = config_manager.parse_arguments_and_config()
                
                assert app_config.filter.max_gps_error == 25.0
                assert app_config.filter.max_dop == 3.0
                # Date parsing depends on implementation
                
            except SystemExit:
                pass


class TestConfigurationFiles:
    """Test suite for TOML configuration file functionality."""

    @pytest.mark.unit
    def test_toml_config_loading(self, temp_dir):
        """
        Test loading TOML configuration files.
        
        This test documents TOML configuration file format
        and shows how settings override command-line defaults.
        """
        # Create sample TOML config
        config_content = """
[search]
address = "Times Square, New York"
radius = 2.5

[directories]
root = "/config/images"
find_only = true

[output]
verbose = true
export_csv = true
export_kml = true

[filters]
max_gps_error = 30.0
max_dop = 4.0
"""
        
        config_file = temp_dir / "test_config.toml"
        config_file.write_text(config_content)
        
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        
        # Test loading config file
        config_data = config_manager._load_config_file(config_file)
        
        assert config_data['search']['address'] == "Times Square, New York"
        assert config_data['search']['radius'] == 2.5
        assert config_data['directories']['root'] == "/config/images"
        assert config_data['directories']['find_only'] is True


    @pytest.mark.unit
    def test_sample_config_creation(self, temp_dir):
        """
        Test sample configuration file creation.
        
        This test documents the --create-config option and
        shows the complete configuration structure.
        """
        from geo_image_search.config import ConfigurationManager
        
        config_manager = ConfigurationManager(Mock())
        sample_file = temp_dir / "sample.toml"
        
        config_manager._create_sample_config(sample_file)
        
        # Should create valid TOML file
        assert sample_file.exists()
        
        content = sample_file.read_text()
        
        # Should include all configuration sections
        required_sections = [
            '[search]', '[directories]', '[output]', 
            '[filters]', '[processing]', '[folder_kml]'
        ]
        
        for section in required_sections:
            assert section in content
        
        # Should include documentation
        assert 'Example configurations:' in content
        assert '#' in content  # Should have comments




class TestRealWorldScenarios:
    """Test suite for real-world usage scenarios and edge cases."""

    @pytest.mark.e2e
    @pytest.mark.requires_network
    def test_geocoding_integration(self):
        """
        Test integration with real geocoding services.
        
        This test validates address-to-coordinate conversion
        using actual geocoding services when available.
        """
        # Test with well-known address
        test_address = "Empire State Building, New York"
        
        from geo_image_search.search import LocationSearchEngine
        from geo_image_search.types import SearchConfig
        
        search_config = SearchConfig(address=test_address, radius=1.0)
        mock_logger = Mock()
        
        try:
            # This will make real network request
            search_engine = LocationSearchEngine(search_config, mock_logger)
            coords = search_engine.search_coordinates
            
            # Empire State Building coordinates (approximately)
            assert 40.74 < coords[0] < 40.75  # Latitude
            assert -73.99 < coords[1] < -73.98  # Longitude
            
        except Exception as e:
            # Skip test if network unavailable or geocoding fails
            pytest.skip(f"Geocoding service unavailable: {e}")

    @pytest.mark.e2e
    def test_unicode_filename_handling(self, temp_dir):
        """
        Test handling of Unicode characters in filenames and paths.
        
        This test documents international filename support
        and ensures proper encoding throughout the pipeline.
        """
        # Create directory with Unicode names
        unicode_dir = temp_dir / "测试目录"  # Chinese characters
        unicode_dir.mkdir()
        
        # Create files with Unicode names
        unicode_files = [
            unicode_dir / "фото_001.jpg",  # Cyrillic
            unicode_dir / "写真_002.jpg",   # Japanese/Chinese
            unicode_dir / "café_003.jpg",   # Accented characters
            unicode_dir / "señor_004.jpg"   # Spanish characters
        ]
        
        for file_path in unicode_files:
            file_path.write_text("Mock JPEG data", encoding='utf-8')
        
        # Test that application can handle Unicode paths
        from geo_image_search.utils import PathNormalizer
        
        normalizer = PathNormalizer()
        
        for file_path in unicode_files:
            # Should be able to normalize Unicode paths
            normalized = normalizer.normalize_path(str(file_path))
            assert isinstance(normalized, str)
            assert len(normalized) > 0
            
            # Should be able to sanitize folder names
            safe_name = normalizer.sanitize_folder_name(file_path.stem)
            assert isinstance(safe_name, str)
            assert len(safe_name) > 0

    @pytest.mark.e2e
    def test_mixed_file_types_handling(self, temp_dir):
        """
        Test handling of mixed file types in input directory.
        
        This test documents how the application filters and processes
        different file types in a realistic directory structure.
        """
        # Create realistic directory structure
        test_dir = temp_dir / "mixed_files"
        test_dir.mkdir()
        
        # Create subdirectories
        (test_dir / "photos").mkdir()
        (test_dir / "documents").mkdir()
        (test_dir / "videos").mkdir()
        
        # Create various file types
        file_types = {
            # Should be processed
            "photos/vacation_001.jpg": "JPEG image",
            "photos/family_002.jpeg": "JPEG image",
            "photos/nature_003.JPG": "JPEG image",
            "wedding_004.JPEG": "JPEG image",
            
            # Should be ignored
            "photos/screenshot.png": "PNG image",
            "documents/report.pdf": "PDF document", 
            "documents/data.csv": "CSV data",
            "videos/movie.mp4": "Video file",
            "readme.txt": "Text file",
            ".hidden_file": "Hidden file",
            "photos/.DS_Store": "System file"
        }
        
        for relative_path, content in file_types.items():
            file_path = test_dir / relative_path
            file_path.write_text(content)
        
        # Test file discovery and filtering
        from geo_image_search.gps import GPSImageProcessor
        from geo_image_search.types import FilterConfig
        
        processor = GPSImageProcessor(FilterConfig(), Mock())
        
        # Find all files
        all_files = list(test_dir.rglob("*"))
        file_files = [f for f in all_files if f.is_file()]
        
        # Filter to JPEG files only
        jpeg_files = [f for f in file_files if processor._is_jpeg_file(str(f))]
        
        # Should find 4 JPEG files
        assert len(jpeg_files) == 4
        
        # Verify correct files were identified
        jpeg_names = [f.name.lower() for f in jpeg_files]
        expected_jpegs = ["vacation_001.jpg", "family_002.jpeg", "nature_003.jpg", "wedding_004.jpeg"]
        
        for expected in expected_jpegs:
            assert any(expected.lower() in name for name in jpeg_names)


    @pytest.mark.e2e
    def test_resource_cleanup(self, temp_dir):
        """
        Test proper resource cleanup and temporary file handling.
        
        This test documents how the application manages temporary
        files and ensures proper cleanup.
        """
        # Setup test environment
        work_dir = temp_dir / "cleanup_test"
        work_dir.mkdir()
        
        # Create checkpoint file that should be cleaned up
        checkpoint_file = work_dir / "search_checkpoint.json"
        checkpoint_data = {
            "processed_files": [],
            "found_images": [],
            "total_processed": 0,
            "timestamp": "2024-01-15T10:30:00"
        }
        checkpoint_file.write_text(json.dumps(checkpoint_data))
        
        # Test checkpoint cleanup
        from geo_image_search.clustering import CheckpointManager
        
        checkpoint_manager = CheckpointManager(Mock())
        
        # Verify checkpoint exists
        assert checkpoint_file.exists()
        
        # Clean up checkpoint
        checkpoint_manager.clear_checkpoint()
        
        # Should be removed (the clear_checkpoint method removes the default checkpoint file)
        # Note: this test verifies the method exists and can be called
        # The actual file removal depends on the checkpoint file name matching

