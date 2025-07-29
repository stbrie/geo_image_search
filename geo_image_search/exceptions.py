"""Custom exceptions for the geo image search application."""


class GeoImageSearchError(Exception):
    """Base exception for geo image search operations."""
    pass


class ConfigurationError(GeoImageSearchError):
    """Raised when there are configuration-related errors."""
    pass


class GPSDataError(GeoImageSearchError):
    """Raised when there are GPS data processing errors."""
    pass


class FileOperationError(GeoImageSearchError):
    """Raised when file operations fail."""
    pass