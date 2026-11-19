import streamlit as st
import requests
import math
import os
import re
from html import unescape
from pathlib import Path

from streamlit.errors import StreamlitSecretNotFoundError

import swiss_services

# ==========================================
# 1. RUNCOMFY AI SETTINGS
# ==========================================

st.set_page_config(
    page_title="RunComfy AI",
    page_icon="🏃",
    layout="wide"
)
# Load RunComfy AI design
css_file = Path(__file__).parent / "style.css"

if css_file.is_file():
    st.markdown(
        f"<style>{css_file.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True
    )

st.markdown("""
<div class="main-title">RunComfy AI</div>
<p class="subtitle">Find a comfortable running route in Switzerland.</p>
""", unsafe_allow_html=True)


def setting(name):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return None


ROUTER_URL = setting("RUNCOMFY_ROUTER_URL") or swiss_services.DEFAULT_ROUTER_URL
cached_running_route = st.cache_data(ttl=900, max_entries=256)(swiss_services.get_running_route)

swiss_map = st.components.v2.component(
    "runcomfy_swiss_map",
    html='<div class="runcomfy-map" aria-label="swisstopo map"></div><div class="map-status" role="status"></div>',
    css=".runcomfy-map { width: 100%; height: min(62vh, 540px); min-height: 320px; }",
    js=Path(__file__).with_name("swiss_map.js").read_text(encoding="utf-8"),
    isolate_styles=False,
)

SEARCH_URL = "https://api3.geo.admin.ch/rest/services/ech/SearchServer"
SEARCH_PARAMS = {
    "type": "locations",
    "origins": "address,gg25,gazetteer,zipcode",
    "limit": 5,
    "sr": 4326,
}

swiss_search = st.components.v2.component(
    "runcomfy_swiss_search",
    html="""
        <form class="swiss-location-search" role="search">
            <label for="swiss-search-input">Enter any Swiss address or location</label>
            <div class="swiss-search-row">
                <div class="swiss-search-field">
                    <input id="swiss-search-input" type="search" role="combobox"
                        aria-autocomplete="list" aria-expanded="false" aria-controls="swiss-search-list"
                        autocomplete="off" maxlength="150" placeholder="e.g. Bahnhof Chur, St. Gallen, Zurich">
                    <ul id="swiss-search-list" role="listbox" aria-label="Swiss locations" hidden></ul>
                </div>
                <button type="submit">Search location</button>
            </div>
            <div class="swiss-search-status" role="status"></div>
        </form>
    """,
    css="""
        .swiss-location-search { color: var(--st-text-color, #262730); }
        .swiss-location-search label { display: block; font-size: .875rem; margin-bottom: .4rem; }
        .swiss-search-row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: start; }
        .swiss-search-field { position: relative; flex: 1 1 15rem; min-width: 0; }
        .swiss-location-search input, .swiss-location-search button {
            min-height: 2.5rem; padding: .45rem .75rem; border-radius: .5rem;
            border: 1px solid var(--st-border-color, #b8b8bf);
            background: var(--st-secondary-background-color, #f0f2f6);
            color: inherit; font: inherit;
        }
        .swiss-location-search input { width: 100%; }
        .swiss-location-search button { cursor: pointer; }
        .swiss-location-search :focus-visible {
            outline: 2px solid var(--st-primary-color, #ff4b4b);
        }
        .swiss-location-search [role=listbox] {
            position: absolute; z-index: 20; inset: 100% 0 auto;
            list-style: none; margin: .2rem 0 0; padding: .25rem;
            max-height: 15rem; overflow-y: auto;
            border: 1px solid var(--st-border-color, #b8b8bf); border-radius: .5rem;
            background: var(--st-background-color, #fff); box-shadow: 0 .3rem .8rem #0002;
        }
        .swiss-location-search [role=option] {
            padding: .45rem .65rem; cursor: pointer; border-radius: .3rem;
        }
        .swiss-location-search [role=option]:hover, .swiss-location-search [aria-selected=true] {
            background: var(--st-secondary-background-color, #f0f2f6);
            outline: 1px solid var(--st-primary-color, #ff4b4b);
        }
        .swiss-search-status { font-size: .875rem; }
    """,
    js=Path(__file__).with_name("swiss_search.js").read_text(encoding="utf-8"),
)

# Scoring limits are unchanged. Warning thresholds are configurable in the UI.
DEFAULT_START = (47.4245, 9.3767)
FITNESS_LIMITS = {"Beginner": 10, "Intermediate": 25, "Advanced": 45}
HILL_MULTIPLIERS = {"Flat": 0.5, "Moderate": 1, "Hilly": 2}


def metric_text(value, unit="", decimals=1):
    value = swiss_services.number(value)
    return "Unavailable" if value is None else f"{value:.{decimals}f}{unit}"


def elevation_limit(fitness, hill_preference):
    return FITNESS_LIMITS[fitness] * HILL_MULTIPLIERS[hill_preference]


# Default location: St. Gallen
if "start" not in st.session_state:
    st.session_state.start = DEFAULT_START

if "start_source" not in st.session_state:
    st.session_state.start_source = (
        "default" if tuple(st.session_state.start) == DEFAULT_START else "selected"
    )
if "start_label" not in st.session_state:
    st.session_state.start_label = (
        "St. Gallen" if st.session_state.start_source == "default"
        else "Previously selected location"
    )

if "routes" not in st.session_state:
    st.session_state.routes = []
if "start_revision" not in st.session_state:
    st.session_state.start_revision = 0


def set_start(location, source, label):
    # Move the start marker and discard routes calculated for the previous location.
    st.session_state.start = location
    st.session_state.start_source = source
    st.session_state.start_label = label
    st.session_state.routes = []
    st.session_state.start_revision += 1


# ==========================================
# 2. SWISS LOCATION SEARCH
# ==========================================

@st.cache_data(ttl=3600, max_entries=512)
def search_locations(address):
    response = requests.get(
        SEARCH_URL,
        params={**SEARCH_PARAMS, "searchText": address},
        timeout=10,
    )
    response.raise_for_status()

    matches = []
    for result in response.json().get("results", []):
        attributes = result.get("attrs", {})
        lat = swiss_services.number(attributes.get("lat"))
        lon = swiss_services.number(attributes.get("lon"))
        if lat is None or lon is None:
            continue

        label = unescape(re.sub(r"<[^>]*>", "", attributes.get("label") or address))
        matches.append((str(result.get("id")), (lat, lon), " ".join(label.split())))

    return matches


def update_location_suggestions():
    request = st.session_state.swiss_location_search.get("lookup")
    if not isinstance(request, dict) or not isinstance(request.get("query"), str):
        return

    query = request["query"].strip()[:150]
    if len(query) < 2:
        return

    batch = {"query": query, "id": request.get("id"), "matches": []}
    try:
        batch["matches"] = [
            {"id": match_id, "label": label}
            for match_id, _, label in search_locations(query)
        ]
    except (requests.RequestException, ValueError):
        batch["error"] = True

    st.session_state.location_suggestions = batch


def submit_location_search():
    submission = st.session_state.swiss_location_search.get("submit")
    if not isinstance(submission, dict) or not isinstance(submission.get("query"), str):
        return

    query = submission["query"].strip()[:150]
    if not query:
        return

    st.session_state.last_location_query = query
    st.session_state.location_suggestions = None
    st.session_state.location_search_message = None

    try:
        matches = search_locations(query)
        selection_id = submission.get("selectionId")
        if selection_id is None:
            match = next(iter(matches), None)
        else:
            match = next((item for item in matches if item[0] == selection_id), None)

        if match:
            _, location, label = match
            st.session_state.last_location_query = label
            set_start(location, "search", label)
        elif selection_id is not None:
            st.session_state.location_search_message = (
                "That suggestion is no longer available. Search again to refresh the matches."
            )
        else:
            st.session_state.location_search_message = "Location not found in Switzerland."
    except (requests.RequestException, ValueError):
        st.session_state.location_search_message = (
            "The Swiss location search is temporarily unavailable. Try again shortly."
        )

def is_swiss_location(lat, lon):

    response = requests.get(

        "https://api3.geo.admin.ch/rest/services/api/MapServer/identify",

        params={

            "geometry": f"{lon},{lat}",

            "geometryType": "esriGeometryPoint",

            "imageDisplay": "500,500,96",

            "mapExtent": f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",

            "tolerance": 1,

            "layers": "all:ch.swisstopo.swissboundaries3d-land-flaeche.fill",

            "sr": 4326,

            "returnGeometry": "false"

        },

        timeout=20

    )

    response.raise_for_status()

    results = response.json().get("results", [])

    return len(results) > 0

# ==========================================
# 3. WEATHER
# ==========================================

@st.cache_data(ttl=1800)
def get_weather(lat, lon):

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": [
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "wind_speed_10m"
            ]
        },
        timeout=20
    )

    response.raise_for_status()

    return response.json()["current"]


# ==========================================
# 4. AIR QUALITY
# ==========================================

@st.cache_data(ttl=1800)
def get_air_quality(lat, lon):

    response = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": [
                "european_aqi",
                "pm2_5"
            ]
        },
        timeout=20
    )

    response.raise_for_status()

    return response.json()["current"]


# ==========================================
# 5. MAP AND ROUTE DATA
# ==========================================
# Route calculation and terrain sampling are provided by swiss_services.py.

# ==========================================
# 8. RUNCOMFY SCORE
# ==========================================

def calculate_score(
    route,
    target_distance,
    fitness,
    hill_preference,
    temperature,
    aqi,
    return_breakdown=False
):
    route_distance = swiss_services.number(route.get("distance"))
    if route_distance is not None and route_distance <= 0:
        route_distance = None

    gain = swiss_services.number(route.get("elevation"))
    if gain is not None and gain < 0:
        gain = None

    temperature, aqi = swiss_services.number(temperature), swiss_services.number(aqi)

    distance_score = (
        max(0, 30 - abs(route_distance - target_distance) * 6)
        if route_distance is not None else None
    )

    elevation_per_km = (
        gain / max(route_distance, 0.1)
        if gain is not None and route_distance is not None else None
    )
    limit = elevation_limit(fitness, hill_preference)
    elevation_score = (
        max(0, 30 - max(0, elevation_per_km - limit))
        if elevation_per_km is not None else None
    )

    temperature_score = (
        max(0, 15 - abs(temperature - 15))
        if temperature is not None else None
    )

    air_score = (
        max(0, 15 - max(0, aqi - 20) * 0.3)
        if aqi is not None else None
    )

    components = [
        {
            "Factor": "Distance",
            "Points": distance_score,
            "Maximum": 30,
            "Input": f"{metric_text(route_distance, ' km')} / target {target_distance:g} km",
            "Calculation": "max(0, 30 - abs(distance - target) × 6)",
        },
        {
            "Factor": "Elevation",
            "Points": elevation_score,
            "Maximum": 30,
            "Input": f"{metric_text(elevation_per_km, ' m/km')}; limit {limit:g} m/km ({fitness}, {hill_preference})",
            "Calculation": "max(0, 30 - max(0, gain per km - limit)); gain per km = gain / max(distance, 0.1)",
        },
        {
            "Factor": "Temperature",
            "Points": temperature_score,
            "Maximum": 15,
            "Input": metric_text(temperature, " °C"),
            "Calculation": "max(0, 15 - abs(temperature - 15))",
        },
        {
            "Factor": "Air quality",
            "Points": air_score,
            "Maximum": 15,
            "Input": f"European AQI: {metric_text(aqi)}",
            "Calculation": "max(0, 15 - max(0, AQI - 20) × 0.3)",
        },
    ]

    available = [item for item in components if item["Points"] is not None]
    raw_total = sum(item["Points"] for item in available)
    available_max = sum(item["Maximum"] for item in available)

    total = raw_total
    if available_max and available_max != 100:
        total = total / available_max * 100

    score = round(max(0, min(100, total))) if available_max else None
    breakdown = {
        "score": score,
        "components": components,
        "raw_total": raw_total,
        "available_max": available_max,
    }
    return breakdown if return_breakdown else score


def preference_warnings(route, preferences):
    """Check saved generation preferences, independently of ranking."""
    warnings = []
    actual = swiss_services.number(route.get("distance"))
    if actual is None or actual <= 0:
        warnings.append("Distance unavailable — the distance and elevation preferences cannot be fully checked.")
    else:
        target = preferences["distance"]
        tolerance = target * preferences["distance_tolerance_pct"] / 100
        if abs(actual - target) > tolerance + 1e-9:
            warnings.append(
                f"Distance mismatch: {actual:.2f} km versus {target:g} km requested. "
                f"Allowed deviation: ±{preferences['distance_tolerance_pct']:g}% (±{tolerance:.2f} km)."
            )
    gain = swiss_services.number(route.get("elevation"))
    if gain is None or gain < 0:
        warnings.append("Elevation unavailable — the elevation preference could not be checked.")
    elif actual is not None and actual > 0:
        gain_per_km = gain / max(actual, 0.1)
        minimum, maximum = preferences["elevation_min"], preferences["elevation_max"]
        if gain_per_km < minimum or gain_per_km > maximum:
            warnings.append(
                f"Elevation mismatch: {gain_per_km:.1f} m gain/km; "
                f"{preferences['hill_preference']} accepts {minimum:g}–{maximum:g} m gain/km."
            )
    return warnings


# ==========================================
# 9. USER INTERFACE
# ==========================================

st.header("📍 Choose your starting point")

swiss_search(
    key="swiss_location_search",
    data={
        "lastQuery": st.session_state.get("last_location_query", ""),
        "suggestions": st.session_state.get("location_suggestions"),
    },
    on_lookup_change=update_location_suggestions,
    on_submit_change=submit_location_search,
)

if search_message := st.session_state.get("location_search_message"):
    st.warning(search_message)

lat, lon = st.session_state.start

st.write("**Selected starting location:**", st.session_state.start_label)
st.caption(f"Latitude {lat:.5f}, longitude {lon:.5f}")
if st.session_state.start_source == "default":
    st.info("Using the default starting location: St. Gallen. Search or confirm a point on the map to change it.")

# Reserve one map near the location controls and draw it after route generation.
map_container = st.container()


# ==========================================
# 10. RUNNING PREFERENCES
# ==========================================

st.header("🏃 Your running preferences")

col1, col2 = st.columns(2)

with col1:

    fitness = st.selectbox(
        "Fitness level",
        ["Beginner", "Intermediate", "Advanced"]
    )

    distance = st.slider(
        "Desired running distance (km)",
        min_value=2,
        max_value=30,
        value=5
    )

with col2:

    hill_preference = st.selectbox(
        "Elevation preference",
        ["Flat", "Moderate", "Hilly"]
    )

# ==========================================
# 11. GENERATE RUNNING ROUTES
# ==========================================


with st.expander("Preference warning thresholds"):
    st.caption(
        "These checks flag mismatches; they do not change the scoring formula. "
        "Distance defaults to ±10%. Elevation maxima default to the existing "
        "fitness limits (10 / 25 / 45 m gain per km), multiplied by "
        "0.5 for Flat, 1 for Moderate, or 2 for Hilly. "
        "Hilly additionally defaults to a minimum of 10 m gain per km."
    )
    distance_tolerance_pct = st.number_input(
        "Allowed distance deviation (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0
    )
    elevation_max = st.number_input(
        "Maximum elevation gain per km for warnings (m/km)",
        min_value=0.0, value=float(elevation_limit(fitness, hill_preference)), step=1.0,
        key=f"warning_elevation_max_{fitness}_{hill_preference}"
    )
    elevation_min = 0.0
    if hill_preference == "Hilly":
        elevation_min = st.number_input(
            "Minimum Hilly elevation gain per km (m/km)",
            min_value=0.0, value=10.0, step=1.0
        )
    
preferences = dict(
    distance=distance,
    fitness=fitness,
    hill_preference=hill_preference,
    distance_tolerance_pct=distance_tolerance_pct,
    elevation_min=elevation_min,
    elevation_max=elevation_max,
)
thresholds_valid = elevation_min <= elevation_max

if not thresholds_valid:
    st.warning("Each minimum warning threshold must be less than or equal to its maximum.")

if st.button("🚀 Find my perfect running route", disabled=not thresholds_valid):

    lat, lon = st.session_state.start

    with st.spinner("Analysing running routes..."):

        try:

            # Try several directions and adjust the waypoint radius on the second pass.
            st.session_state.routes = []
            routes = []
            first_pass_distances = {}
            errors = []
            matches = 0
            tolerance = distance * distance_tolerance_pct / 100
            for attempt in range(8):
                try:
                    route = cached_running_route(
                        ROUTER_URL, lat, lon, distance, attempt, first_pass_distances.get(attempt % 4)
                    )
                except swiss_services.RoutingUnavailable as error:
                    errors.append(str(error))
                    break
                except (requests.RequestException, ValueError):
                    errors.append("The pedestrian routing service could not complete the request.")
                    if len(errors) == 2:
                        break
                    continue

                if route is None:
                    continue
                if attempt < 4:
                    first_pass_distances[attempt] = route["distance"]

                # Keep the preference warning useful, but skip large distance mismatches.
                if abs(route["distance"] - distance) > distance * 0.35 or any(
                    route["coordinates"] in (existing["coordinates"], existing["coordinates"][::-1])
                    for existing in routes
                ):
                    continue
                routes.append(route)
                if abs(route["distance"] - distance) <= tolerance + 1e-9:
                    matches += 1
                    if matches == 3:
                        break

            if not routes:
                raise swiss_services.RoutingUnavailable(
                    errors[-1] if errors else
                    "No suitable running loop found. Try another starting point or distance."
                )

            # Score the three loops closest to the requested distance.
            routes.sort(key=lambda route: abs(route["distance"] - distance))
            routes = routes[:3]
            try:
                weather = get_weather(lat, lon)
            except (requests.RequestException, ValueError, KeyError):
                weather = {}
            try:
                air = get_air_quality(lat, lon)
            except (requests.RequestException, ValueError, KeyError):
                air = {}
            temperature = swiss_services.number(weather.get("temperature_2m"))
            aqi = swiss_services.number(air.get("european_aqi"))

            terrain_lines = [swiss_services.project_route(route["coordinates"]) for route in routes]
                    
            for route, terrain_line in zip(routes, terrain_lines):                
                try:
                    route["elevation"] = swiss_services.get_elevation_gain(terrain_line)
                except (requests.RequestException, ValueError):
                    route["elevation"] = None
                
                route["score_breakdown"] = calculate_score(
                    route,
                    distance,
                    fitness,
                    hill_preference,
                    temperature,
                    aqi,
                    return_breakdown=True
                )
                route["score"] = route["score_breakdown"]["score"]
                route["preference_warnings"] = preference_warnings(route, preferences)

            routes.sort(
                key=lambda route: route["score"] if route["score"] is not None else -1,
                reverse=True
            )

            # Save the results and the settings used to calculate them.
            st.session_state.routes = routes
            st.session_state.route_view = 0
            st.session_state.result_preferences = preferences.copy()
            st.session_state.result_start = tuple(st.session_state.start)
            st.session_state.result_start_label = st.session_state.start_label
            st.session_state.result_start_source = st.session_state.start_source

            st.session_state.weather = weather
            st.session_state.air = air

        except swiss_services.RoutingUnavailable as error:
            st.error(str(error))
        except Exception as error:

            st.error(f"An error occurred: {error}")


with map_container:
    # Use the same map for the selected start, a pending point and the generated loops.
    route_colors = ("#087f5b", "#1554c4", "#8c239e")
    map_routes = [
        {
            "path": [point[:2] for point in route["coordinates"]],
            "color": route_colors[i],
            "label": f"Route {i + 1} · {metric_text(route.get('distance'), ' km')}",
        }
        for i, route in enumerate(st.session_state.routes)
    ]
    route_view = 0
    if map_routes:
        route_view = st.selectbox(
            "Show running routes on the map",
            range(len(map_routes) + 1),
            format_func=lambda index: map_routes[index - 1]["label"] if index else "All routes",
            key="route_view",
        )
        st.caption("Click a route to see its label. To choose a new start, click elsewhere on the map or enable the option below.")
        pick_on_route = st.checkbox("Pick a new starting point", key="pick_on_route")
    else:
        pick_on_route = True
        st.caption("Click the map to choose a starting point.")

    revision = st.session_state.start_revision
    previous_map_state = st.session_state.get("shared_swiss_map") or {}
    pending = previous_map_state.get("point")
    if not isinstance(pending, dict) or pending.get("revision") != revision:
        pending = None

    picker = swiss_map(
        key="shared_swiss_map",
        data={
            "center": {"lat": lat, "lng": lon},
            "revision": revision,
            "pending": pending,
            "routes": map_routes,
            "routeView": route_view,
            "pickOnRoute": pick_on_route,
        },
        default={"point": None},
        on_point_change=lambda: None,
    )
    clicked = picker.point
    # Make the clicked point the new start only after confirmation and a country check.
    if isinstance(clicked, dict) and clicked.get("revision") == revision:
        selected_lat = swiss_services.number(clicked.get("lat"))
        selected_lon = swiss_services.number(clicked.get("lng"))
        if (selected_lat is not None and 45.7 <= selected_lat <= 47.9
                and selected_lon is not None and 5.8 <= selected_lon <= 10.7):
            st.write(f"Selected: {selected_lat:.5f}, {selected_lon:.5f}")
            if st.button("📍 Confirm starting point"):
                try:
                    if is_swiss_location(selected_lat, selected_lon):
                        set_start((selected_lat, selected_lon), "map", "Confirmed map location")
                        st.rerun()
                    else:
                        st.warning("Please choose a location in Switzerland.")
                except (requests.RequestException, ValueError) as error:
                    st.error(f"Location check failed: {error}")
        else:
            st.warning("Please choose a location in Switzerland.")


# ==========================================
# 12. DISPLAY RESULTS
# ==========================================

if st.session_state.routes:

    routes = st.session_state.routes

    weather = st.session_state.weather
    air = st.session_state.air

    lat, lon = st.session_state.get("result_start", st.session_state.start)
    saved_preferences = st.session_state.get("result_preferences")
    if saved_preferences is None:
        st.info("Generate routes again to see preference checks and score explanations.")
    elif saved_preferences != preferences:
        st.info("Preferences or warning thresholds have changed. These results use the settings below; generate routes again to apply your changes.")

    st.write("**Starting location used for these routes:**",
             st.session_state.get("result_start_label", st.session_state.start_label))
    st.caption(f"Latitude {lat:.5f}, longitude {lon:.5f}")
    if st.session_state.get("result_start_source", st.session_state.start_source) == "default":
        st.info("These routes use the default starting location: St. Gallen.")
    if saved_preferences:
        st.caption(
            f"Generated for {saved_preferences['distance']:g} km · {saved_preferences['fitness']} · "
            f"Warning thresholds: distance ±{saved_preferences['distance_tolerance_pct']:g}%; "
            f"elevation {saved_preferences['elevation_min']:g}–{saved_preferences['elevation_max']:g} m/km."
        )

    st.header("🌤️ Current running conditions")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Temperature",
        metric_text(weather.get('temperature_2m'), ' °C')
    )

    c2.metric(
        "Feels like",
        metric_text(weather.get('apparent_temperature'), ' °C')
    )

    c3.metric(
        "Air Quality Index",
        metric_text(air.get("european_aqi"))
    )

    c4.metric(
        "Wind",
        metric_text(weather.get('wind_speed_10m'), ' km/h')
    )

    st.write(
        f"🌧️ Current precipitation: "
        f"{metric_text(weather.get('precipitation'), ' mm')}"
    )

    # ======================================
    # RECOMMENDATIONS
    # ======================================

    st.header("🏆 Your personalized recommendations")

    medals = ["🥇", "🥈", "🥉"]

    for i, route in enumerate(routes):

        st.subheader(
            f"{medals[i]} Route {i+1}"
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Distance",
            metric_text(route.get('distance'), ' km')
        )

        col2.metric(
            "Elevation gain",
            metric_text(route.get('elevation'), ' m', 0)
        )

        col3.metric(
            "RunComfy Score",
            metric_text(route.get('score'), '/100', 0)
        )

        for message in route.get("preference_warnings", []):
            st.warning(message)

        with st.expander(f"How Route {i+1} was scored"):
            breakdown = route.get("score_breakdown")
            if not breakdown:
                st.info("Score details unavailable. Generate this route again to see its calculation.")
            else:
                for component in breakdown["components"]:
                    points = component["Points"]
                    label = "Unavailable — omitted" if points is None else f"{points:.2f} / {component['Maximum']} points"
                    st.write(f"**{component['Factor']}: {label}**")
                    st.caption(component["Input"])
                    st.code(component["Calculation"], language="text")
                maximum = breakdown["available_max"]
                if not maximum:
                    st.write("Score unavailable: no scoring inputs are available.")
                elif maximum == 100:
                    st.write(f"Total: {breakdown['raw_total']:.2f} / 100 → rounded score {breakdown['score']}/100.")
                else:
                    st.write(
                        f"Available total: {breakdown['raw_total']:.2f} / {maximum}. "
                        f"Rescaled to 100 and rounded: {breakdown['score']}/100."
                    )
                st.caption(
                    "Elevation scoring penalizes gain above its limit; it does not reward a minimum amount of hills. "
                    "Preference warnings are separate checks and do not deduct points. "
                    "Feels-like temperature, wind and precipitation are displayed but do not affect this score."
                )

        if i == 0:

            st.success(
                "⭐ Best matching running route!"
            )

        st.divider()

    st.caption(
        "RunComfy AI uses real routing, weather and "
        "air-quality data. Scores are rule-based."
    )

    st.caption(
        "Maps and elevation: © swisstopo. Routing: Valhalla, © OpenStreetMap contributors. "
        "Weather and air quality: Open-Meteo."        "Weather and air quality: Open-Meteo."
    )
