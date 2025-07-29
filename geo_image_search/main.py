"""Main application module for geo image search."""

import logging
import sys
import shutil
import signal
from pathlib import Path

from .constants import Constants
from .exceptions import ConfigurationError, GPSDataError, FileOperationError
from .config import ConfigurationManager
from .gps import GPSImageProcessor
from .search import LocationSearchEngine
from .export import CSVExporter, KMLExporter
from .clustering import ClusteringEngine, CheckpointManager
from .utils import LoggingSetup, FileOperationManager
from .types import ImageData, ApplicationConfig


class SearchWorkflow:
    """Orchestrates the image search workflow."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.gps_processor: GPSImageProcessor | None = None
        self.search_engine: LocationSearchEngine | None = None
        self.clustering_engine: ClusteringEngine | None = None
        self.checkpoint_manager: CheckpointManager | None = None
        self.csv_exporter: CSVExporter | None = None
        self.kml_exporter: KMLExporter | None = None
        self.file_manager: FileOperationManager | None = None

    def run(self, app_config: ApplicationConfig):
        """Run the main search workflow."""
        # Initialize components
        self._initialize_components(app_config.filter, app_config.search)

        # Validate and set up directories
        root_path = self._validate_directories(app_config.directory)

        # Handle checkpoint resume
        processed_files_set = self._handle_checkpoint_resume(app_config.processing)

        # Scan and process images
        found_images = self._scan_and_process_images(
            root_path, app_config.directory, app_config.output, processed_files_set
        )

        # Handle case where no images found
        if not found_images:
            self.logger.warning("No matching images found")
            self.logger.info("Search completed - no matching images found")
            return

        # Process and export results
        self._handle_exports(found_images, app_config.directory, app_config.output)

        # Copy files if needed
        self._copy_files_if_needed(found_images, app_config.directory)

        # Clean up
        assert self.checkpoint_manager is not None, "Components must be initialized first"
        self.checkpoint_manager.clear_checkpoint()
        self.logger.info("Search completed successfully")

    def _initialize_components(self, filter_config, search_config):
        """Initialize all workflow components."""
        self.gps_processor = GPSImageProcessor(filter_config, self.logger)
        self.search_engine = LocationSearchEngine(search_config, self.logger)
        self.clustering_engine = ClusteringEngine(self.logger)
        self.checkpoint_manager = CheckpointManager(self.logger)
        self.csv_exporter = CSVExporter(self.logger)
        self.kml_exporter = KMLExporter(self.logger)
        self.file_manager = FileOperationManager(self.logger)

        # Initialize search location
        self.search_engine.initialize_search_location()

    def _validate_directories(self, directory_config):
        """Validate directory configuration and return root path."""
        if not directory_config.root:
            self.logger.error("Root directory not specified")
            sys.exit(Constants.ErrorCodes.NO_ROOT_DIRECTORY)

        root_path = Path(directory_config.root)
        if not root_path.exists():
            self.logger.error(f"Root directory does not exist: {root_path}")
            sys.exit(Constants.ErrorCodes.ROOT_DIRECTORY_NOT_FOUND)

        return root_path

    def _handle_checkpoint_resume(self, processing_config):
        """Handle checkpoint resume and return set of processed files."""
        assert self.checkpoint_manager is not None, "Components must be initialized first"
        processed_files_set = set()
        if processing_config.resume:
            checkpoint_data = self.checkpoint_manager.load_checkpoint()
            if checkpoint_data:
                processed_files, _ = checkpoint_data
                processed_files_set = set(processed_files)
        return processed_files_set

    def _scan_and_process_images(
        self, root_path, directory_config, output_config, processed_files_set
    ):
        """Scan directory tree and process images, returning found images."""
        assert self.search_engine is not None, "Components must be initialized first"
        found_images: list[ImageData] = []
        total_processed = 0

        self.logger.info(f"Scanning directory: {root_path}")
        self.logger.info(f"Search center: {self.search_engine.search_coords}")
        self.logger.info(f"Search radius: {self.search_engine.search_config.radius} miles")

        # Walk through directory tree
        for current_dir in root_path.rglob("*"):
            if not current_dir.is_dir():
                continue

            # Skip output directory if configured
            if self._should_skip_directory(current_dir, directory_config):
                continue

            # Process JPEG files in directory
            for file_path in current_dir.iterdir():
                if not self._should_process_file(file_path, processed_files_set):
                    continue

                total_processed += 1

                # Process individual image file
                image_data = self._process_image_file(file_path, output_config)
                if image_data:
                    found_images.append(image_data)

                # Handle checkpoint saving
                self._handle_checkpoint_saving(total_processed, str(file_path))

        self.logger.info(f"Found {len(found_images)} matching images")
        return found_images

    def _should_skip_directory(self, current_dir, directory_config):
        """Check if directory should be skipped during scanning."""
        if directory_config.output_directory and directory_config.output_directory != "Do Not Save":
            try:
                output_path = Path(directory_config.output_directory)
                if current_dir.is_relative_to(output_path):
                    return True
            except (ValueError, OSError):
                pass
        return False

    def _should_process_file(self, file_path, processed_files_set):
        """Check if file should be processed."""
        if not file_path.is_file():
            return False

        if file_path.suffix.lower() not in Constants.JPEG_EXTENSIONS:
            return False

        # Skip if already processed
        file_id = str(file_path)
        if file_id in processed_files_set:
            return False

        return True

    def _process_image_file(self, file_path, output_config):
        """Process a single image file and return image data if within radius."""
        assert (
            self.gps_processor is not None and self.search_engine is not None
        ), "Components must be initialized first"
        try:
            image_data = self.gps_processor.extract_image_gps_data(str(file_path))
            if not image_data:
                return None

            # Check if within search radius
            image_coords = (image_data["latitude"], image_data["longitude"])
            if self.search_engine.is_within_radius(image_coords):
                if output_config.verbose:
                    distance_miles = self.search_engine.calculate_distance_miles(image_coords)
                    self.logger.info(
                        f"Found: {image_data['filename']} ({distance_miles:.2f} miles)"
                    )
                return image_data

        except Exception as e:
            if output_config.verbose:
                self.logger.warning(f"Error processing {file_path}: {e}")

        return None

    def _handle_checkpoint_saving(self, total_processed, file_id):
        """Handle periodic checkpoint saving."""
        assert self.checkpoint_manager is not None, "Components must be initialized first"
        if total_processed % Constants.CHECKPOINT_INTERVAL_FILES == 0:
            self.checkpoint_manager.save_checkpoint([file_id], total_processed)

    def _handle_exports(self, found_images, directory_config, output_config):
        """Handle CSV and KML exports."""
        assert (
            self.clustering_engine is not None
            and self.csv_exporter is not None
            and self.kml_exporter is not None
            and self.search_engine is not None
        ), "Components must be initialized first"
        # Handle clustering if requested (for exports)
        clusters = None
        if directory_config.sort_by_location:
            clusters = self.clustering_engine.cluster_images_by_location(found_images)
            self.logger.info(f"Organized into {len(clusters)} location clusters")

        # Export CSV
        if output_config.save_addresses:
            self.csv_exporter.export_image_addresses(
                found_images, directory_config.output_directory or "."
            )

        # Export KML
        if output_config.export_kml:
            kml_content = self.kml_exporter.build_kml_from_image_data(
                found_images, self.search_engine.search_coords
            )
            with open("search_results.kml", "w", encoding="utf-8") as f:
                f.write(kml_content)
            self.logger.info("KML export completed")

    def _copy_files_if_needed(self, found_images, directory_config):
        """Copy files to output directory if not in find-only mode."""
        if directory_config.find_only or not directory_config.output_directory:
            return

        assert (
            self.clustering_engine is not None and self.file_manager is not None
        ), "Components must be initialized first"
        # Handle clustering for file organization
        if directory_config.sort_by_location:
            clusters = self.clustering_engine.cluster_images_by_location(found_images)
            copied_count = self.file_manager.copy_images_by_clusters(
                clusters, directory_config.output_directory
            )
        else:
            copied_count = self.file_manager.copy_images_simple(
                found_images, directory_config.output_directory
            )

        self.logger.info(f"Copied {copied_count} images to {directory_config.output_directory}")


def main() -> None:
    """Main execution function using refactored architecture."""
    # Set up logging
    logging_setup = LoggingSetup()
    logger = logging_setup.setup_logging()

    try:
        # Parse configuration
        config_manager = ConfigurationManager(logger)
        app_config = config_manager.parse_arguments_and_config()

        # Handle folder KML export mode
        if app_config.folder_kml.folder_path:
            logger.info("Running in folder KML export mode")
            kml_exporter = KMLExporter(logger)
            try:
                output_path = kml_exporter.export_kml_from_folder(
                    app_config.folder_kml.folder_path,
                    app_config.folder_kml.output_kml_path,
                    app_config.folder_kml.recursive,
                    GPSImageProcessor(app_config.filter, logger),
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

        # Run search workflow
        workflow = SearchWorkflow(logger)
        workflow.run(app_config)

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
