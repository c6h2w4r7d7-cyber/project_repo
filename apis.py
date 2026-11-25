# AI use: generated with ChatGPT (OpenAI, 2026); moved here and commented
# with Claude (Anthropic, Claude Opus 5.5, 2026). See README.md, "AI use".
"""Data from external APIs: Swiss location search, weather and air quality.

(Route finding and elevation are in routing.py.)
st.cache_data remembers each answer for a while, so repeated requests
with the same input do not call the API again.
"""

import re
from html import unescape

import requests
import streamlit as st

from helpers import number

GEOADMIN_SEARCH_URL = "https://api3.geo.admin.ch/rest/services/ech/SearchServer"
GEOADMIN_IDENTIFY_URL = "https://api3.geo.admin.ch/rest/services/api/MapServer/identify"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


@st.cache_data(ttl=3600, max_entries=512)
def search_locations(text):
    """Up to five Swiss places matching the text, as {label: (lat, lon)}."""
    response = requests.get(
        GEOADMIN_SEARCH_URL,
        params={
            "searchText": text,
            "type": "locations",
            "origins": "address,gg25,gazetteer,zipcode",  # addresses, towns, place names, postcodes
            "limit": 5,
            "sr": 4326,  # answer in normal GPS coordinates
        },
        timeout=10,  # give up after 10 seconds
    )
    response.raise_for_status()  # stop with an error if the API answered with one

    # The answer is JSON: a list of results, each with a label and coordinates.
    matches = {}
    for result in response.json().get("results", []):
        attributes = result.get("attrs", {})
        lat = number(attributes.get("lat"))
        lon = number(attributes.get("lon"))
        if lat is None or lon is None:
            continue
        # The label contains HTML such as "<b>St. Gallen</b>": keep only the text.
        label = unescape(re.sub(r"<[^>]*>", "", attributes.get("label") or text))
        matches[" ".join(label.split())] = (lat, lon)
    return matches


def is_swiss_location(lat, lon):
    """True if the point lies inside the Swiss national border (swisstopo)."""
    # Asks: which parts of the layer "Swiss national territory" lie at this point?
    # No result means the point is outside Switzerland. imageDisplay, mapExtent
    # and tolerance are required by the API (a small map around the point).
    response = requests.get(
        GEOADMIN_IDENTIFY_URL,
        params={
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "imageDisplay": "500,500,96",
            "mapExtent": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}",
            "tolerance": 1,
            "layers": "all:ch.swisstopo.swissboundaries3d-land-flaeche.fill",
            "sr": 4326,
            "returnGeometry": "false",
        },
        timeout=20,
    )
    response.raise_for_status()
    return len(response.json().get("results", [])) > 0


@st.cache_data(ttl=1800)
def get_weather(lat, lon):
    """Current temperature, felt temperature, precipitation and wind (Open-Meteo)."""
    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": [
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "wind_speed_10m",
            ],
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["current"]


@st.cache_data(ttl=1800)
def get_air_quality(lat, lon):
    """Current European Air Quality Index (Open-Meteo)."""
    response = requests.get(
        AIR_QUALITY_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": ["european_aqi"],
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["current"]
