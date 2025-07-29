"""Main application module for geo image search."""

import logging
import sys
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
    """
    Manages the end-to-end workflow for searching and processing geotagged images
        within a directory tree.

    This class coordinates the initialization of processing components,
        scanning directories for images, extracting GPS data, filtering images by location,
        handling checkpoints for resumable processing, exporting results (CSV/KML),
        and optionally copying found images to an output directory.

    Attributes:
        logger (logging.Logger): Logger for workflow events and errors.
        gps_processor (GPSImageProcessor | None): Extracts GPS data from images.
        search_engine (LocationSearchEngine | None): Determines if images
            are within the search radius.
        clustering_engine (ClusteringEngine | None): Groups images by location for organization.
        checkpoint_manager (CheckpointManager | None): Manages checkpointing for
            resumable processing.
        csv_exporter (CSVExporter | None): Exports image data to CSV files.
        kml_exporter (KMLExporter | None): Exports image data to KML files.
        file_manager (FileOperationManager | None): Handles file copying operations.

    Methods:
        run(app_config: ApplicationConfig):
            Executes the main workflow: initializes components, scans directories, processes images,
            exports results, copies files, and manages checkpoints.

        _initialize_components(filter_config, search_config):
            Initializes all required workflow components.

        _validate_directories(directory_config):
            Validates the root directory configuration and returns its path.

        _handle_checkpoint_resume(processing_config):
            Loads checkpoint data if resuming, returning a set of already processed files.

        _scan_and_process_images(root_path, directory_config, output_config, processed_files_set):
            Scans the directory tree, processes images, and returns a list of found images.

        _should_skip_directory(current_dir, directory_config):
            Determines if a directory should be skipped during scanning.

        _should_process_file(file_path, processed_files_set):
            Determines if a file should be processed based on type and checkpoint status.

        _process_image_file(file_path, output_config):
            Processes a single image file, returning image data if it matches search criteria.

        _handle_checkpoint_saving(total_processed, file_id):
            Periodically saves checkpoint data during processing.

        _handle_exports(found_images, directory_config, output_config):
            Handles exporting results to CSV and KML formats.

        _copy_files_if_needed(found_images, directory_config):
            Copies found images to the output directory, optionally organizing by location clusters.
    """

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
        """
        Executes the main workflow for the geo image search application.

        This method performs the following steps:
        1. Initializes required components using the provided application configuration.
        2. Validates and sets up necessary directories for processing.
        3. Handles checkpoint resume logic to continue from previous state if applicable.
        4. Scans and processes images based on the configuration and previously processed files.
        5. Handles the case where no matching images are found, logging appropriate messages.
        6. Processes and exports the results of the image search.
        7. Copies found image files to the output directory if required.
        8. Clears the checkpoint and logs completion status.

        Args:
            app_config (ApplicationConfig): The configuration object containing all necessary
                parameters for filtering, searching, directory paths, output settings,
                and processing options.

        Returns:
            None
        """

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
        """
        Initializes core components required for geo image search operations.

        Args:
            filter_config (dict): Configuration parameters for filtering GPS images.
            search_config (dict): Configuration parameters for location search.

        Initializes the following components:
            - GPSImageProcessor: Processes images with GPS data using the provided
                filter configuration.
            - LocationSearchEngine: Handles location-based search operations using the provided
                search configuration.
            - ClusteringEngine: Manages clustering of location data.
            - CheckpointManager: Handles checkpointing for process recovery.
            - CSVExporter: Exports search results to CSV format.
            - KMLExporter: Exports search results to KML format.
            - FileOperationManager: Manages file operations related to the search process.

        Also initializes the search location in the LocationSearchEngine.
        """

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
        """
        Validates the existence of the root directory specified in the directory configuration.

        Args:
            directory_config: An object containing directory configuration, expected to have a
                'root' attribute.

        Returns:
            Path: A Path object representing the validated root directory.

        Raises:
            SystemExit: If the root directory is not specified or does not exist, logs an error and
                exits the program with an appropriate error code.
        """
        if not directory_config.root:
            self.logger.error("Root directory not specified")
            sys.exit(Constants.ErrorCodes.NO_ROOT_DIRECTORY)

        root_path = Path(directory_config.root)
        if not root_path.exists():
            self.logger.error(f"Root directory does not exist: {root_path}")
            sys.exit(Constants.ErrorCodes.ROOT_DIRECTORY_NOT_FOUND)

        return root_path

    def _handle_checkpoint_resume(self, processing_config):
        """
        Handles resuming from a checkpoint by loading the set of already processed files.

        Args:
            processing_config: An object containing configuration for processing,
                including whether to resume from a checkpoint.

        Returns:
            set: A set of filenames that have already been processed, as recorded in the checkpoint.
        """
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
        """
        Scans the specified root directory and its subdirectories for image files, processes them,
        and returns a list of images matching the search criteria.

        Args:
            root_path (Path): The root directory to scan for images.
            directory_config (dict): Configuration for directory scanning, including directories to
                skip.
            output_config (dict): Configuration for output processing.
            processed_files_set (set): Set of file paths that have already been processed.

        Returns:
            list[ImageData]: A list of ImageData objects representing images that match the search
                criteria.
        """
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
        """
        Determines whether the given directory should be skipped based on the output
            directory configuration.

        Args:
            current_dir (Path): The current directory being processed.
            directory_config (object): Configuration object containing the output
                directory information.

        Returns:
            bool: True if the current directory should be skipped (i.e., it is within the output
                directory), False otherwise.
        """
        if directory_config.output_directory and directory_config.output_directory != "Do Not Save":
            try:
                output_path = Path(directory_config.output_directory)
                if current_dir.is_relative_to(output_path):
                    return True
            except (ValueError, OSError):
                pass
        return False

    def _should_process_file(self, file_path, processed_files_set):
        """
        Determines whether a given file should be processed based on several criteria.
        Args:
            file_path (Path): The path to the file to check.
            processed_files_set (set): A set containing identifiers of files that have
                already been processed.
        Returns:
            bool: True if the file should be processed; False otherwise.
        Criteria for processing:
            - The file must exist and be a file.
            - The file's extension must be one of the allowed JPEG extensions.
            - The file must not have been processed already (not present in processed_files_set).
        """

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
        """
        Processes an image file to extract GPS data and determine if it is within the search radius.

        Args:
            file_path (str or Path): The path to the image file to process.
            output_config (object): Configuration object containing output options,
                such as verbosity.

        Returns:
            dict or None: A dictionary containing image GPS data if the image is within
                the search radius, otherwise None. Returns None if GPS data
                cannot be extracted or an error occurs.

        Raises:
            AssertionError: If required components (gps_processor, search_engine)
                are not initialized.
        """
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

        except (OSError, IOError, PermissionError) as e:
            if output_config.verbose:
                self.logger.warning(f"File I/O error processing {file_path}: {e}")
        except (ValueError, TypeError) as e:
            if output_config.verbose:
                self.logger.warning(f"Data processing error for {file_path}: {e}")

        return None

    def _handle_checkpoint_saving(self, total_processed, file_id):
        """
        Handles the saving of checkpoints during file processing.

        This method asserts that the checkpoint manager is initialized, and saves a checkpoint
        if the total number of processed files is a multiple of the defined checkpoint interval.

        Args:
            total_processed (int): The total number of files processed so far.
            file_id (Any): The identifier of the current file being processed.

        Raises:
            AssertionError: If the checkpoint manager is not initialized.
        """
        assert self.checkpoint_manager is not None, "Components must be initialized first"
        if total_processed % Constants.CHECKPOINT_INTERVAL_FILES == 0:
            self.checkpoint_manager.save_checkpoint([file_id], total_processed)

    def _handle_exports(self, found_images, directory_config, output_config):
        """
        Handles the export of image search results based on the provided configuration.

        This method performs the following actions:
        - Clusters images by location if requested in the directory configuration.
        - Exports image addresses to a CSV file if enabled in the output configuration.
        - Generates and saves a KML file containing image data and search coordinates if requested.

        Args:
            found_images (list): List of image data objects found during the search.
            directory_config (DirectoryConfig): Configuration object specifying
                directory and sorting options.
            output_config (OutputConfig): Configuration object specifying export options (CSV, KML).

        Raises:
            AssertionError: If required components (clustering engine, CSV exporter, KML
                exporter, search engine) are not initialized.
        """
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
        """
        Copies found images to the specified output directory if required by the configuration.

        Depending on the directory configuration, images can be organized by location
            clusters or copied directly. If 'find_only' is True or no output directory
            is specified, no files are copied.

        Args:
            found_images (list): List of image file paths or image objects found during search.
            directory_config (DirectoryConfig): Configuration object specifying output directory,
                sorting, and other options.

        Returns:
            None
        """
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
            except (OSError, IOError, PermissionError) as e:
                logger.error("Folder KML export failed - file I/O error: %s", e)
                sys.exit(Constants.ErrorCodes.FILE_OPERATION_ERROR)
            except (ConfigurationError, ValueError) as e:
                logger.error("Folder KML export failed - configuration error: %s", e)
                sys.exit(Constants.ErrorCodes.CONFIGURATION_ERROR)
            except FileOperationError as e:
                logger.error("Folder KML export failed - file operation error: %s", e)
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
        logger.error("Configuration error: %s", e)
        sys.exit(Constants.ErrorCodes.CONFLICTING_OPTIONS)
    except GPSDataError as e:
        logger.error("GPS data error: %s", e)
        sys.exit(Constants.ErrorCodes.GPS_DATA_ERROR)
    except FileOperationError as e:
        logger.error("File operation error: %s", e)
        sys.exit(Constants.ErrorCodes.FILE_OPERATION_ERROR)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Unexpected error: %s", e)
        sys.exit(Constants.ErrorCodes.GENERAL_ERROR)


if __name__ == "__main__":
    main()
