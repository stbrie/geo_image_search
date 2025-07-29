"""Geographic clustering functionality for images."""

import logging
from datetime import datetime

try:
    from geopy.distance import distance
    from geopy.geocoders import Nominatim
except ImportError:
    distance = None
    Nominatim = None

from .constants import Constants
from .types import ImageData


class ClusteringEngine:
    """Handles geographic clustering of images."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        
        if not distance or not Nominatim:
            raise ImportError("geopy library is required for clustering. Install with: pip install geopy")
    
    def cluster_images_by_location(self, 
                                   image_data_list: list[ImageData], 
                                   cluster_radius: float = 0.1) -> dict[str, list[ImageData]]:
        """Cluster images by geographic proximity."""
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
        """Generate a descriptive cluster name."""
        lat, lon = location
        
        # Try to get address for cluster center
        try:
            geolocator = Nominatim(user_agent=Constants.DEFAULT_USER_AGENT)
            location_info = geolocator.reverse(location, timeout=10)
            
            if location_info and location_info.raw.get('address'):
                address = location_info.raw['address']
                
                # Build name from address components
                name_parts = []
                for component in ['city', 'town', 'village', 'county', 'state']:
                    if component in address:
                        name_parts.append(address[component])
                        break
                
                if name_parts:
                    return f"Cluster_{name_parts[0].replace(' ', '_')}"
            
        except Exception as e:
            self.logger.debug(f"Could not get address for cluster center: {e}")
        
        # Fallback to coordinate-based name
        return f"Cluster_{lat:.3f}_{lon:.3f}"


class CheckpointManager:
    """Handles checkpoint and resume functionality."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.checkpoint_file = "geo_search_checkpoint.json"
    
    def save_checkpoint(self, processed_files: list[str], total_files: int) -> None:
        """Save current progress to checkpoint file."""
        import json
        
        checkpoint_data = {
            "processed_files": processed_files,
            "total_files": total_files,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            with open(self.checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)
            self.logger.debug(f"Checkpoint saved: {len(processed_files)}/{total_files} files processed")
        except Exception as e:
            self.logger.warning(f"Could not save checkpoint: {e}")
    
    def load_checkpoint(self) -> tuple[list[str], int] | None:
        """Load checkpoint data if available."""
        import json
        from pathlib import Path
        
        checkpoint_path = Path(self.checkpoint_file)
        if not checkpoint_path.exists():
            return None
        
        try:
            with open(checkpoint_path, 'r') as f:
                checkpoint_data = json.load(f)
            
            processed_files = checkpoint_data.get("processed_files", [])
            total_files = checkpoint_data.get("total_files", 0)
            timestamp = checkpoint_data.get("timestamp", "Unknown")
            
            self.logger.info(f"Found checkpoint from {timestamp}: {len(processed_files)}/{total_files} files processed")
            return processed_files, total_files
            
        except Exception as e:
            self.logger.warning(f"Could not load checkpoint: {e}")
            return None
    
    def clear_checkpoint(self) -> None:
        """Remove checkpoint file."""
        from pathlib import Path
        
        checkpoint_path = Path(self.checkpoint_file)
        if checkpoint_path.exists():
            try:
                checkpoint_path.unlink()
                self.logger.debug("Checkpoint file cleared")
            except Exception as e:
                self.logger.warning(f"Could not clear checkpoint: {e}")