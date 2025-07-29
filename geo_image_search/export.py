"""Export functionality for CSV and KML formats."""

import csv
import logging
import os
from pathlib import Path
from typing import List

from .constants import Constants

from fastkml.kml import KML
from fastkml.containers import Document, Folder
from fastkml.views import LookAt
from fastkml.features import Placemark
from pygeoif.geometry import Point

from .types import ImageData
from .utils import PathNormalizer


class ExportManager:
    """
    Manages export operations for geo image search functionality.

    Attributes:
        logger (logging.Logger): Logger instance for logging export-related events.
        path_normalizer (PathNormalizer): Utility for normalizing file system paths.

    Args:
        logger (logging.Logger): Logger to be used for export operations.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.path_normalizer = PathNormalizer()


class CSVExporter(ExportManager):
    """
    Handles exporting image address data to a CSV file.

    This class extends ExportManager and provides functionality to export
    a list of image metadata (including GPS coordinates and address information)
    to a CSV file in a specified output directory.

    Methods
    -------
    export_image_addresses(csv_data: List[ImageData], output_directory: str) -> bool
        Exports the provided image data to a CSV file named 'image_addresses.csv'
        in the given output directory. Returns True if export is successful,
        otherwise returns False.
    """

    def export_image_addresses(self, csv_data: List[ImageData], output_directory: str) -> bool:
        """
        Exports image address data to a CSV file in the specified output directory.

        Args:
            csv_data (List[ImageData]): A list of ImageData objects containing image
                                        metadata and address information.
            output_directory (str): The directory where the CSV file will be saved.

        Returns:
            bool: True if the export was successful, False otherwise.

        Notes:
            - If csv_data is empty, the method logs an info message and returns False.
            - If output_directory is set to "Do Not Save", the method logs a
                    warning and returns False.
            - The CSV file is named "image_addresses.csv" and contains the following columns:
              "filename", "path", "latitude", "longitude", "date_taken", "address".
            - Any errors during file writing are logged and the method returns False.
        """

        if not csv_data:
            self.logger.info("No GPS data found in images for CSV export.")
            return False

        if output_directory == "Do Not Save":
            self.logger.warning("Cannot export CSV in find-only mode.")
            return False

        csv_path = os.path.join(output_directory, "image_addresses.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = ["filename", "path", "latitude", "longitude", "date_taken", "address"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_data)

            self.logger.info(f"Exported {len(csv_data)} image addresses to {csv_path}")
            return True
        except (OSError, IOError) as e:
            self.logger.error(f"Error writing CSV file: {e}")
            return False


class KMLExporter(ExportManager):
    """KMLExporter is a class for exporting GPS-tagged image data to KML (Keyhole Markup Language)
        files.

    This class provides methods to:
    - Build KML content from a list of image metadata, including image previews and location points.
    - Export KML files from a folder containing GPS-tagged JPEG images, optionally scanning
        subfolders.
    - Calculate the geographic center (centroid) of all images for map centering.
    - Normalize and sanitize file paths for KML compatibility.
    - Fix CDATA encoding issues in generated KML files.

    Inheritance:
        ExportManager

        logger (logging.Logger): Logger instance for logging export operations.

    Methods:
        build_kml_from_image_data(image_data_list, center_coords=None, folder_name="Images"):

        export_kml_from_folder(folder_path, output_kml_path=None,
                                recursive=True, gps_processor=None):
            Generate and export a KML file from all GPS-tagged images in a folder.

        _fix_cdata_in_kml(kml_path):
            Internal method to fix CDATA encoding in the generated KML file.
    """

    def build_kml_from_image_data(
        self,
        image_data_list: List[ImageData],
        center_coords: tuple[float, float] | None = None,
        folder_name: str = "Images",
    ) -> str:
        """
        Build KML content from a list of image data.

        Args:
            image_data_list: List of ImageData dictionaries
            center_coords: Optional tuple of (lat, lon) for search center point
            folder_name: Name for the KML folder

        Returns:
            KML content as string
        """
        if not image_data_list:
            raise ValueError("No image data provided for KML export")

        kml_doc, images_folder = self._create_kml_document_structure(
            folder_name, len(image_data_list)
        )

        if center_coords:
            self._add_center_point_placemark(images_folder, center_coords)

        self._add_image_placemarks(images_folder, image_data_list)

        return kml_doc.to_string(prettyprint=True)

    def _create_kml_document_structure(
        self, folder_name: str, image_count: int
    ) -> tuple[KML, Folder]:
        """
        Creates the basic KML document structure for exporting GPS-tagged images.
        Args:
            folder_name (str): The name of the folder to be used in the KML structure.
            image_count (int): The number of GPS-tagged images to include in the folder description.
        Returns:
            tuple[KML, Folder]: A tuple containing the root KML object and the Folder object
                where image placemarks can be appended.
        """
        kml_doc = KML()

        doc = Document(
            id="geo_image_search_results",
            name="Geo Image Search Results",
            description="GPS-tagged images exported from folder",
        )
        kml_doc.append(doc)

        images_folder = Folder(
            name=folder_name,
            description=f"Found {image_count} GPS-tagged images",
        )
        doc.append(images_folder)

        return kml_doc, images_folder

    def _add_center_point_placemark(
        self, images_folder: Folder, center_coords: tuple[float, float]
    ) -> None:
        """
        Adds a placemark representing the center point to the specified KML folder.
        This placemark is labeled "Center Point" and is positioned at the given
        latitude and longitude. It includes a description with the coordinates and
        sets the KML view to focus on this point.
        Args:
            images_folder (Folder): The KML folder to which the center point placemark
                will be added.
            center_coords (tuple[float, float]): A tuple containing the latitude and longitude of
                the center point.
        Returns:
            None
        """

        lookat = LookAt(
            range=Constants.KML_CENTER_VIEW_RANGE,
            latitude=center_coords[0],
            longitude=center_coords[1],
        )
        center_point = Placemark(
            name="Center Point",
            description=f"Center at {center_coords[0]:.6f}, {center_coords[1]:.6f}",
            geometry=Point(center_coords[1], center_coords[0], 0),  # lon, lat
            view=lookat,
        )
        images_folder.append(center_point)

    def _add_image_placemarks(
        self, images_folder: Folder, image_data_list: List[ImageData]
    ) -> None:
        """
        Adds image placemarks to the specified folder.

        Iterates over a list of ImageData objects, creates a placemark for each image,
        and appends it to the provided images_folder.

        Args:
            images_folder (Folder): The folder to which image placemarks will be added.
            image_data_list (List[ImageData]): A list of ImageData objects representing images to
                be added as placemarks.

        Returns:
            None
        """
        for i, img_data in enumerate(image_data_list, 1):
            placemark = self._create_image_placemark(img_data, i)
            images_folder.append(placemark)

    def _create_image_placemark(self, img_data: ImageData, image_number: int) -> Placemark:
        """
        Creates a KML Placemark object for a given image, including its location and view settings.

        Args:
            img_data (ImageData): A dictionary containing image metadata, including 'filename',
                'longitude', and 'latitude'.
            image_number (int): The sequential number of the image.

        Returns:
            Placemark: A KML Placemark object representing the image's location and view.
        """

        description = self._build_image_description(img_data, image_number)

        longi = float(img_data["longitude"])
        lati = float(img_data["latitude"])
        lookat = LookAt(range=Constants.KML_POINT_VIEW_RANGE, latitude=lati, longitude=longi)

        return Placemark(
            name=img_data["filename"],
            description=description,
            geometry=Point(longi, lati, 0),
            view=lookat,
        )

    def _build_image_description(self, img_data: ImageData, image_number: int) -> str:
        """
        Builds an HTML-formatted image description for KML export.

        The description includes the image number, the date taken (if available),
        and an embedded image with a maximum width of 500px. The content is wrapped
        in a CDATA section for safe inclusion in KML files.

        Args:
            img_data (ImageData): Dictionary-like object containing image metadata.
            image_number (int): The sequential number of the image.

        Returns:
            str: The formatted image description as an HTML string.
        """

        description_parts = [f"<![CDATA[Image {image_number}"]

        if img_data.get("date_taken"):
            description_parts.append(f"<br/>Date: {img_data['date_taken']}")

        description_parts.append(
            '<br/><img style="max-width:500px;" src="'
            f'{self.path_normalizer.get_kml_image_path(img_data["path"])}">]]>'
        )

        return "".join(description_parts)

    def export_kml_from_folder(
        self,
        folder_path: str,
        output_kml_path: str | None = None,
        recursive: bool = True,
        gps_processor=None,
    ) -> bool:
        """
        Exports GPS-tagged images from a specified folder to a KML file.

        Scans the given folder (optionally recursively) for images containing GPS metadata,
        processes their location data, and generates a KML file representing their positions.
        The KML file is saved to the specified output path or a default location.

        Args:
            folder_path (str): Path to the folder containing images to scan.
            output_kml_path (str | None, optional): Path to save the generated KML file. If None,
                                                    a default path is used.
            recursive (bool, optional): Whether to scan subfolders recursively. Defaults to True.
            gps_processor (optional): An object or function to process GPS metadata from images.

        Returns:
            bool: True if the KML export was successful, False otherwise.
        """
        if not self._validate_folder_export_inputs(gps_processor, folder_path):
            return False

        folder_path = self.path_normalizer.normalize_path(folder_path)
        self.logger.info(f"Scanning folder for GPS-tagged images: {folder_path}")

        image_data_list = self._collect_image_data(folder_path, recursive, gps_processor)
        if not image_data_list:
            return False

        center_coords = self._calculate_center_point(image_data_list)
        return self._generate_and_save_kml(
            image_data_list, center_coords, folder_path, output_kml_path
        )

    def _validate_folder_export_inputs(self, gps_processor, folder_path: str) -> bool:
        """
        Validates the inputs required for exporting data to a folder.

        Args:
            gps_processor: The GPS processor object required for KML export.
            folder_path (str): The path to the folder where data will be exported.

        Returns:
            bool: True if the inputs are valid, False otherwise. Logs errors if validation fails.
        """

        if not gps_processor:
            self.logger.error("GPS processor is required for KML export")
            return False

        normalized_path = self.path_normalizer.normalize_path(folder_path)
        if not os.path.exists(normalized_path):
            self.logger.error(f"Folder does not exist: {normalized_path}")
            return False

        return True

    def _collect_image_data(
        self, folder_path: str, recursive: bool, gps_processor
    ) -> List[ImageData]:
        """
        Collects image data from a specified folder, optionally processing subfolders recursively,
        and extracts GPS information using the provided GPS processor.

        Args:
            folder_path (str): The path to the folder containing image files.
            recursive (bool): Whether to process subfolders recursively.
            gps_processor: An object or function responsible for extracting GPS data from images.

        Returns:
            List[ImageData]: A list of ImageData objects containing information
                                about images with GPS data.
        """

        image_data_list = []
        files_processed = 0

        if recursive:
            files_processed = self._process_folder_recursively(
                folder_path, gps_processor, image_data_list
            )
        else:
            files_processed = self._process_folder_non_recursively(
                folder_path, gps_processor, image_data_list
            )

        self.logger.info(f"Processed {files_processed} image files")
        self.logger.info(f"Found {len(image_data_list)} images with GPS data")

        if not image_data_list:
            self.logger.info("No GPS-tagged images found in the specified folder.")

        return image_data_list

    def _process_folder_recursively(
        self, folder_path: str, gps_processor, image_data_list: List[ImageData]
    ) -> int:
        """
        Recursively processes all JPEG images in the specified folder and its subfolders.

        Args:
            folder_path (str): The path to the root folder to search for images.
            gps_processor: An object responsible for determining JPEG files and processing GPS data.
            image_data_list (List[ImageData]): A list to store processed image data.

        Returns:
            int: The total number of JPEG files processed.
        """
        files_processed = 0
        for dirpath, _, filenames in os.walk(folder_path):
            for filename in filenames:
                if gps_processor.is_jpeg_file(filename):
                    image_path = os.path.join(dirpath, filename)
                    files_processed += 1
                    self._process_single_image(image_path, gps_processor, image_data_list)
        return files_processed

    def _process_folder_non_recursively(
        self, folder_path: str, gps_processor, image_data_list: List[ImageData]
    ) -> int:
        """
        Processes JPEG image files in the specified folder (non-recursively), extracting GPS data
            and appending results to the provided image data list.
        Args:
            folder_path (str): Path to the folder containing image files.
            gps_processor: An object responsible for identifying JPEG files and extracting GPS data.
            image_data_list (List[ImageData]): A list to which processed image data
                will be appended.
        Returns:
            int: The number of JPEG files successfully processed.
        Logs:
            Errors encountered while accessing the folder are logged.
        """
        files_processed = 0
        try:
            for filename in os.listdir(folder_path):
                if gps_processor.is_jpeg_file(filename):
                    image_path = os.path.join(folder_path, filename)
                    files_processed += 1
                    self._process_single_image(image_path, gps_processor, image_data_list)
        except (OSError, PermissionError) as e:
            self.logger.error(f"Error accessing folder: {e}")
        return files_processed

    def _process_single_image(
        self, image_path: str, gps_processor, image_data_list: List[ImageData]
    ) -> None:
        """
        Processes a single image by extracting its GPS data and appending it to the
            provided image data list.

        Args:
            image_path (str): The file path to the image to be processed.
            gps_processor: An object responsible for extracting GPS data from the image.
            image_data_list (List[ImageData]): A list to which the extracted
                GPS data will be appended.

        Returns:
            None
        """
        self.logger.info(f"Processing: {image_path}")
        gps_data = gps_processor.extract_image_gps_data(image_path)
        if gps_data:
            image_data_list.append(gps_data)

    def _calculate_center_point(self, image_data_list: List[ImageData]) -> tuple[float, float]:
        """
        Calculates the geographic center point (average latitude and longitude)
            from a list of image data.

        Args:
            image_data_list (List[ImageData]): A list of image data dictionaries, each
                containing 'latitude' and 'longitude' keys.

        Returns:
            tuple[float, float]: A tuple containing the average latitude and longitude.

        Logs:
            The calculated center point coordinates at info level.
        """

        total_lat = sum(img["latitude"] for img in image_data_list)
        total_lon = sum(img["longitude"] for img in image_data_list)
        center_coords = (total_lat / len(image_data_list), total_lon / len(image_data_list))

        self.logger.info(f"Calculated center point: {center_coords[0]:.6f}, {center_coords[1]:.6f}")
        return center_coords

    def _generate_and_save_kml(
        self,
        image_data_list: List[ImageData],
        center_coords: tuple[float, float],
        folder_path: str,
        output_kml_path: str | None,
    ) -> bool:
        """
        Generates a KML file from a list of image data and saves it to disk.

        Args:
            image_data_list (List[ImageData]): List of image data objects
                containing GPS information.
            center_coords (tuple[float, float]): Latitude and longitude
                coordinates for the map center.
            folder_path (str): Path to the folder containing the images.
            output_kml_path (str | None): Optional path for the output KML file. If
                 None, a default path is used.

        Returns:
            bool: True if the KML file was successfully created and saved, False otherwise.

        Raises:
            Logs errors for file I/O issues or invalid data, but does not propagate exceptions.
        """
        try:
            folder_name = os.path.basename(folder_path) or "Images"
            kml_content = self.build_kml_from_image_data(
                image_data_list, center_coords, folder_name
            )

            kml_path = self._determine_output_path(output_kml_path, folder_name)
            self._write_kml_file(kml_path, kml_content)

            self.logger.info(f"KML file created: {kml_path}")
            self.logger.info(f"Exported {len(image_data_list)} GPS-tagged images to KML")
            return True

        except (OSError, IOError, PermissionError) as e:
            self.logger.error(f"Error creating KML file: {e}")
            return False
        except ValueError as e:
            self.logger.error(f"Invalid data for KML generation: {e}")
            return False

    def _determine_output_path(self, output_kml_path: str | None, folder_name: str) -> Path:
        """
        Determines the output file path for the KML file.

        If `output_kml_path` is provided, returns its Path. Otherwise, generates a safe file name
        based on the given `folder_name`, sanitizes it, and appends '_images.kml' to the current
        working directory.

        Args:
            output_kml_path (str | None): The explicit path to the output KML file, if provided.
            folder_name (str): The name of the folder to use for generating the output file name.

        Returns:
            Path: The resolved output path for the KML file.
        """

        if output_kml_path:
            return Path(output_kml_path)

        safe_folder_name = self.path_normalizer.sanitize_folder_name(folder_name)
        return Path.cwd() / f"{safe_folder_name}_images.kml"

    def _write_kml_file(self, kml_path: Path, kml_content: str) -> None:
        """
        Writes the provided KML content to a file at the specified path and applies CDATA fixes.

        Args:
            kml_path (Path): The path where the KML file will be written.
            kml_content (str): The KML content to write to the file.

        Returns:
            None
        """

        with open(kml_path, "w", encoding="utf-8") as f:
            f.write(kml_content)
        self._fix_cdata_in_kml(kml_path)

    def _fix_cdata_in_kml(self, kml_path: Path):
        """
        Fixes CDATA sections in a KML file by replacing escaped angle brackets (&lt; and &gt;)
        with their literal counterparts (< and >).

        Args:
            kml_path (Path): The path to the KML file to be fixed.

        Side Effects:
            Modifies the KML file in place, replacing escaped angle brackets.

        Exceptions:
            Logs a warning if the file cannot be read or written due to an OSError or IOError.
        """

        try:
            with open(kml_path, "r", encoding="utf-8") as f:
                kml_content = f.read()
            kml_content = kml_content.replace("&lt;", "<").replace("&gt;", ">")
            with open(kml_path, "w", encoding="utf-8") as f:
                f.write(kml_content)
        except (OSError, IOError) as e:
            self.logger.warning(f"Could not fix CDATA in KML file: {e}")
