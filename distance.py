"""
Straight-line ("as the crow flies") distance calculation using the
Haversine formula — the standard way to calculate distance between two
points on a sphere given their latitude/longitude.

This deliberately ignores roads, turns, one-way streets, etc. It answers
"how far apart are these two points in a straight line," which is a
reasonable v1 stand-in for "is this store worth the detour" without
needing a mapping/routing API.
"""
import math

EARTH_RADIUS_MILES = 3958.8


def haversine_distance_miles(lat1, lon1, lat2, lon2):
    """
    Returns the straight-line distance in miles between two lat/long points.
    """
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    return round(EARTH_RADIUS_MILES * c, 2)


if __name__ == "__main__":
    # Quick sanity check: Rolla Walmart vs Rolla Aldi (a few miles apart)
    walmart = (37.9436, -91.7768)
    aldi = (37.9580, -91.7793)
    distance = haversine_distance_miles(*walmart, *aldi)
    print(f"Walmart to Aldi (straight-line): {distance} miles")
