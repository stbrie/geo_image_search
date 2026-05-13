Geo Image Search — Field Reference
==================================

This tool walks a folder of JPEG photos, reads each one's GPS metadata,
and either lists or copies the ones near a target location.


Search parameters
-----------------

Address
    A street address, city, landmark, or any place name. Resolved to
    coordinates via OpenStreetMap's Nominatim service (requires internet).
    Examples:
        Baltimore, MD
        1600 Pennsylvania Ave NW, Washington, DC
        Eiffel Tower

    Either Address OR Latitude+Longitude is required (not both).

Latitude / Longitude
    Decimal degrees, e.g. 39.2904 / -76.6122. North and East are positive,
    South and West are negative. Use this when you want a precise center
    without geocoding, or when you're searching offline.

Radius (miles)
    How far from the center to look. Defaults to 0.05 miles (~265 ft).
    Tip: start small (0.25–0.5) for a known address; widen if you get
    no hits.

Cluster radius (yards)
    Only used when "Sort by location" is on. Sets the grouping
    distance in YARDS — typical values are 50–500 yd. Any photo
    within this distance of an existing cluster's anchor point
    joins that cluster. Leave blank to reuse the search Radius
    (which is in miles). Bigger value → fewer, larger groups.


Directories
-----------

Images root directory  (required)
    The top folder to search. The tool walks every subfolder underneath
    it looking for .jpg / .jpeg files.

Output directory
    Where matching images get copied. Required unless "Find only" is
    checked. The actual output goes to:
        <Images root>/geo_loc/<this name>
    so matched photos stay alongside your originals.


Options
-------

Copy files to output directory
    When checked (default), matching images are copied into the Output
    directory. Uncheck for a dry run — matches are listed in the log
    only. The Output directory is still used for CSV / KML exports
    when unchecked, so you can preview a search and capture results
    without duplicating photos.

Save addresses to CSV
    For every photo that has GPS data (not just matches), do a reverse
    geocode and write filename, lat, lon, and the resulting address to
    image_addresses.csv in the output directory. Requires Output directory.
    Note: this is slow on large libraries — Nominatim is rate-limited
    to one lookup per second.

Verbose output
    Print every directory scanned and every decision made. Useful for
    debugging; noisy for normal runs.

Also show images outside radius
    In verbose mode, also print the ones that DIDN'T match (with an "X").
    Off by default.

Resume from previous checkpoint
    If a search was interrupted (Ctrl+C, Cancel, crash), the tool wrote
    a checkpoint file. Re-checking this picks up where you left off
    instead of re-scanning every file. Checkpoint location depends on
    whether an output directory was set — see Checkpoints section below.

Export KML for Google Earth
    Write a .kml file alongside the matches that you can open in Google
    Earth to see the photos as pinned placemarks (with thumbnails).

Sort by location (cluster into folders)
    Group geo-tagged photos by geographic proximity. Each cluster
    becomes its own KML folder (and, when copying is enabled, its own
    disk folder under the Output directory). Use Cluster radius to
    control the grouping distance; if blank it falls back to Radius.

    Works in any combination with Copy files:
      * Copy on  + Output dir: disk folders AND KML folders
      * Copy off + Output dir: KML folders, no disk copies
      * Copy off, no Output dir: KML folders in the working directory


Filters
-------

Date from / Date to
    Restrict to photos taken in this date range. Uses the EXIF
    DateTimeOriginal field (falls back to DateTime / DateTimeDigitized).
    Format is YYYY-MM-DD. Either end can be blank.


Saved defaults
--------------

The GUI auto-saves your option checkboxes, the Radius, the Images
root, and the Output directory to a small JSON file at:
    ~/.geo_image_search_gui.json

Next time you launch, those fields come back the way you left them.
Use Settings → Preferences… to set or change the root / output
defaults directly.

The "Create sample config…" button still writes a TOML file for use
with the CLI. The CLI auto-discovers it in any of:
    ./geo_image_search.toml
    ~/.config/geo_image_search/config.toml
    ~/.geo_image_search.toml


Tips
----

  * Geocoding (Address → coordinates, and Save addresses' reverse lookup)
    needs internet and respects Nominatim's 1-request-per-second rate
    limit. For big libraries, prefer coordinates over Address.

  * For a sanity check, run with Find only + Verbose first to see what
    matches and why before copying anything.

  * If your photo library is huge and you might cancel partway,
    leave Resume off the first run; if it gets interrupted, run again
    with Resume on.

  * EXIF GPS data isn't on most phone photos by default unless location
    services are on for the camera. iOS and Android both write it when
    enabled.


Checkpoints
-----------

The tool saves progress every ~100 files or 30 seconds. On Ctrl+C
(CLI) or Cancel (GUI), it writes a final checkpoint before exiting.

  * With an Output directory: <output>/checkpoint.pkl
  * Find-only mode:           ~/.geo_image_search_checkpoints/checkpoint_<hash>.pkl

The checkpoint is keyed to the search parameters; if you change the
center or radius, the next run starts fresh.
