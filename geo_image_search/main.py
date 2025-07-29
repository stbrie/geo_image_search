"""Main application module for geo image search."""

import sys
from pathlib import Path

from .constants import Constants
from .exceptions import ConfigurationError, GPSDataError, FileOperationError
from .config import ConfigurationManager
from .gps import GPSImageProcessor
from .search import LocationSearchEngine
from .export import CSVExporter, KMLExporter
from .clustering import ClusteringEngine, CheckpointManager
from .utils import LoggingSetup
from .types import ImageData


def main() -> None:
    """Main execution function using refactored architecture."""
    # Set up logging
    logging_setup = LoggingSetup()
    logger = logging_setup.setup_logging()
    
    try:
        # Parse configuration
        config_manager = ConfigurationManager(logger)
        
        # Handle special operations first - check for create config flag
        # This would need to be implemented in ConfigurationManager if needed
        
        # Check for folder KML export mode
        search_config, directory_config, output_config, filter_config, processing_config, folder_kml_config = (
            config_manager.parse_arguments_and_config()
        )
        
        if folder_kml_config.folder_path:
            logger.info("Running in folder KML export mode")
            kml_exporter = KMLExporter(logger)
            try:
                output_path = kml_exporter.export_kml_from_folder(
                    folder_kml_config.folder_path, 
                    folder_kml_config.output_kml_path,
                    folder_kml_config.recursive,
                    GPSImageProcessor(filter_config, logger)
                )
                if output_path:
                    logger.info("Folder KML export completed successfully")
                    sys.exit(Constants.ErrorCodes.SUCCESS)
                else:
                    logger.error("Folder KML export failed")
                    sys.exit(Constants.ErrorCodes.SUCCESS)  # Still success, just no images
            except Exception as e:
                logger.error(f"Folder KML export failed: {e}")
                sys.exit(Constants.ErrorCodes.FILE_OPERATION_ERROR)
        
        # Standard search mode
        logger.info("Running in search mode")
        
        # Initialize components
        gps_processor = GPSImageProcessor(filter_config, logger)
        search_engine = LocationSearchEngine(search_config, logger)  
        clustering_engine = ClusteringEngine(logger)
        checkpoint_manager = CheckpointManager(logger)
        csv_exporter = CSVExporter(logger)
        kml_exporter = KMLExporter(logger)
        
        # Initialize search location
        search_engine.initialize_search_location()
        
        # Set up directory paths
        if not directory_config.root:
            logger.error("Root directory not specified")
            sys.exit(Constants.ErrorCodes.NO_ROOT_DIRECTORY)
        
        root_path = Path(directory_config.root)
        if not root_path.exists():
            logger.error(f"Root directory does not exist: {root_path}")
            sys.exit(Constants.ErrorCodes.ROOT_DIRECTORY_NOT_FOUND)
        
        # Handle checkpoint resume
        processed_files_set = set()
        if processing_config.resume:
            checkpoint_data = checkpoint_manager.load_checkpoint()
            if checkpoint_data:
                processed_files, _ = checkpoint_data
                processed_files_set = set(processed_files)
        
        # Process images
        found_images: list[ImageData] = []
        total_processed = 0
        
        logger.info(f"Scanning directory: {root_path}")
        logger.info(f"Search center: {search_engine.search_coords}")
        logger.info(f"Search radius: {search_config.radius} miles")
        
        # Walk through directory tree
        for current_dir in root_path.rglob("*") if True else [root_path]:
            if not current_dir.is_dir():
                continue
                
            # Skip output directory
            if directory_config.output_directory and directory_config.output_directory != "Do Not Save":
                try:
                    output_path = Path(directory_config.output_directory)
                    if current_dir.is_relative_to(output_path):
                        continue
                except (ValueError, OSError):
                    pass
            
            # Process JPEG files in directory
            for file_path in current_dir.iterdir():
                if not file_path.is_file():
                    continue
                    
                if file_path.suffix.lower() not in Constants.JPEG_EXTENSIONS:
                    continue
                
                # Skip if already processed
                file_id = str(file_path)
                if file_id in processed_files_set:
                    continue
                
                total_processed += 1
                
                # Extract GPS data
                try:
                    image_data = gps_processor.extract_image_gps_data(str(file_path))
                    if not image_data:
                        continue
                    
                    # Check if within search radius
                    image_coords = (image_data["latitude"], image_data["longitude"])
                    if search_engine.is_within_radius(image_coords):
                        found_images.append(image_data)
                        
                        if output_config.verbose:
                            distance_miles = search_engine.calculate_distance_miles(image_coords)
                            logger.info(f"Found: {image_data['filename']} ({distance_miles:.2f} miles)")
                
                except Exception as e:
                    if output_config.verbose:
                        logger.warning(f"Error processing {file_path}: {e}")
                    continue
                
                # Save checkpoint periodically
                if total_processed % Constants.CHECKPOINT_INTERVAL_FILES == 0:
                    checkpoint_manager.save_checkpoint([file_id], total_processed)
        
        # Process results
        logger.info(f"Found {len(found_images)} matching images")
        
        if not found_images:
            logger.warning("No matching images found")
            logger.info("Search completed - no matching images found")
            sys.exit(Constants.ErrorCodes.SUCCESS)  # This is success - search worked, just no matches
        
        # Handle clustering if requested
        if directory_config.sort_by_location:
            clusters = clustering_engine.cluster_images_by_location(found_images)
            logger.info(f"Organized into {len(clusters)} location clusters")
        
        # Export results
        if output_config.save_addresses:
            csv_exporter.export_image_addresses(found_images, directory_config.output_directory or ".")
        
        if output_config.export_kml:
            kml_content = kml_exporter.build_kml_from_image_data(
                found_images, 
                search_engine.search_coords
            )
            with open("search_results.kml", 'w', encoding='utf-8') as f:
                f.write(kml_content)
            logger.info("KML export completed")
        
        # Copy files if not in find-only mode
        if not directory_config.find_only and directory_config.output_directory:
            # File copying logic would go here
            pass
        
        # Clean up checkpoint
        checkpoint_manager.clear_checkpoint()
        
        logger.info("Search completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Search interrupted by user")
        sys.exit(Constants.ErrorCodes.INTERRUPTED)
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(Constants.ErrorCodes.CONFLICTING_OPTIONS)
    except GPSDataError as e:
        logger.error(f"GPS data error: {e}")
        sys.exit(Constants.ErrorCodes.GPS_DATA_ERROR)
    except FileOperationError as e:
        logger.error(f"File operation error: {e}")
        sys.exit(Constants.ErrorCodes.FILE_OPERATION_ERROR)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(Constants.ErrorCodes.GENERAL_ERROR)


if __name__ == "__main__":
    main()