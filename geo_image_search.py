#!/usr/bin/env python3

import os
import re
import sys
import getopt
from shutil import copyfile
from exif import Image
from geopy.geocoders import Nominatim
from geopy import distance


def set_up():
    find = False
    image_addresses = False
    location_address = ""
    output_directory = ""
    verbose = False
    root_images_directory = "/mnt/c/Documents and Settings/jack_local/Pictures/Camera Dump/"
    print('ARGV        :', sys.argv[1:])
    loc_format = '{0:}: {1:.7n}, {2:.7n} ({3:.3n})'
    try:
        opts, args = getopt.getopt(sys.argv[1:],
                                   "hofiva:",
                                   ["address=",
                                    "output-directory",
                                    "find-only",
                                    "image-addresses",
                                    "verbose"])
        print('OPTIONS       :', opts)
    except getopt.GetoptError as err:
        print('geo_image_search.py --address=<address> --output_directory=<output directory> --find-only --image-addresses')
        print(str(err))
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-a", "--address"):
            address = arg
        if opt in ("-o", "--output-directory"):
            output_directory = arg
        if opt in ("-f", "--find-only"):
            find = True
        if opt in ("-i", "--image-addresses"):
            image_addresses = True
        if opt in ("-v", "--verbose"):
            verbose = True


    print("Address is " + address)

    geolocator = Nominatim(user_agent="geo_image_search")
    location = geolocator.geocode(address)
    search_loc = (location.latitude, location.longitude)
    print("Nominatim address: " + location.address)
    print("Lat, Long: " + str(location.latitude), str(location.longitude))


    if not output_directory:
        file_address = copy.deepcopy(address)
        fa_re = re.compile(r"[\s,]+")
        file_address = fa_re.sub('_', file_address)
        output_directory = root_images_directory + "geo_loc/" + file_address + "/"
    else:
        output_directory = root_images_directory + "geo_loc/" + output_directory + "/"
        od_re = re.compile(output_directory)
        print("output_directory: " + output_directory)
        print("root images_directory: " + images_directory)
    if not os.path.exists(output_directory):
        if verbose:
            print("Output directory does not exist.")
            print("Creating " + output_directory)
        os.makedirs(output_directory)
    else:
        print("Output directory exists.")

    print(location.address)

    jpeg_file_regex = re.compile(r"^.*\.(jpg)|(jpeg)$")

    files_list = []
    file_counter = 0

def __main__():
    set_up()
    for dirpath, dirnames, filenames in os.walk(root_images_directory):
        if verbose:
            print(dirpath)
        if od_re.search(dirpath):
            print("skipping output_directory")
            next()

        for file_name in filenames:
            if jpeg_file_regex.search(file_name):
                imagename = dirpath + "/" + file_name
                with open(imagename, 'rb') as image_file:
                    my_image = Image(image_file)
                    lat_deg_dec = None
                    long_deg_dec = None
                    try:
                        lat_deg_dec = my_image.gps_latitude[0]
                        lat_deg_dec = lat_deg_dec + my_image.gps_latitude[1]/60
                        lat_deg_dec = lat_deg_dec + my_image.gps_latitude[2]/3600
                    except AttributeError:
                    # print (imagename + " has no latitude.")
                        pass
                    try:
                        long_deg_dec = my_image.gps_longitude[0]
                        long_deg_dec = long_deg_dec + my_image.gps_longitude[1]/60
                        long_deg_dec = long_deg_dec + my_image.gps_longitude[2]/3600
                    except AttributeError:
                    # print (imagename + " has no longitude.")
                        pass
                    if lat_deg_dec and long_deg_dec:
                        long_deg_dec = -1 * long_deg_dec
                        image_loc = (lat_deg_dec, long_deg_dec)
                        if distance.distance(search_loc, image_loc).miles < .5:
                            if verbose:
                                print("+ " +
                                      loc_format.format(file_name,
                                                        lat_deg_dec,
                                                        long_deg_dec,
                                                        distance.distance(search_loc, image_loc).miles))
                            if output_directory:
                                destination = output_directory + "/" + file_name
                                copyfile(imagename, destination)
                        else:
                            if verbose:
                                print("- " +
                                      loc_format.format(file_name,
                                                        lat_deg_dec,
                                                        long_deg_dec,
                                                        distance.distance(search_loc, image_loc).miles))
                    else:
                        pass
