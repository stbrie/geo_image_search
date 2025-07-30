# Geo Image Search 2.0

A Python command-line tool for finding and organizing JPEG images based on their GPS metadata. Version 2.0 features a complete modular architecture refactor for better maintainability and developer experience.

## 🆕 What's New in Version 2.0

- **Modular Architecture**: Broken down from a single 3,500+ line file into focused, single-responsibility modules
- **Type Safety**: Full Python 3.12+ type hints with union types and dataclasses
- **Proper Logging**: Structured logging replaces scattered print statements
- **Better Error Handling**: Custom exception hierarchy with semantic error codes
- **Improved Testing**: Modular design enables easy unit testing and dependency injection
- **Package Structure**: Installable package with proper entry points
- **Required Dependencies**: All dependencies are now required - no more conditional importing or degraded functionality

## Features

- **Location-based search**: Find images within a configurable radius of an address or coordinates
- **Independent KML export**: Generate Google Earth KML files from any folder of GPS-tagged images
- **Geographic clustering**: Sort images into subfolders by location clusters
- **Advanced filtering**: Date range and GPS accuracy filtering
- **Multiple export formats**: CSV and KML output
- **TOML configuration**: Comprehensive configuration file support
- **Resume functionality**: Checkpoint-based processing for large collections

## Installation

### From Source (Development)

```bash
# Clone the repository
git clone <repository-url>
cd geo_image_search

# Install in development mode
pip install -e .
```

### Dependencies

**Required:**
- Python 3.11+
- `exif` - EXIF metadata extraction
- `geopy` - Distance calculations and geocoding
- `fastkml` - KML export functionality
- `pygeoif` - Geographic data processing for KML

**Note:** All dependencies are required. The application will fail at import time if any are missing.

## Geocoding Service Usage

This application uses the **Nominatim** geocoding service provided by OpenStreetMap to convert addresses to coordinates. 

### Important Usage Guidelines

**REQUIRED**: You must provide a proper User-Agent string that identifies your application. This is both:
- A technical requirement for the service to work
- A courtesy requirement per OpenStreetMap's usage policy

Configure your User-Agent in the configuration file:
```toml
[geocoding]
user_agent = "MyApp/1.0 (your-email@example.com)"
```

Or via command line:
```bash
python -m geo_image_search --user-agent "MyApp/1.0 (your-email@example.com)" ...
```

### Usage Policy

Please read and follow the **Nominatim Usage Policy**: https://operations.osmfoundation.org/policies/nominatim/

**Key requirements:**
- Provide a valid User-Agent identifying your application and contact information
- Respect rate limits (max 1 request per second for continuous use)
- Use appropriate bulk geocoding methods for large datasets
- Consider setting up your own Nominatim instance for heavy usage

**Good User-Agent examples:**
- `geo_image_search/1.0 (john@example.com)`
- `MyPhotoApp/2.1 +https://example.com/contact`
- `Research Project XYZ (researcher@university.edu)`

**Bad User-Agent examples:**
- `geo_image_search/1.0` (no contact info)
- `Mozilla/5.0` (pretending to be a browser)
- `Python` (too generic)

### Rate Limiting

The application automatically includes timeout handling for geocoding requests. For large batches of address-to-coordinate conversions, the built-in timeouts and error handling will manage service availability.

## Architecture Overview

The application is now organized into focused modules:

```
geo_image_search/
├── __init__.py          # Package initialization
├── main.py              # Main application orchestrator
├── constants.py         # Application constants and error codes
├── types.py             # Type definitions and dataclasses
├── exceptions.py        # Custom exception hierarchy
├── utils.py             # Utility classes (logging, path handling, etc.)
├── config.py            # Configuration management and argument parsing
├── gps.py               # GPS data extraction from images
├── search.py            # Location-based searching and distance calculations
├── export.py            # CSV and KML export functionality
└── clustering.py        # Geographic clustering and checkpoint management
```

### Key Components

#### Configuration Management (`config.py`)
- **ConfigurationManager**: Handles TOML config files and argument parsing
- Validates configuration and provides helpful error messages
- Supports configuration hierarchy: CLI args → TOML files → defaults

#### GPS Processing (`gps.py`)
- **GPSImageProcessor**: Extracts GPS metadata from JPEG images
- Applies filtering (date ranges, GPS accuracy, DOP values)
- Handles EXIF parsing with proper error handling

#### Location Search (`search.py`)
- **LocationSearchEngine**: Handles geocoding and distance calculations
- Supports both address-based and coordinate-based searches
- Integrates with Nominatim for address resolution

#### Export Systems (`export.py`)
- **CSVExporter**: Creates CSV files with image metadata
- **KMLExporter**: Generates Google Earth KML files
- Proper error handling and path normalization

#### Clustering (`clustering.py`)
- **ClusteringEngine**: Groups images by geographic proximity
- **CheckpointManager**: Provides resume functionality for large searches
- Smart cluster naming using reverse geocoding

## Usage

### Basic Search

```bash
# Search by address with 1-mile radius
python -m geo_image_search -d /path/to/images -a "New York, NY" -r 1.0 -o output_folder

# Search by coordinates
python -m geo_image_search -d /path/to/images -t 40.7128 -g -74.0060 -r 0.5 -o results

# Find-only mode (no file copying)
python -m geo_image_search -d /path/to/images -a "Paris" -r 2.0 --find_only -v
```

### Independent KML Export

```bash
# Generate KML from existing folder
python -m geo_image_search --export-folder-kml /path/to/photos

# Custom output and non-recursive scan
python -m geo_image_search --export-folder-kml /photos --output-kml vacation.kml --no-recursive

# Apply filters
python -m geo_image_search --export-folder-kml /photos --date-from 2024-01-01 --date-to 2024-12-31 -v
```

### Configuration Management

```bash
# Create sample configuration file
python -m geo_image_search --create-config

# Use custom config file
python -m geo_image_search --config my_settings.toml
```

## Configuration

The application supports comprehensive TOML configuration files:

```toml
[search]
address = "New York, NY"
radius = 1.0

[directories] 
root = "/path/to/photos"
output_directory = "found_images"

[folder_kml]
folder_path = "/home/user/photos"
output_kml_path = "my_photos.kml"
recursive = true
verbose = true

[filters]
date_from = "2024-01-01"
date_to = "2024-12-31"
max_gps_error = 50.0
```

Configuration files are searched in this order:
1. Path specified with `--config`
2. `./geo_image_search.toml`
3. `~/.config/geo_image_search/config.toml`
4. `~/.geo_image_search.toml`

## Development

### Project Structure Benefits

1. **Modularity**: Each module has a single responsibility
2. **Testability**: Components can be unit tested in isolation
3. **Type Safety**: Full type hints improve IDE support and catch errors early
4. **Maintainability**: Changes are localized to specific modules
5. **Extensibility**: New features can be added without affecting existing code

### Error Handling

The application uses a structured error hierarchy:

```python
GeoImageSearchError (base)
├── ConfigurationError    # Configuration validation issues
├── GPSDataError         # GPS processing problems  
└── FileOperationError   # File system operations
```

Exit codes are semantic and documented in `constants.py`.

### Logging

Proper structured logging throughout:

```python
from geo_image_search.utils import LoggingSetup

logging_setup = LoggingSetup()
logger = logging_setup.setup_logging()
logger.info("Operation completed successfully")
```

## Migration from Version 1.x

The new modular version maintains full command-line compatibility with the original monolithic version. Simply replace calls to `geo_image_search.py` with `python -m geo_image_search`.

### Key Improvements

- **Performance**: Better memory usage with focused object lifetimes
- **Reliability**: Proper error handling and validation
- **Maintainability**: 8 focused modules instead of 1 monolithic file
- **Developer Experience**: Type hints, better IDE support, easier debugging
- **Testing**: Modular design enables comprehensive unit testing

## Platform Support

Works on Windows, Linux, and WSL with proper path normalization. Tested on:
- Windows 10/11 with WSL
- Linux (Ubuntu, Debian)
- macOS (limited testing)

## Contributing

The modular architecture makes contributions much easier:

1. **Add new features**: Create focused modules following existing patterns
2. **Fix bugs**: Changes are localized to specific components
3. **Add tests**: Each module can be tested independently
4. **Improve performance**: Optimize individual components without affecting others

## License

MIT License - see LICENSE file for details.

## Changelog

### Version 2.0.0
- Complete architectural refactoring from monolithic to modular design
- Added proper type hints throughout
- Implemented structured logging
- Created custom exception hierarchy
- Added comprehensive configuration validation
- Improved error messages and user experience
- Made package installable with proper entry points
- Eliminated conditional importing - all dependencies are now required
- Updated dependency list to use `pygeoif` instead of `shapely`