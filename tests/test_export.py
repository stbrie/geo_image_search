"""
Tests for the export module.

These tests verify CSV and KML export functionality and serve as documentation
for export formats and cross-platform path handling.
"""

import tempfile
import csv
from pathlib import Path
from unittest.mock import Mock, mock_open
import pytest

from geo_image_search.export import CSVExporter, KMLExporter
from geo_image_search.types import ImageData
from geo_image_search.exceptions import FileOperationError


class TestCSVExport:
    """Test suite for CSV export functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.csv_exporter = CSVExporter(self.mock_logger)
        
        # Sample image data for testing
        self.sample_images = [
            {
                "filename": "photo1.jpg",
                "path": "/photos/photo1.jpg", 
                "latitude": 40.7128,
                "longitude": -74.0060,
                "date_taken": "2024:01:15 10:30:00"
            },
            {
                "filename": "photo2.jpg",
                "path": "/photos/photo2.jpg",
                "latitude": 40.7589,
                "longitude": -73.9851,
                "date_taken": "2024:01:16 14:20:00"
            }
        ]

    @pytest.mark.unit
    def test_csv_export_basic(self):
        """
        Test basic CSV export functionality.
        
        This test documents the CSV export format and shows
        how image data is exported to CSV files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test CSV export
            result = self.csv_exporter.export_image_addresses(
                self.sample_images, temp_dir
            )
            
            # Should succeed
            assert result is True
            
            # Check that CSV file was created
            csv_file = Path(temp_dir) / "image_addresses.csv"
            assert csv_file.exists()
            
            # Verify CSV content
            with open(csv_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
            # Should have 2 rows
            assert len(rows) == 2
            
            # Check first row content
            assert rows[0]['filename'] == 'photo1.jpg'
            assert float(rows[0]['latitude']) == 40.7128
            assert float(rows[0]['longitude']) == -74.0060

    @pytest.mark.unit
    def test_csv_export_empty_data(self):
        """
        Test CSV export with no data.
        
        This test shows how the exporter handles empty datasets
        and provides appropriate feedback.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test with empty list
            result = self.csv_exporter.export_image_addresses([], temp_dir)
            
            # Should return False for empty data
            assert result is False
            
            # Should log appropriate message
            self.mock_logger.info.assert_called_with(
                "No GPS data found in images for CSV export."
            )

    @pytest.mark.unit
    def test_csv_export_error_handling(self):
        """
        Test CSV export error scenarios.
        
        This test documents how file operation errors are handled
        during CSV export operations.
        """
        # Test with invalid output directory
        result = self.csv_exporter.export_image_addresses(
            self.sample_images, "Do Not Save"
        )
        
        # Should return False and log warning
        assert result is False
        self.mock_logger.warning.assert_called_with(
            "Cannot export CSV in find-only mode."
        )


class TestKMLExport:
    """Test suite for KML export functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.kml_exporter = KMLExporter(self.mock_logger)
        
        # Sample image data
        self.sample_images = [
            {
                "filename": "vacation1.jpg",
                "path": "/photos/vacation1.jpg",
                "latitude": 40.7128,
                "longitude": -74.0060,
                "date_taken": "2024:06:15 10:30:00"
            },
            {
                "filename": "vacation2.jpg", 
                "path": "/photos/vacation2.jpg",
                "latitude": 40.7589,
                "longitude": -73.9851,
                "date_taken": "2024:06:16 14:20:00"
            }
        ]

    @pytest.mark.unit
    def test_kml_generation_basic(self):
        """
        Test basic KML file generation.
        
        This test documents the KML export format and shows
        how image locations are converted to KML placemarks.
        """
        # Test KML generation with search center
        search_center = (40.7128, -74.0060)
        kml_content = self.kml_exporter.build_kml_from_image_data(
            self.sample_images, search_center
        )
        
        # Should generate valid KML content
        assert kml_content is not None
        assert isinstance(kml_content, str)
        
        # Should contain KML structure
        assert '<kml xmlns="http://www.opengis.net/kml/2.2">' in kml_content
        assert '<Document id="geo_image_search_results">' in kml_content
        assert '</Document>' in kml_content
        assert '</kml>' in kml_content
        
        # Should contain placemarks for each image 
        assert 'vacation1.jpg' in kml_content
        assert 'vacation2.jpg' in kml_content

    @pytest.mark.unit
    def test_kml_placemark_creation(self):
        """
        Test individual placemark creation in KML.
        
        This test shows how individual images are converted
        to KML placemarks with proper coordinates and metadata.
        """
        single_image = [self.sample_images[0]]
        
        kml_content = self.kml_exporter.build_kml_from_image_data(
            single_image, None
        )
        
        # Should contain placemark for the image
        assert '<Placemark>' in kml_content
        assert '</Placemark>' in kml_content
        
        # Should contain coordinates (longitude,latitude format in KML)
        assert '-74.006,40.7128' in kml_content
        
        # Should contain image name
        assert 'vacation1.jpg' in kml_content

    @pytest.mark.unit
    def test_kml_center_point_handling(self):
        """
        Test search center point in KML.
        
        This test shows how search center points are visualized
        in KML files to show the search location.
        """
        search_center = (40.7500, -74.0000)
        
        # Test with center point
        kml_with_center = self.kml_exporter.build_kml_from_image_data(
            self.sample_images, search_center
        )
        
        # Should contain center point placemark
        assert 'Center Point' in kml_with_center
        assert '-74.0,40.75' in kml_with_center
        
        # Test without center point
        kml_without_center = self.kml_exporter.build_kml_from_image_data(
            self.sample_images, None
        )
        
        # Should not contain center point
        assert 'Center Point' not in kml_without_center

    @pytest.mark.unit
    def test_kml_folder_export(self):
        """
        Test folder-based KML export.
        
        This test documents the folder scanning and export process
        for generating KML from existing image directories.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock image files
            image_dir = Path(temp_dir) / "photos"
            image_dir.mkdir()
            
            (image_dir / "test1.jpg").write_text("mock image 1")
            (image_dir / "test2.jpg").write_text("mock image 2")
            
            # Create mock GPS processor
            mock_gps_processor = Mock()
            mock_gps_processor.is_jpeg_file.return_value = True
            mock_gps_processor.extract_image_gps_data.side_effect = [
                self.sample_images[0],
                self.sample_images[1]
            ]
            
            # Test folder export
            result = self.kml_exporter.export_kml_from_folder(
                str(image_dir), None, True, mock_gps_processor
            )
            
            # Should return success
            assert result is True


    @pytest.mark.unit  
    def test_path_normalization_in_export(self):
        """
        Test path handling in export files.
        
        This test documents cross-platform path handling
        and ensures paths are properly formatted for export.
        """
        # Test with Windows-style paths
        windows_image = {
            "filename": "windows.jpg",
            "path": "C:\\Photos\\windows.jpg",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "date_taken": "2024:01:15 10:30:00"
        }
        
        kml_content = self.kml_exporter.build_kml_from_image_data(
            [windows_image], None
        )
        
        # Paths in KML should use forward slashes
        assert 'C:/Photos/windows.jpg' in kml_content or 'file://' in kml_content
        assert '\\' not in kml_content  # No backslashes in final KML


class TestExportIntegration:
    """Integration tests for export functionality."""

    @pytest.mark.integration
    def test_real_file_export(self):
        """
        Test export with actual file operations.
        
        This test validates that exports work with real filesystem
        operations and produce valid output files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = Mock()
            csv_exporter = CSVExporter(logger)
            kml_exporter = KMLExporter(logger)
            
            sample_data = [
                {
                    "filename": "real_test.jpg",
                    "path": str(Path(temp_dir) / "real_test.jpg"),
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                    "date_taken": "2024:07:04 12:00:00"
                }
            ]
            
            # Test CSV export
            csv_result = csv_exporter.export_image_addresses(sample_data, temp_dir)
            assert csv_result is True
            
            csv_file = Path(temp_dir) / "image_addresses.csv"
            assert csv_file.exists()
            assert csv_file.stat().st_size > 0
            
            # Test KML export
            kml_content = kml_exporter.build_kml_from_image_data(
                sample_data, (37.7749, -122.4194)
            )
            
            kml_file = Path(temp_dir) / "export_test.kml"
            kml_file.write_text(kml_content, encoding='utf-8')
            
            assert kml_file.exists()
            assert kml_file.stat().st_size > 0
            
            # Verify KML is well-formed XML
            content = kml_file.read_text(encoding='utf-8').strip()
            assert content.startswith('<kml')
            assert content.endswith('</kml>')