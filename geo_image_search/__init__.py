"""
Geo Image Search - A Python tool for finding and organizing GPS-tagged images.

This package provides functionality to:
- Search through directory trees for JPEG images with GPS metadata
- Filter images based on proximity to a target location
- Export results to CSV and KML formats
- Cluster images by geographic location
- Resume interrupted searches with checkpoint functionality
"""

__version__ = "2.0.0"
__author__ = "stbrie"

from .main import main

__all__ = ["main"]
