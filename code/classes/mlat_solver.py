#!/usr/bin/env python

import numpy as np
from scipy.optimize import minimize
from pyproj import Proj
from pyproj import Transformer

# Coordinate reference for GPS input (WGS84)
gps_ref = Proj("epsg:4326")

class Mlat:
    "True-range multilateration solver"

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
        self.gps2local = Transformer.from_proj(gps_ref, local_ref).transform
        self.local2gps = Transformer.from_proj(local_ref, gps_ref).transform

    def solve(self,locs,dists,x0=None):
        "Estimate a position given a list of passive beacon locations and distances"

        # Convert the lat, lons of all passive beacons to a matrix
        # [x1, y1, z1;
        #  x2, y2, z2;
        #    ...     ]
        P = np.array([gps2local(locs[m]['lat'],locs[m]['lon']) + (0,) for m in locs.keys()])

        # Convert distances to a matrix
        D = np.array([dists[m] for m in dists.keys()])

        # Initial guess: average of passive beacon locations if none given.
        if not x0:
            x0 = np.mean(P, axis=0)
            x0[2] = -10

        # Position constraints: none in x,y, z must be negative (below sea-level)
        bounds = [(None,None), (None,None), (-100, 0)]
        x = minimize(rms_dists, x0, args=(P,D), method='TNC',
                     bounds=bounds, jac=1e-1, options={'ftol':1e-4})

        # Convert estimate to lat,lon
        lat,lon = self.local2gps(x[0],x[1])

        # Return coordinates lat,lon,z
        return lat,lon,x[2]


def obj_fun(x,P,D):
    # The estimated position is the point x which minimizes the difference between:
    # - Measured distance from all passive beacons
    # - Computed distance between x and all passive beacons
    # Compute the RMS of this difference over all beacons
    dists = np.linalg.norm(P-x, axis=1)
    return np.sqrt(np.mean(np.square(dists-D)))
