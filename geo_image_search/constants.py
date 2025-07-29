"""Constants and error codes for the geo image search application."""


class Constants:
    """
    Constants used throughout the geo_image_search application.

    Attributes:
        JPEG_EXTENSIONS (set): Supported JPEG file extensions.
        DEFAULT_RADIUS (float): Default search radius in kilometers.
        CHECKPOINT_INTERVAL_FILES (int): Number of files processed before checkpointing.
        DEFAULT_USER_AGENT (str): Default user agent string for HTTP requests.
        GEOCODING_TIMEOUT_SECONDS (int): Timeout for geocoding operations in seconds.
        KML_CENTER_VIEW_RANGE (int): Default view range for KML center points in meters.
        KML_POINT_VIEW_RANGE (int): Default view range for KML points in meters.

    Classes:
        ErrorCodes: Application exit codes indicating various error and success states.

            SUCCESS (int): Successful execution.
            INTERRUPTED (int): Execution interrupted by user or system.
            NO_ROOT_DIRECTORY (int): Root directory not specified.
            NO_OUTPUT_DIRECTORY (int): Output directory not specified.
            CONFLICTING_OPTIONS (int): Conflicting command-line options provided.
            GEOCODING_FAILED (int): Geocoding operation failed.
            INVALID_COORDINATES (int): Provided coordinates are invalid.
            ROOT_DIRECTORY_NOT_FOUND (int): Specified root directory not found.
            NO_LOCATION_FOUND (int): No location found for the given input.
            MISSING_OUTPUT_FOR_ADDRESSES (int): Output missing for provided addresses.
            INVALID_DATE_FROM (int): Invalid 'date from' value.
            INVALID_DATE_TO (int): Invalid 'date to' value.
            SORT_LOCATION_FIND_ONLY_CONFLICT (int): Conflict between sort and
                                                    location-find-only options.
            SORT_LOCATION_NO_OUTPUT (int): No output specified for sort-location operation.
            FILE_OPERATION_ERROR (int): Error during file operations.
            GPS_DATA_ERROR (int): Error related to GPS data.
            CONFIGURATION_ERROR (int): Error in application configuration.
            GENERAL_ERROR (int): General application error.
    """

    JPEG_EXTENSIONS = {".jpg", ".jpeg", ".JPG", ".JPEG"}
    DEFAULT_RADIUS = 0.1
    CHECKPOINT_INTERVAL_FILES = 100
    DEFAULT_USER_AGENT = "github/stbrie: geo_image_search"

    # Geocoding timeouts
    GEOCODING_TIMEOUT_SECONDS = 10

    # KML view ranges in meters
    KML_CENTER_VIEW_RANGE = 200
    KML_POINT_VIEW_RANGE = 50

    class ErrorCodes:
        """
        ErrorCodes

        A collection of integer constants representing various error and status codes used
            throughout the geo_image_search application.

        Attributes:
            SUCCESS (int): Operation completed successfully.
            INTERRUPTED (int): Operation was interrupted.
            NO_ROOT_DIRECTORY (int): Root directory was not specified.
            NO_OUTPUT_DIRECTORY (int): Output directory was not specified.
            CONFLICTING_OPTIONS (int): Conflicting command-line options were provided.
            GEOCODING_FAILED (int): Geocoding operation failed.
            INVALID_COORDINATES (int): Provided coordinates are invalid.
            ROOT_DIRECTORY_NOT_FOUND (int): Specified root directory does not exist.
            NO_LOCATION_FOUND (int): No location could be determined.
            MISSING_OUTPUT_FOR_ADDRESSES (int): Output missing for provided addresses.
            INVALID_DATE_FROM (int): 'From' date is invalid.
            INVALID_DATE_TO (int): 'To' date is invalid.
            SORT_LOCATION_FIND_ONLY_CONFLICT (int): Conflict between sort and
                                                    location-find-only options.
            SORT_LOCATION_NO_OUTPUT (int): No output specified for sort/location operation.
            FILE_OPERATION_ERROR (int): Error occurred during file operation.
            GPS_DATA_ERROR (int): Error related to GPS data.
            CONFIGURATION_ERROR (int): Error in application configuration.
            GENERAL_ERROR (int): General or unspecified error.
        """

        SUCCESS = 0
        INTERRUPTED = 1
        NO_ROOT_DIRECTORY = 2
        NO_OUTPUT_DIRECTORY = 3
        CONFLICTING_OPTIONS = 4
        GEOCODING_FAILED = 6
        INVALID_COORDINATES = 7
        ROOT_DIRECTORY_NOT_FOUND = 8
        NO_LOCATION_FOUND = 9
        MISSING_OUTPUT_FOR_ADDRESSES = 10
        INVALID_DATE_FROM = 11
        INVALID_DATE_TO = 12
        SORT_LOCATION_FIND_ONLY_CONFLICT = 15
        SORT_LOCATION_NO_OUTPUT = 16
        FILE_OPERATION_ERROR = 17
        GPS_DATA_ERROR = 18
        CONFIGURATION_ERROR = 19
        GENERAL_ERROR = 20
