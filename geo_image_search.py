#!/usr/bin/env python3

import os
import re
import sys
import getopt
from shutil import copyfile
from exif import Image
from geopy.geocoders import Nominatim
from geopy import distance

class GeoImageSearch: # pylint: disable=too-many-instance-attributes
    def __init__(self):
        self.find = False
        self.opts = None
        self.args = None
        self.address = None
        self.root_images_directory = None
        self.od_re = None
        self.location = None
        self.search_coords = None
        self.image_addresses = False
        self.images_directory = None
        self.location_address = ""
        self.output_directory = ""
        self.user_output_directory = None
        self.verbose = ""
        self.argv = sys.argv[1:]
        self.geolocator = Nominatim(user_agent="geo_image_search")
        self.ts_re = re.compile(r'^.*/$')
        self.fs_re = re.compile(r'([.,\s]+)')
        self.jpeg_file_regex = re.compile(r"^.*\.(jpg)|(jpeg)$")
        print('ARGV        :', self.argv)
        self.loc_format = '{0:}: {1:.7n}, {2:.7n} ({3:.3n})'

    def get_opts(self):
        try:
            self.opts, self.args = getopt.getopt(self.argv,
                                                 "hofiva",
                                                 ['address=',
                                                  'output-directory=',
                                                  'find-only',
                                                  'image-addresses',
                                                  'verbose',
                                                  'images-root-directory='])
            print('OPTIONS    :', self.opts)
        except getopt.GetoptError as err:
            self.usage(err)

        for opt, arg in self.opts:
            if opt in ("-a", "--address"):
                self.address = arg
            if opt in ("-o", "--output-directory"):
                self.user_output_directory = arg
            if opt in ("-f", "--find-only"):
                self.find = True
            if opt in ("-i", "--image-addresses"):
                self.image_addresses = True
            if opt in ("-v", "--verbose"):
                self.verbose = True
            if opt in ('-r', '--images-root-directory'):
                self.root_images_directory = arg


    def usage(self, err=None):
        print('Usage:')
        print('  geo_image_search.py')
        print('    --help (switch... display usage info')
        print('    --verbose (switch... display extra information)')
        print('    --address=<address to match to images>')
        print('    --images-root-directory=<folder to recurse down for images to locate>')
        print('    --output-directory=<subfolder of images-root to save found images>')
        print('    --find-only (switch... do not copy found images, display matches only)')
        print('    --image-addresses (switch... save image ', end='')
        print('addresses in text file in output-directory)')
        if err:
            print(str(err))
            sys.exit(2)
        else:
            sys.exit(0)
    def set_root_images_directory(self):
        if not self.root_images_directory:
            self.root_images_directory = '/mnt/c/Documents and Settings/jack_local/Pictures/Camera Dump/'
        if not self.ts_re.search(self.root_images_directory):
            self.root_images_directory = self.root_images_directory + '/'
    def set_output_directory(self):
        if not self.user_output_directory:
            print('No output directory specified.  Results not saved.')
            self.usage() # exit for now.  I don't want to overly complicate flow logic.
        if self.verbose:
            print('User output directory: ' + self.user_output_directory)
        od_stripped = self.fs_re.sub("_",self.user_output_directory)
        if self.verbose:
            print('Setting od_stripped: ' + od_stripped)
        self.od_re = re.compile(od_stripped)
        self.output_directory = self.root_images_directory + "geo_loc/" + od_stripped + "/"

    def set_directories(self):
        self.set_root_images_directory()
        self.set_output_directory()
        if self.verbose:
            print("output_directory: " + self.output_directory)
            print("root images_directory: " + self.root_images_directory)
        if not os.path.exists(self.output_directory):
            if self.verbose:
                print("Output directory does not exist.")
                print("Creating " + self.output_directory)
            os.makedirs(self.output_directory)
        else:
            print("Output directory exists.")

    def startup(self):
        self.get_opts()
        print("User address is " + str(self.address))
        self.location = self.geolocator.geocode(self.address)
        self.search_coords = (self.location.latitude, self.location.longitude)
        print("Nominatim address: " + self.location.address)
        print("Lat, Long: " + str(self.location.latitude), str(self.location.longitude))
        self.set_directories()




    files_list = []
    file_counter = 0

if __name__ == '__main__':
    gis = GeoImageSearch()
    gis.startup()

    for dirpath, dirnames, filenames in os.walk(gis.root_images_directory):
        if gis.verbose:
            print(dirpath)
        if gis.od_re.search(dirpath):
            print("Skipping output_directory..." + dirpath)
            next

        for file_name in filenames:
            if gis.jpeg_file_regex.search(file_name):
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
                        if distance.distance(gis.search_coords, image_loc).miles < .5:
                            if gis.verbose:
                                print("+ " +
                                      gis.loc_format.format(file_name,
                                                            lat_deg_dec,
                                                            long_deg_dec,
                                                            distance.distance(gis.search_coords,
                                                                              image_loc).miles))
                            if gis.output_directory:
                                destination = gis.output_directory + "/" + file_name
                                copyfile(imagename, destination)
                        else:
                            if gis.verbose:
                                print("- " +
                                      gis.loc_format.format(file_name,
                                                            lat_deg_dec,
                                                            long_deg_dec,
                                                            distance.distance(gis.search_coords,
                                                                              image_loc).miles))
                    else:
                        pass
