"""Constants and error codes for the geo image search application."""

from datetime import datetime


class Constants:
    """Application constants."""
    JPEG_EXTENSIONS = {".jpg", ".jpeg", ".JPG", ".JPEG"}
    DEFAULT_RADIUS = 0.1
    CHECKPOINT_INTERVAL_FILES = 100
    DEFAULT_USER_AGENT = "github/stbrie: geo_image_search"
    
    # Geocoding timeouts
    GEOCODING_TIMEOUT_SECONDS = 10
    
    # KML view ranges in meters
    KML_CENTER_VIEW_RANGE = 200
    KML_POINT_VIEW_RANGE = 50
    
    class ErrorCodes:
        """Application exit codes."""
        SUCCESS = 0
        INTERRUPTED = 1
        NO_ROOT_DIRECTORY = 2
        NO_OUTPUT_DIRECTORY = 3
        CONFLICTING_OPTIONS = 4
        GEOCODING_FAILED = 6
        INVALID_COORDINATES = 7
        ROOT_DIRECTORY_NOT_FOUND = 8
        NO_LOCATION_FOUND = 9
        MISSING_OUTPUT_FOR_ADDRESSES = 10
        INVALID_DATE_FROM = 11
        INVALID_DATE_TO = 12
        SORT_LOCATION_FIND_ONLY_CONFLICT = 15
        SORT_LOCATION_NO_OUTPUT = 16
        FILE_OPERATION_ERROR = 17
        GPS_DATA_ERROR = 18
        GENERAL_ERROR = 19