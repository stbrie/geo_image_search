#!/usr/bin/env python3
"""
Geo Image Search - Find and organize GPS-tagged images.

A Python command-line tool for finding and organizing JPEG images based on
their GPS metadata. This is the new modular version of the application.
"""

import sys
from pathlib import Path
from geo_image_search.main import main

# Add the package directory to Python path
sys.path.insert(0, str(Path(__file__).parent))


if __name__ == "__main__":
    main()
