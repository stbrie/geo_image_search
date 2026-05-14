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
import re
import signal
import sqlite3
import sys
import threading
import time
import tomllib
from datetime import datetime, timezone
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

# argparse default for --radius. Sentinel for "user did not supply" is None;
# we apply this value at attribute-assignment time if nothing overrode it.
DEFAULT_RADIUS_MILES = 0.05


class StartupError(Exception):
    """Raised when GeoImageSearch can't start: bad config, missing paths,
    location lookup failed, mutually-exclusive flags, etc. `main()` catches
    this and reports a clean error instead of a stack trace."""


def _next_unique_path(destination, *, padding: int = 3) -> Path:
    """Return `destination` if it doesn't exist, else append `_NNN` (zero-
    padded) before the extension. Tries 1..999, then falls back to a unix
    timestamp so the returned path is always free."""
    dest = Path(destination)
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem}_{i:0{padding}d}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}_{int(time.time())}{suffix}"


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


class _Mp4MetadataAdapter:
    """Expose MP4/MOV/M4V metadata via the same attribute names the `exif`
    library uses, so the existing GPS-extraction and date-range pipeline can
    consume videos without changes.

    Reads the QuickTime/ISO BMFF atom tree:
      - moov/udta/(c)xyz  -> ISO 6709 location string set by iPhone/Android
      - moov/mvhd          -> creation_time (seconds since 1904-01-01 UTC)

    GPS is exposed as a fake DMS tuple of (decimal_degrees, 0, 0) plus an
    N/S/E/W ref, so convert_dhms_to_decimal() reconstructs the original
    decimal value. Modern iOS also writes location to moov/meta/keys+ilst;
    we don't parse that yet because (c)xyz is still written alongside it.
    """

    _MAC_EPOCH_OFFSET = 2082844800  # seconds between 1904-01-01 and 1970-01-01

    def __init__(self, file_obj):
        file_obj.seek(0, 2)
        file_size = file_obj.tell()
        file_obj.seek(0)

        gps_payload = self._find_atom_path(
            file_obj, file_size, [b"moov", b"udta", b"\xa9xyz"]
        )
        if gps_payload:
            lat, lon = self._parse_iso6709(gps_payload)
            if lat is not None and lon is not None:
                self.gps_latitude = (abs(lat), 0.0, 0.0)
                self.gps_latitude_ref = "N" if lat >= 0 else "S"
                self.gps_longitude = (abs(lon), 0.0, 0.0)
                self.gps_longitude_ref = "E" if lon >= 0 else "W"

        mvhd_payload = self._find_atom_path(file_obj, file_size, [b"moov", b"mvhd"])
        if mvhd_payload:
            dt_str = self._parse_mvhd_creation_time(mvhd_payload)
            if dt_str:
                self.datetime_original = dt_str

    @staticmethod
    def _read_atom_header(f, end_offset):
        """Return (type_bytes, payload_offset, atom_end_offset) for the atom at
        the current file position, or None on EOF / malformed header."""
        atom_start = f.tell()
        if atom_start + 8 > end_offset:
            return None
        size_bytes = f.read(4)
        type_bytes = f.read(4)
        if len(size_bytes) < 4 or len(type_bytes) < 4:
            return None
        size = int.from_bytes(size_bytes, "big")
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return None
            size = int.from_bytes(ext, "big")
        elif size == 0:
            size = end_offset - atom_start
        if size < 8 or atom_start + size > end_offset:
            return None
        return type_bytes, f.tell(), atom_start + size

    @classmethod
    def _find_atom_in_range(cls, f, end_offset, target):
        while f.tell() < end_offset:
            hdr = cls._read_atom_header(f, end_offset)
            if hdr is None:
                return None
            atype, payload_start, atom_end = hdr
            if atype == target:
                return payload_start, atom_end
            f.seek(atom_end)
        return None

    @classmethod
    def _find_atom_path(cls, f, file_size, path):
        """Walk nested atoms, returning the bytes of the deepest atom's payload."""
        f.seek(0)
        end = file_size
        payload_start = atom_end = 0
        for atom_type in path:
            found = cls._find_atom_in_range(f, end, atom_type)
            if found is None:
                return None
            payload_start, atom_end = found
            f.seek(payload_start)
            end = atom_end
        return f.read(atom_end - payload_start)

    @staticmethod
    def _parse_iso6709(payload):
        # (c)xyz is a QuickTime string atom: 2-byte length + 2-byte language code,
        # then the ISO 6709 string ("+37.7749-122.4194/" or with altitude).
        if len(payload) < 4:
            return None, None
        s = payload[4:].decode("latin-1", errors="replace").rstrip("\x00").rstrip("/")
        m = re.match(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s)
        if not m:
            return None, None
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            return None, None

    @classmethod
    def _parse_mvhd_creation_time(cls, payload):
        if len(payload) < 4:
            return None
        version = payload[0]
        if version == 1:
            if len(payload) < 12:
                return None
            ct = int.from_bytes(payload[4:12], "big")
        else:
            if len(payload) < 8:
                return None
            ct = int.from_bytes(payload[4:8], "big")
        if ct == 0:
            return None
        unix_ts = ct - cls._MAC_EPOCH_OFFSET
        if unix_ts < 0:
            return None
        try:
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime(
                "%Y:%m:%d %H:%M:%S"
            )
        except (ValueError, OverflowError, OSError):
            return None


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
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
    SUPPORTED_EXTENSIONS = JPEG_EXTENSIONS | HEIC_EXTENSIONS | VIDEO_EXTENSIONS

    def load_config_file(self, config_path: str | Path | None = None) -> dict:
        """
        Load configuration from TOML file.

        If `config_path` is explicitly provided and does not exist (or fails to
        parse), this raises StartupError — silent fallthrough to the standard
        locations would surprise users who passed `--config`. If `config_path`
        is None, fall back to the standard search order:
          1. geo_image_search.toml in current directory
          2. ~/.config/geo_image_search/config.toml
          3. ~/.geo_image_search.toml
        """
        if config_path:
            explicit = Path(config_path)
            if not explicit.exists():
                raise StartupError(
                    f"Config file not found: {explicit}"
                )
            try:
                with open(explicit, "rb") as f:
                    config_data = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError) as e:
                raise StartupError(f"Could not load config file {explicit}: {e}") from e
            if self.verbose:
                print(f"Loaded configuration from: {explicit}")
            self.config_file = explicit
            return config_data

        for config_file in (
            Path.cwd() / "geo_image_search.toml",
            Path.home() / ".config" / "geo_image_search" / "config.toml",
            Path.home() / ".geo_image_search.toml",
        ):
            if not config_file.exists():
                continue
            try:
                with open(config_file, "rb") as f:
                    config_data = tomllib.load(f)
            except OSError as e:
                print(f"Warning: Could not load config file {config_file}: {e}")
                continue
            except tomllib.TOMLDecodeError as e:
                print(f"Warning: Could not parse config file {config_file}: {e}")
                continue
            if self.verbose:
                print(f"Loaded configuration from: {config_file}")
            self.config_file = config_file
            return config_data

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
overwrite = false                # Overwrite existing files instead of auto-renaming
single_location = false          # Treat search as a single address; nest output under country/state/city/...

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

    # (section, key, args_attr). Order matches how the keys appear in the
    # sample TOML; new flags add one line each. "Unset" means args.<attr> is
    # None (for strings/numbers) or False (for booleans) — since argparse
    # defaults are None for all string/number args and False for store_true,
    # we can use one rule for everything.
    _CONFIG_MAP: tuple[tuple[str, str, str], ...] = (
        ("search", "address", "address"),
        ("search", "latitude", "latitude"),
        ("search", "longitude", "longitude"),
        ("search", "radius", "radius"),
        ("search", "cluster_radius", "cluster_radius"),
        ("search", "far", "far"),
        ("directories", "root", "root"),
        ("directories", "output_directory", "output_directory"),
        ("directories", "find_only", "find_only"),
        ("directories", "sort_by_location", "sort_by_location"),
        ("directories", "overwrite", "overwrite"),
        ("directories", "single_location", "single_location"),
        ("output", "save_addresses", "save_addresses"),
        ("output", "export_kml", "export_kml"),
        ("output", "verbose", "verbose"),
        ("filters", "date_from", "date_from"),
        ("filters", "date_to", "date_to"),
        ("processing", "resume", "resume"),
    )

    def merge_config_with_args(self, config_data: dict, args: argparse.Namespace) -> None:
        """Fill in unset args from config_data. CLI values take precedence:
        we only overwrite when the arg is None (unset string/number) or False
        (unset store_true flag)."""
        for section, key, attr in self._CONFIG_MAP:
            section_data = config_data.get(section, {})
            if key not in section_data:
                continue
            current = getattr(args, attr, None)
            if current in (None, False):
                setattr(args, attr, section_data[key])

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        """Build the CLI argument parser. No side effects."""
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
        parser.add_argument("-o", "--output_directory", action="store",
                            help="<output directory> to copy images to (optional)")
        parser.add_argument("-f", "--find_only", action="store_true",
                            help="(optional) if set, do not copy files or save data.")
        parser.add_argument("-a", "--address", action="store",
                            help="(optional) <address> address to match to images")
        parser.add_argument("-i", "--save_addresses", action="store_true",
                            help="Save ALL image addresses to CSV file in output directory (requires -o)")
        parser.add_argument("-v", "--verbose", action="store_true",
                            help="print additional information")
        parser.add_argument("-d", "--root", action="store",
                            help="(required) the <root directory> of where to begin searching for images")
        parser.add_argument("-t", "--latitude", type=float,
                            help="(optional) if set, use the decimal latitude to center the search.")
        parser.add_argument("-g", "--longitude", type=float,
                            help="(optional) if set, use this decimal longitude to center the search.")
        parser.add_argument(
            "-r", "--radius", type=float, default=None,
            help=f"(optional, defaults to {DEFAULT_RADIUS_MILES}) the radius of the search in miles.",
        )
        parser.add_argument("--cluster-radius", type=float,
                            help="(optional) Radius in YARDS used for grouping when --sort-by-location is set. "
                                 "Defaults to --radius (which is in miles).")
        parser.add_argument("-x", "--far", action="store_true",
                            help="(optional) show images that are further than radius from centerpoint")
        parser.add_argument("--resume", action="store_true",
                            help="Resume from a previous interrupted search (uses checkpoint file)")
        parser.add_argument("--export-kml", action="store_true",
                            help="Export matched images as KML file for Google Earth")
        parser.add_argument("--date-from", type=str,
                            help="Filter images from this date (YYYY-MM-DD format)")
        parser.add_argument("--date-to", type=str,
                            help="Filter images to this date (YYYY-MM-DD format)")
        parser.add_argument("--config", type=str,
                            help="Path to TOML configuration file (optional)")
        parser.add_argument("--create-config", type=str, nargs="?", const="geo_image_search.toml",
                            help="Create a sample configuration file and exit (optionally specify path)")
        parser.add_argument("--sort-by-location", action="store_true",
                            help="Group images into geographic clusters (uses --cluster-radius if set, "
                                 "else --radius). Disk folders only when copying; KML always grouped.")
        parser.add_argument("--overwrite", action="store_true",
                            help="Overwrite files in the output directory instead of auto-renaming "
                                 "duplicates with a numeric suffix.")
        parser.add_argument("--single-location", action="store_true",
                            help="Treat the search as a single location rather than discovering clusters. "
                                 "Requires --address or --latitude/--longitude. All in-radius matches go "
                                 "into one nested folder built from the structured address "
                                 "(country/state/city/postcode/road/number). Mutually exclusive with "
                                 "--sort-by-location.")
        return parser

    def _validate_args(self, args: argparse.Namespace) -> None:
        """Raise StartupError for any invalid CLI/config combination."""
        if not args.root:
            raise StartupError("Missing required argument: -d/--root")

        if args.save_addresses and not args.output_directory:
            raise StartupError("--save_addresses requires --output_directory to be specified")

        if args.sort_by_location and args.single_location:
            raise StartupError("--single-location and --sort-by-location are mutually exclusive")

        if args.sort_by_location and not args.find_only and not args.output_directory:
            raise StartupError("--sort-by-location requires --output_directory when copying files")

        if args.single_location:
            if not args.address and (args.latitude is None or args.longitude is None):
                raise StartupError("--single-location requires --address or --latitude/--longitude")
            if not args.find_only and not args.output_directory:
                raise StartupError("--single-location requires --output_directory when copying files")

    def _parse_date(self, value: str | None, flag: str) -> "datetime.date | None":
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise StartupError(f"Invalid date format for {flag}: {value}. Use YYYY-MM-DD") from None

    def _assign_attrs(self, args: argparse.Namespace) -> None:
        """Copy parsed args onto self, applying defaults and unit conversions."""
        self.address = args.address
        self.user_output_directory = args.output_directory
        self.find_only = args.find_only
        self.image_addresses = args.save_addresses
        self.verbose = args.verbose
        self.root_images_directory = args.root
        self.lat = args.latitude
        self.lon = args.longitude
        self.radius = args.radius if args.radius is not None else DEFAULT_RADIUS_MILES
        # cluster_radius is entered in YARDS; store as miles so it's directly
        # comparable to geopy's distance.miles in find_or_create_cluster.
        self.cluster_radius = (
            args.cluster_radius / 1760.0 if args.cluster_radius is not None else None
        )
        self.far = args.far
        self.resume = args.resume
        self.sort_by_location = args.sort_by_location
        self.export_kml = args.export_kml
        self.overwrite = args.overwrite
        self.single_location = args.single_location
        self.date_from = self._parse_date(args.date_from, "--date-from")
        self.date_to = self._parse_date(args.date_to, "--date-to")

    def get_opts(self) -> None:
        """Parse argv, merge with TOML config, validate, and assign onto self.

        Raises StartupError on any invalid input. The --create-config flag
        short-circuits the entire pipeline with sys.exit(0) after writing the
        sample file (intended user-facing behavior).
        """
        parser = self._build_parser()
        args = parser.parse_args(self.argv)

        if args.create_config:
            self.create_sample_config(args.create_config)
            sys.exit(0)

        self.config_data = self.load_config_file(args.config)
        if self.config_data:
            self.merge_config_with_args(self.config_data, args)

        self._validate_args(args)
        self._assign_attrs(args)

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
            if self.sort_by_location:
                print("Location-based sorting enabled: grouping images by geographic clusters")
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
        """Normalize and validate `self.root_images_directory`. Raises
        StartupError if unset or pointing at a non-existent path."""
        if not self.root_images_directory:
            raise StartupError(
                "No images root directory specified. -d/--root is not optional."
            )

        self.root_images_directory = self.normalize_path(self.root_images_directory)

        if not os.path.exists(self.root_images_directory):
            raise StartupError(
                f"Root directory does not exist: {self.root_images_directory}"
            )

    def fix_cdata_in_kml(self, kml_path):
        with open(kml_path, "r", encoding="utf-8") as f:
            kml_content = f.read()
        kml_content = kml_content.replace("&lt;", "<").replace("&gt;", ">")
        with open(kml_path, "w", encoding="utf-8") as f:
            f.write(kml_content)

    def set_output_directory(self):
        """Pick the effective output directory.

        - If the user supplied --output_directory, normalize it and use it
          verbatim (also used for CSV/KML even in find-only mode).
        - In find-only mode without an output dir, set the sentinel
          "Do Not Save" to signal "no file operations".
        - Otherwise raise StartupError: we need one or the other.
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
            raise StartupError(
                "No output directory specified and not find-only. Use one or the other."
            )

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
        self.overwrite = False
        self.single_location = False
        # When single_location is active, these hold the structured pieces of
        # the chosen center so find_or_create_cluster can build a nested path
        # and a readable display name without redoing the Nominatim lookup.
        self._single_location_path_parts: list[str] | None = None
        self._single_location_display: str | None = None
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

        has_center = bool(self.address) or (self.lat is not None and self.lon is not None)

        if has_center:
            if self.address:
                try:
                    self.location = self.geolocator.geocode(query=self.address)
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    raise StartupError(f"Geocoding failed: {e}") from e
            else:
                try:
                    self.location = self.geolocator.reverse(
                        query=f"{self.lat}, {self.lon}"
                    )
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    raise StartupError(
                        f"Latitude/longitude did not return a valid location: {e}"
                    ) from e

            if self.location:
                self.search_coords = (self.location.latitude, self.location.longitude)
                print(f"Nominatim address: {self.location.address}")
                print(f"Lat, Lon: {self.location.latitude}, {self.location.longitude}")
                if self.sort_by_location:
                    cluster_yards = (self.cluster_radius or self.radius) * 1760.0
                    print(
                        f"Sort-by-location + center: keeping images within "
                        f"{self.radius} mi of center, then clustering by "
                        f"{cluster_yards:.0f} yd."
                    )
                if self.single_location:
                    # Reverse-geocode (uses the SQLite cache) so we get a
                    # structured address regardless of whether the user gave
                    # us an address string or raw coordinates.
                    _, raw = self._reverse_geocode(
                        self.search_coords[0], self.search_coords[1]
                    )
                    self._single_location_path_parts = (
                        self._build_single_location_path_parts(raw)
                    )
                    fallback = self.address or f"{self.search_coords[0]:.5f}_{self.search_coords[1]:.5f}"
                    self._single_location_display = (
                        self._build_single_location_display(raw, fallback)
                    )
                    nested = "/".join(self._single_location_path_parts or [])
                    print(
                        f"Single-location mode: in-radius matches go under "
                        f"{nested or self._single_location_display}"
                    )
            else:
                raise StartupError("No location returned from Nominatim.")
        elif self.sort_by_location:
            print("Location-based sorting mode: grouping all images by geographic clusters")
            if self.verbose:
                cluster_radius_miles = self.cluster_radius or self.radius
                print(f"Using cluster radius of {cluster_radius_miles} miles for grouping")
        else:
            raise StartupError("No address or coordinates provided for search center.")

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

        except (AttributeError, TypeError, ValueError) as e:
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
            if ext in GeoImageSearch.VIDEO_EXTENSIONS:
                return _Mp4MetadataAdapter(img_file)
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

        if not self.overwrite:
            destination = str(_next_unique_path(destination))

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
                        "address": "",
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
                    "cluster_folder": "",
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
                    destination = os.path.join(self.output_directory, filename)
                    if not self.overwrite:
                        unique = _next_unique_path(destination)
                        if str(unique) != destination and self.verbose:
                            print(f"   Renamed to avoid overwrite: {unique.name}")
                        destination = str(unique)

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

        if self.sort_by_location or self.single_location:
            # Honor --radius before clustering/collecting. (Standard mode
            # applies the same check inside process_standard_image.)
            if self.search_coords and self.radius:
                distance_miles = distance.distance(
                    self.search_coords, (lat_deg_dec, long_deg_dec)
                ).miles
                if distance_miles >= self.radius:
                    if self.verbose:
                        print(
                            f"  -> {filename}: {distance_miles:.2f}mi from center, "
                            f"outside {self.radius}mi radius"
                        )
                    return False
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

        csv_path = Path(self.output_directory) / "image_addresses.csv"
        tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
        fieldnames = [
            "filename",
            "path",
            "latitude",
            "longitude",
            "address",
            "cluster_folder",
        ]
        # Phase 1: build the temp file. If this fails, the data is suspect
        # and we don't want to save it under any name.
        try:
            with open(tmp_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.csv_data)
        except (OSError, IOError, ValueError) as e:
            print(f"Error writing CSV file: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return

        # Phase 2: swap into place. If the canonical name is locked, save
        # to image_addresses_NNN.csv beside it so the run's data isn't lost.
        try:
            self._atomic_replace_with_retry(tmp_path, csv_path)
            print(f"Exported {len(self.csv_data)} image addresses to {csv_path}")
            return
        except PermissionError as e:
            fallback = self._next_fallback_csv_path(csv_path)
            try:
                tmp_path.replace(fallback)
                print(
                    f"{csv_path.name} appears to be locked "
                    f"(open in Excel, or being synced by OneDrive/Dropbox?). "
                    f"Saved {len(self.csv_data)} rows to {fallback} instead. "
                    f"Underlying error: {e}"
                )
                return
            except OSError as e2:
                print(
                    f"Error writing CSV file: both {csv_path.name} and "
                    f"{fallback.name} failed ({e2})."
                )
        except OSError as e:
            print(f"Error replacing CSV file: {e}")

        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _next_fallback_csv_path(canonical: Path) -> Path:
        """Find image_addresses_NNN.csv beside `canonical`. Returned path is
        guaranteed not to exist; caller has already determined `canonical`
        itself is unusable (locked or otherwise)."""
        # _next_unique_path checks whether `canonical` itself is free; here we
        # know it's effectively taken, so seed with a name we know exists.
        if not canonical.exists():
            return canonical
        return _next_unique_path(canonical)

    @staticmethod
    def _atomic_replace_with_retry(
        tmp_path: Path, dest_path: Path, attempts: int = 3, backoff_s: float = 0.2
    ) -> None:
        """os.replace, but tolerate brief Windows file locks (OneDrive, AV
        scanners, an Explorer thumbnailer) by retrying a few times before
        giving up. Raises the last PermissionError on final failure."""
        last_exc: PermissionError | None = None
        for i in range(attempts):
            try:
                tmp_path.replace(dest_path)
                return
            except PermissionError as e:
                last_exc = e
                if i < attempts - 1:
                    time.sleep(backoff_s)
        assert last_exc is not None
        raise last_exc

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

            # Cache of intermediate KML Folders keyed by their full path tuple,
            # so siblings sharing ancestors (e.g. two clusters in the same
            # city) reuse one parent chain instead of duplicating it.
            folder_cache: dict[tuple[str, ...], Folder] = {}

            def parent_folder_for(parent_parts: tuple[str, ...]) -> Folder:
                if not parent_parts:
                    return doc
                if parent_parts in folder_cache:
                    return folder_cache[parent_parts]
                parent = parent_folder_for(parent_parts[:-1])
                new_folder = Folder(name=parent_parts[-1])
                parent.append(new_folder)
                folder_cache[parent_parts] = new_folder
                return new_folder

            # Create folder for search area
            for folder_name, results in self.kml_results.items():
                cluster_name = self.get_cluster_name_by_folder(folder_name)
                parts = self.get_cluster_path_parts_by_folder(folder_name)

                if parts and len(parts) > 1:
                    parent_folder = parent_folder_for(tuple(parts[:-1]))
                else:
                    parent_folder = doc

                search_folder = Folder(
                    name=cluster_name,
                    description=f"Search center and radius ({self.radius} miles)",
                )
                parent_folder.append(search_folder)

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
                    media_path = self.get_kml_image_path(res["path"])
                    if Path(res["path"]).suffix.lower() in GeoImageSearch.VIDEO_EXTENSIONS:
                        media_html = f'<a href="file:///{media_path}">Open video</a>'
                    else:
                        media_html = f'<img style="max-width:500px;" src="file:///{media_path}">'
                    description = f"<![CDATA[Found File {counter}{media_html}]]>"
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
        except (OSError, ValueError, TypeError, AttributeError) as e:
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
        """Path for the checkpoint file. Stored as JSON to avoid pickle's
        arbitrary-code-execution risk on load."""
        if self.output_directory == "Do Not Save":
            checkpoint_dir = Path.home() / ".geo_image_search_checkpoints"
            checkpoint_dir.mkdir(exist_ok=True)
            search_id = f"{abs(hash((str(self.search_coords), self.radius, str(self.root_images_directory))))}"
            return checkpoint_dir / f"checkpoint_{search_id}.json"
        else:
            return Path(self.output_directory) / "checkpoint.json"

    def save_checkpoint(self):
        """Save current progress to checkpoint file."""
        if not self.checkpoint_file:
            self.checkpoint_file = self.get_checkpoint_path()

        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

        checkpoint_data = {
            # set -> list for JSON; restored back to set on load.
            "processed_files": sorted(self.processed_files_set),
            "csv_data": self.csv_data,
            # tuple -> list for JSON; restored to tuple on load for == comparison.
            "search_coords": list(self.search_coords) if self.search_coords else None,
            "radius": self.radius,
            "root_images_directory": str(self.root_images_directory),
            "timestamp": time.time(),
            "version": "2",
        }

        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f)
            if self.verbose:
                print(f"Checkpoint saved: {len(self.processed_files_set)} files processed")
        except (OSError, TypeError) as e:
            if self.verbose:
                print(f"Warning: Could not save checkpoint: {e}")

    def load_checkpoint(self):
        """Load progress from checkpoint file. Returns True on successful
        resume; False (and starts fresh) if the file is missing, malformed,
        or its search parameters don't match the current run."""
        if not self.checkpoint_file:
            self.checkpoint_file = self.get_checkpoint_path()

        if not self.checkpoint_file.exists():
            if self.verbose:
                print("No checkpoint file found, starting fresh")
            return False

        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load checkpoint file: {e}. Starting fresh.")
            return False

        try:
            saved_coords = checkpoint_data.get("search_coords")
            saved_coords_tuple = tuple(saved_coords) if saved_coords else None
            if (
                saved_coords_tuple != self.search_coords
                or checkpoint_data.get("radius") != self.radius
                or checkpoint_data.get("root_images_directory") != str(self.root_images_directory)
            ):
                print("Warning: Checkpoint parameters don't match current search. Starting fresh.")
                return False

            self.processed_files_set = set(checkpoint_data.get("processed_files", []))
            self.csv_data = checkpoint_data.get("csv_data", [])

            print(
                f"Resumed from checkpoint: {len(self.processed_files_set)} files already processed"
            )
            return True
        except (TypeError, ValueError) as e:
            print(f"Warning: Malformed checkpoint file: {e}. Starting fresh.")
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

    @staticmethod
    def _nominatim_address_dict(raw):
        """Return the inner address-fields dict from a Nominatim raw response."""
        if not isinstance(raw, dict):
            return {}
        addr = raw.get("address")
        return addr if isinstance(addr, dict) else {}

    @classmethod
    def _build_single_location_path_parts(cls, raw):
        """Build the nested path components for single-location output, ordered
        country / state / city / postcode / road / house_number. Missing
        fields are skipped. Returns None if nothing usable was found."""
        addr = cls._nominatim_address_dict(raw)
        if not addr:
            return None

        parts: list[str] = []

        cc = addr.get("country_code")
        if cc:
            parts.append(str(cc).upper())

        # ISO3166-2-lvl4 gives a uniform subdivision code (e.g. "US-MD",
        # "GB-LND"); fall back to the spelled-out state/region.
        state_iso = addr.get("ISO3166-2-lvl4") or ""
        if "-" in state_iso:
            parts.append(state_iso.split("-", 1)[1])
        elif addr.get("state"):
            parts.append(addr["state"])

        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("hamlet")
            or addr.get("suburb")
        )
        if city:
            parts.append(city)

        if addr.get("postcode"):
            parts.append(addr["postcode"])

        if addr.get("road"):
            parts.append(addr["road"])

        if addr.get("house_number"):
            parts.append(addr["house_number"])

        return parts or None

    @classmethod
    def _flatten_path_parts_to_folder_name(cls, parts) -> str:
        """Join structured address parts into one flat folder-name segment.
        Each part is normalized (illegal chars and whitespace -> underscore),
        then joined with `_`. Allow up to 200 chars (vs sanitize_folder_name's
        100) because a full address legitimately runs longer than a city
        name."""
        if not parts:
            return "Unknown_Location"
        cleaned = [str(p).strip() for p in parts if p]
        if not cleaned:
            return "Unknown_Location"
        joined = "_".join(cleaned)
        safe = re.sub(r'[<>:"/\\|?*]', "_", joined)
        safe = re.sub(r"[_\s]+", "_", safe).strip("_")
        if len(safe) > 200:
            safe = safe[:200]
        return safe or "Unknown_Location"

    @classmethod
    def _build_single_location_display(cls, raw, fallback):
        """Human-readable one-line address for KML / verbose output. Falls
        back to the supplied string when Nominatim couldn't be parsed."""
        addr = cls._nominatim_address_dict(raw)
        if not addr:
            return fallback

        street = None
        if addr.get("house_number") and addr.get("road"):
            street = f"{addr['house_number']} {addr['road']}"
        elif addr.get("road"):
            street = addr["road"]

        city = addr.get("city") or addr.get("town") or addr.get("village")
        state_iso = addr.get("ISO3166-2-lvl4") or ""
        state_code = state_iso.split("-", 1)[1] if "-" in state_iso else None
        locale = ", ".join(p for p in (city, state_code, addr.get("postcode")) if p)

        line = ", ".join(p for p in (street, locale) if p)
        return line or fallback

    def find_or_create_cluster(self, lat: float, lon: float) -> str:
        """
        Find an existing cluster within radius or create a new one.

        Args:
            lat: Latitude of the image
            lon: Longitude of the image

        Returns:
            Folder path for the cluster
        """
        image_coords = (lat, lon)

        # Single-location mode: one fixed cluster, name & path derived from
        # the search center's structured address. All matches collapse here.
        if self.single_location:
            if self.location_clusters:
                return self.location_clusters[0]["folder_path"]

            parts = self._single_location_path_parts or []
            flat_name = (
                self._flatten_path_parts_to_folder_name(parts) if parts else "Single_Location"
            )
            cluster_folder = os.path.join(self.output_directory, flat_name)

            if not self.find_only and self.output_directory != "Do Not Save":
                os.makedirs(cluster_folder, exist_ok=True)

            name = self._single_location_display or flat_name
            self.location_clusters.append(
                {
                    "name": name,
                    "center": self.search_coords or image_coords,
                    "folder_path": cluster_folder,
                    "image_count": 0,
                    "path_parts": parts or None,
                }
            )
            if self.verbose:
                print(f"  -> Single-location target: {name}")
            return cluster_folder

        # Cluster radius overrides the search radius for grouping; fall back
        # to search radius, then to 1.0 if neither is set.
        radius = self.cluster_radius or self.radius or 1.0

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

        address, raw = self._reverse_geocode(avg_lat, avg_lon)
        parts = self._build_single_location_path_parts(raw) if raw else None

        if parts:
            safe_name = self._flatten_path_parts_to_folder_name(parts)
            fallback_display = address.split(",")[0] if address else safe_name
            cluster_name = self._build_single_location_display(raw, fallback_display)
        else:
            # Reverse geocode returned nothing useful — fall back to the old
            # placename heuristic so we still get a meaningful folder.
            addr_dict = self._nominatim_address_dict(raw)
            placename = (
                addr_dict.get("neighbourhood")
                or addr_dict.get("suburb")
                or addr_dict.get("city")
            )
            if not placename and address:
                placename = address.split(",")[0]
            cluster_name = (
                placename
                or f"Cluster_{len(self.location_clusters) + 1}_{lat:.3f}_{lon:.3f}"
            )
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
            "path_parts": parts,
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

    def get_cluster_path_parts_by_folder(self, folder_path: str):
        """Return the structured address parts stored on a cluster, or None
        when the cluster lacks them (e.g., reverse-geocode failed)."""
        for cluster in self.location_clusters:
            if cluster["folder_path"] == folder_path:
                return cluster.get("path_parts")
        return None

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

        if (not self.sort_by_location and not self.single_location) or not self.location_clusters:
            return

        if self.single_location:
            print("\nSingle-Location Summary:")
            print(
                f"All matched images placed in one folder ({self.radius} mile radius):"
            )
        else:
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

    try:
        gis.startup()
    except StartupError as e:
        print(f"Error: {e}")
        sys.exit(2)

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

    if gis.sort_by_location or gis.single_location:
        # Print cluster summary instead of standard search results
        gis.print_cluster_summary()
    else:
        print(f"Found {images_found} images within {gis.radius} miles of search location")

    if files_processed > 0:
        print(f"Processing rate: {files_processed/elapsed_time:.1f} files/second")
        if not gis.sort_by_location and not gis.single_location:
            print(f"Match rate: {(images_found/files_processed)*100:.1f}% of processed files")

    if files_processed == 0:
        print("No supported image or video files found in the specified directory.")
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
