"""Route calculation and Swiss federal geodata for RunComfy."""

import json
import math
import threading
import time

import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point


DEFAULT_ROUTER_URL = "https://valhalla1.openstreetmap.de/route"
PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"
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


def is_running_loop(line, lat, lon, distance):
    # Check that both ends are near the selected start and meet on the same path.
    start = Point(TO_LV95.transform(lon, lat, errcheck=True))
    first = Point(line.coords[0])
    last = Point(line.coords[-1])
    if first.distance(last) > 5 or max(first.distance(start), last.distance(start)) > 120:
        return False

    # Skip routes that stray too far for the requested distance.
    if max(math.hypot(x - start.x, y - start.y) for x, y in line.coords) > distance * 400:
        return False

    # Count overlapping stretches once, then reject routes that retrace too much.
    unique_length = line.union(line).length
    if unique_length < 0.82 * line.length:
        return False

    # A loop needs some spread, even when its paths only run close in parallel.
    return line.convex_hull.area >= 0.08 * unique_length**2 / (4 * math.pi)


def get_running_route(router_url, lat, lon, distance, attempt, previous_distance=None):
    # Ask the pedestrian router to visit two waypoints and return to the start.
    radius, bearing = loop_waypoints(distance, attempt, previous_distance)
    start = {"lat": lat, "lon": lon, "search_cutoff": 120}
    waypoints = [
        {**waypoint_at_bearing(lat, lon, radius, angle), "type": "through", "search_cutoff": 400}
        for angle in (bearing, bearing + 60)
    ]
    payload = {
        "locations": [start, *waypoints, start],
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
    # Return only usable loops drawn from the routing service's geometry.
    for route in result.get("routes", []):
        coordinates = route.get("geometry", {}).get("coordinates", [])
        distance_m = number(route.get("distance"))
        if len(coordinates) < 4 or distance_m is None or distance_m <= 0:
            continue
        line = project_route(coordinates)
        if is_running_loop(line, lat, lon, distance):
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

