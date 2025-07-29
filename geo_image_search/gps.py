"""GPS data processing and image metadata extraction."""

import logging
import os
from pathlib import Path

try:
    from exif import Image
except ImportError:
    Image = None

from .constants import Constants
from .exceptions import GPSDataError
from .types import ImageData, FilterConfig
from .utils import GPSFilter, DateParser


class GPSImageProcessor:
    """Handles GPS data extraction and processing from images."""
    
    def __init__(self, filter_config: FilterConfig, logger: logging.Logger):
        self.filter_config = filter_config
        self.logger = logger
        self.gps_filter = GPSFilter(filter_config, logger)
        self.date_parser = DateParser()
        
        if not Image:
            raise ImportError("exif library is required for GPS processing. Install with: pip install exif")
        
    def extract_image_gps_data(self, image_path: str) -> ImageData | None:
        """
        Extract GPS and metadata from a single image file.
        
        Args:
            image_path: Full path to the image file
            
        Returns:
            ImageData dict or None if no GPS data or error reading file
        """
        if not self._is_jpeg_file(image_path):
            return None
            
        filename = os.path.basename(image_path)
        
        try:
            with open(image_path, "rb") as img_file:
                my_image = self._load_and_validate_image(img_file, filename)
                if not my_image:
                    return None
                
                # Apply date filters
                if not self.gps_filter.apply_date_filters(my_image, filename):
                    return None
                
                # Extract GPS coordinates
                lat_deg_dec, long_deg_dec = self._get_decimal_coords(my_image)
                
                if lat_deg_dec is None or long_deg_dec is None:
                    return None
                
                # Apply GPS accuracy filters
                if not self.gps_filter.apply_gps_accuracy_filters(my_image, filename):
                    return None
                
                # Extract date information
                date_taken = self._extract_date_taken(my_image)
                
                return ImageData(
                    filename=filename,
                    path=image_path,
                    latitude=lat_deg_dec,
                    longitude=long_deg_dec,
                    date_taken=date_taken
                )
                
        except (OSError, IOError, PermissionError) as e:
            self.logger.warning(f"Error processing {image_path}: {e}")
            return None
    
    def _is_jpeg_file(self, filename: str) -> bool:
        """Check if a file is a JPEG image based on its file extension."""
        return Path(filename).suffix.lower() in Constants.JPEG_EXTENSIONS
    
    def _load_and_validate_image(self, img_file, filename: str):
        """Load and validate an image file."""
        try:
            return Image(img_file)
        except (OSError, IOError, MemoryError) as e:
            self.logger.info(f"Error reading {filename}. Corrupt file? {e}")
            return None
        except ValueError as e:
            self.logger.info(f"Invalid image format {filename}: {e}")
            return None
    
    def _get_decimal_coords(self, image: Image) -> tuple[float | None, float | None]:
        """
        Extract and convert GPS coordinates from an image to decimal degrees format.
        
        Args:
            image: An image object that may contain GPS metadata
            
        Returns:
            Tuple containing (latitude, longitude) in decimal degrees format
        """
        lat_deg_dec = None
        long_deg_dec = None

        # Get latitude
        try:
            lat = image.gps_latitude
            lat_ref = getattr(image, "gps_latitude_ref", "N")
            decimal_latitude = self._convert_dhms_to_decimal(lat)
            if decimal_latitude:
                # Apply negative sign for South
                lat_deg_dec = decimal_latitude if lat_ref == "N" else -decimal_latitude
        except AttributeError as e:
            self.logger.debug(f"Image has no latitude GPS data: {e}")

        # Get longitude
        try:
            lon = image.gps_longitude
            lon_ref = getattr(image, "gps_longitude_ref", "W")
            decimal_longitude = self._convert_dhms_to_decimal(lon)
            if decimal_longitude:
                # Apply negative sign for West
                long_deg_dec = decimal_longitude if lon_ref == "E" else -decimal_longitude
        except AttributeError as e:
            self.logger.debug(f"Image has no longitude data: {e}")

        return lat_deg_dec, long_deg_dec
    
    def _convert_dhms_to_decimal(self, dhms) -> float | None:
        """
        Convert degrees, minutes, seconds (DMS) format to decimal degrees.
        
        Args:
            dhms: A list containing [degrees, minutes, seconds] values
            
        Returns:
            The decimal degree equivalent of the DMS values, or None if invalid
        """
        if not dhms or len(dhms) < 3:
            return None

        degrees = dhms[0]
        minutes = dhms[1] / 60
        seconds = dhms[2] / 3600
        return degrees + minutes + seconds
    
    def _extract_date_taken(self, image: Image) -> str | None:
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