#!/usr/bin/env python

import numpy as np
from scipy import optimize
from pyproj import Proj
from pyproj import Transformer

class Mlat:
    "True-range multilateration solver"

    # Coordinate reference for GPS input (WGS84)
    gps_ref = Proj("epsg:4326")

    def __init__(self, config):
        # If we're in a local coordinate system, i.e. passive beacon locations
        # are static and specified in meters, then act as if we're in an
        # azimuthal equidistant projection centered at 0'0"N 0'0"E. We can then
        # convert prescribed locations (in meters) to degrees lat/lon and
        # proceed as if we were using GPS input for positions.
        if config['settings']['coords'] == 'local':
            local_ref = Proj(proj="aeqd", lat_0=0, lon_0=0, datum="WGS84", units="m")
        # Otherwise, if we're in lat/lon mode, use the defined origin as the center of
        # our local coordinate reference.
        elif config['settings']['coords'] == 'latlon':
            lat0 = config['settings']['lat0']
            lon0 = config['settings']['lon0']
            local_ref = Proj(proj="aeqd", lat_0=lat0, lon_0=lon0, datum="WGS84", units="m")

        # Define coordinate transformations
        gps2local = Transformer.from_proj(gps_ref, local_ref).transform
        local2gps = Transformer.from_proj(local_ref, gps_ref).transform

    def solve(self,locs,dists):
        "Estimate a position given a list of passive beacon locations and distances"
