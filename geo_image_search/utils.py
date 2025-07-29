"""Utility classes for the geo image search application."""

import logging
import os
import re
from datetime import datetime, date
from pathlib import Path
from .constants import Constants
from .exceptions import ConfigurationError, GPSDataError
from .types import FilterConfig


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
        normalized = Path(image_path).as_posix()
        if not normalized.startswith('/'):
            normalized = '/' + normalized
        return normalized
    
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


class GPSFilter:
    """Handles GPS data filtering and validation."""
    
    def __init__(self, filter_config: FilterConfig, logger: logging.Logger):
        self.filter_config = filter_config
        self.logger = logger
        self.date_parser = DateParser()
    
    def apply_gps_accuracy_filters(self, image, filename: str) -> bool:
        """Apply GPS accuracy filters to an image."""
        # Check GPS horizontal error
        if self.filter_config.max_gps_error is not None:
            try:
                if hasattr(image, 'gps_horizontal_error'):
                    gps_error = float(image.gps_horizontal_error)
                    if gps_error > self.filter_config.max_gps_error:
                        self.logger.debug(f"Filtered {filename}: GPS error {gps_error}m > {self.filter_config.max_gps_error}m")
                        return False
            except (AttributeError, ValueError, TypeError):
                # If we can't get GPS error, don't filter
                pass
        
        # Check Dilution of Precision (DOP)
        if self.filter_config.max_dop is not None:
            try:
                if hasattr(image, 'gps_dop'):
                    dop = float(image.gps_dop)
                    if dop > self.filter_config.max_dop:
                        self.logger.debug(f"Filtered {filename}: DOP {dop} > {self.filter_config.max_dop}")
                        return False
            except (AttributeError, ValueError, TypeError):
                # If we can't get DOP, don't filter
                pass
        
        return True
    
    def apply_date_filters(self, image, filename: str) -> bool:
        """Apply date range filters to an image."""
        if not self.filter_config.date_from and not self.filter_config.date_to:
            return True
        
        # Extract date from image
        image_date = self._extract_image_date(image)
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
    
    def _extract_image_date(self, image) -> str | None:
        """Extract date taken from EXIF data."""
        date_fields = ["datetime_original", "datetime", "datetime_digitized"]
        for field in date_fields:
            try:
                if hasattr(image, field):
                    date_str = getattr(image, field)
                    if date_str:
                        return date_str
            except AttributeError:
                continue
        return None