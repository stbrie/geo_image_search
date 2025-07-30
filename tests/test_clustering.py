"""Tests for the clustering module.

These tests verify the ClusteringEngine and CheckpointManager classes according to
the actual API implementation documented in TESTING_PLAN.md. They serve as 
documentation for geographic clustering and checkpoint functionality.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import pytest

from geo_image_search.clustering import ClusteringEngine, CheckpointManager
from geo_image_search.types import GeocodingConfig


class TestClusteringEngine:
    """Test suite for ClusteringEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        
        # Sample image data for testing
        self.sample_images = [
            {
                "filename": "photo1.jpg",
                "path": "/photos/photo1.jpg", 
                "latitude": 40.7128,   # NYC
                "longitude": -74.0060,
                "date_taken": "2024:01:15 10:30:00"
            },
            {
                "filename": "photo2.jpg", 
                "path": "/photos/photo2.jpg",
                "latitude": 40.7140,  # Very close to photo1 (within 0.1 miles)
                "longitude": -74.0070,
                "date_taken": "2024:01:15 11:00:00"
            },
            {
                "filename": "photo3.jpg",
                "path": "/photos/photo3.jpg", 
                "latitude": 37.7749,  # San Francisco (far away)
                "longitude": -122.4194,
                "date_taken": "2024:01:16 14:20:00"
            }
        ]

    def test_clustering_engine_initialization(self):
        """
        Test ClusteringEngine constructor.
        
        This test shows how to create a clustering engine and verifies
        the geopy dependency requirement.
        """
        # Test successful initialization
        clustering_engine = ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
        
        assert clustering_engine.logger == self.mock_logger
        
        # Test that geopy requirement is checked
        with patch('geo_image_search.clustering.distance', None):
            with pytest.raises(ImportError) as exc_info:
                ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
            
            assert "geopy library is required" in str(exc_info.value)
            assert "pip install geopy" in str(exc_info.value)

    def test_cluster_images_by_location_basic(self):
        """
        Test cluster_images_by_location() method with default radius.
        
        This test documents the clustering behavior with the default 0.1 mile 
        radius and shows how images are grouped by proximity.
        """
        clustering_engine = ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
        
        # Mock geocoding to avoid network calls and ensure predictable names
        with patch('geo_image_search.clustering.Nominatim') as mock_nominatim:
            mock_geolocator = Mock()
            mock_nominatim.return_value = mock_geolocator
            
            # Mock different responses for NYC and SF
            def mock_reverse(location, timeout=None):
                lat, lon = location
                if abs(lat - 40.7128) < 1:  # NYC area
                    mock_result = Mock()
                    mock_result.raw = {'address': {'city': 'New York'}}
                    return mock_result
                else:  # SF area
                    mock_result = Mock()
                    mock_result.raw = {'address': {'city': 'San Francisco'}}
                    return mock_result
            
            mock_geolocator.reverse.side_effect = mock_reverse
            
            # Test clustering with default radius (0.1 miles)
            clusters = clustering_engine.cluster_images_by_location(
                self.sample_images
            )
        
            # Should return a dictionary of cluster_name -> list of images
            assert isinstance(clusters, dict)
            
            # Should have at least 1 cluster, possibly 2 (NYC and SF are far)
            assert len(clusters) >= 1
            
            # Total images should be preserved
            total_images = sum(len(images) for images in clusters.values())
            assert total_images == 3
            
            # Each cluster should have at least one image
            for cluster_name, images in clusters.items():
                assert len(images) >= 1
                assert isinstance(cluster_name, str)
                assert len(cluster_name) > 0

    def test_cluster_images_by_location_custom_radius(self):
        """
        Test clustering with custom radius values.
        
        This test shows how the cluster_radius parameter affects clustering
        and documents the radius effect on grouping behavior.
        """
        clustering_engine = ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
        
        # Test with very small radius - should create more clusters
        small_radius_clusters = clustering_engine.cluster_images_by_location(
            self.sample_images, cluster_radius=0.01
        )
        
        # Test with very large radius - should create fewer clusters 
        large_radius_clusters = clustering_engine.cluster_images_by_location(
            self.sample_images, cluster_radius=10.0
        )
        
        # Small radius should create more or equal clusters than large radius
        assert len(small_radius_clusters) >= len(large_radius_clusters)
        
        # With large radius, might get just 1 cluster containing all images
        if len(large_radius_clusters) == 1:
            cluster_name = list(large_radius_clusters.keys())[0]
            assert len(large_radius_clusters[cluster_name]) == 3

    def test_cluster_images_by_location_empty_data(self):
        """
        Test clustering with empty image list.
        
        This test documents how the clustering engine handles empty datasets
        and shows the expected return value.
        """
        clustering_engine = ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
        
        # Test with empty list
        empty_clusters = clustering_engine.cluster_images_by_location([])
        
        # Should return empty dictionary
        assert not empty_clusters
        assert isinstance(empty_clusters, dict)

    def test_generate_cluster_name(self):
        """
        Test _generate_cluster_name() method.
        
        This test documents the cluster naming strategy and shows how
        cluster names are generated from coordinates and index.
        """
        clustering_engine = ClusteringEngine(GeocodingConfig(user_agent="test_agent/1.0"), self.mock_logger)
        
        # Test cluster name generation
        location = (40.7128, -74.0060)
        cluster_index = 1
        
        with patch.object(
            clustering_engine, 
            '_generate_cluster_name', 
            wraps=clustering_engine._generate_cluster_name
        ) as mock_generate:
            # Call the method
            cluster_name = clustering_engine._generate_cluster_name(
                location, cluster_index
            )
            
            # Should be called with the provided parameters
            mock_generate.assert_called_once_with(location, cluster_index)
            
            # Should return a string
            assert isinstance(cluster_name, str)
            assert len(cluster_name) > 0


class TestCheckpointManager:
    """Test suite for CheckpointManager class."""

    def setup_method(self):
        """Set up test fixtures.""" 
        self.mock_logger = Mock()

    def test_checkpoint_manager_initialization(self):
        """
        Test CheckpointManager constructor.
        
        This test shows how to create a checkpoint manager and verifies
        the initialization with logger parameter.
        """
        checkpoint_manager = CheckpointManager(self.mock_logger)
        
        assert checkpoint_manager.logger == self.mock_logger
        assert hasattr(checkpoint_manager, 'checkpoint_file')
        assert checkpoint_manager.checkpoint_file == "geo_search_checkpoint.json"

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.dump')
    @patch('geo_image_search.clustering.datetime')
    def test_save_checkpoint(self, mock_datetime, mock_json_dump, mock_file_open):
        """
        Test save_checkpoint() method.
        
        This test documents checkpoint data persistence and shows
        how checkpoint files are created with processed files, total count,
        and timestamp.
        """
        checkpoint_manager = CheckpointManager(self.mock_logger)
        
        # Mock datetime.now().isoformat() to return predictable timestamp
        mock_datetime.now.return_value.isoformat.return_value = (
            "2024-01-15T10:30:00"
        )
        
        processed_files = ["/path/image1.jpg", "/path/image2.jpg"] 
        total_files = 10
        
        # Call save_checkpoint
        checkpoint_manager.save_checkpoint(processed_files, total_files)
        
        # Should open checkpoint file for writing
        mock_file_open.assert_called_once_with(
            "geo_search_checkpoint.json", 'w', encoding='utf-8'
        )
        
        # Should write JSON data with processed files, total, and timestamp
        expected_data = {
            'processed_files': processed_files,
            'total_files': total_files,
            'timestamp': '2024-01-15T10:30:00'
        }
        mock_json_dump.assert_called_once_with(
            expected_data, mock_file_open().__enter__(), indent=2
        )

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    @patch('pathlib.Path.exists')
    def test_load_checkpoint(self, mock_path_exists, mock_json_load, 
                           mock_file_open):
        """
        Test load_checkpoint() method.
        
        This test documents checkpoint data loading and shows how the method
        returns a tuple of processed files and total count, handling timestamps.
        """
        checkpoint_manager = CheckpointManager(self.mock_logger)
        
        # Mock the JSON data that would be loaded (with timestamp)
        expected_data = {
            'processed_files': ["/path/image1.jpg"],
            'total_files': 5,
            'timestamp': '2024-01-15T10:30:00'
        }
        mock_json_load.return_value = expected_data
        
        # Mock file exists
        mock_path_exists.return_value = True
        
        result = checkpoint_manager.load_checkpoint()
        
        # Should return tuple of (processed_files, total_files)
        assert result == (["/path/image1.jpg"], 5)
        
        # Should check if checkpoint file exists
        mock_path_exists.assert_called_once()
        
        # Should open and load from checkpoint file
        # The actual implementation uses Path(checkpoint_file) so it's a Path object
        from pathlib import Path
        expected_path = Path(checkpoint_manager.checkpoint_file)
        mock_file_open.assert_called_once_with(expected_path, 'r', encoding='utf-8')
        mock_json_load.assert_called_once()
        
        # Should log info about loaded checkpoint with timestamp
        expected_log = "Found checkpoint from 2024-01-15T10:30:00: 1/5 files processed"
        self.mock_logger.info.assert_called_with(expected_log)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.unlink')
    def test_clear_checkpoint(self, mock_unlink, mock_exists):
        """
        Test clear_checkpoint() method.
        
        This test documents checkpoint cleanup and shows how
        checkpoint files are removed from the filesystem.
        """
        checkpoint_manager = CheckpointManager(self.mock_logger)
        
        # Mock file exists
        mock_exists.return_value = True
        
        checkpoint_manager.clear_checkpoint()
        
        # Should check if file exists and remove it
        mock_exists.assert_called_once()
        mock_unlink.assert_called_once()
        
        # Should log debug message
        self.mock_logger.debug.assert_called_with("Checkpoint file cleared")