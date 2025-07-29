"""Setup script for geo_image_search package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README").read_text()

setup(
    name="geo-image-search",
    version="2.0.0",
    author="stbrie",
    description="A Python tool for finding and organizing GPS-tagged images",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "exif>=1.3.0",
        "geopy>=2.0.0",
    ],
    extras_require={
        "kml": ["fastkml>=0.12", "shapely>=2.0.0"],
        "toml": ["tomli>=1.2.0"],
        "all": ["fastkml>=0.12", "shapely>=2.0.0", "tomli>=1.2.0"],
    },
    entry_points={
        "console_scripts": [
            "geo-image-search=geo_image_search.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Graphics",
        "Topic :: Scientific/Engineering :: GIS",
    ],
    keywords="gps exif image search location geocoding kml",
    project_urls={
        "Bug Reports": "https://github.com/stbrie/geo_image_search/issues",
        "Source": "https://github.com/stbrie/geo_image_search",
    },
)