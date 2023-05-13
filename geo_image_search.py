import os
import re
import sys
import argparse
from shutil import copyfile
from exif import Image
from geopy.geocoders import Nominatim
from geopy import distance
import pprint

class GeoImageSearch: # pylint: disable=too-many-instance-attributes
    def __init__(self):
        self.find_only = False
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
        self.lat = None # the center of the target location
        self.lon = None # the center of the target location
        self.radius = .5 # the radius in feet of images to look for.
        self.far = False
        self.argv = sys.argv[1:]
        self.geolocator = Nominatim(user_agent="github/stbrie: geo_image_search")
        self.ts_re = re.compile(r'^.*/$')
        self.fs_re = re.compile(r'([.,\s]+)')
        self.jpeg_file_regex = re.compile(r"^.*\.(jpg)|(jpeg)$")
        self.printed_directory = {}
        print('ARGV        :', self.argv)
        self.loc_format = '{0:}: {1:.7n}, {2:.7n} ({3:.3n})'

    def get_opts(self):
        parser = argparse.ArgumentParser(
            prog="geo_image_search.py",
            description="Finds images based on location data found in .jpeg metadata.",
            epilog="Text at the bottom."
        )

        parser.add_argument("-o", "--output_directory", action="store",help="<output directory> to copy images to (optional)")
        parser.add_argument("-f", "--find_only", action="store_true", help="(optional) if set, do not copy files or save data.")
        parser.add_argument("-a", "--address", action="store", help="(optional) <address> address to match to images")
        parser.add_argument("-i", "--save_addresses", action="store_true", help="(optional) if set, save the ALL the image addreses in a csv in the <output directory> which must be set.")
        parser.add_argument("-v", "--verbose", action="store_true", help='print additional information')
        parser.add_argument("-d", "--root", action="store", required=True, help="(required) the <root directory> of where to begin searching for images")
        parser.add_argument("-t", "--latitude", action="store", help="(optional) if set, use the decimal latitude to center the search.")
        parser.add_argument("-g", "--longitude", action="store", help="(optional) if set, use this decimal longitude to center the search.")
        parser.add_argument("-r", "--radius", action="store", default=.5, help="(optional, defaults to 2640) the radius of the search in feet.")
        parser.add_argument("-x", "--far", action="store_true", help="(optional) show images that are further than radius from centerpoint")
        try:
            args = parser.parse_args()
        except Exception as e:
            print(e)
            sys.exit(250)

        self.address = args.address
        self.user_output_directory = args.output_directory
        self.find_only = args.find_only
        self.image_addresses = args.save_addresses
        self.verbose = args.verbose
        self.root_images_directory = args.root
        self.lat = args.latitude
        self.lon = args.longitude
        if args.radius != .5:
            self.radius = abs(float(args.radius) / 5280)
        
        if self.verbose:
            print(f"Address: {self.address}")
            print(f"User Output Directory: {self.user_output_directory}")
            print(f"Find Only: {self.find_only}")
            print(f"Save Image Addresses: {self.image_addresses}")
            print(f"Verbose: {self.verbose}")
            print(f"Root Images Directory: {self.root_images_directory}")
            print(f"Latitude: {self.lat}")
            print(f"Longitude: {self.lon}")
            print(f"Radius: {self.radius}")

    def set_root_images_directory(self):
        if not self.root_images_directory:
            print("No images root directory specified.  --images-root-directory is not optional")
            sys.exit(2)
        if not self.ts_re.search(self.root_images_directory):
            self.root_images_directory = self.root_images_directory 

    def set_output_directory(self):
        
        if not self.find_only:
            if not self.user_output_directory:
                print('No output directory specified and not find only. Use one or the other.')
                sys.exit(3)
            else:
               if self.verbose:
                    print('User output directory: ' + self.user_output_directory)
                    od_stripped = self.fs_re.sub("_",self.user_output_directory)
                    print('   Setting stripped output directory: ' + od_stripped)
                    self.od_re = re.compile(od_stripped)
                    self.output_directory = self.root_images_directory + "geo_loc/" + od_stripped + "/"
                    print('   User output directory: ' + self.output_directory)
        else:
            if self.user_output_directory:
                print('--find_only set and User Output Directory set.  Use one or the other.')
                sys.exit(4)
            else:
                print('Finding and outputting image path only.')
                self.output_directory = "Do Not Save"


    def set_directories(self):
        self.set_root_images_directory()
        self.set_output_directory()
        if self.verbose:
            print("Images Root Directory: " + self.root_images_directory)
        if self.output_directory != "Do Not Save":
            if not os.path.exists(self.output_directory):
                if self.verbose:
                    print("   Output directory does not exist.")
                    print("   Creating " + self.output_directory)
                os.makedirs(self.output_directory)
            else:
                print("   Output directory exists.")
        else:
            pass
    
    def set_location(self):
        
        if (not self.address) and (not (self.lat and self.lon)):
            print("Missing usage arguments: --address or --latitude and --longitude.")
            sys.exit(5)
        if self.address:
            print(f"User address is {str(self.address)}")
            self.location = self.geolocator.geocode(query=self.address)
            if not self.location:
                # TODO: geopy has exceptions we could use.  That might be more useful than this.
                print("User address does not return a valid location object.")
                sys.exit(6)
            else:
                pass # success!
        else:
            if self.lon and self.lat:
                self.location=self.geolocator.reverse(query=f"{str(self.lat)}, {str(self.lon)}")
                if not self.location:
                    # TODO: geopy has exceptions we could use.  That might be more useful than this.
                    print("Latitude, Longitude does not return a valid location object.")
                    sys.exit(7)
                else:
                    pass # success!

        self.search_coords = (self.location.latitude, self.location.longitude)
        print(f"Nominatum address: {self.location.address}")
        print(f"Lat, Lon: {str(self.location.latitude)}, {str(self.location.longitude)}")

    def startup(self):
        self.get_opts()
        pp = pprint.PrettyPrinter(indent=4)
        
        print("User address is " + str(self.address))
        self.set_location()
        self.set_directories()

    def calc_distance(self, dir_path, file_name, image_file):
        try:
            my_image = Image(image_file)          
        except Exception as e:
            print(f"Corrupt file? {e}")
        lat_deg_dec = None
        long_deg_dec = None

        try:
            lat_deg_dec = my_image.gps_latitude[0]
            lat_deg_dec = lat_deg_dec + my_image.gps_latitude[1]/60
            lat_deg_dec = lat_deg_dec + my_image.gps_latitude[2]/3600
        except AttributeError:
            if gis.verbose:
                print (f"{imagename} has no latitude.")
            else:
                pass
        except Exception as e:
            if gis.verbose:
                print(f"{imagename}: {e}")
            else:
                pass                    
        try:
            long_deg_dec = my_image.gps_longitude[0]
            long_deg_dec = long_deg_dec + my_image.gps_longitude[1]/60
            long_deg_dec = long_deg_dec + my_image.gps_longitude[2]/3600
        except AttributeError:
            if self.verbose:
                print (f"{imagename} has no longitude.")
            else:
                pass
        except Exception as e:
            if self.verbose:
                print(f"{imagename}: {e}")
            else:
                pass                        
        if lat_deg_dec and long_deg_dec:
            long_deg_dec = -1 * long_deg_dec # TODO: Make this not stupid.
            
            image_loc = (lat_deg_dec, long_deg_dec)
            distance_miles = distance.distance(self.search_coords, image_loc).miles
            if distance_miles < gis.radius:
                if gis.verbose:
                    print("+ " +
                            self.loc_format.format(file_name,
                                                lat_deg_dec,
                                                long_deg_dec,
                                                distance_miles))
                else:
                    if self.printed_directory.get(dir_path, False):
                        pass # already printed it.
                    else:

                        print(f"\n{dir_path}: ")
                        self.printed_directory[dir_path] = True

                    print(f"   + {file_name} {distance_miles:.2f}mi")
                if self.output_directory and not self.find_only:
                    destination = f"{self.output_directory}/{file_name}"
                    copyfile(imagename, destination)
            else:
                if self.verbose and self.far:
                    print("X " +
                            self.loc_format.format(file_name,
                                                lat_deg_dec,
                                                long_deg_dec,
                                                distance_miles))
        else:
            pass # no lattitude and longitude from the image.  Can't calculate distance.



    files_list = []
    file_counter = 0


            
if __name__ == '__main__':
    gis = GeoImageSearch()
    gis.startup()
    files_list = []
    file_counter = 0
    dirpath = ''
    dirnames = []
    filenames = []
    fifty_counter = 0
    for dirpath, dirnames, filenames in os.walk(gis.root_images_directory):
        fifty_counter = fifty_counter + 1
        if gis.verbose:
            print(f"{dirpath=}")
        else:
            print(".", end="", flush=True)
            if fifty_counter % 50 == 0:
                print("",flush=True)
                print(f"{fifty_counter}: ", end="", flush=True)
            else:
                pass
        if gis.od_re is not None and gis.od_re.search(dirpath):
            print(f"Skipping output_directory... {dirpath}")
            continue

        for file_name in filenames:
            if gis.jpeg_file_regex.search(file_name):
                imagename = os.path.join(dirpath, file_name)
                with open(imagename, 'rb') as image_file:
                    try:
                        gis.calc_distance(dirpath, file_name, image_file)
                    except Exception as e:
                        print(e)
                        
                    # my_image = Image(image_file)
                        
                    # lat_deg_dec = None
                    # long_deg_dec = None
                    # try:
                    #     lat_deg_dec = my_image.gps_latitude[0]
                    #     lat_deg_dec = lat_deg_dec + my_image.gps_latitude[1]/60
                    #     lat_deg_dec = lat_deg_dec + my_image.gps_latitude[2]/3600
                    # except AttributeError:
                    #     if gis.verbose:
                    #         print (f"{imagename} has no latitude.")
                    #     else:
                    #         pass
                    # except Exception as e:
                    #     if gis.verbose:
                    #         print(f"{imagename}: {e}")
                    #     else:
                    #         pass                    
                    # try:
                    #     long_deg_dec = my_image.gps_longitude[0]
                    #     long_deg_dec = long_deg_dec + my_image.gps_longitude[1]/60
                    #     long_deg_dec = long_deg_dec + my_image.gps_longitude[2]/3600
                    # except AttributeError:
                    #     if gis.verbose:
                    #         print (f"{imagename} has no longitude.")
                    #     else:
                    #         pass
                    # except Exception as e:
                    #     if gis.verbose:
                    #         print(f"{imagename}: {e}")
                    #     else:
                    #         pass                        
                    # if lat_deg_dec and long_deg_dec:
                    #     long_deg_dec = -1 * long_deg_dec # TODO: Make this not stupid.
                        
                    #     image_loc = (lat_deg_dec, long_deg_dec)
                    #     distance_miles = distance.distance(gis.search_coords, image_loc).miles
                    #     if distance_miles < gis.radius:
                    #         if gis.verbose:
                    #             print("+ " +
                    #                   gis.loc_format.format(file_name,
                    #                                         lat_deg_dec,
                    #                                         long_deg_dec,
                    #                                         distance_miles))
                    #         else:
                    #             print(f"+ {file_name} {distance_miles}mi")
                    #         if gis.output_directory and not gis.find_only:
                    #             destination = f"{gis.output_directory}/{file_name}"
                    #             copyfile(imagename, destination)
                    #     else:
                    #         if gis.verbose and gis.far:
                    #             print("X " +
                    #                   gis.loc_format.format(file_name,
                    #                                         lat_deg_dec,
                    #                                         long_deg_dec,
                    #                                         distance_miles))
                    # else:
                    #     pass # no lattitude and longitude from the image.  Can't calculate distance.
