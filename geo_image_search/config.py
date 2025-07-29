"""Configuration management for the geo image search application."""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import NoReturn

import tomllib

from .constants import Constants
from .exceptions import ConfigurationError, FileOperationError
from .types import (
    SearchConfig,
    DirectoryConfig,
    OutputConfig,
    FilterConfig,
    ProcessingConfig,
    FolderKMLConfig,
    ApplicationConfig,
)
from .utils import PathNormalizer, DateParser
from .export import KMLExporter
from .gps import GPSImageProcessor


class ConfigurationManager:
    """Manages application configuration by parsing command-line arguments and TOML
        configuration files, merging their values, validating the resulting configuration,
        and providing configuration objects
    for use throughout the application.
    Responsibilities:
        - Parse command-line arguments using argparse.
        - Load configuration from TOML files, supporting multiple standard locations.
        - Merge configuration file values with command-line arguments, prioritizing
            explicit arguments.
        - Validate configuration for required fields and logical consistency.
        - Handle special modes such as sample config creation and folder KML export.
        - Provide configuration objects for search, directory, output, filtering, processing,
            and folder KML export.
    Methods:
        __init__(logger: logging.Logger)
            Initializes the ConfigurationManager with a logger and utility helpers.
        parse_arguments_and_config() -> ApplicationConfig
            Parses command-line arguments and configuration files, merges them, validates,
                and returns an ApplicationConfig object containing all configuration sections.
        _create_argument_parser() -> argparse.ArgumentParser
            Creates and configures the argument parser for command-line options.
        _load_config_file(config_path: str | Path | None = None) -> dict
            Loads configuration from a TOML file, searching standard locations if no path is
            provided.
        _merge_config_with_args(config_data: dict, args: argparse.Namespace) -> None
            Merges configuration file data into command-line arguments based on defined
            field mappings.
        _apply_field_mapping(config_data: dict, args: argparse.Namespace, mapping: tuple) -> None
            Applies a single field mapping from the configuration file to the arguments namespace.
        _parse_date_arg(args: argparse.Namespace, field_name: str) -> date | None
            Parses a date argument from the arguments namespace.
        _handle_folder_kml_mode(args: argparse.Namespace) -> NoReturn
            Handles the folder KML export mode, running the export and exiting the application.
        _create_sample_config(output_path: str | Path | None = None) -> None
            Creates a sample TOML configuration file with documentation and example settings.
        _validate_configuration(app_config: ApplicationConfig) -> None
            Validates the complete configuration for required fields and logical consistency.
    Exceptions:
        Raises ConfigurationError for invalid or missing configuration.
        Raises FileOperationError for file creation errors.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.path_normalizer = PathNormalizer()
        self.date_parser = DateParser()

    def parse_arguments_and_config(self) -> ApplicationConfig:
        """
        Parses command line arguments and configuration file, merges them, and constructs the
            application configuration.

        This method performs the following steps:
        1. Parses command line arguments using an argument parser.
        2. Handles early exit if the user requests to create a sample configuration file.
        3. Loads configuration data from a TOML file if specified.
        4. Merges configuration file data with command line arguments.
        5. Handles special folder KML export mode if requested.
        6. Validates required arguments (e.g., root directory).
        7. Constructs configuration objects for search, directory, output, filter, processing, and
            folder KML settings.
        8. Validates the combined configuration.
        9. Returns an ApplicationConfig object containing all configuration sections.

        Raises:
            ConfigurationError: If required arguments are missing or configuration is invalid.

        Returns:
            ApplicationConfig: The fully constructed application configuration object.
        """

        # Parse command line arguments
        args = self._create_argument_parser().parse_args()

        # Handle early exits
        if args.create_config:
            self._create_sample_config(args.create_config)
            sys.exit(Constants.ErrorCodes.SUCCESS)

        # Load TOML configuration
        config_data = self._load_config_file(getattr(args, "config", None))

        # Merge configuration with arguments
        if config_data:
            self._merge_config_with_args(config_data, args)

        # Handle folder KML export mode
        if hasattr(args, "export_folder_kml") and args.export_folder_kml:
            self._handle_folder_kml_mode(args)  # we exit when we are just making the kml.

        # Validate required arguments
        if not args.root:
            raise ConfigurationError("Root directory (-d/--root) is required")

        # Create configuration objects from parsed arguments
        search_config = SearchConfig(
            address=args.address,
            latitude=args.latitude,
            longitude=args.longitude,
            radius=args.radius,
            far=getattr(args, "far", False),
        )

        directory_config = DirectoryConfig(
            root=args.root,
            output_directory=args.output_directory,
            find_only=args.find_only,
            sort_by_location=getattr(args, "sort_by_location", False),
        )

        output_config = OutputConfig(
            save_addresses=args.save_addresses,
            export_kml=getattr(args, "export_kml", False),
            verbose=args.verbose,
        )

        filter_config = FilterConfig(
            max_gps_error=getattr(args, "max_gps_error", None),
            max_dop=getattr(args, "max_dop", None),
            date_from=self._parse_date_arg(args, "date_from"),
            date_to=self._parse_date_arg(args, "date_to"),
        )

        processing_config = ProcessingConfig(resume=getattr(args, "resume", False))

        folder_kml_config = FolderKMLConfig()

        # Create configuration object
        app_config = ApplicationConfig(
            search=search_config,
            directory=directory_config,
            output=output_config,
            filter=filter_config,
            processing=processing_config,
            folder_kml=folder_kml_config,
        )

        # Validate configuration
        self._validate_configuration(app_config)

        return app_config

    def _create_argument_parser(self) -> argparse.ArgumentParser:
        """
        Creates and configures an argparse.ArgumentParser for the geo_image_search application.

        The parser supports a variety of command-line arguments for searching images by location
        data found in JPEG metadata, exporting results, filtering by date, and advanced
        configuration options.

        Returns:
            argparse.ArgumentParser: Configured argument parser with all supported options.

        Supported Arguments:
            -o, --output_directory         Output directory to copy images to (optional).
            -f, --find_only                If set, do not copy files or save data.
            -a, --address                  Address to match to images (optional).
            -i, --save_addresses           Save all image addresses to CSV file in output directory
                                            (requires -o).
            -v, --verbose                  Print additional information.
            -d, --root                     Root directory to begin searching for images (required).
            -t, --latitude                 Decimal latitude to center the search (optional).
            -g, --longitude                Decimal longitude to center the search (optional).
            -r, --radius                   Radius of the search in miles (optional, defaults to
                                            Constants.DEFAULT_RADIUS).
            -x, --far                      Show images that are further than radius from
                                            centerpoint (optional).
            --resume                       Resume from a previous interrupted search (uses
                                            checkpoint file).
            --export-kml                   Export matched images as KML file for Google Earth.
            --max-gps-error                Maximum GPS horizontal error in meters to accept.
            --max-dop                      Maximum Dilution of Precision value to accept.
            --date-from                    Filter images from this date (YYYY-MM-DD format).
            --date-to                      Filter images to this date (YYYY-MM-DD format).
            --config                       Path to TOML configuration file (optional).
            --create-config                Create a sample configuration file and exit (optionally
                                            specify path).
            --sort-by-location             Sort images into subfolders by geographic clusters.
            --export-folder-kml            Generate KML from all GPS-tagged images in the specified
                                            folder.
            --output-kml                   Output path for KML file when using --export-folder-kml
                                            (optional).
            --no-recursive                 Don't search subfolders recursively when using
                                            --export-folder-kml.

        The parser also provides detailed help and usage examples in its description and epilog.
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

        # Basic arguments
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
            default=Constants.DEFAULT_RADIUS,
            help=(
                f"(optional, defaults to {Constants.DEFAULT_RADIUS})"
                " the radius of the search in miles."
            ),
        )
        parser.add_argument(
            "-x",
            "--far",
            action="store_true",
            help="(optional) show images that are further than radius from centerpoint",
        )

        # Advanced features
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
            "--max-gps-error",
            type=float,
            help="Maximum GPS horizontal error in meters to accept (e.g., 50)",
        )
        parser.add_argument(
            "--max-dop",
            type=float,
            help="Maximum Dilution of Precision value to accept (e.g., 5.0)",
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
            help="Sort images into subfolders by geographic clusters (uses radius for grouping)",
        )
        parser.add_argument(
            "--export-folder-kml",
            type=str,
            help=(
                "Generate KML from all GPS-tagged images in"
                " the specified folder (independent of search)"
            ),
        )
        parser.add_argument(
            "--output-kml",
            type=str,
            help="Output path for KML file when using --export-folder-kml (optional)",
        )
        parser.add_argument(
            "--no-recursive",
            action="store_true",
            help="Don't search subfolders recursively when using --export-folder-kml",
        )

        return parser

    def _load_config_file(self, config_path: str | Path | None = None) -> dict:
        """
        Loads configuration data from a TOML file.

        This method attempts to load configuration from a specified path or from standard
        locations if no path is provided. It supports Python's built-in TOML parser (tomllib)

        Args:
            config_path (str | Path | None): Optional path to a configuration file. If not provided,
                standard locations are checked.

        Returns:
            dict: The loaded configuration as a dictionary. Returns an empty dictionary if no
                configuration file is found or if loading/parsing fails.

        Logs:
            - Info when a configuration file is successfully loaded.
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
                    with open(config_file, "rb") as f:
                        config_data = tomllib.load(f)
                    self.logger.info(f"Loaded configuration from: {config_file}")
                    return config_data
                except (OSError, IOError) as e:
                    self.logger.warning(f"Could not load config file {config_file}: {e}")
                    continue
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.warning(f"Could not parse config file {config_file}: {e}")
                    continue

        return {}

    def _merge_config_with_args(self, config_data: dict, args: argparse.Namespace) -> None:
        """
        Merges configuration data from a dictionary (typically loaded from a TOML file) with
            command-line arguments.

        This method systematically applies a set of field mappings to update the `args`
            namespace with values from `config_data` according to specific merge strategies.
            Each mapping specifies the TOML section, argument name, TOML field, and the
            strategy to use for merging (e.g., use non-empty strings, check for None,
            apply default values, handle booleans, etc.).

        After applying all field mappings, the method handles a special case for the
            `no_recursive` argument, which uses inverse logic based on the `recursive`
            field in the `folder_kml` section of the configuration.

        Args:
            config_data (dict): The configuration data loaded from a TOML file,
                                organized by sections.
            args (argparse.Namespace): The namespace containing command-line
                                        arguments to be updated.

        Returns:
            None
        """

        # Define field mappings for systematic merging
        field_mappings = [
            # (toml_section, arg_name, toml_field, merge_strategy)
            ("search", "address", "address", "string_not_empty"),
            ("search", "latitude", "latitude", "none_check"),
            ("search", "longitude", "longitude", "none_check"),
            ("search", "radius", "radius", "default_value", Constants.DEFAULT_RADIUS),
            ("search", "far", "far", "boolean_false_to_true"),
            ("directories", "root", "root", "string_not_empty"),
            ("directories", "output_directory", "output_directory", "string_not_empty"),
            ("directories", "find_only", "find_only", "boolean_false_to_true"),
            (
                "directories",
                "sort_by_location",
                "sort_by_location",
                "getattr_boolean_false_to_true",
            ),
            ("output", "save_addresses", "save_addresses", "boolean_false_to_true"),
            ("output", "export_kml", "export_kml", "getattr_boolean_false_to_true"),
            ("output", "verbose", "verbose", "boolean_false_to_true"),
            ("filters", "max_gps_error", "max_gps_error", "hasattr_none_check"),
            ("filters", "max_dop", "max_dop", "hasattr_none_check"),
            ("filters", "date_from", "date_from", "getattr_none_check"),
            ("filters", "date_to", "date_to", "getattr_none_check"),
            ("processing", "resume", "resume", "getattr_boolean_false_to_true"),
            ("folder_kml", "export_folder_kml", "folder_path", "hasattr_empty_check"),
            ("folder_kml", "output_kml", "output_kml_path", "hasattr_empty_check"),
            ("folder_kml", "verbose", "verbose", "boolean_false_to_true"),
        ]

        # Apply all field mappings
        for mapping in field_mappings:
            self._apply_field_mapping(config_data, args, mapping)

        # Handle special case for no_recursive (inverse logic)
        folder_kml_config = config_data.get("folder_kml", {})
        if not hasattr(args, "no_recursive") or not args.no_recursive:
            if folder_kml_config.get("recursive", True) is False:
                args.no_recursive = True

    def _apply_field_mapping(
        self, config_data: dict, args: argparse.Namespace, mapping: tuple
    ) -> None:
        """
        Applies a single field mapping from a configuration dictionary to an argparse.
            Namespace object based on a specified merge strategy.

        Args:
            config_data (dict): The configuration data, typically loaded from a TOML file.
            args (argparse.Namespace): The namespace containing argument values to be updated.
            mapping (tuple): A tuple specifying the mapping, containing:
                - toml_section (str): The section in the config data.
                - arg_name (str): The name of the argument in the namespace.
                - toml_field (str): The field name in the config section.
                - merge_strategy (str): The strategy to use for merging values.
                - [default_value] (optional): The default value for 'default_value' strategy.

        Merge Strategies:
            - "string_not_empty": Sets the argument if it is empty/falsy and config value exists.
            - "none_check": Sets the argument if it is None and config value exists.
            - "default_value": Sets the argument if it matches a specific default value and
                                config value exists.
            - "boolean_false_to_true": Sets the argument if it is False and config value is True.
            - "getattr_boolean_false_to_true": Like above, but uses getattr with default False.
            - "hasattr_none_check": Sets the argument if it does not exist or is None and
                                        config value exists.
            - "getattr_none_check": Sets the argument if it is None/falsy and config value exists.
            - "hasattr_empty_check": Sets the argument if it does not exist or is empty/falsy and
                                        config value exists.

        Returns:
            None
        """
        toml_section = mapping[0]
        arg_name = mapping[1]
        toml_field = mapping[2]
        merge_strategy = mapping[3]

        section_data = config_data.get(toml_section, {})

        if merge_strategy == "string_not_empty":
            # For string fields: use config if arg is empty/falsy
            if not getattr(args, arg_name, None) and toml_field in section_data:
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "none_check":
            # For fields that could be None: use config if arg is None
            if getattr(args, arg_name, None) is None and toml_field in section_data:
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "default_value":
            # For fields with specific default values
            default_value = mapping[4]
            if getattr(args, arg_name) == default_value and toml_field in section_data:
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "boolean_false_to_true":
            # For boolean fields: use config if arg is False and config is True
            if not getattr(args, arg_name, False) and section_data.get(toml_field, False):
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "getattr_boolean_false_to_true":
            # For optional boolean fields using getattr
            if not getattr(args, arg_name, False) and section_data.get(toml_field, False):
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "hasattr_none_check":
            # For fields that may not exist or be None
            if not hasattr(args, arg_name) or getattr(args, arg_name) is None:
                if toml_field in section_data:
                    setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "getattr_none_check":
            # For optional fields using getattr with None check
            if not getattr(args, arg_name, None) and toml_field in section_data:
                setattr(args, arg_name, section_data[toml_field])

        elif merge_strategy == "hasattr_empty_check":
            # For fields that may not exist or be empty
            if not hasattr(args, arg_name) or not getattr(args, arg_name):
                if toml_field in section_data:
                    setattr(args, arg_name, section_data[toml_field])

    def _parse_date_arg(self, args: argparse.Namespace, field_name: str) -> date | None:
        """Parse a date argument from the args namespace."""
        date_str = getattr(args, field_name, None)
        if date_str:
            return self.date_parser.parse_date(date_str, field_name)
        return None

    def _handle_folder_kml_mode(self, args: argparse.Namespace) -> NoReturn:
        """Handle folder KML export mode and exit."""
        # Import here to avoid circular imports

        # Create minimal configuration for folder export
        folder_kml_config = FolderKMLConfig(
            folder_path=args.export_folder_kml,
            output_kml_path=getattr(args, "output_kml", None),
            recursive=not getattr(args, "no_recursive", False),
            verbose=args.verbose,
        )

        filter_config = FilterConfig(
            max_gps_error=getattr(args, "max_gps_error", None),
            max_dop=getattr(args, "max_dop", None),
            date_from=self._parse_date_arg(args, "date_from"),
            date_to=self._parse_date_arg(args, "date_to"),
        )

        # Run folder KML export and exit
        kml_exporter = KMLExporter(self.logger)
        gps_processor = GPSImageProcessor(filter_config, self.logger)

        # Ensure folder_path is not None (should always be valid in this context)
        if folder_kml_config.folder_path is None:
            raise ConfigurationError("Folder path is required for KML export")

        success = kml_exporter.export_kml_from_folder(
            folder_kml_config.folder_path,
            folder_kml_config.output_kml_path,
            folder_kml_config.recursive,
            gps_processor,
        )
        sys.exit(Constants.ErrorCodes.SUCCESS if success else Constants.ErrorCodes.INTERRUPTED)

    def _create_sample_config(self, output_path: str | Path | None = None) -> None:
        """Creates a sample configuration file for Geo Image Search in TOML format.

        If no output path is provided, the file is saved as 'geo_image_search.toml' in the current
        working directory. Otherwise, the file is saved to the specified output path.

        The sample configuration includes sections for search parameters, directory settings,
        output options, advanced filters, processing behavior, and folder KML export options.
        It also provides example configurations for common use cases.

        Parameters:
            output_path (str | Path | None): Optional path to save the sample configuration file.
                                                If None, defaults to 'geo_image_search.toml' in
                                                the current working directory.

        Raises:
            FileOperationError: If the configuration file cannot be created due to an OS or IO
                                error.
        """

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
            raise FileOperationError(f"Could not create config file: {e}") from e

    def _validate_configuration(self, app_config: ApplicationConfig) -> None:
        """
        Validates the application configuration for required options and constraints.

        Checks:
            - If 'save_addresses' is enabled, ensures 'output_directory' is specified.
            - If 'sort_by_location' is enabled:
                - Ensures 'find_only' is not enabled simultaneously.
                - Ensures 'output_directory' is specified.

        Raises:
            ConfigurationError: If any configuration requirement is not met.

        Args:
            app_config (ApplicationConfig): The application configuration to validate.
        """

        # Validate save_addresses requires output directory
        if app_config.output.save_addresses and not app_config.directory.output_directory:
            raise ConfigurationError("--save_addresses requires --output_directory to be specified")

        # Validate sort_by_location requirements
        if app_config.directory.sort_by_location:
            if app_config.directory.find_only:
                raise ConfigurationError(
                    "--sort-by-location requires copying files (cannot use with --find_only)"
                )
            if not app_config.directory.output_directory:
                raise ConfigurationError(
                    "--sort-by-location requires --output_directory to be specified"
                )
