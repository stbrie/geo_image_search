# flake8: noqa: E501
"""
A tool for searching and organizing JPEG images based on their GPS location metadata.

This module provides functionality to:
- Search through directory trees for JPEG images
- Extract GPS coordinates from EXIF metadata
- Find images within a specified radius of a target location
- Optionally copy matching images to an output directory
- Support both address-based and coordinate-based location searches

The GeoImageSearch class handles:
- Command-line argument parsing for search parameters
- GPS coordinate extraction and conversion from EXIF data
- Distance calculations using geopy
- File operations for organizing found images
- Verbose output and progress tracking

Example usage:
    python geo_image_search.py -d /path/to/images -a "New York, NY" -r 5.0 -o /output/dir
    python geo_image_search.py -d /path/to/images -t 40.7128 -g -74.0060 -r 2.0 --find_only

Attributes:
    JPEG_EXTENSIONS (set): File extensions considered as JPEG images

Main functionality is provided through the GeoImageSearch class which manages:
- Location geocoding via Nominatim
- EXIF GPS data extraction
- Distance-based filtering
- File copying and organization
"""
import argparse
import csv
import json
import os
import pickle
import re
import signal
import sqlite3
import sys
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path
from shutil import copyfile
import platform
from exif import Image
from geopy import distance
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim
from typing import Dict, List

# KML export support
try:
    from fastkml.kml import KML
    from fastkml.containers import Document, Folder
    from fastkml.views import LookAt
    from fastkml.features import Placemark
    from fastkml.styles import IconStyle, Style, StyleUrl
    from pygeoif.geometry import Point

    KML_AVAILABLE = True
except ImportError:
    KML_AVAILABLE = False
    kml = None
    Point = None

CAMERA_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/camera.png"
CAMERA_STYLE_ID = "cameraIcon"

# Persistent reverse-geocode cache lives in the user's home so it survives
# across runs and is shared between CLI and GUI.
GEOCODE_CACHE_FILE = Path.home() / ".geo_image_search_cache.sqlite"


class _GeocodeCache:
    """SQLite-backed cache of Nominatim reverse-geocode results.

    Keyed by lat/lon rounded to 4 decimals (~11m); two photos that close
    share an entry, which matches typical consumer-GPS accuracy and gives
    real hit rates without coarsening street-level answers.
    """

    _KEY_PRECISION = 4

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reverse_geocode (
                lat_key REAL NOT NULL,
                lon_key REAL NOT NULL,
                address TEXT NOT NULL,
                raw_json TEXT,
                PRIMARY KEY (lat_key, lon_key)
            )
            """
        )
        self.conn.commit()

    @classmethod
    def _key(cls, lat: float, lon: float) -> tuple[float, float]:
        return (round(lat, cls._KEY_PRECISION), round(lon, cls._KEY_PRECISION))

    def get(self, lat: float, lon: float) -> tuple[str | None, dict | None]:
        """Return (address, raw) if cached, else (None, None)."""
        cur = self.conn.execute(
            "SELECT address, raw_json FROM reverse_geocode WHERE lat_key=? AND lon_key=?",
            self._key(lat, lon),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        address, raw_json = row
        raw = json.loads(raw_json) if raw_json else None
        return address, raw

    def put(self, lat: float, lon: float, address: str, raw: dict | None = None) -> None:
        raw_json = json.dumps(raw) if raw else None
        lat_k, lon_k = self._key(lat, lon)
        self.conn.execute(
            "INSERT OR REPLACE INTO reverse_geocode "
            "(lat_key, lon_key, address, raw_json) VALUES (?, ?, ?, ?)",
            (lat_k, lon_k, address, raw_json),
        )
        self.conn.commit()

    def size(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM reverse_geocode")
        return cur.fetchone()[0]

    def clear(self) -> int:
        """Delete all cached entries. Returns rows removed."""
        cur = self.conn.execute("DELETE FROM reverse_geocode")
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

# HEIC support — register the pillow-heif plugin so PIL can open .heic/.heif.
# Falls back gracefully if the package isn't installed.
try:
    import pillow_heif
    from PIL import Image as PILImage

    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False
    PILImage = None


class _PILExifAdapter:
    """Expose PIL's EXIF data via the attribute names the `exif` library uses,
    so HEIC files flow through the same downstream code as JPEG without changes.

    Only the fields downstream code reads are exposed; missing tags raise
    AttributeError on access, matching the `exif` library's behavior.
    """

    _GPS_IFD = 0x8825
    _EXIF_IFD = 0x8769
    _DATETIME = 0x0132

    def __init__(self, pil_img):
        exif_data = pil_img.getexif()
        try:
            gps = exif_data.get_ifd(self._GPS_IFD) or {}
        except (KeyError, AttributeError):
            gps = {}
        try:
            ifd = exif_data.get_ifd(self._EXIF_IFD) or {}
        except (KeyError, AttributeError):
            ifd = {}

        # GPS sub-IFD: 1=lat_ref ('N'/'S'), 2=lat, 3=lon_ref ('E'/'W'), 4=lon
        if 1 in gps:
            self.gps_latitude_ref = gps[1]
        if 2 in gps:
            self.gps_latitude = gps[2]
        if 3 in gps:
            self.gps_longitude_ref = gps[3]
        if 4 in gps:
            self.gps_longitude = gps[4]

        # Datetimes
        if 0x9003 in ifd:
            self.datetime_original = ifd[0x9003]
        if 0x9004 in ifd:
            self.datetime_digitized = ifd[0x9004]
        if self._DATETIME in exif_data:
            self.datetime = exif_data[self._DATETIME]


class GeoImageSearch:  # pylint: disable=too-many-instance-attributes
    """
    A class for searching and filtering JPEG images based on their GPS metadata location.

    This class provides functionality to:
    - Search through a directory tree for JPEG images with GPS metadata
    - Filter images based on proximity to a specified location (address or coordinates)
    - Copy matching images to an output directory
    - Generate CSV files with image address information

    The search can be centered on either:
    - A text address (geocoded using Nominatim)
    - Specific latitude/longitude coordinates

    Images are filtered based on a configurable radius from the center point, with
    distances calculated using the great circle distance formula.

    Attributes:
        JPEG_EXTENSIONS (set): Supported JPEG file extensions
        find_only (bool): If True, only find images without copying them
        address (str | None): Text address for search center
        root_images_directory (str | None): Root directory to search for images
        search_coords (tuple[float, float] | None): Search center coordinates (lat, lon)
        radius (float | None): Search radius in miles
        output_directory (str): Directory to copy matching images to
        geolocator (Nominatim): Geocoding service instance
        verbose (bool): Enable verbose output

    Example:
        searcher = GeoImageSearch()
        searcher.startup()  # Parse arguments and initialize
        # Process images using calc_distance() method
    """

    JPEG_EXTENSIONS = {".jpg", ".jpeg"}
    HEIC_EXTENSIONS = {".heic", ".heif"}
    SUPPORTED_EXTENSIONS = JPEG_EXTENSIONS | HEIC_EXTENSIONS

    def load_config_file(self, config_path: str | Path | None = None) -> dict:
        """
        Load configuration from TOML file.

        Searches for config file in this order:
        1. Provided config_path argument
        2. --config command line argument
        3. geo_image_search.toml in current directory
        4. ~/.config/geo_image_search/config.toml
        5. ~/.geo_image_search.toml

        Args:
            config_path: Optional path to specific config file

        Returns:
            dict: Configuration data loaded from TOML file
        """
        config_locations = []

        # Add provided path if given
        if config_path:
            config_locations.append(Path(config_path))

        # Add standard locations
        config_locations.extend(
            [
                Path.cwd() / "geo_image_search.toml",
                Path.home() / ".config" / "geo_image_search" / "config.toml",
                Path.home() / ".geo_image_search.toml",
            ]
        )

        for config_file in config_locations:
            if config_file.exists():
                try:
                    if tomllib:
                        with open(config_file, "rb") as f:
                            config_data = tomllib.load(f)
                        if self.verbose:
                            print(f"Loaded configuration from: {config_file}")
                        self.config_file = config_file
                        return config_data
                    else:
                        print(
                            f"Warning: TOML support not available, skipping config file {config_file}"
                        )
                        continue
                except (OSError, IOError) as e:
                    print(f"Warning: Could not load config file {config_file}: {e}")
                    continue
                except Exception as e:  # Catch TOML decode errors generically
                    print(f"Warning: Could not parse config file {config_file}: {e}")
                    continue

        return {}

    def get_kml_image_path(self, path):
        if platform.system() == "Windows":
            return path.replace("\\", "/")
        if path.startswith("/mnt/"):
            drive = path[5]
            win_path = f"{drive.upper()}:"
            rest = path[6:]
            return win_path + rest.replace("/", "\\")
        return path

    def create_sample_config(self, output_path: str | Path | None = None) -> None:
        """Create a sample configuration file with documentation."""
        if not output_path:
            output_path = Path.cwd() / "geo_image_search.toml"
        else:
            output_path = Path(output_path)

        sample_config = """# Geo Image Search Configuration File
# Save this as geo_image_search.toml in your working directory,
# ~/.config/geo_image_search/config.toml, or ~/.geo_image_search.toml

[search]
# Default search parameters
address = "New York, NY"  # Default address for search center
# latitude = 40.7128      # Alternative: use coordinates instead of address  
# longitude = -74.0060
radius = 1.0              # Search radius in miles
# cluster_radius = 100    # Group radius in YARDS for sort_by_location (defaults to "radius" in miles)
far = false              # Show images outside radius

[directories] 
# Directory settings
root = "/path/to/photos"          # Root directory to search for images
output_directory = "found_images" # Output directory for matched images
find_only = false                # Only find images, don't copy them
sort_by_location = false         # Sort images into subfolders by geographic clusters

[output]
# Output and export options
save_addresses = false    # Save all image addresses to CSV
export_kml = false       # Export results as KML for Google Earth
verbose = false          # Enable verbose output

[filters]
# Advanced filtering options
date_from = "2020-01-01" # Filter images from this date (YYYY-MM-DD)
date_to = "2024-12-31"   # Filter images to this date (YYYY-MM-DD)

[processing]
# Processing behavior
resume = false          # Resume from previous interrupted search

# Example configurations:
# For vacation photos: radius = 0.5, save_addresses = true
# For large archives: find_only = true, resume = true, verbose = true
# For specific events: date_from and date_to with precise coordinates
"""

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(sample_config)
            print(f"Sample configuration file created: {output_path}")
            print("Edit this file with your preferred settings.")
        except (OSError, IOError) as e:
            print(f"Error creating sample config file: {e}")

    def merge_config_with_args(self, config_data: dict, args: argparse.Namespace) -> None:
        """
        Merge configuration file data with command-line arguments.
        Command-line arguments take precedence over config file settings.

        Args:
            config_data: Dictionary loaded from TOML config file
            args: Parsed command-line arguments
        """
        # Search settings
        search_config = config_data.get("search", {})
        if not args.address and "address" in search_config:
            args.address = search_config["address"]
        if args.latitude is None and "latitude" in search_config:
            args.latitude = search_config["latitude"]
        if args.longitude is None and "longitude" in search_config:
            args.longitude = search_config["longitude"]
        if args.radius == 0.05 and "radius" in search_config:  # 0.05 is default
            args.radius = search_config["radius"]
        if args.cluster_radius is None and "cluster_radius" in search_config:
            args.cluster_radius = search_config["cluster_radius"]
        if not args.far and search_config.get("far", False):
            args.far = search_config["far"]

        # Directory settings
        dir_config = config_data.get("directories", {})
        if not args.root and "root" in dir_config:
            args.root = dir_config["root"]
        if not args.output_directory and "output_directory" in dir_config:
            args.output_directory = dir_config["output_directory"]
        if not args.find_only and dir_config.get("find_only", False):
            args.find_only = dir_config["find_only"]
        if not args.sort_by_location and dir_config.get("sort_by_location", False):
            args.sort_by_location = dir_config["sort_by_location"]

        # Output settings
        output_config = config_data.get("output", {})
        if not args.save_addresses and output_config.get("save_addresses", False):
            args.save_addresses = output_config["save_addresses"]
        if not args.export_kml and output_config.get("export_kml", False):
            args.export_kml = output_config["export_kml"]
        if not args.verbose and output_config.get("verbose", False):
            args.verbose = output_config["verbose"]

        # Filter settings
        filter_config = config_data.get("filters", {})
        if not args.date_from and "date_from" in filter_config:
            args.date_from = filter_config["date_from"]
        if not args.date_to and "date_to" in filter_config:
            args.date_to = filter_config["date_to"]

        # Processing settings
        proc_config = config_data.get("processing", {})
        if not args.resume and proc_config.get("resume", False):
            args.resume = proc_config["resume"]

    def get_opts(self):
        """
        Parse command line arguments for the geo image search application.

        Sets up argument parser with options for:
        - Output directory for copying matched images
        - Find-only mode (no file operations)
        - Address matching for reverse geocoding
        - Saving all image addresses to CSV
        - Verbose output mode
        - Root directory for image search (required)
        - Latitude/longitude coordinates for search center
        - Search radius in miles (default 0.1)
        - Far mode to show images outside radius

        Parses arguments and assigns them to instance attributes for use
        throughout the application. Prints configuration in verbose mode.

        Returns:
            None: Arguments are stored as instance attributes
        """
        parser = argparse.ArgumentParser(
            prog="geo_image_search.py",
            description="Finds images based on location data found in .jpeg metadata.",
            epilog="Examples:\n"
            "  %(prog)s -d /photos -a 'New York, NY' -r 2.0 -o found_images\n"
            "  %(prog)s -d /photos -t 40.7128 -g -74.0060 -r 0.5 --find_only\n"
            "  %(prog)s -d /photos -a 'Paris' -r 1.0 -o paris_pics -i -v\n"
            "  %(prog)s --create-config  # Create sample config file\n"
            "  %(prog)s --config my_settings.toml  # Use custom config file\n\n"
            "Configuration files (TOML format) are searched in this order:\n"
            "  1. Path specified with --config\n"
            "  2. ./geo_image_search.toml\n"
            "  3. ~/.config/geo_image_search/config.toml\n"
            "  4. ~/.geo_image_search.toml",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parser.add_argument(
            "-o",
            "--output_directory",
            action="store",
            help="<output directory> to copy images to (optional)",
        )
        parser.add_argument(
            "-f",
            "--find_only",
            action="store_true",
            help="(optional) if set, do not copy files or save data.",
        )
        parser.add_argument(
            "-a",
            "--address",
            action="store",
            help="(optional) <address> address to match to images",
        )
        parser.add_argument(
            "-i",
            "--save_addresses",
            action="store_true",
            help="Save ALL image addresses to CSV file in output directory (requires -o)",
        )
        parser.add_argument(
            "-v", "--verbose", action="store_true", help="print additional information"
        )
        parser.add_argument(
            "-d",
            "--root",
            action="store",
            help="(required) the <root directory> of where to begin searching for images",
        )
        parser.add_argument(
            "-t",
            "--latitude",
            type=float,
            help="(optional) if set, use the decimal latitude to center the search.",
        )
        parser.add_argument(
            "-g",
            "--longitude",
            type=float,
            help="(optional) if set, use this decimal longitude to center the search.",
        )
        parser.add_argument(
            "-r",
            "--radius",
            type=float,
            default=0.05,
            help="(optional, defaults to .05) the radius of the search in miles.",
        )
        parser.add_argument(
            "--cluster-radius",
            type=float,
            help="(optional) Radius in YARDS used for grouping when "
            "--sort-by-location is set. Defaults to --radius (which is in miles).",
        )
        parser.add_argument(
            "-x",
            "--far",
            action="store_true",
            help="(optional) show images that are further than radius from centerpoint",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume from a previous interrupted search (uses checkpoint file)",
        )
        parser.add_argument(
            "--export-kml",
            action="store_true",
            help="Export matched images as KML file for Google Earth",
        )
        parser.add_argument(
            "--date-from",
            type=str,
            help="Filter images from this date (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--date-to",
            type=str,
            help="Filter images to this date (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--config",
            type=str,
            help="Path to TOML configuration file (optional)",
        )
        parser.add_argument(
            "--create-config",
            type=str,
            nargs="?",
            const="geo_image_search.toml",
            help="Create a sample configuration file and exit (optionally specify path)",
        )
        parser.add_argument(
            "--sort-by-location",
            action="store_true",
            help="Group images into geographic clusters (uses --cluster-radius if set, "
            "else --radius). Disk folders only when copying; KML always grouped.",
        )

        args = parser.parse_args(self.argv)

        # Handle config file creation request early
        if args.create_config:
            self.create_sample_config(args.create_config)
            sys.exit(0)

        # Load configuration file first
        config_path = args.config if hasattr(args, "config") else None
        self.config_data = self.load_config_file(config_path)

        # Merge config file settings with command line arguments
        if self.config_data:
            self.merge_config_with_args(self.config_data, args)

        # Validate required arguments after config file merging
        if not args.root:
            parser.error("the following arguments are required: -d/--root")

        self.address = args.address
        self.user_output_directory = args.output_directory
        self.find_only = args.find_only
        self.image_addresses = args.save_addresses
        self.verbose = args.verbose
        self.root_images_directory = args.root
        self.lat = args.latitude
        self.lon = args.longitude
        self.radius = args.radius
        # cluster_radius is entered in YARDS; we store it in miles so it's
        # directly comparable to geopy's distance.miles in find_or_create_cluster.
        self.cluster_radius = (
            args.cluster_radius / 1760.0 if args.cluster_radius is not None else None
        )
        self.resume = args.resume
        self.sort_by_location = args.sort_by_location
        self.export_kml = args.export_kml

        # Parse date filters
        self.date_from = None
        self.date_to = None
        if args.date_from:
            try:
                self.date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
            except ValueError:
                print(
                    f"Error: Invalid date format for --date-from: {args.date_from}. Use YYYY-MM-DD"
                )
                sys.exit(11)
        if args.date_to:
            try:
                self.date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()
            except ValueError:
                print(f"Error: Invalid date format for --date-to: {args.date_to}. Use YYYY-MM-DD")
                sys.exit(12)

        # Initialize checkpoint tracking
        self.checkpoint_file = None
        self.processed_files_set = set()
        self.last_checkpoint_time = time.time()

        # Validate save_addresses requires output directory
        if self.image_addresses and not self.user_output_directory:
            print("Error: --save_addresses requires --output_directory to be specified")
            sys.exit(10)

        # Validate sort_by_location requirements
        if self.sort_by_location:
            if not self.find_only and not self.user_output_directory:
                print(
                    "Error: --sort-by-location requires --output_directory when copying files"
                )
                sys.exit(16)
            if self.verbose:
                print("Location-based sorting enabled: grouping images by geographic clusters")

        if self.verbose:
            print(f"Configuration file: {self.config_file or 'None'}")
            print(f"Address: {self.address}")
            print(f"User Output Directory: {self.user_output_directory}")
            print(f"Find Only: {self.find_only}")
            print(f"Save Image Addresses: {self.image_addresses}")
            print(f"Verbose: {self.verbose}")
            print(f"Root Images Directory: {self.root_images_directory}")
            print(f"Latitude: {self.lat}")
            print(f"Longitude: {self.lon}")
            print(f"Radius: {self.radius}")
            if self.config_data:
                print("Active configuration sections:", list(self.config_data.keys()))

    def normalize_path(self, path_str):
        """
        Normalize a file path to an absolute path appropriate for the host OS.

        On native Windows the path is kept in Windows form (drive letters preserved).
        On Linux/macOS, Windows-style drive paths (e.g. "C:\\folder") are converted
        to WSL mount form ("/mnt/c/folder") so the same config files work under WSL.
        """
        if platform.system() == "Windows":
            # Keep native Windows paths; just resolve to absolute.
            return str(Path(path_str).resolve())

        normalized = path_str.replace("\\", "/")
        if len(normalized) > 1 and normalized[1] == ":":
            drive = normalized[0].lower()
            normalized = f"/mnt/{drive}{normalized[2:]}"
        return str(Path(normalized).resolve())

    def is_supported_image_file(self, filename):
        """Return True if the file is a JPEG or HEIC image we can process."""
        return Path(filename).suffix.lower() in GeoImageSearch.SUPPORTED_EXTENSIONS

    def set_root_images_directory(self):
        """
        Set and validate the root images directory.

        This method validates that a root images directory has been specified,
        normalizes the path, and checks that the directory exists on the filesystem.

        Raises:
            SystemExit: With code 2 if no root images directory is specified.
            SystemExit: With code 8 if the specified directory does not exist.

        Side Effects:
            - Updates self.root_images_directory with the normalized path
            - Prints error messages to stdout before exiting on failure
        """
        if not self.root_images_directory:
            print("No images root directory specified.  --images-root-directory is not optional")
            sys.exit(2)

        self.root_images_directory = self.normalize_path(self.root_images_directory)

        if not os.path.exists(self.root_images_directory):
            print(f"Root directory does not exist: {self.root_images_directory}")
            sys.exit(8)

    def fix_cdata_in_kml(self, kml_path):
        with open(kml_path, "r", encoding="utf-8") as f:
            kml_content = f.read()
        kml_content = kml_content.replace("&lt;", "<").replace("&gt;", ">")
        kml_content
        with open(kml_path, "w", encoding="utf-8") as f:
            f.write(kml_content)

    def set_output_directory(self):
        """
        Configure the output directory for processed images based on user settings.

        This method handles two distinct modes of operation:
        1. Normal mode: Creates an output directory structure under root_images_directory/geo_loc/
        2. Find-only mode: Sets output to indicate no saving should occur

        In normal mode (find_only=False):
        - Requires user_output_directory to be specified
        - Normalizes the user-provided output directory path
        - Creates a sanitized directory name by replacing invalid characters with underscores
        - Constructs final output path as: root_images_directory/geo_loc/sanitized_name

        In find-only mode (find_only=True):
        - Ensures no output directory is specified by user
        - Sets output_directory to "Do Not Save" to indicate no file operations

        Raises:
            SystemExit: With code 3 if no output directory specified in normal mode
            SystemExit: With code 4 if output directory specified in find-only mode

        Side Effects:
            - Updates self.output_directory with the determined output path
            - Prints status messages if verbose mode is enabled
            - May normalize self.user_output_directory path
        """

        if self.user_output_directory:
            self.user_output_directory = self.normalize_path(self.user_output_directory)
            self.output_directory = self.user_output_directory

            if self.verbose:
                print("Output directory: " + self.output_directory)
            if self.find_only:
                print(
                    "Find-only mode: image files will NOT be copied, but the "
                    "output directory will be used for CSV/KML exports."
                )
        elif self.find_only:
            print("Finding and outputting image path only.")
            self.output_directory = "Do Not Save"
        else:
            print("No output directory specified and not find only. Use one or the other.")
            sys.exit(3)

    def set_directories(self):
        """
        Set up the root images directory and output directory for the geo image search.

        This method calls helper methods to set the root images directory and output directory.
        If verbose mode is enabled, it prints the root images directory path. For the output
        directory, it creates the directory if it doesn't exist (unless set to "Do Not Save"),
        and prints status messages about directory creation or existence when in verbose mode.

        The method handles three scenarios for the output directory:
        1. Directory doesn't exist: Creates it and optionally prints creation message
        2. Directory exists: Optionally prints existence confirmation
        3. Output is set to "Do Not Save": No action taken

        Side Effects:
            - Creates output directory if it doesn't exist
            - Prints status messages to console when verbose mode is enabled

        Raises:
            OSError: If directory creation fails due to permissions or other filesystem issues
        """
        self.set_root_images_directory()
        self.set_output_directory()
        if self.verbose:
            print("Images Root Directory: " + str(self.root_images_directory))
        if self.output_directory != "Do Not Save":
            if not os.path.exists(self.output_directory):
                if self.verbose:
                    print("   Output directory does not exist.")
                    print("   Creating " + self.output_directory)
                os.makedirs(self.output_directory)
            else:
                print("   Output directory exists.")
        else:
            pass

    def __init__(self, argv=None):
        self.find_only = False
        self.opts = None
        self.args = None
        self.address: str | None = None
        self.root_images_directory: str | None = None
        self.od_re = None
        self.location = None
        self.search_coords: tuple[float, float] | None = None
        self.image_addresses = False
        self.images_directory = None
        self.location_address = ""
        self.output_directory = ""
        self.user_output_directory = None
        self.verbose = False
        self.lat = None  # the center of the target location
        self.lon = None  # the center of the target location
        self.radius: float | None = None  # the set by getopts.
        self.cluster_radius: float | None = None  # overrides radius for clustering
        self.far = False
        self.resume = False
        self.sort_by_location = False
        self.location_clusters = []  # Store location clusters for sorting
        self.argv = list(argv) if argv is not None else sys.argv[1:]
        self.cancel_event: threading.Event | None = None
        self.geolocator = Nominatim(user_agent="github/stbrie: geo_image_search")
        try:
            self.geocode_cache: _GeocodeCache | None = _GeocodeCache(GEOCODE_CACHE_FILE)
        except sqlite3.Error as e:
            print(f"Warning: could not open geocode cache: {e}")
            self.geocode_cache = None
        self.printed_directory = {}
        self.csv_data = []  # Store image data for CSV export
        self.last_geocode_time = 0  # Rate limiting for geocoding
        print("ARGV        :", self.argv)
        self.loc_format = "{0:}: {1:.7n}, {2:.7n} ({3:.3n})"
        self.config_file = None
        self.config_data = {}
        self.export_kml = False
        self.date_from = None
        self.date_to = None
        self.checkpoint_file = None
        self.processed_files_set = set()
        self.last_checkpoint_time = time.time()
        self.kml_results: Dict[str, List[Dict[str, str]]] = {}

    def startup(self):
        """
        Initialize the geo image search application.

        Performs the startup sequence by getting user options, setting the location
        based on the provided address (unless in sort-by-location mode), and configuring
        the necessary directories for the application to operate.

        This method should be called once during application initialization to
        prepare all required components before performing image searches.
        """
        self.get_opts()

        # Skip location setup if we're in sort-by-location mode
        if not self.sort_by_location:
            if self.address:
                try:
                    self.location = self.geolocator.geocode(query=self.address)
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    print(f"Geocoding failed: {e}")
                    sys.exit(6)
            elif self.lon and self.lat:
                try:
                    self.location = self.geolocator.reverse(
                        query=f"{str(self.lat)}, {str(self.lon)}"
                    )
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    print(f"Latitude, Longitude does not return a valid location object: {e}")
                    sys.exit(7)

            if self.location:
                self.search_coords = (self.location.latitude, self.location.longitude)
                print(f"Nominatum address: {self.location.address}")
                print(f"Lat, Lon: {str(self.location.latitude)}, {str(self.location.longitude)}")
            else:
                print("No location from Nominatim")
                sys.exit(9)
        else:
            print("Location-based sorting mode: grouping all images by geographic clusters")
            if self.verbose:
                print(f"Using radius of {self.radius} miles for clustering")

        self.set_directories()

        # Load checkpoint if resuming
        if self.resume:
            self.load_checkpoint()

    def convert_dhms_to_decimal(self, dhms):
        """
        Convert degrees, minutes, seconds (DMS) format to decimal degrees.

        Args:
            dhms (list): A list containing [degrees, minutes, seconds] values.
                        Must have at least 3 elements.

        Returns:
            float: The decimal degree equivalent of the DMS values.
            None: If dhms is None, empty, or has fewer than 3 elements.

        Example:
            >>> converter.convert_dhms_to_decimal([45, 30, 15])
            45.50416666666667
        """
        if not dhms or len(dhms) < 3:
            return None

        degrees = dhms[0]
        minutes = dhms[1] / 60
        seconds = dhms[2] / 3600
        return degrees + minutes + seconds

    def get_decimal_coords(self, image) -> tuple[float | None, float | None]:
        """
        Extract and convert GPS coordinates from an image to decimal degrees format.

        This method attempts to retrieve GPS latitude and longitude data from an image
        and converts them from degrees, minutes, seconds format to decimal degrees.
        It also handles GPS reference directions (N/S for latitude, E/W for longitude).

        Args:
            image: An image object that may contain GPS metadata with gps_latitude
                   and gps_longitude attributes.

        Returns:
            tuple[float | None, float | None]: A tuple containing (latitude, longitude)
            in decimal degrees format. Returns (None, None) if GPS data is not available
            or cannot be converted.

        Notes:
            - If verbose mode is enabled, prints diagnostic messages when GPS data
              is missing or cannot be processed
            - Handles AttributeError exceptions when GPS data is not present in the image
            - Uses the convert_dhms_to_decimal method to perform coordinate conversion
            - Properly handles GPS reference directions (N/S/E/W)
        """
        lat_deg_dec = None
        long_deg_dec = None

        # Get latitude
        try:
            lat = image.gps_latitude
            lat_ref = getattr(image, "gps_latitude_ref", "N")
            decimal_latitude = self.convert_dhms_to_decimal(lat)
            if decimal_latitude:
                # Apply negative sign for South
                lat_deg_dec = decimal_latitude if lat_ref == "N" else -decimal_latitude
            elif self.verbose:
                print("Could not find decimal latitude in file.")
        except AttributeError as e:
            if self.verbose:
                print(f"Image has no latitude GPS data: {e}")

        # Get longitude
        try:
            lon = image.gps_longitude
            lon_ref = getattr(image, "gps_longitude_ref", "W")
            decimal_longitude = self.convert_dhms_to_decimal(lon)
            if decimal_longitude:
                # Apply negative sign for West
                long_deg_dec = decimal_longitude if lon_ref == "E" else -decimal_longitude
            elif self.verbose:
                print("Could not find longitude in file.")
        except AttributeError as e:
            if self.verbose:
                print(f"Image has no longitude data {e}")

        return lat_deg_dec, long_deg_dec

    def check_date_range(self, image, filename: str) -> bool:
        """
        Check if an image's date falls within the specified date range.

        Args:
            image: Image object with EXIF data
            filename: Name of the image file for error reporting

        Returns:
            bool: True if image is within date range (or no date filters set), False otherwise
        """
        # If no date filters are set, accept all images
        if not self.date_from and not self.date_to:
            return True

        try:
            # Try to get the image date from EXIF data
            # Common EXIF date fields: datetime_original, datetime, datetime_digitized
            image_date_str = None

            # Try different EXIF date fields in order of preference
            date_fields = ["datetime_original", "datetime", "datetime_digitized"]
            for field in date_fields:
                try:
                    if hasattr(image, field):
                        image_date_str = getattr(image, field)
                        if image_date_str:
                            break
                except AttributeError:
                    continue

            if not image_date_str:
                if self.verbose:
                    print(f"  -> {filename}: No date information found in EXIF")
                return False

            # Parse the EXIF date (usually in format "YYYY:MM:DD HH:MM:SS")
            # Handle both full datetime and date-only formats
            try:
                if " " in image_date_str:
                    # Full datetime format
                    image_date = datetime.strptime(image_date_str, "%Y:%m:%d %H:%M:%S").date()
                else:
                    # Date only format
                    image_date = datetime.strptime(image_date_str, "%Y:%m:%d").date()
            except ValueError:
                # Try alternative format (some cameras use different separators)
                try:
                    image_date = datetime.strptime(image_date_str.split()[0], "%Y-%m-%d").date()
                except ValueError:
                    if self.verbose:
                        print(f"  -> {filename}: Could not parse date '{image_date_str}'")
                    return False

            # Check against date range
            if self.date_from and image_date < self.date_from:
                if self.verbose:
                    print(f"  -> {filename}: Date {image_date} is before {self.date_from}")
                return False

            if self.date_to and image_date > self.date_to:
                if self.verbose:
                    print(f"  -> {filename}: Date {image_date} is after {self.date_to}")
                return False

            if self.verbose:
                print(f"  -> {filename}: Date {image_date} is within range")
            return True

        except Exception as e:
            if self.verbose:
                print(f"  -> {filename}: Error checking date: {e}")
            return False

    def _reverse_geocode(self, lat: float, lon: float):
        """Reverse-geocode lat/lon, going through the cache first.

        Returns (address_str, raw_dict) on success, (None, None) on failure.
        Rate-limits Nominatim to 1 req/s on cache miss.
        """
        if self.geocode_cache is not None:
            addr, raw = self.geocode_cache.get(lat, lon)
            if addr is not None:
                return addr, raw

        current_time = time.time()
        if current_time - self.last_geocode_time < 1.0:
            time.sleep(1.0 - (current_time - self.last_geocode_time))

        try:
            location = self.geolocator.reverse(f"{lat},{lon}", exactly_one=True)
            self.last_geocode_time = time.time()
        except (OSError, IOError, ValueError, GeocoderTimedOut, GeocoderServiceError) as e:
            if self.verbose:
                print(f"Reverse geocode failed for ({lat}, {lon}): {e}")
            return None, None

        if not location or not getattr(location, "address", None):
            return None, None

        raw = getattr(location, "raw", None)
        if self.geocode_cache is not None:
            try:
                self.geocode_cache.put(lat, lon, location.address, raw)
            except sqlite3.Error as e:
                if self.verbose:
                    print(f"Warning: could not write geocode cache: {e}")
        return location.address, raw

    def load_and_validate_image(self, img_file, filename):
        ext = Path(filename).suffix.lower()
        try:
            if ext in GeoImageSearch.HEIC_EXTENSIONS:
                if not HEIC_AVAILABLE:
                    if self.verbose:
                        print(f"Skipping HEIC file (pillow-heif not installed): {filename}")
                    return False
                pil_img = PILImage.open(img_file)
                return _PILExifAdapter(pil_img)
            return Image(img_file)
        except (OSError, IOError, MemoryError) as e:
            if self.verbose:
                print(f"Error reading {filename}. Corrupt file? {e}")
            return False
        except ValueError as e:
            if self.verbose:
                print(f"Invalid image format {filename}: {e}")
            return False

    def process_clustered_image(self, dir_path, filename, lat_deg_dec, long_deg_dec):
        if self.verbose:
            print(f"Processing {filename} at {lat_deg_dec:.6f}, {long_deg_dec:.6f}")

        # Find or create appropriate cluster
        cluster_folder = self.find_or_create_cluster(lat_deg_dec, long_deg_dec)

        source_path = os.path.join(dir_path, filename)
        destination = os.path.join(cluster_folder, filename)

        # Handle duplicate filenames
        counter = 1
        original_destination = destination
        while os.path.exists(destination):
            name, ext = os.path.splitext(original_destination)
            destination = f"{name}_{counter:03d}{ext}"
            counter += 1

        try:
            if not self.find_only:
                copyfile(source_path, destination)
                if self.verbose:
                    print(f"  -> Copied to {destination}")
            self.increment_cluster_count(cluster_folder)

            # Add to CSV data if requested
            if self.image_addresses:
                self.csv_data.append(
                    {
                        "filename": filename,
                        "path": source_path,
                        "latitude": lat_deg_dec,
                        "longitude": long_deg_dec,
                        "cluster_folder": os.path.basename(cluster_folder),
                    }
                )

            # Always add to KML results in clustering mode
            self.add_kml_result(
                filename,
                source_path,
                lat_deg_dec,
                long_deg_dec,
                0.0,  # No distance from center in clustering mode
                cluster_folder,
            )

            return True

        except (OSError, IOError) as e:
            if self.verbose:
                print(f"  -> Error copying {filename}: {e}")
            return False

    def process_standard_image(self, dir_path, filename, lat_deg_dec, long_deg_dec):
        # Collect CSV data if requested (for all images with GPS, not just matches)
        if self.image_addresses and lat_deg_dec and long_deg_dec:
            address, _ = self._reverse_geocode(lat_deg_dec, long_deg_dec)
            if address is None:
                address = "Geocoding failed"

            self.csv_data.append(
                {
                    "filename": filename,
                    "path": dir_path,
                    "latitude": lat_deg_dec,
                    "longitude": long_deg_dec,
                    "address": address,
                }
            )

        if lat_deg_dec and long_deg_dec and self.search_coords and self.radius:
            image_loc = (lat_deg_dec, long_deg_dec)
            distance_miles = distance.distance(self.search_coords, image_loc).miles
            if distance_miles < self.radius:
                source_path = os.path.join(dir_path, filename)
                if self.verbose:
                    print(
                        f"+ {filename}: {lat_deg_dec:.7n}, {long_deg_dec:.7n} ({distance_miles:.3n})"
                    )
                else:
                    if not self.printed_directory.get(dir_path, False):
                        print(f"\n{dir_path}: ")
                        self.printed_directory[dir_path] = True

                    print(f"   + {filename} {distance_miles:.2f}mi")
                if self.output_directory and not self.find_only:
                    destination = f"{self.output_directory}/{filename}"

                    # Handle duplicate filenames
                    if os.path.exists(destination):
                        base, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(f"{self.output_directory}/{base}_{counter}{ext}"):
                            counter += 1
                        destination = f"{self.output_directory}/{base}_{counter}{ext}"
                        if self.verbose:
                            print(f"   Renamed to avoid overwrite: {base}_{counter}{ext}")

                    copyfile(source_path, destination)

                # Add to KML results if KML export is enabled — store the
                # full source path so Google Earth can resolve thumbnails.
                self.add_kml_result(
                    filename, source_path, lat_deg_dec, long_deg_dec, distance_miles, ""
                )

                return True  # Indicate a match was found
            else:
                if self.verbose and self.far:
                    print(
                        "X "
                        + self.loc_format.format(
                            filename, lat_deg_dec, long_deg_dec, distance_miles
                        )
                    )
            return False

    def calc_distance(self, dir_path, filename, img_file):
        """
        Calculate the distance between an image's GPS coordinates and search coordinates.

        This method extracts GPS coordinates from an image file, calculates the distance
        to the search coordinates, and processes the image based on whether it falls
        within the specified search radius. Also supports location-based clustering.

        Args:
            dir_path (str): The directory path containing the image file
            filename (str): The name of the image file
            img_file (str): The full path to the image file

        Returns:
            bool: True if image was processed successfully, False otherwise

        Side Effects:
            - Prints image information if within radius or if verbose mode is enabled
            - Copies matching images to output directory if configured
            - Updates printed_directory tracker for directory headers
            - Handles and reports various image processing errors
            - For location sorting mode: groups images into clusters

        Notes:
            - Images without GPS coordinates are silently skipped
            - Longitude values are negated (TODO: make hemisphere configurable)
            - Distance calculations use the geopy.distance module
            - Error handling covers corrupt files, invalid formats, and memory issues
        """

        # Check date range first (before GPS processing)
        my_image = self.load_and_validate_image(img_file, filename)
        if not my_image:
            return False

        if not self.check_date_range(my_image, filename):
            return False

        lat_deg_dec, long_deg_dec = self.get_decimal_coords(my_image)

        if lat_deg_dec is None or long_deg_dec is None:
            if self.verbose:
                print(f"  -> {filename}: No GPS coordinates found")
            return False

        if self.sort_by_location:
            # Location-based sorting mode
            return self.process_clustered_image(dir_path, filename, lat_deg_dec, long_deg_dec)
        else:
            # Original distance-based logic for standard search mode
            return self.process_standard_image(dir_path, filename, lat_deg_dec, long_deg_dec)

    def export_csv_data(self):
        """Export collected image address data to CSV file."""
        if not self.image_addresses or not self.csv_data:
            if self.image_addresses and not self.csv_data:
                print("No GPS data found in images for CSV export.")
            return

        if self.output_directory == "Do Not Save":
            print("Cannot export CSV in find-only mode.")
            return

        csv_path = os.path.join(self.output_directory, "image_addresses.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = ["filename", "path", "latitude", "longitude", "address"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.csv_data)

            print(f"Exported {len(self.csv_data)} image addresses to {csv_path}")
        except (OSError, IOError) as e:
            print(f"Error writing CSV file: {e}")

    def export_kml_data(self):
        """Export matched images to KML file for Google Earth."""
        if not self.export_kml:
            return

        if not KML_AVAILABLE:
            print("Warning: KML export not available. Install 'fastkml' and 'shapely' packages.")
            return

        # Import KML-related classes only if KML_AVAILABLE is True
        try:

            # Create KML document
            assert Point is not None
            k = KML()

            # Shared camera icon style for all photo placemarks.
            camera_style = Style(
                id=CAMERA_STYLE_ID,
                styles=[IconStyle(icon_href=CAMERA_ICON_URL)],
            )

            # Create document
            doc = Document(
                id="geo_image_search_results",
                name="Geo Image Search Results",
                description="Images found within search radius",
                styles=[camera_style],
            )

            k.append(doc)

            # Create folder for search area
            for folder_name, results in self.kml_results.items():
                cluster_name = self.get_cluster_name_by_folder(folder_name)

                search_folder = Folder(
                    name=cluster_name,
                    description=f"Search center and radius ({self.radius} miles)",
                )
                doc.append(search_folder)

                # Add search center point
                if self.search_coords:
                    lookat = LookAt(
                        range=200, latitude=self.search_coords[0], longitude=self.search_coords[1]
                    )
                    center_point = Placemark(
                        name="Search Center",
                        description=f"Search center at {self.search_coords[0]:.6f}, {self.search_coords[1]:.6f}",
                        geometry=Point(self.search_coords[1], self.search_coords[0], 0),
                        view=lookat,
                    )  # lon, lat
                    search_folder.append(center_point)
                counter = 0

                for res in results:
                    counter += 1
                    description = (
                        f"<![CDATA[Found File {counter}"
                        f'<img style="max-width:500px;" src="file:///{self.get_kml_image_path(res['path'])}">]]>'
                    )
                    longi = float(res.get("longitude", 0))
                    lati = float(res.get("latitude", 0))
                    lookat = LookAt(range=50, latitude=lati, longitude=longi)
                    k_point = Placemark(
                        name=res.get("filename"),
                        description=description,
                        geometry=Point(longi, lati, 0),
                        view=lookat,
                        style_url=StyleUrl(url=f"#{CAMERA_STYLE_ID}"),
                    )
                    search_folder.append(k_point)

            # Add each matched image as a placemark

            # Write KML file
            if self.output_directory == "Do Not Save":
                kml_path = Path.cwd() / "geo_search_results.kml"
            else:
                kml_path = Path(self.output_directory) / "geo_search_results.kml"

            with open(kml_path, "w", encoding="utf-8") as f:
                f.write(k.to_string(prettyprint=True))

            self.fix_cdata_in_kml(kml_path)
            print(f"Exported {len(self.kml_results)} image locations to {kml_path}")
        except Exception as e:
            print(f"Error during KML export: {e}")

    def add_kml_result(
        self,
        filename,
        filepath,
        latitude,
        longitude,
        distance_miles,
        cluster_folder="default folder",
    ):
        """Add a matched image to KML results for export."""
        if not (self.export_kml and KML_AVAILABLE):
            if self.verbose:
                print(f"{self.export_kml=} {KML_AVAILABLE=}")
            return
        key = cluster_folder or "Found Images"

        if key not in self.kml_results:
            self.kml_results[key] = []

        self.kml_results[key].append(
            {
                "filename": filename,
                "path": filepath,
                "latitude": latitude,
                "longitude": longitude,
                "distance": distance_miles,
                "cluster_folder": cluster_folder,
            }
        )

    def get_checkpoint_path(self):
        """Get the path for the checkpoint file."""
        if self.output_directory == "Do Not Save":
            # Use a temporary directory for find-only mode
            checkpoint_dir = Path.home() / ".geo_image_search_checkpoints"
            checkpoint_dir.mkdir(exist_ok=True)
            # Create unique filename based on search parameters
            search_id = f"{abs(hash((str(self.search_coords), self.radius, str(self.root_images_directory))))}"
            return checkpoint_dir / f"checkpoint_{search_id}.pkl"
        else:
            return Path(self.output_directory) / "checkpoint.pkl"

    def save_checkpoint(self):
        """Save current progress to checkpoint file."""
        if not self.checkpoint_file:
            self.checkpoint_file = self.get_checkpoint_path()

        # Ensure checkpoint directory exists
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

        checkpoint_data = {
            "processed_files": self.processed_files_set,
            "csv_data": self.csv_data,
            "search_coords": self.search_coords,
            "radius": self.radius,
            "root_images_directory": str(self.root_images_directory),
            "timestamp": time.time(),
            "version": "1.0",  # For future compatibility
        }

        try:
            with open(self.checkpoint_file, "wb") as f:
                pickle.dump(checkpoint_data, f)
            if self.verbose:
                print(f"Checkpoint saved: {len(self.processed_files_set)} files processed")
        except (OSError, IOError) as e:
            if self.verbose:
                print(f"Warning: Could not save checkpoint: {e}")

    def load_checkpoint(self):
        """Load progress from checkpoint file."""
        if not self.checkpoint_file:
            self.checkpoint_file = self.get_checkpoint_path()

        if not self.checkpoint_file.exists():
            if self.verbose:
                print("No checkpoint file found, starting fresh")
            return False

        try:
            with open(self.checkpoint_file, "rb") as f:
                checkpoint_data = pickle.load(f)

            # Validate checkpoint compatibility
            if (
                checkpoint_data.get("search_coords") != self.search_coords
                or checkpoint_data.get("radius") != self.radius
                or checkpoint_data.get("root_images_directory") != str(self.root_images_directory)
            ):
                print("Warning: Checkpoint parameters don't match current search. Starting fresh.")
                return False

            # Restore state
            self.processed_files_set = checkpoint_data.get("processed_files", set())
            self.csv_data = checkpoint_data.get("csv_data", [])

            print(
                f"Resumed from checkpoint: {len(self.processed_files_set)} files already processed"
            )
            return True

        except (OSError, IOError, pickle.PickleError) as e:
            print(f"Warning: Could not load checkpoint file: {e}. Starting fresh.")
            return False

    def should_save_checkpoint(self, files_processed):
        """Determine if we should save a checkpoint (every 100 files or 30 seconds)."""
        current_time = time.time()
        return files_processed % 100 == 0 or current_time - self.last_checkpoint_time > 30

    def cleanup_checkpoint(self):
        """Remove checkpoint file after successful completion."""
        if self.checkpoint_file and self.checkpoint_file.exists():
            try:
                self.checkpoint_file.unlink()
                if self.verbose:
                    print("Checkpoint file cleaned up")
            except (OSError, IOError) as e:
                if self.verbose:
                    print(f"Warning: Could not remove checkpoint file: {e}")

    def get_file_identifier(self, dirpath, filename):
        """Create a unique identifier for a file to track processing."""
        return f"{dirpath}::{filename}"

    def sanitize_folder_name(self, name: str) -> str:
        """
        Convert a string into a safe folder name.

        Args:
            name: The string to sanitize

        Returns:
            A filesystem-safe folder name
        """
        if not name:
            return "Unknown_Location"

        # Remove common problematic characters and replace with underscores
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
        # Replace multiple spaces/underscores with single underscore
        safe_name = re.sub(r"[_\s]+", "_", safe_name)
        # Remove leading/trailing underscores
        safe_name = safe_name.strip("_")

        # Truncate if too long (Windows has 260 char path limit)
        if len(safe_name) > 100:
            safe_name = safe_name[:100]

        return safe_name or "Unknown_Location"

    def find_or_create_cluster(self, lat: float, lon: float) -> str:
        """
        Find an existing cluster within radius or create a new one.

        Args:
            lat: Latitude of the image
            lon: Longitude of the image

        Returns:
            Folder path for the cluster
        """
        # Cluster radius overrides the search radius for grouping; fall back
        # to search radius, then to 1.0 if neither is set.
        radius = self.cluster_radius or self.radius or 1.0

        image_coords = (lat, lon)

        # Check if this location is within radius of any existing cluster
        for cluster in self.location_clusters:
            cluster_center = cluster["center"]
            cluster_distance = distance.distance(cluster_center, image_coords).miles

            if cluster_distance <= radius:
                if self.verbose:
                    print(
                        f"  -> Adding to existing cluster: {cluster['name']} ({cluster_distance:.2f}mi from center)"
                    )
                if "coords" not in cluster:
                    cluster["coords"] = []
                cluster["coords"].append(image_coords)
                return cluster["folder_path"]

        # Create a new cluster
        coords_list = [image_coords]
        avg_lat = sum(c[0] for c in coords_list) / len(coords_list)
        avg_lon = sum(c[1] for c in coords_list) / len(coords_list)

        placename = None
        address, raw = self._reverse_geocode(avg_lat, avg_lon)
        if raw:
            addr_dict = raw.get("address", {}) if isinstance(raw, dict) else {}
            placename = (
                addr_dict.get("neighbourhood")
                or addr_dict.get("suburb")
                or addr_dict.get("city")
            )
        if not placename and address:
            placename = address.split(",")[0]

        cluster_name = placename or f"Cluster_{len(self.location_clusters) + 1}_{lat:.3f}_{lon:.3f}"
        safe_name = self.sanitize_folder_name(cluster_name)
        cluster_folder = os.path.join(self.output_directory, safe_name)

        # Only create a real directory when we'll actually copy files into it.
        # In find-only mode the cluster is a logical grouping for KML only.
        if not self.find_only and self.output_directory != "Do Not Save":
            os.makedirs(cluster_folder, exist_ok=True)

        # Add to clusters list
        new_cluster = {
            "name": cluster_name,
            "center": image_coords,
            "folder_path": cluster_folder,
            "image_count": 0,
        }
        self.location_clusters.append(new_cluster)

        if self.verbose:
            print(f"  -> Created new cluster: {cluster_name}")

        return cluster_folder

    def get_cluster_name_by_folder(self, folder_path: str) -> str:
        for cluster in self.location_clusters:
            if cluster["folder_path"] == folder_path:
                return cluster["name"]
        return os.path.basename(folder_path)

    def increment_cluster_count(self, folder_path: str):
        """
        Increments the cluster count for the specified folder.

        Args:
            folder_path (str): The path to the folder whose cluster count should be incremented.

        Returns:
            None

        Raises:
            FileNotFoundError: If the specified folder does not exist.
            Exception: If there is an error updating the cluster count.
        """

        for cluster in self.location_clusters:
            if cluster["folder_path"] == folder_path:
                cluster["image_count"] += 1
                break

    def print_cluster_summary(self):
        """
        Prints a summary of geographic image clusters, including cluster count, center coordinates,
        image counts per cluster, and total images organized. If verbose mode is enabled, also prints
        average images per cluster and separation distances between cluster centers.

        Returns:
            None

        Notes:
            - Requires self.sort_by_location to be True and self.location_clusters to be populated.
            - Uses self.radius for cluster radius and self.verbose for additional output.
            - Assumes each cluster is a dict with keys: "folder_path", "center", and "image_count".
        """

        if not self.sort_by_location or not self.location_clusters:
            return

        print("\nLocation Clustering Summary:")
        print(
            f"Created {len(self.location_clusters)} geographic clusters using {self.radius} mile radius:"
        )
        print("-" * 70)

        total_images = 0
        for i, cluster in enumerate(self.location_clusters, 1):
            folder_name = os.path.basename(cluster["folder_path"])
            center_lat, center_lon = cluster["center"]
            count = cluster["image_count"]
            total_images += count

            print(f"{i:2d}. {folder_name}")
            print(f"    Center: {center_lat:.6f}, {center_lon:.6f}")
            print(f"    Images: {count}")

        print("-" * 70)
        print(f"Total images organized: {total_images}")

        if self.verbose:
            print(f"Average images per cluster: {total_images/len(self.location_clusters):.1f}")

            # Show cluster distances
            if len(self.location_clusters) > 1:
                print("\nCluster separation distances:")
                for i, cluster1 in enumerate(self.location_clusters):
                    for j, cluster2 in enumerate(self.location_clusters[i + 1 :], i + 1):
                        dist = distance.distance(cluster1["center"], cluster2["center"]).miles
                        name1 = os.path.basename(cluster1["folder_path"])
                        name2 = os.path.basename(cluster2["folder_path"])
                        print(f"  {name1} <-> {name2}: {dist:.2f} miles")


def main(argv=None, cancel_event=None):
    """
    Run the geo image search. Used by both the CLI and the GUI.

    Args:
        argv: argument list (excluding program name); defaults to sys.argv[1:].
        cancel_event: optional threading.Event. When set, the file walk exits
                      cleanly after saving a checkpoint — used by the GUI's
                      Cancel button.
    """
    files_processed = 0
    gis = GeoImageSearch(argv=argv)
    gis.cancel_event = cancel_event

    def signal_handler(signum, frame):  # noqa: ARG001
        """SIGINT handler: save checkpoint and exit cleanly."""
        print(f"\nInterrupted by user. Processed {files_processed} files so far.")
        print("Saving checkpoint for resume...")
        gis.save_checkpoint()
        if gis.image_addresses and gis.csv_data:
            print("Saving partial CSV data...")
            gis.export_csv_data()
        print("Use --resume flag to continue from where you left off.")
        sys.exit(1)

    # signal.signal() only works from the main thread; from a GUI worker thread
    # we rely on cancel_event instead.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, signal_handler)

    print(f"1. {hasattr(gis, 'search_coords')=}")

    gis.startup()

    print(f"2. {hasattr(gis, 'search_coords')=}")

    print(f"Scanning directory: {gis.root_images_directory}")
    print(f"Search center: {gis.search_coords}")
    print(f"Search radius: {gis.radius} miles")
    print("-" * 50)

    images_found = 0
    start_time = time.time()
    cancelled = False

    for dirpath, dirnames, filenames in os.walk(str(gis.root_images_directory)):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        # Skip the output directory to avoid processing copied images
        if gis.output_directory != "Do Not Save":
            try:
                if Path(dirpath).is_relative_to(Path(gis.output_directory)):
                    if gis.verbose:
                        print(f"Skipping output directory: {dirpath}")
                    continue
            except ValueError:
                # is_relative_to can fail if paths are on different drives
                pass

        if gis.verbose:
            print(f"Scanning: {dirpath}")
        else:
            print(".", end="", flush=True)
            if files_processed % 100 == 0 and files_processed > 0:
                print(f" [{files_processed} processed]", flush=True)

        for file_name in filenames:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if gis.is_supported_image_file(file_name):
                # Check if this file was already processed (for resume functionality)
                file_id = gis.get_file_identifier(dirpath, file_name)
                if file_id in gis.processed_files_set:
                    if gis.verbose:
                        print(f"Skipping already processed file: {file_name}")
                    continue

                files_processed += 1

                imagename = os.path.join(dirpath, file_name)
                try:
                    with open(imagename, "rb") as image_file:
                        if gis.calc_distance(dirpath, file_name, image_file):
                            images_found += 1

                    # Mark file as processed
                    gis.processed_files_set.add(file_id)

                    # Save checkpoint periodically
                    if gis.should_save_checkpoint(files_processed):
                        gis.save_checkpoint()
                        gis.last_checkpoint_time = time.time()

                except PermissionError:
                    if gis.verbose:
                        print(f"Permission denied: {imagename}")
                except (OSError, IOError) as e:
                    if gis.verbose:
                        print(f"Error processing {imagename}: {e}")
                finally:
                    # Always mark as processed even if there was an error
                    gis.processed_files_set.add(file_id)

        if cancelled:
            break

    end_time = time.time()
    elapsed_time = end_time - start_time

    if cancelled:
        print(f"\nCancelled by user. Processed {files_processed} files so far.")
        print("Saving checkpoint for resume...")
        gis.save_checkpoint()
        if gis.image_addresses and gis.csv_data:
            print("Saving partial CSV data...")
            gis.export_csv_data()
        print("Use --resume flag to continue from where you left off.")
        return

    print(f"\nProcessed {files_processed} image files in {elapsed_time:.1f} seconds")

    if gis.sort_by_location:
        # Print cluster summary instead of standard search results
        gis.print_cluster_summary()
    else:
        print(f"Found {images_found} images within {gis.radius} miles of search location")

    if files_processed > 0:
        print(f"Processing rate: {files_processed/elapsed_time:.1f} files/second")
        if not gis.sort_by_location:
            print(f"Match rate: {(images_found/files_processed)*100:.1f}% of processed files")

    if files_processed == 0:
        print("No JPEG files found in the specified directory.")
    elif images_found == 0:
        print("No images found within the search radius. Try increasing the radius with -r")

    # Export CSV data if requested
    if gis.image_addresses:
        gis.export_csv_data()

    # Export KML data if requested
    if gis.export_kml:
        gis.export_kml_data()

    # Clean up checkpoint file on successful completion
    gis.cleanup_checkpoint()


if __name__ == "__main__":
    main()
