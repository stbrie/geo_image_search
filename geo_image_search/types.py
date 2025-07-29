"""Type definitions for the geo image search application."""

from dataclasses import dataclass
from datetime import date
from typing import TypedDict


class ImageData(TypedDict):
    """Type definition for image data."""
    filename: str
    path: str
    latitude: float
    longitude: float
    date_taken: str | None


@dataclass
class SearchConfig:
    """Search configuration parameters."""
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius: float = 0.1
    far: bool = False


@dataclass
class DirectoryConfig:
    """Directory configuration parameters."""
    root: str | None = None
    output_directory: str | None = None
    find_only: bool = False
    sort_by_location: bool = False


@dataclass
class OutputConfig:
    """Output configuration parameters."""
    save_addresses: bool = False
    export_kml: bool = False
    verbose: bool = False


@dataclass
class FilterConfig:
    """Filter configuration parameters."""
    max_gps_error: float | None = None
    max_dop: float | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass
class ProcessingConfig:
    """Processing configuration parameters."""
    resume: bool = False


@dataclass
class FolderKMLConfig:
    """Folder KML export configuration parameters."""
    folder_path: str | None = None
    output_kml_path: str | None = None
    recursive: bool = True
    verbose: bool = False
    date_from: date | None = None
    date_to: date | None = None