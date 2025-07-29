"""Configuration management for the geo image search application."""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from .constants import Constants
from .exceptions import ConfigurationError, FileOperationError
from .types import (
    SearchConfig, DirectoryConfig, OutputConfig, FilterConfig, 
    ProcessingConfig, FolderKMLConfig
)
from .utils import PathNormalizer, DateParser


class ConfigurationManager:
    """Handles all configuration loading and argument parsing."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.path_normalizer = PathNormalizer()
        self.date_parser = DateParser()
        
    def parse_arguments_and_config(self) -> tuple[
        SearchConfig, DirectoryConfig, OutputConfig, FilterConfig, 
        ProcessingConfig, FolderKMLConfig
    ]:
        """
        Parse command line arguments and load configuration files.
        
        Returns:
            Tuple of all configuration objects
        """
        # Parse command line arguments
        args = self._create_argument_parser().parse_args()
        
        # Handle early exits
        if args.create_config:
            self._create_sample_config(args.create_config)
            sys.exit(Constants.ErrorCodes.SUCCESS)
        
        # Load TOML configuration
        config_data = self._load_config_file(getattr(args, 'config', None))
        
        # Merge configuration with arguments
        if config_data:
            self._merge_config_with_args(config_data, args)
        
        # Handle folder KML export mode
        if hasattr(args, 'export_folder_kml') and args.export_folder_kml:
            return self._handle_folder_kml_mode(args)
        
        # Validate required arguments
        if not args.root:
            raise ConfigurationError("Root directory (-d/--root) is required")
        
        # Create configuration objects from parsed arguments
        search_config = SearchConfig(
            address=args.address,
            latitude=args.latitude,
            longitude=args.longitude,
            radius=args.radius,
            far=getattr(args, 'far', False)
        )
        
        directory_config = DirectoryConfig(
            root=args.root,
            output_directory=args.output_directory,
            find_only=args.find_only,
            sort_by_location=getattr(args, 'sort_by_location', False)
        )
        
        output_config = OutputConfig(
            save_addresses=args.save_addresses,
            export_kml=getattr(args, 'export_kml', False),
            verbose=args.verbose
        )
        
        filter_config = FilterConfig(
            max_gps_error=getattr(args, 'max_gps_error', None),
            max_dop=getattr(args, 'max_dop', None),
            date_from=self._parse_date_arg(args, 'date_from'),
            date_to=self._parse_date_arg(args, 'date_to')
        )
        
        processing_config = ProcessingConfig(
            resume=getattr(args, 'resume', False)
        )
        
        folder_kml_config = FolderKMLConfig()
        
        # Validate configuration
        self._validate_configuration(
            search_config, directory_config, output_config, filter_config
        )
        
        return (
            search_config, directory_config, output_config, 
            filter_config, processing_config, folder_kml_config
        )
    
    def _create_argument_parser(self) -> argparse.ArgumentParser:
        """Create and configure the argument parser."""
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

        # Basic arguments
        parser.add_argument(
            "-o", "--output_directory", action="store",
            help="<output directory> to copy images to (optional)",
        )
        parser.add_argument(
            "-f", "--find_only", action="store_true",
            help="(optional) if set, do not copy files or save data.",
        )
        parser.add_argument(
            "-a", "--address", action="store",
            help="(optional) <address> address to match to images",
        )
        parser.add_argument(
            "-i", "--save_addresses", action="store_true",
            help="Save ALL image addresses to CSV file in output directory (requires -o)",
        )
        parser.add_argument(
            "-v", "--verbose", action="store_true", 
            help="print additional information"
        )
        parser.add_argument(
            "-d", "--root", action="store",
            help="(required) the <root directory> of where to begin searching for images",
        )
        parser.add_argument(
            "-t", "--latitude", type=float,
            help="(optional) if set, use the decimal latitude to center the search.",
        )
        parser.add_argument(
            "-g", "--longitude", type=float,
            help="(optional) if set, use this decimal longitude to center the search.",
        )
        parser.add_argument(
            "-r", "--radius", type=float, default=Constants.DEFAULT_RADIUS,
            help=f"(optional, defaults to {Constants.DEFAULT_RADIUS}) the radius of the search in miles.",
        )
        parser.add_argument(
            "-x", "--far", action="store_true",
            help="(optional) show images that are further than radius from centerpoint",
        )
        
        # Advanced features
        parser.add_argument(
            "--resume", action="store_true",
            help="Resume from a previous interrupted search (uses checkpoint file)",
        )
        parser.add_argument(
            "--export-kml", action="store_true",
            help="Export matched images as KML file for Google Earth",
        )
        parser.add_argument(
            "--max-gps-error", type=float,
            help="Maximum GPS horizontal error in meters to accept (e.g., 50)",
        )
        parser.add_argument(
            "--max-dop", type=float,
            help="Maximum Dilution of Precision value to accept (e.g., 5.0)",
        )
        parser.add_argument(
            "--date-from", type=str,
            help="Filter images from this date (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--date-to", type=str,
            help="Filter images to this date (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--config", type=str,
            help="Path to TOML configuration file (optional)",
        )
        parser.add_argument(
            "--create-config", type=str, nargs="?", const="geo_image_search.toml",
            help="Create a sample configuration file and exit (optionally specify path)",
        )
        parser.add_argument(
            "--sort-by-location", action="store_true",
            help="Sort images into subfolders by geographic clusters (uses radius for grouping)",
        )
        parser.add_argument(
            "--export-folder-kml", type=str,
            help="Generate KML from all GPS-tagged images in the specified folder (independent of search)",
        )
        parser.add_argument(
            "--output-kml", type=str,
            help="Output path for KML file when using --export-folder-kml (optional)",
        )
        parser.add_argument(
            "--no-recursive", action="store_true",
            help="Don't search subfolders recursively when using --export-folder-kml",
        )
        
        return parser
    
    def _load_config_file(self, config_path: str | Path | None = None) -> dict:
        """Load configuration from TOML file."""
        if not tomllib:
            self.logger.warning("TOML support not available. Install tomli for Python < 3.11")
            return {}
            
        config_locations = []

        # Add provided path if given
        if config_path:
            config_locations.append(Path(config_path))

        # Add standard locations
        config_locations.extend([
            Path.cwd() / "geo_image_search.toml",
            Path.home() / ".config" / "geo_image_search" / "config.toml",
            Path.home() / ".geo_image_search.toml",
        ])

        for config_file in config_locations:
            if config_file.exists():
                try:
                    with open(config_file, "rb") as f:
                        config_data = tomllib.load(f)
                    self.logger.info(f"Loaded configuration from: {config_file}")
                    return config_data
                except (OSError, IOError) as e:
                    self.logger.warning(f"Could not load config file {config_file}: {e}")
                    continue
                except Exception as e:
                    self.logger.warning(f"Could not parse config file {config_file}: {e}")
                    continue

        return {}
    
    def _merge_config_with_args(self, config_data: dict, args: argparse.Namespace) -> None:
        """Merge configuration file data with command-line arguments."""
        # Search settings
        search_config = config_data.get("search", {})
        if not args.address and "address" in search_config:
            args.address = search_config["address"]
        if args.latitude is None and "latitude" in search_config:
            args.latitude = search_config["latitude"]
        if args.longitude is None and "longitude" in search_config:
            args.longitude = search_config["longitude"]
        if args.radius == Constants.DEFAULT_RADIUS and "radius" in search_config:
            args.radius = search_config["radius"]
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
        if not getattr(args, 'sort_by_location', False) and dir_config.get("sort_by_location", False):
            args.sort_by_location = dir_config["sort_by_location"]

        # Output settings
        output_config = config_data.get("output", {})
        if not args.save_addresses and output_config.get("save_addresses", False):
            args.save_addresses = output_config["save_addresses"]
        if not getattr(args, 'export_kml', False) and output_config.get("export_kml", False):
            args.export_kml = output_config["export_kml"]
        if not args.verbose and output_config.get("verbose", False):
            args.verbose = output_config["verbose"]

        # Filter settings
        filter_config = config_data.get("filters", {})
        if not hasattr(args, 'max_gps_error') or args.max_gps_error is None:
            if "max_gps_error" in filter_config:
                args.max_gps_error = filter_config["max_gps_error"]
        if not hasattr(args, 'max_dop') or args.max_dop is None:
            if "max_dop" in filter_config:
                args.max_dop = filter_config["max_dop"]
        if not getattr(args, 'date_from', None) and "date_from" in filter_config:
            args.date_from = filter_config["date_from"]
        if not getattr(args, 'date_to', None) and "date_to" in filter_config:
            args.date_to = filter_config["date_to"]

        # Processing settings
        proc_config = config_data.get("processing", {})
        if not getattr(args, 'resume', False) and proc_config.get("resume", False):
            args.resume = proc_config["resume"]

        # Folder KML export settings
        folder_kml_config = config_data.get("folder_kml", {})
        if not hasattr(args, 'export_folder_kml') or not args.export_folder_kml:
            if "folder_path" in folder_kml_config:
                args.export_folder_kml = folder_kml_config["folder_path"]
        if not hasattr(args, 'output_kml') or not args.output_kml:
            if "output_kml_path" in folder_kml_config:
                args.output_kml = folder_kml_config["output_kml_path"]
        if not hasattr(args, 'no_recursive') or not args.no_recursive:
            if folder_kml_config.get("recursive", True) is False:
                args.no_recursive = True
        if not args.verbose and folder_kml_config.get("verbose", False):
            args.verbose = folder_kml_config["verbose"]
    
    def _parse_date_arg(self, args: argparse.Namespace, field_name: str) -> date | None:
        """Parse a date argument from the args namespace."""
        date_str = getattr(args, field_name, None)
        if date_str:
            return self.date_parser.parse_date(date_str, field_name)
        return None
    
    def _handle_folder_kml_mode(self, args: argparse.Namespace) -> tuple:
        """Handle folder KML export mode and exit."""
        # Import here to avoid circular imports
        from .export import KMLExporter
        from .gps import GPSImageProcessor
        
        # Create minimal configuration for folder export
        folder_kml_config = FolderKMLConfig(
            folder_path=args.export_folder_kml,
            output_kml_path=getattr(args, 'output_kml', None),
            recursive=not getattr(args, 'no_recursive', False),
            verbose=args.verbose
        )
        
        filter_config = FilterConfig(
            max_gps_error=getattr(args, 'max_gps_error', None),
            max_dop=getattr(args, 'max_dop', None),
            date_from=self._parse_date_arg(args, 'date_from'),
            date_to=self._parse_date_arg(args, 'date_to')
        )
        
        # Run folder KML export and exit
        kml_exporter = KMLExporter(self.logger)
        gps_processor = GPSImageProcessor(filter_config, self.logger)
        
        success = kml_exporter.export_kml_from_folder(
            folder_kml_config.folder_path,
            folder_kml_config.output_kml_path,
            folder_kml_config.recursive,
            gps_processor
        )
        sys.exit(Constants.ErrorCodes.SUCCESS if success else Constants.ErrorCodes.INTERRUPTED)
    
    def _create_sample_config(self, output_path: str | Path | None = None) -> None:
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
max_gps_error = 50.0     # Maximum GPS horizontal error in meters
max_dop = 5.0           # Maximum Dilution of Precision
date_from = "2020-01-01" # Filter images from this date (YYYY-MM-DD)
date_to = "2024-12-31"   # Filter images to this date (YYYY-MM-DD)

[processing]
# Processing behavior
resume = false          # Resume from previous interrupted search

[folder_kml]
# Independent KML export from existing folders (bypasses normal search)
# folder_path = "/path/to/photos"     # Default folder to scan for GPS images
# output_kml_path = "images.kml"      # Default KML output filename
# recursive = true                    # Search subfolders recursively
# verbose = false                     # Enable verbose output for folder export

# Example configurations:
# For vacation photos: radius = 0.5, save_addresses = true
# For large archives: find_only = true, resume = true, verbose = true
# For specific events: date_from and date_to with precise coordinates
# For folder KML export: folder_path = "/photos", recursive = true, output_kml_path = "vacation.kml"
"""

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(sample_config)
            self.logger.info(f"Sample configuration file created: {output_path}")
            self.logger.info("Edit this file with your preferred settings.")
        except (OSError, IOError) as e:
            self.logger.error(f"Error creating sample config file: {e}")
            raise FileOperationError(f"Could not create config file: {e}")
    
    def _validate_configuration(
        self, 
        search_config: SearchConfig, 
        directory_config: DirectoryConfig, 
        output_config: OutputConfig, 
        filter_config: FilterConfig
    ) -> None:
        """Validate the complete configuration."""        
        # Validate save_addresses requires output directory
        if output_config.save_addresses and not directory_config.output_directory:
            raise ConfigurationError("--save_addresses requires --output_directory to be specified")

        # Validate sort_by_location requirements
        if directory_config.sort_by_location:
            if directory_config.find_only:
                raise ConfigurationError(
                    "--sort-by-location requires copying files (cannot use with --find_only)"
                )
            if not directory_config.output_directory:
                raise ConfigurationError("--sort-by-location requires --output_directory to be specified")