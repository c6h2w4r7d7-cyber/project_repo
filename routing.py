# AI use: generated with ChatGPT (OpenAI, 2026). With Claude (Anthropic,
# Claude Opus 5.5, 2026): find_routes() moved here from app.py, the loop checks
# changed (one loop per direction, no dead-end detours), to_gpx() and
# turns_around() written, and the file simplified and commented.
# See README.md, "AI use".
"""Find closed running loops and their elevation gain.

How a loop is built: the router (Valhalla, a free route planner using
OpenStreetMap data) walks from the start to two waypoints and back to the
start. This gives a triangle-shaped loop; other directions give other loops.
The elevation gain comes from the swisstopo terrain profile.
"""

import json
import math
import threading
import time

import requests
import streamlit as st
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

import settings
from helpers import number

ROUTER_URL = "https://valhalla1.openstreetmap.de/route"  # free public Valhalla server
PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"  # swisstopo heights

# GPS coordinates (degrees) → Swiss LV95 coordinates (metres), to measure lengths.
TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)

# The public router allows one request per second for all users together.
# The lock makes requests from several users wait for each other.
ROUTER_LOCK = threading.Lock()
last_request = -math.inf

ATTEMPTS = 8  # loops we ask the router for
ROUTES_SHOWN = 3  # loops we recommend


class RoutingUnavailable(RuntimeError):
    """The router cannot be used right now, or no usable loop was found."""


def find_routes(lat, lon, distance):
    """Up to three different loops close to the requested distance (km).

    Each route is a dict with "coordinates", "distance" (km) and "elevation"
    (metres of climbing). Raises RoutingUnavailable if no loop is found.
    """
    # 1. Ask the router for loops in four directions, two tries per direction.
    #    The second try uses the first one's length to get closer to the target.
    best = {}  # direction → the loop closest to the requested distance
    errors = []
    for attempt in range(ATTEMPTS):
        direction = attempt % 4  # 0 = north, 1 = east, 2 = south, 3 = west
        first_try = best.get(direction)
        try:
            loop = get_running_route(
                lat, lon, distance, attempt, first_try["distance"] if first_try else None
            )
        except RoutingUnavailable as error:
            errors.append(str(error))
            break  # the service is down or overloaded: stop asking
        except (requests.RequestException, ValueError):
            errors.append("The pedestrian routing service could not complete the request.")
            if len(errors) == 2:
                break  # two failed requests: give up instead of waiting longer
            continue

        if loop is None:
            continue
        # Two loops in the same direction are nearly the same route,
        # so keep only the one closer to the requested distance.
        if first_try is None or abs(loop["distance"] - distance) < abs(first_try["distance"] - distance):
            best[direction] = loop

    loops = list(best.values())
    if not loops:
        raise RoutingUnavailable(
            errors[-1] if errors else
            "No closed running loop was found. Try another starting point or distance."
        )

    # 2. Add the elevation gain to the loops closest to the requested distance
    #    (one swisstopo request per loop, so only as many as we need).
    loops.sort(key=lambda loop: abs(loop["distance"] - distance))
    routes = []
    for loop in loops:
        try:
            loop["elevation"] = get_elevation_gain(project_route(loop["coordinates"]))
        except (requests.RequestException, ValueError):
            loop["elevation"] = None
        if loop["elevation"] is None:
            continue  # without elevation we cannot score the route
        routes.append(loop)
        if len(routes) == ROUTES_SHOWN:
            break

    if not routes:
        raise RoutingUnavailable(
            "Loops were found, but their elevation could not be checked, "
            "so they are not recommended."
        )
    return routes


@st.cache_data(ttl=900, max_entries=256)  # same question within 15 min: reuse the answer
def get_running_route(lat, lon, distance, attempt, previous_distance=None):
    """Ask the router for one loop. Returns None if it is not a usable loop."""
    # The loop: start → waypoint 1 → waypoint 2 → back to the start, on foot.
    # "through" = no turning around at a waypoint; search_cutoff = how far (m)
    # the router may look for the nearest path to a point.
    radius, bearing = loop_waypoints(distance, attempt, previous_distance)
    start = {"lat": lat, "lon": lon, "search_cutoff": 120}
    waypoints = [
        {**waypoint_at_bearing(lat, lon, radius, angle), "type": "through", "search_cutoff": 400}
        for angle in (bearing, bearing + 60)
    ]
    request = {
        "locations": [start, *waypoints, start],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"use_ferry": 0, "max_hiking_difficulty": 1}},
        "format": "osrm",
        "shape_format": "geojson",  # the path as a list of [lon, lat] points
        "units": "kilometers",
    }

    # Wait until one second has passed since the last request, then send this one.
    global last_request
    with ROUTER_LOCK:
        time.sleep(max(0, 1.05 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        response = requests.get(
            ROUTER_URL,
            params={"json": json.dumps(request, separators=(",", ":"))},
            headers={"X-Client-Id": "RunComfyAI", "User-Agent": "RunComfyAI/1.0"},
            timeout=12,
        )

    # HTTP status codes: 429 = too many requests, 503 = server overloaded, ...
    if response.status_code in (401, 403, 429, 503):
        raise RoutingUnavailable(
            f"The pedestrian routing service is unavailable (HTTP {response.status_code}). "
            "Try again shortly."
        )
    result = response.json()
    if result.get("code") in ("NoRoute", "NoSegment") or result.get("error_code") in (170, 171, 442, 443):
        return None  # no path between the points, e.g. a waypoint in a lake
    response.raise_for_status()  # any other error becomes an exception

    # Keep the router's path only if it passes our loop checks.
    for route in result.get("routes", []):
        coordinates = route.get("geometry", {}).get("coordinates", [])
        distance_m = number(route.get("distance"))
        if len(coordinates) < 4 or distance_m is None or distance_m <= 0:
            continue
        if is_running_loop(project_route(coordinates), lat, lon, distance):
            return {"coordinates": coordinates, "distance": distance_m / 1000}
    return None


def loop_waypoints(distance, attempt, previous_distance=None):
    """Radius (km) and direction (degrees) of the triangle for one attempt.

    Attempts 0–3 point north, east, south and west. Attempts 4–7 use the
    same directions, resized with the distance the first try gave; if the
    first try failed, they turn by 45° instead.
    """
    bearing = (attempt % 4) * 90
    if attempt < 4:
        # Triangle sides of 0.27 × distance; the roads add the rest.
        return distance * 0.27, bearing
    if previous_distance is None:
        return distance * 0.22, bearing + 45
    scale = max(0.45, min(1.45, distance / previous_distance))
    return distance * 0.27 * scale, bearing


def waypoint_at_bearing(lat, lon, radius_km, bearing):
    """The point radius_km away in compass direction bearing (0° = north).

    Standard great-circle formula on a sphere with the Earth's radius of 6371 km.
    """
    latitude = math.radians(lat)
    bearing = math.radians(bearing)
    angle = radius_km / 6371  # the distance as an angle at the Earth's centre
    destination_lat = math.asin(
        math.sin(latitude) * math.cos(angle)
        + math.cos(latitude) * math.sin(angle) * math.cos(bearing)
    )
    delta_lon = math.atan2(
        math.sin(bearing) * math.sin(angle) * math.cos(latitude),
        math.cos(angle) - math.sin(latitude) * math.sin(destination_lat),
    )
    return {"lat": math.degrees(destination_lat), "lon": (lon + math.degrees(delta_lon) + 180) % 360 - 180}


def is_running_loop(line, lat, lon, distance):
    """Check that the router's path (in metres) is a real running loop."""
    if line.is_empty or line.length <= 0:
        return False

    # The route's points, without a point repeated right after itself.
    coordinates = [point for i, point in enumerate(line.coords) if i == 0 or point != line.coords[i - 1]]
    if len(coordinates) < 4:
        return False

    start = Point(TO_LV95.transform(lon, lat, errcheck=True))
    first = Point(coordinates[0])
    last = Point(coordinates[-1])

    # Closed: it ends where it begins, within 120 m of the chosen start.
    if first.distance(last) > 5 or max(first.distance(start), last.distance(start)) > 120:
        return False

    # Not too far away: no point more than 0.4 × distance from the start.
    if max(math.hypot(x - start.x, y - start.y) for x, y in coordinates) > distance * 400:
        return False

    # No detours into dead ends: the path never turns around to run back.
    if any(turns_around(a, b, c) for a, b, c in zip(coordinates, coordinates[1:], coordinates[2:])):
        return False

    # Only a small share is run twice: the way from the start to the loop and back.
    segments = [LineString((a, b)) for a, b in zip(coordinates, coordinates[1:])]
    unique_length = unary_union(segments).length
    if unique_length < (1 - settings.MAX_REPEATED_SHARE) * line.length:
        return False

    # Round enough: the area enclosed is at least 8% of a circle with the same length.
    return line.convex_hull.area >= 0.08 * unique_length**2 / (4 * math.pi)


def turns_around(a, b, c):
    """True if the path a → b → c turns at b and runs back the way it came."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    wx, wy = c[0] - b[0], c[1] - b[1]
    length_u, length_w = math.hypot(ux, uy), math.hypot(wx, wy)
    if length_u < 1 or length_w < 1:
        return False  # too short to tell a direction
    # Cosine of the angle between both directions: -1 means exactly backwards.
    return (ux * wx + uy * wy) / (length_u * length_w) < -0.998


def to_gpx(route, name):
    """The route as a GPX file, the standard format of running apps and watches."""
    # GPX is XML: one <trkpt> (track point) per point of the route.
    points = "\n".join(
        f'      <trkpt lat="{point[1]}" lon="{point[0]}"/>' for point in route["coordinates"]
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="RunComfy AI" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{name}</name>
    <trkseg>
{points}
    </trkseg>
  </trk>
</gpx>
"""


def project_route(coordinates):
    """GPS points (lon, lat) → line in Swiss LV95 coordinates (metres)."""
    longitude, latitude = zip(*(point[:2] for point in coordinates))
    easting, northing = TO_LV95.transform(longitude, latitude, errcheck=True)
    line = LineString(zip(easting, northing))
    if not line.is_valid or line.length <= 0:
        raise ValueError("Invalid route geometry")
    return line


def get_elevation_gain(line):
    """Metres of climbing along the line: the sum of all uphill steps (swisstopo).

    Returns None if the terrain profile is incomplete.
    """
    coordinates = list(line.coords)
    if len(coordinates) > 5000:
        # The API accepts at most 5000 points: keep every n-th one, incl. both ends.
        coordinates = [coordinates[round(i * (len(coordinates) - 1) / 4999)] for i in range(5000)]
    response = requests.post(
        PROFILE_URL,
        data={
            "geom": json.dumps({"type": "LineString", "coordinates": coordinates}),
            "sr": 2056,
            "nb_points": min(400, max(2, math.ceil(line.length / 40) + 1)),  # one height every ~40 m
        },
        timeout=12,
    )
    response.raise_for_status()
    profile = response.json()  # a list of points, each with its height
    if not isinstance(profile, list):
        return None
    heights = [number(point.get("alts", {}).get("COMB")) for point in profile]
    # Missing or impossible heights (outside Switzerland there is no data).
    if len(heights) < 2 or any(height is None or height < -100 for height in heights):
        return None
    # Add up every step uphill (b higher than a); steps downhill count 0.
    return round(sum(max(0, b - a) for a, b in zip(heights, heights[1:])))
