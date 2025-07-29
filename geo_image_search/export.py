"""Export functionality for CSV and KML formats."""

import csv
import logging
import os
from pathlib import Path
from typing import List, Dict

try:
    from fastkml.kml import KML
    from fastkml.containers import Document, Folder
    from fastkml.views import LookAt
    from fastkml.features import Placemark
    from pygeoif.geometry import Point
    KML_AVAILABLE = True
except ImportError:
    KML_AVAILABLE = False
    KML = None
    Document = None
    Folder = None
    LookAt = None
    Placemark = None
    Point = None

from .exceptions import FileOperationError
from .types import ImageData
from .utils import PathNormalizer


class ExportManager:
    """Base class for export functionality."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.path_normalizer = PathNormalizer()


class CSVExporter(ExportManager):
    """Handles CSV export functionality."""
    
    def export_image_addresses(self, csv_data: List[Dict], output_directory: str) -> bool:
        """Export collected image address data to CSV file."""
        if not csv_data:
            self.logger.info("No GPS data found in images for CSV export.")
            return False

        if output_directory == "Do Not Save":
            self.logger.warning("Cannot export CSV in find-only mode.")
            return False

        csv_path = os.path.join(output_directory, "image_addresses.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = ["filename", "path", "latitude", "longitude", "address"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_data)

            self.logger.info(f"Exported {len(csv_data)} image addresses to {csv_path}")
            return True
        except (OSError, IOError) as e:
            self.logger.error(f"Error writing CSV file: {e}")
            return False


class KMLExporter(ExportManager):
    """Handles KML export functionality."""
    
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        if not KML_AVAILABLE:
            self.logger.warning("KML export not available. Install 'fastkml' and 'shapely' packages.")
    
    def build_kml_from_image_data(
        self, 
        image_data_list: List[ImageData], 
        center_coords: tuple[float, float] | None = None, 
        folder_name: str = "Images"
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
        if not KML_AVAILABLE:
            raise ImportError("KML export not available. Install 'fastkml' and 'shapely' packages.")
        
        if not image_data_list:
            raise ValueError("No image data provided for KML export")
        
        # Create KML document
        k = KML()
        
        # Create document
        doc = Document(
            id="geo_image_search_results",
            name="Geo Image Search Results",
            description="GPS-tagged images exported from folder",
        )
        k.append(doc)
        
        # Create folder for images
        images_folder = Folder(
            name=folder_name,
            description=f"Found {len(image_data_list)} GPS-tagged images",
        )
        doc.append(images_folder)
        
        # Add center point if provided
        if center_coords:
            lookat = LookAt(
                range=200, latitude=center_coords[0], longitude=center_coords[1]
            )
            center_point = Placemark(
                name="Center Point",
                description=f"Center at {center_coords[0]:.6f}, {center_coords[1]:.6f}",
                geometry=Point(center_coords[1], center_coords[0], 0),  # lon, lat
                view=lookat,
            )
            images_folder.append(center_point)
        
        # Add each image as a placemark
        for i, img_data in enumerate(image_data_list, 1):
            description_parts = [f"<![CDATA[Image {i}"]
            
            # Add date if available
            if img_data.get("date_taken"):
                description_parts.append(f"<br/>Date: {img_data['date_taken']}")
            
            # Add image preview
            description_parts.append(f'<br/><img style="max-width:500px;" src="file:///{self.path_normalizer.get_kml_image_path(img_data["path"])}">]]>')
            
            description = "".join(description_parts)
            
            longi = float(img_data["longitude"])
            lati = float(img_data["latitude"])
            lookat = LookAt(range=50, latitude=lati, longitude=longi)
            
            k_point = Placemark(
                name=img_data["filename"],
                description=description,
                geometry=Point(longi, lati, 0),
                view=lookat,
            )
            images_folder.append(k_point)
        
        return k.to_string(prettyprint=True)
    
    def export_kml_from_folder(
        self, 
        folder_path: str, 
        output_kml_path: str | None = None, 
        recursive: bool = True,
        gps_processor = None
    ) -> bool:
        """
        Generate KML from all GPS-tagged images in a folder.
        
        Args:
            folder_path: Path to folder containing images
            output_kml_path: Optional output path for KML file
            recursive: Whether to search subfolders recursively
            gps_processor: GPS processor for extracting image data
            
        Returns:
            True if successful, False otherwise
        """
        if not KML_AVAILABLE:
            self.logger.warning("KML export not available. Install 'fastkml' and 'shapely' packages.")
            return False
        
        if not gps_processor:
            self.logger.error("GPS processor is required for KML export")
            return False
        
        folder_path = self.path_normalizer.normalize_path(folder_path)
        if not os.path.exists(folder_path):
            self.logger.error(f"Folder does not exist: {folder_path}")
            return False
        
        self.logger.info(f"Scanning folder for GPS-tagged images: {folder_path}")
        
        # Collect all image data
        image_data_list = []
        files_processed = 0
        
        if recursive:
            # Walk through all subdirectories
            for dirpath, _, filenames in os.walk(folder_path):
                for filename in filenames:
                    if gps_processor._is_jpeg_file(filename):
                        image_path = os.path.join(dirpath, filename)
                        files_processed += 1
                        
                        self.logger.info(f"Processing: {image_path}")
                        
                        gps_data = gps_processor.extract_image_gps_data(image_path)
                        if gps_data:
                            image_data_list.append(gps_data)
        else:
            # Only scan the specified folder (not subdirectories)
            try:
                for filename in os.listdir(folder_path):
                    if gps_processor._is_jpeg_file(filename):
                        image_path = os.path.join(folder_path, filename)
                        files_processed += 1
                        
                        self.logger.info(f"Processing: {image_path}")
                        
                        gps_data = gps_processor.extract_image_gps_data(image_path)
                        if gps_data:
                            image_data_list.append(gps_data)
            except (OSError, PermissionError) as e:
                self.logger.error(f"Error accessing folder: {e}")
                return False
        
        self.logger.info(f"Processed {files_processed} image files")
        self.logger.info(f"Found {len(image_data_list)} images with GPS data")
        
        if not image_data_list:
            self.logger.info("No GPS-tagged images found in the specified folder.")
            return False
        
        # Calculate center point (centroid of all images)
        total_lat = sum(img["latitude"] for img in image_data_list)
        total_lon = sum(img["longitude"] for img in image_data_list)
        center_coords = (total_lat / len(image_data_list), total_lon / len(image_data_list))
        
        self.logger.info(f"Calculated center point: {center_coords[0]:.6f}, {center_coords[1]:.6f}")
        
        # Generate KML content
        try:
            folder_name = os.path.basename(folder_path) or "Images"
            kml_content = self.build_kml_from_image_data(image_data_list, center_coords, folder_name)
            
            # Determine output path
            if output_kml_path:
                kml_path = Path(output_kml_path)
            else:
                safe_folder_name = self.path_normalizer.sanitize_folder_name(folder_name)
                kml_path = Path.cwd() / f"{safe_folder_name}_images.kml"
            
            # Write KML file
            with open(kml_path, "w", encoding="utf-8") as f:
                f.write(kml_content)
            
            self._fix_cdata_in_kml(kml_path)
            self.logger.info(f"KML file created: {kml_path}")
            self.logger.info(f"Exported {len(image_data_list)} GPS-tagged images to KML")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating KML file: {e}")
            return False
    
    def _fix_cdata_in_kml(self, kml_path: Path):
        """Fix CDATA encoding in KML file."""
        try:
            with open(kml_path, "r", encoding="utf-8") as f:
                kml_content = f.read()
            kml_content = kml_content.replace("&lt;", "<").replace("&gt;", ">")
            with open(kml_path, "w", encoding="utf-8") as f:
                f.write(kml_content)
        except (OSError, IOError) as e:
            self.logger.warning(f"Could not fix CDATA in KML file: {e}")