"""Geographic clustering functionality for images."""

import logging
import json
from pathlib import Path
from datetime import datetime

from geopy.distance import distance
from geopy.geocoders import Nominatim

from .constants import Constants
from .types import ImageData


class ClusteringEngine:
    """Handles geographic clustering of images."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

        if not distance or not Nominatim:
            raise ImportError(
                "geopy library is required for clustering. Install with: pip install geopy"
            )

    def cluster_images_by_location(
        self, image_data_list: list[ImageData], cluster_radius: float = 0.1
    ) -> dict[str, list[ImageData]]:
        """
        Groups images into location-based clusters using geographic coordinates.
        Each image is assigned to a cluster if its location is within `cluster_radius` miles
        of an existing cluster center. Otherwise, a new cluster is created for the image.
        Images without valid latitude or longitude are skipped.
        Args:
            image_data_list (list[ImageData]): List of image metadata dictionaries, each containing
                'latitude' and 'longitude' keys.
            cluster_radius (float, optional): Maximum distance in miles to consider images as part
                of the same cluster. Defaults to 0.1.
        Returns:
            dict[str, list[ImageData]]: Dictionary mapping cluster names to lists of image data
                belonging to each cluster.
        """
        # Ensure geopy is available (checked in __init__)
        assert distance is not None, "geopy.distance should be available"

        clusters: dict[str, list[ImageData]] = {}
        cluster_centers: list[tuple[float, float, str]] = []

        for img_data in image_data_list:
            if img_data["latitude"] is None or img_data["longitude"] is None:
                continue

            img_location = (img_data["latitude"], img_data["longitude"])

            # Find existing cluster within radius
            assigned_cluster = None
            for center_lat, center_lon, cluster_name in cluster_centers:
                center_location = (center_lat, center_lon)
                distance_obj = distance(img_location, center_location)
                distance_miles = distance_obj.miles

                if distance_miles <= cluster_radius:
                    assigned_cluster = cluster_name
                    break

            # Create new cluster if none found
            if assigned_cluster is None:
                cluster_name = self._generate_cluster_name(img_location, len(cluster_centers))
                cluster_centers.append((img_data["latitude"], img_data["longitude"], cluster_name))
                assigned_cluster = cluster_name
                clusters[assigned_cluster] = []

            clusters[assigned_cluster].append(img_data)

        self.logger.info(f"Created {len(clusters)} location clusters")
        return clusters

    def _generate_cluster_name(self, location: tuple[float, float], cluster_index: int) -> str:
        """
        Generates a human-readable name for a cluster based on its geographic location.

        Attempts to reverse geocode the cluster center coordinates to obtain a location name
        (e.g., city, town, village, county, or state). If successful, returns a name based on
        the first available address component. If reverse geocoding fails or no suitable address
        component is found, falls back to a name based on the cluster index and coordinates.

        Args:
            location (tuple[float, float]): The (latitude, longitude) of the cluster center.
            cluster_index (int): The index of the cluster for uniqueness.

        Returns:
            str: A name for the cluster, either based on location or coordinates.
        """

        # Ensure geopy is available (checked in __init__)
        assert Nominatim is not None, "geopy.geocoders.Nominatim should be available"

        lat, lon = location

        # Try to get address for cluster center
        try:
            geolocator = Nominatim(user_agent=Constants.DEFAULT_USER_AGENT)
            location_info = geolocator.reverse(
                location, timeout=Constants.GEOCODING_TIMEOUT_SECONDS
            )

            if location_info and location_info.raw.get("address"):
                address = location_info.raw["address"]

                # Build name from address components
                name_parts = []
                for component in ["city", "town", "village", "county", "state"]:
                    if component in address:
                        name_parts.append(address[component])
                        break

                if name_parts:
                    return f"Cluster_{name_parts[0].replace(' ', '_')}"

        except (OSError, IOError, ConnectionError, TimeoutError) as e:
            # Network/connectivity errors (timeout, connection refused, etc.)
            self.logger.debug(f"Network error getting address for cluster center: {e}")
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            # Data parsing errors (missing keys, wrong data types, invalid data)
            self.logger.debug(f"Data parsing error for cluster center address: {e}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Catch any other unexpected errors but log them as warnings since they're unexpected
            self.logger.warning(f"Unexpected error getting address for cluster center: {e}")
            # Still fallback gracefully

        # Fallback to coordinate-based name with index for uniqueness
        return f"Cluster_{cluster_index}_{lat:.3f}_{lon:.3f}"


class CheckpointManager:
    """
    CheckpointManager handles saving, loading, and clearing progress checkpoints for file
        processing tasks.

    This class provides methods to persist the state of processed files and total file
    count to a JSON checkpoint file, allowing tasks to resume from the last saved state
    in case of interruptions. It also manages error handling and logging
    for file system and data serialization issues.

    Attributes:
        logger (logging.Logger): Logger instance for recording events and errors.
        checkpoint_file (str): Path to the checkpoint file (default: "geo_search_checkpoint.json").

    Methods:
        save_checkpoint(processed_files: list[str], total_files: int) -> None:
            Saves the current progress (list of processed files and total file count) to
            the checkpoint file.

        load_checkpoint() -> tuple[list[str], int] | None:
            Loads checkpoint data from the file if available, returning processed files and
            total file count.
            Returns None if the checkpoint is missing or corrupted.

        clear_checkpoint() -> None:
            Removes the checkpoint file from disk.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.checkpoint_file = "geo_search_checkpoint.json"

    def save_checkpoint(self, processed_files: list[str], total_files: int) -> None:
        """
        Saves a checkpoint of the current processing state to a file.

        Args:
            processed_files (list[str]): List of file paths that have been processed.
            total_files (int): Total number of files to be processed.

        Writes:
            A JSON file containing the processed files, total files, and a timestamp.

        Logs:
            Debug message on successful save.
            Warning on file system errors (e.g., permissions, disk issues).
            Error on JSON serialization errors or unexpected exceptions.

        Exceptions:
            Handles and logs OSError, IOError, PermissionError, TypeError, ValueError, and
                any other unexpected exceptions.
        """

        checkpoint_data = {
            "processed_files": processed_files,
            "total_files": total_files,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f, indent=2)
            self.logger.debug(
                f"Checkpoint saved: {len(processed_files)}/{total_files} files processed"
            )
        except (OSError, IOError, PermissionError) as e:
            # File system errors (permissions, disk full, file locked, etc.)
            self.logger.warning(f"File system error saving checkpoint: {e}")
        except (TypeError, ValueError) as e:
            # JSON serialization errors (invalid data types)
            self.logger.error(f"Data serialization error saving checkpoint: {e}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Any other unexpected errors
            self.logger.error(f"Unexpected error saving checkpoint: {e}")

    def load_checkpoint(self) -> tuple[list[str], int] | None:
        """
        Loads a checkpoint file containing information about processed files and total files.

        Returns:
            tuple[list[str], int] | None:
                - A tuple containing a list of processed file paths and the total
                    number of files if the checkpoint exists and is valid.
                - None if the checkpoint file does not exist, is corrupted, has an invalid format,
                    or if any error occurs during loading.

        Logs:
            - Information about the checkpoint if loaded successfully.
            - Warnings for file system errors, corrupted files, or invalid formats.
            - Errors for any unexpected exceptions.
        """

        checkpoint_path = Path(self.checkpoint_file)
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)

            processed_files = checkpoint_data.get("processed_files", [])
            total_files = checkpoint_data.get("total_files", 0)
            timestamp = checkpoint_data.get("timestamp", "Unknown")
            log_text = (
                f"Found checkpoint from {timestamp}:"
                f" {len(processed_files)}/{total_files} files processed"
            )
            self.logger.info(log_text)
            return processed_files, total_files

        except (OSError, IOError, PermissionError) as e:
            # File system errors (file not found, permissions, etc.)
            self.logger.warning(f"File system error loading checkpoint: {e}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            # JSON parsing errors (corrupted checkpoint file)
            self.logger.warning(f"Corrupted checkpoint file, ignoring: {e}")
            return None
        except (KeyError, TypeError) as e:
            # Data structure errors (unexpected checkpoint format)
            self.logger.warning(f"Invalid checkpoint format, ignoring: {e}")
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Any other unexpected errors
            self.logger.error(f"Unexpected error loading checkpoint: {e}")
            return None

    def clear_checkpoint(self) -> None:
        """
        Removes the checkpoint file if it exists.

        Attempts to delete the checkpoint file specified by `self.checkpoint_file`.
        Logs a debug message if the file is successfully removed.
        Handles and logs file system errors (such as permission issues or file locks)
        and any other unexpected exceptions.

        Returns:
            None
        """

        checkpoint_path = Path(self.checkpoint_file)
        if checkpoint_path.exists():
            try:
                checkpoint_path.unlink()
                self.logger.debug("Checkpoint file cleared")
            except (OSError, IOError, PermissionError) as e:
                # File system errors (permissions, file locked, etc.)
                self.logger.warning(f"File system error clearing checkpoint: {e}")
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Any other unexpected errors
                self.logger.error(f"Unexpected error clearing checkpoint: {e}")
