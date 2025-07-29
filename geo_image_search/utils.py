"""Utility classes for the geo image search application."""

import logging
import os
import re
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict
from .constants import Constants
from .exceptions import ConfigurationError, GPSDataError, FileOperationError
from .types import FilterConfig, ImageData


class LoggingSetup:
    """Handles logging configuration."""
    
    @staticmethod
    def setup_logging(level: int = logging.INFO) -> logging.Logger:
        """Set up logging configuration."""
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        return logging.getLogger(__name__)


class PathNormalizer:
    """Handles path normalization across different platforms."""
    
    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalize a file path for the current platform."""
        if not path:
            return path
            
        # Convert to Path object for normalization
        normalized_path = Path(path).resolve()
        return str(normalized_path)
    
    @staticmethod
    def get_kml_image_path(image_path: str) -> str:
        """Get the proper image path format for KML files."""
        # KML expects forward slashes and file:// URLs
        # First convert any backslashes to forward slashes
        normalized = image_path.replace('\\', '/')
        # Ensure it starts with forward slash
        if not normalized.startswith('/'):
            normalized = '/' + normalized
        return f"file://{normalized}"
    
    @staticmethod
    def sanitize_folder_name(folder_name: str) -> str:
        """Sanitize a folder name for use in file names."""
        # Remove or replace invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', folder_name)
        sanitized = sanitized.strip('. ')
        return sanitized if sanitized else 'images'


class DateParser:
    """Handles date parsing and validation."""
    
    @staticmethod
    def parse_date(date_str: str, field_name: str) -> date:
        """Parse a date string in YYYY-MM-DD format."""
        if not date_str:
            raise ConfigurationError(f"Empty date string for {field_name}")
            
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as e:
            raise ConfigurationError(f"Invalid date format for {field_name}: {date_str}. Use YYYY-MM-DD") from e
    
    @staticmethod
    def is_date_in_range(image_date: str | None, date_from: date | None, date_to: date | None) -> bool:
        """Check if an image date falls within the specified range."""
        if not image_date or (not date_from and not date_to):
            return True
            
        try:
            # Parse image date (EXIF format: "YYYY:MM:DD HH:MM:SS")
            if ':' in image_date:
                img_date = datetime.strptime(image_date[:10], "%Y:%m:%d").date()
            else:
                img_date = datetime.strptime(image_date[:10], "%Y-%m-%d").date()
            
            if date_from and img_date < date_from:
                return False
            if date_to and img_date > date_to:
                return False
                
            return True
            
        except (ValueError, TypeError):
            # If we can't parse the date, include the image
            return True
    
    @staticmethod
    def extract_image_date(image) -> str | None:
        """
        Extract date taken from EXIF data.
        
        This method consolidates duplicate date extraction logic that was
        previously scattered across GPSImageProcessor and GPSFilter classes.
        Now uses ImageMetadata wrapper for consistent encapsulation.
        
        Args:
            image: An image object with EXIF metadata
            
        Returns:
            Date string in EXIF format or None if no date found
        """
        # Use ImageMetadata wrapper for consistent encapsulation
        metadata = ImageMetadata(image)
        return metadata.extract_date_taken()


class ImageMetadata:
    """
    Wrapper class that encapsulates image attribute access.
    
    This class provides a clean interface for accessing EXIF metadata,
    eliminating the need for direct hasattr/getattr calls and improving
    testability by providing a consistent API.
    """
    
    def __init__(self, image):
        self._image = image
    
    def get_gps_horizontal_error(self) -> float | None:
        """Get GPS horizontal error in meters, if available."""
        try:
            if hasattr(self._image, 'gps_horizontal_error'):
                return float(self._image.gps_horizontal_error)
        except (AttributeError, ValueError, TypeError):
            pass
        return None
    
    def get_gps_dop(self) -> float | None:
        """Get GPS Dilution of Precision value, if available."""
        try:
            if hasattr(self._image, 'gps_dop'):
                return float(self._image.gps_dop)
        except (AttributeError, ValueError, TypeError):
            pass
        return None
    
    def extract_date_taken(self) -> str | None:
        """Extract date taken from EXIF data with priority order."""
        date_fields = ["datetime_original", "datetime", "datetime_digitized"]
        for field in date_fields:
            try:
                if hasattr(self._image, field):
                    date_str = getattr(self._image, field)
                    if date_str:
                        return date_str
            except AttributeError:
                continue
        return None
    
    def get_gps_latitude(self) -> list | None:
        """Get GPS latitude coordinates in DMS format."""
        try:
            if hasattr(self._image, 'gps_latitude'):
                return self._image.gps_latitude
        except AttributeError:
            pass
        return None
    
    def get_gps_latitude_ref(self) -> str:
        """Get GPS latitude reference (N/S), defaulting to 'N'."""
        try:
            if hasattr(self._image, 'gps_latitude_ref'):
                return self._image.gps_latitude_ref
        except AttributeError:
            pass
        return "N"
    
    def get_gps_longitude(self) -> list | None:
        """Get GPS longitude coordinates in DMS format."""
        try:
            if hasattr(self._image, 'gps_longitude'):
                return self._image.gps_longitude
        except AttributeError:
            pass
        return None
    
    def get_gps_longitude_ref(self) -> str:
        """Get GPS longitude reference (E/W), defaulting to 'W'."""
        try:
            if hasattr(self._image, 'gps_longitude_ref'):
                return self._image.gps_longitude_ref
        except AttributeError:
            pass
        return "W"


class GPSFilter:
    """Handles GPS data filtering and validation."""
    
    def __init__(self, filter_config: FilterConfig, logger: logging.Logger):
        self.filter_config = filter_config
        self.logger = logger
        self.date_parser = DateParser()
    
    def apply_gps_accuracy_filters(self, image, filename: str) -> bool:
        """Apply GPS accuracy filters to an image."""
        metadata = ImageMetadata(image)
        
        # Check GPS horizontal error
        if self.filter_config.max_gps_error is not None:
            gps_error = metadata.get_gps_horizontal_error()
            if gps_error is not None and gps_error > self.filter_config.max_gps_error:
                self.logger.debug(f"Filtered {filename}: GPS error {gps_error}m > {self.filter_config.max_gps_error}m")
                return False
        
        # Check Dilution of Precision (DOP)
        if self.filter_config.max_dop is not None:
            dop = metadata.get_gps_dop()
            if dop is not None and dop > self.filter_config.max_dop:
                self.logger.debug(f"Filtered {filename}: DOP {dop} > {self.filter_config.max_dop}")
                return False
        
        return True
    
    def apply_date_filters(self, image, filename: str) -> bool:
        """Apply date range filters to an image."""
        if not self.filter_config.date_from and not self.filter_config.date_to:
            return True
        
        # Extract date from image using ImageMetadata wrapper
        metadata = ImageMetadata(image)
        image_date = metadata.extract_date_taken()
        if not image_date:
            # If no date available, include the image (conservative approach)
            return True
        
        is_in_range = self.date_parser.is_date_in_range(
            image_date, 
            self.filter_config.date_from, 
            self.filter_config.date_to
        )
        
        if not is_in_range:
            self.logger.debug(f"Filtered {filename}: date {image_date} outside range")
        
        return is_in_range


class FileOperationManager:
    """Handles file copying and organization operations."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.path_normalizer = PathNormalizer()
    
    def copy_images_simple(self, images: List[ImageData], output_directory: str) -> int:
        """Copy images to output directory without clustering."""
        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        
        copied_count = 0
        for image_data in images:
            try:
                source_path = Path(image_data["path"])
                dest_path = output_path / image_data["filename"]
                
                # Handle duplicate filenames
                counter = 1
                original_dest = dest_path
                while dest_path.exists():
                    stem = original_dest.stem
                    suffix = original_dest.suffix
                    dest_path = output_path / f"{stem}_{counter}{suffix}"
                    counter += 1
                
                shutil.copy2(source_path, dest_path)
                copied_count += 1
                self.logger.debug(f"Copied: {source_path} -> {dest_path}")
                
            except Exception as e:
                self.logger.error(f"Failed to copy {image_data['filename']}: {e}")
                
        return copied_count
    
    def copy_images_by_clusters(self, clusters: Dict[str, List[ImageData]], output_directory: str) -> int:
        """Copy images organized by location clusters."""
        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        
        copied_count = 0
        for cluster_name, cluster_images in clusters.items():
            # Create cluster subfolder
            cluster_folder = output_path / self.path_normalizer.sanitize_folder_name(cluster_name)
            cluster_folder.mkdir(parents=True, exist_ok=True)
            
            self.logger.info(f"Processing cluster: {cluster_name} ({len(cluster_images)} images)")
            
            for image_data in cluster_images:
                try:
                    source_path = Path(image_data["path"])
                    dest_path = cluster_folder / image_data["filename"]
                    
                    # Handle duplicate filenames within cluster
                    counter = 1
                    original_dest = dest_path
                    while dest_path.exists():
                        stem = original_dest.stem
                        suffix = original_dest.suffix
                        dest_path = cluster_folder / f"{stem}_{counter}{suffix}"
                        counter += 1
                    
                    shutil.copy2(source_path, dest_path)
                    copied_count += 1
                    self.logger.debug(f"Copied: {source_path} -> {dest_path}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to copy {image_data['filename']}: {e}")
        
        return copied_count