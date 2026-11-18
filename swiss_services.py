"""Route calculation and Swiss federal geodata for RunComfy."""

import json
import math
import threading
import time
from io import BytesIO

import requests
from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString


DEFAULT_ROUTER_URL = "https://valhalla1.openstreetmap.de/route"
PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"
WMS_URL = "https://wms.geo.admin.ch/"
FOREST_LAYER = "ch.swisstopo.swisstlm3d-wald"
TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)
ROUTER_LOCK = threading.Lock()
last_public_request = -math.inf


class RoutingUnavailable(RuntimeError):
    pass


def number(value):
    """Return a finite number, keeping missing data distinct from zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def waypoint_at_bearing(lat, lon, radius_km, bearing):
    latitude = math.radians(lat)
    bearing = math.radians(bearing)
    angle = radius_km / 6371
    destination_lat = math.asin(
        math.sin(latitude) * math.cos(angle)
        + math.cos(latitude) * math.sin(angle) * math.cos(bearing)
    )
    delta_lon = math.atan2(
        math.sin(bearing) * math.sin(angle) * math.cos(latitude),
        math.cos(angle) - math.sin(latitude) * math.sin(destination_lat),
    )
    return {"lat": math.degrees(destination_lat), "lon": (lon + math.degrees(delta_lon) + 180) % 360 - 180}


def loop_waypoints(distance, attempt, previous_distance=None):
    # Resize the triangle using the previous route distance when available.
    bearing = (attempt % 4) * 90
    if attempt < 4:
        return distance * 0.27, bearing
    if previous_distance is None:
        return distance * 0.22, bearing + 45
    scale = max(0.45, min(1.45, distance / previous_distance))
    return distance * 0.27 * scale, bearing


def get_running_route(router_url, lat, lon, distance, attempt, previous_distance=None):
    radius, bearing = loop_waypoints(distance, attempt, previous_distance)
    start = {"lat": lat, "lon": lon}
    payload = {
        "locations": [
            start,
            waypoint_at_bearing(lat, lon, radius, bearing),
            waypoint_at_bearing(lat, lon, radius, bearing + 60),
            start,
        ],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"use_ferry": 0, "max_hiking_difficulty": 1}},
        "format": "osrm",
        "shape_format": "geojson",
        "units": "kilometers",
    }
    options = {
        "params": {"json": json.dumps(payload, separators=(",", ":"))},
        "headers": {"X-Client-Id": "RunComfyAI", "User-Agent": "RunComfyAI/1.0"},
        "timeout": 12,
    }
    if router_url == DEFAULT_ROUTER_URL:
        # Share the public endpoint's one-request-per-second budget across sessions.
        global last_public_request
        with ROUTER_LOCK:
            time.sleep(max(0, 1.05 - (time.monotonic() - last_public_request)))
            last_public_request = time.monotonic()
            response = requests.get(router_url, **options)
    else:
        response = requests.get(router_url, **options)

    if response.status_code in (401, 403, 429, 503):
        raise RoutingUnavailable(
            f"The pedestrian routing service is unavailable (HTTP {response.status_code}). Try again shortly."
        )
    result = response.json()
    if result.get("code") in ("NoRoute", "NoSegment") or result.get("error_code") in (170, 171, 442, 443):
        return None
    response.raise_for_status()
    for route in result.get("routes", []):
        coordinates = route.get("geometry", {}).get("coordinates", [])
        distance_m = number(route.get("distance"))
        if len(coordinates) >= 3 and distance_m is not None and distance_m > 0:
            return {"coordinates": coordinates, "distance": distance_m / 1000}
    return None


def project_route(coordinates):
    longitude, latitude = zip(*(point[:2] for point in coordinates))
    easting, northing = TO_LV95.transform(longitude, latitude, errcheck=True)
    line = LineString(zip(easting, northing))
    if not line.is_valid or line.length <= 0:
        raise ValueError("Invalid route geometry")
    return line


def get_elevation_gain(line):
    coordinates = list(line.coords)
    if len(coordinates) > 5000:
        # Retain the endpoints while respecting the profile API's vertex limit.
        coordinates = [coordinates[round(i * (len(coordinates) - 1) / 4999)] for i in range(5000)]
    response = requests.post(
        PROFILE_URL,
        data={
            "geom": json.dumps({"type": "LineString", "coordinates": coordinates}),
            "sr": 2056,
            "nb_points": min(400, max(2, math.ceil(line.length / 40) + 1)),
        },
        timeout=12,
    )
    response.raise_for_status()
    profile = response.json()
    if not isinstance(profile, list):
        return None
    heights = [number(point.get("alts", {}).get("COMB")) for point in profile]
    if len(heights) < 2 or any(height is None or height < -100 for height in heights):
        return None
    return round(sum(max(0, b - a) for a, b in zip(heights, heights[1:])))


def get_forest_coverages(lines):
    """Sample evenly along each route using the SwissTLM3D forest mask."""
    bounds = [line.bounds for line in lines]
    west = min(box[0] for box in bounds) - 20
    south = min(box[1] for box in bounds) - 20
    east = max(box[2] for box in bounds) + 20
    north = max(box[3] for box in bounds) + 20
    resolution = max(5, (east - west) / 1024, (north - south) / 1024)
    width = math.ceil((east - west) / resolution)
    height = math.ceil((north - south) / resolution)
    response = requests.get(
        WMS_URL,
        params={
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
            "LAYERS": FOREST_LAYER, "STYLES": "default", "CRS": "EPSG:2056",
            "BBOX": f"{west},{south},{east},{north}",
            "WIDTH": width, "HEIGHT": height, "FORMAT": "image/png", "TRANSPARENT": "TRUE",
        },
        timeout=12,
    )
    response.raise_for_status()
    try:
        with Image.open(BytesIO(response.content)) as image:
            if image.size != (width, height):
                raise ValueError("Unexpected forest map dimensions")
            alpha = image.convert("RGBA").getchannel("A")
    except OSError as error:
        raise ValueError("The forest map could not be read") from error

    coverages = []
    for line in lines:
        covered = 0
        for i in range(100):
            point = line.interpolate((i + 0.5) / 100, normalized=True)
            x = int((point.x - west) * width / (east - west))
            y = int((north - point.y) * height / (north - south))
            covered += alpha.getpixel((x, y)) >= 128
        coverages.append(covered)
    return coverages
