"""GPS data processing and image metadata extraction."""

import logging
import os
from pathlib import Path

from exif import Image

from .constants import Constants
from .types import ImageData, FilterConfig
from .utils import GPSFilter, DateParser, ImageMetadata


class GPSImageProcessor:
    """Processes JPEG images to extract GPS metadata and filter images based on configurable
        criteria.

    This class provides methods to:
    - Validate and load JPEG image files.
    - Extract GPS coordinates and convert them to decimal degrees.
    - Apply date and GPS accuracy filters to images.
    - Retrieve metadata such as the date the photo was taken.

    Attributes:
        filter_config (FilterConfig): Configuration for filtering images.
        logger (logging.Logger): Logger for recording processing events and errors.
        gps_filter (GPSFilter): Helper for applying GPS and date filters.
        date_parser (DateParser): Utility for parsing date information from images.

    Methods:
        extract_image_gps_data(image_path: str) -> ImageData | None:
            Extracts GPS and metadata from a single image file, applying filters.

        is_jpeg_file(filename: str) -> bool:
            Checks if the file has a JPEG extension.

        _load_and_validate_image(img_file, filename: str) -> Image | None:
            Loads and validates the image format from a file-like object.

        _get_decimal_coords(image: Image) -> tuple[float | None, float | None]:
            Extracts and converts GPS coordinates to decimal degrees.

        _convert_dhms_to_decimal(dhms) -> float | None:
            Converts degrees, minutes, seconds (DMS) format to decimal degrees.
    """

    def __init__(self, filter_config: FilterConfig, logger: logging.Logger):
        self.filter_config = filter_config
        self.logger = logger
        self.gps_filter = GPSFilter(filter_config, logger)
        self.date_parser = DateParser()

    def extract_image_gps_data(self, image_path: str) -> ImageData | None:
        """
        Extract GPS and metadata from a single image file.

        Args:
            image_path: Full path to the image file

        Returns:
            ImageData dict or None if no GPS data or error reading file
        """
        if not self.is_jpeg_file(image_path):
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

                # Extract date information using ImageMetadata wrapper
                metadata = ImageMetadata(my_image)
                date_taken = metadata.extract_date_taken()

                return ImageData(
                    filename=filename,
                    path=image_path,
                    latitude=lat_deg_dec,
                    longitude=long_deg_dec,
                    date_taken=date_taken,
                )

        except (OSError, IOError, PermissionError) as e:
            self.logger.warning(f"Error processing {image_path}: {e}")
            return None

    def is_jpeg_file(self, filename: str) -> bool:
        """
        Check if the given filename has a JPEG file extension.

        Args:
            filename (str): The name of the file to check.

        Returns:
            bool: True if the file has a JPEG extension, False otherwise.
        """

        return Path(filename).suffix.lower() in Constants.JPEG_EXTENSIONS

    def _load_and_validate_image(self, img_file, filename: str) -> Image | None:
        """
        Attempts to load an image from the given file-like object and validates its format.

        Parameters:
            img_file: A file-like object containing the image data.
            filename (str): The name of the image file, used for logging purposes.

        Returns:
            Image | None: An Image object if loading and validation succeed; otherwise, None.

        Logs:
            - Info message if the image file is corrupt or cannot be read.
            - Info message if the image format is invalid.
        """

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

        # Use ImageMetadata wrapper for consistent encapsulation
        metadata = ImageMetadata(image)

        # Get latitude
        lat = metadata.get_gps_latitude()
        if lat:
            lat_ref = metadata.get_gps_latitude_ref()
            decimal_latitude = self._convert_dhms_to_decimal(lat)
            if decimal_latitude:
                # Apply negative sign for South
                lat_deg_dec = decimal_latitude if lat_ref == "N" else -decimal_latitude

        # Get longitude
        lon = metadata.get_gps_longitude()
        if lon:
            lon_ref = metadata.get_gps_longitude_ref()
            decimal_longitude = self._convert_dhms_to_decimal(lon)
            if decimal_longitude:
                # Apply negative sign for West
                long_deg_dec = decimal_longitude if lon_ref == "E" else -decimal_longitude

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
