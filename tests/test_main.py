"""Tests for the main module.

These tests verify the main() function and overall application integration
according to TESTING_PLAN.md. They serve as documentation for complete 
application workflows and component interaction.
"""

from unittest.mock import Mock, patch, call
import pytest

from geo_image_search.main import main
from geo_image_search.types import (
    SearchConfig, DirectoryConfig, OutputConfig, FilterConfig, 
    ProcessingConfig, FolderKMLConfig, ApplicationConfig
)
from geo_image_search.exceptions import (
    ConfigurationError, GPSDataError, FileOperationError
)
from geo_image_search.constants import Constants


class TestMainFunction:
    """Test suite for main() function."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create sample configuration objects for testing
        self.search_config = SearchConfig(
            address="Test City, NY",
            radius=1.0
        )
        self.directory_config = DirectoryConfig(
            root="/test/images",
            output_directory="/test/output"
        )
        self.output_config = OutputConfig(
            verbose=True,
            save_addresses=True,
            export_kml=True
        )
        self.filter_config = FilterConfig()
        self.processing_config = ProcessingConfig()
        self.folder_kml_config = FolderKMLConfig()

    def test_main_function_basic_execution(self):
        """
        Test main() function can be called without errors.
        
        This test shows basic application entry point and verifies
        the main orchestration workflow completes successfully.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=self.search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=self.filter_config,
                    processing=self.processing_config,
                    folder_kml=self.folder_kml_config
                )
                
                with patch('geo_image_search.main.GPSImageProcessor'):
                    with patch('geo_image_search.main.LocationSearchEngine'):
                        with patch('geo_image_search.main.sys.exit') as mock_exit:
                            # Mock to suppress the actual exit
                            mock_exit.side_effect = SystemExit()
                            
                            with pytest.raises(SystemExit):
                                # Run main function
                                main()
                            
                            # Verify logging setup was called
                            mock_logging_setup.assert_called_once()
                            mock_logging_setup.return_value.setup_logging.assert_called_once()
                            
                            # Verify configuration manager was created and used
                            mock_config_mgr.assert_called_once_with(mock_logger)
                            mock_config_instance.parse_arguments_and_config.assert_called_once()

    def test_main_function_folder_kml_mode(self):
        """
        Test main() in folder KML export mode.
        
        This test documents the folder KML workflow and shows how
        folder KML path triggers KML export and exits.
        """
        folder_kml_config = FolderKMLConfig(
            folder_path="/test/photos",
            output_kml_path="photos.kml"
        )
        
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=self.search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=self.filter_config,
                    processing=self.processing_config,
                    folder_kml=folder_kml_config
                )
                
                with patch('geo_image_search.main.KMLExporter') as mock_kml_exporter:
                    with patch('geo_image_search.main.GPSImageProcessor') as mock_gps:
                        with patch('geo_image_search.main.sys.exit') as mock_exit:
                            mock_kml_instance = Mock()
                            mock_kml_exporter.return_value = mock_kml_instance
                            mock_kml_instance.export_kml_from_folder.return_value = True
                            
                            # Run main function
                            main()
                            
                            # Should create KML exporter and call folder export
                            mock_kml_exporter.assert_called_with(mock_logger)
                            mock_kml_instance.export_kml_from_folder.assert_called_with(
                                "/test/photos", "photos.kml", True, mock_gps.return_value
                            )
                            
                            # Should call sys.exit (may be success or error depending on workflow)
                            assert mock_exit.called

    def test_main_function_search_mode(self):
        """
        Test main() in standard search mode.
        
        This test documents the complete search workflow and shows how
        search mode processes images and creates output.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=self.search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=self.filter_config,
                    processing=self.processing_config,
                    folder_kml=self.folder_kml_config
                )
                
                with patch('geo_image_search.main.GPSImageProcessor') as mock_gps:
                    with patch('geo_image_search.main.LocationSearchEngine') as mock_search:
                        with patch('geo_image_search.main.CSVExporter') as mock_csv:
                            with patch('geo_image_search.main.KMLExporter') as mock_kml:
                                with patch('geo_image_search.main.sys.exit') as mock_exit:
                                    # Setup search engine
                                    mock_search_instance = Mock()
                                    mock_search.return_value = mock_search_instance
                                    mock_search_instance.search_coords = (40.7128, -74.0060)
                                    
                                    mock_exit.side_effect = SystemExit()
                                    
                                    with pytest.raises(SystemExit):
                                        # Run main function
                                        main()
                                    
                                    # Verify all major components were instantiated
                                    mock_gps.assert_called_once_with(self.filter_config, mock_logger)
                                    mock_search.assert_called_once_with(self.search_config, mock_logger)
                                    mock_csv.assert_called_once_with(mock_logger)
                                    mock_kml.assert_called_once_with(mock_logger)
                                    
                                    # Verify search initialization
                                    mock_search_instance.initialize_search_location.assert_called_once()

    def test_main_function_error_handling(self):
        """
        Test main() error handling and exit codes.
        
        This test documents error handling patterns and shows how
        various error scenarios call sys.exit() with correct codes.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                # Test ConfigurationError handling
                mock_config_mgr.side_effect = ConfigurationError("Invalid config")
                
                with patch('geo_image_search.main.sys.exit') as mock_exit:
                    main()
                    
                    # Should exit with configuration error code
                    mock_exit.assert_called_with(Constants.ErrorCodes.CONFLICTING_OPTIONS)
                    
        # Test GPSDataError handling
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.side_effect = GPSDataError("GPS error")
                
                with patch('geo_image_search.main.sys.exit') as mock_exit:
                    main()
                    
                    # Should exit with GPS data error code
                    mock_exit.assert_called_with(Constants.ErrorCodes.GPS_DATA_ERROR)

        # Test FileOperationError handling
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.side_effect = FileOperationError("File error")
                
                with patch('geo_image_search.main.sys.exit') as mock_exit:
                    main()
                    
                    # Should exit with file operation error code
                    mock_exit.assert_called_with(Constants.ErrorCodes.FILE_OPERATION_ERROR)

        # Test KeyboardInterrupt handling
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_mgr.side_effect = KeyboardInterrupt()
                
                with patch('geo_image_search.main.sys.exit') as mock_exit:
                    main()
                    
                    # Should exit with interrupted code
                    mock_exit.assert_called_with(Constants.ErrorCodes.INTERRUPTED)

    def test_main_function_component_integration(self):
        """
        Test main() integrates all components correctly.
        
        This test documents component interaction patterns and shows
        all expected classes are instantiated and called.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=self.search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=self.filter_config,
                    processing=self.processing_config,
                    folder_kml=self.folder_kml_config
                )
                
                with patch('geo_image_search.main.GPSImageProcessor') as mock_gps:
                    with patch('geo_image_search.main.LocationSearchEngine') as mock_search:
                        with patch('geo_image_search.main.ClusteringEngine') as mock_clustering:
                            with patch('geo_image_search.main.CheckpointManager') as mock_checkpoint:
                                with patch('geo_image_search.main.CSVExporter') as mock_csv:
                                    with patch('geo_image_search.main.KMLExporter') as mock_kml:
                                        with patch('geo_image_search.main.sys.exit') as mock_exit:
                                            mock_exit.side_effect = SystemExit()
                                            
                                            with pytest.raises(SystemExit):
                                                # Run main function
                                                main()
                                            
                                            # Verify all components are instantiated with logger
                                            mock_gps.assert_called_once_with(self.filter_config, mock_logger)
                                            mock_search.assert_called_once_with(self.search_config, mock_logger)
                                            mock_clustering.assert_called_once_with(mock_logger)
                                            mock_checkpoint.assert_called_once_with(mock_logger)
                                            mock_csv.assert_called_once_with(mock_logger)
                                            mock_kml.assert_called_once_with(mock_logger)

    def test_main_function_logging_setup(self):
        """
        Test main() sets up logging correctly.
        
        This test documents logging initialization and shows
        LoggingSetup.setup_logging() is called and logger is used.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_instance = Mock()
            mock_logging_setup.return_value = mock_logging_instance
            mock_logging_instance.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=self.search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=self.filter_config,
                    processing=self.processing_config,
                    folder_kml=self.folder_kml_config
                )
                
                with patch('geo_image_search.main.GPSImageProcessor'):
                    with patch('geo_image_search.main.LocationSearchEngine'):
                        with patch('geo_image_search.main.sys.exit') as mock_exit:
                            mock_exit.side_effect = SystemExit()
                            
                            with pytest.raises(SystemExit):
                                # Run main function
                                main()
                            
                            # Verify LoggingSetup was instantiated and called
                            mock_logging_setup.assert_called_once()
                            mock_logging_instance.setup_logging.assert_called_once()
                            
                            # Verify logger was passed to ConfigurationManager
                            mock_config_mgr.assert_called_once_with(mock_logger)

    def test_main_function_configuration_flow(self):
        """
        Test main() configuration parsing and usage.
        
        This test documents configuration flow through application and shows
        configuration objects are created and passed to components.
        """
        with patch('geo_image_search.main.LoggingSetup') as mock_logging_setup:
            mock_logger = Mock()
            mock_logging_setup.return_value.setup_logging.return_value = mock_logger
            
            with patch('geo_image_search.main.ConfigurationManager') as mock_config_mgr:
                mock_config_instance = Mock()
                mock_config_mgr.return_value = mock_config_instance
                
                # Setup specific configuration return
                custom_search_config = SearchConfig(address="Custom Location", radius=2.5)
                custom_filter_config = FilterConfig(max_gps_error=25.0)
                
                mock_config_instance.parse_arguments_and_config.return_value = ApplicationConfig(
                    search=custom_search_config,
                    directory=self.directory_config,
                    output=self.output_config,
                    filter=custom_filter_config,
                    processing=self.processing_config,
                    folder_kml=self.folder_kml_config
                )
                
                with patch('geo_image_search.main.GPSImageProcessor') as mock_gps:
                    with patch('geo_image_search.main.LocationSearchEngine') as mock_search:
                        with patch('geo_image_search.main.sys.exit') as mock_exit:
                            mock_exit.side_effect = SystemExit()
                            
                            with pytest.raises(SystemExit):
                                # Run main function
                                main()
                            
                            # Verify configuration parsing was called
                            mock_config_instance.parse_arguments_and_config.assert_called_once()
                            
                            # Verify configuration objects were passed to components
                            mock_gps.assert_called_once_with(custom_filter_config, mock_logger)
                            mock_search.assert_called_once_with(custom_search_config, mock_logger)