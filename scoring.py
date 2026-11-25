# AI use: generated with ChatGPT (OpenAI, 2026); simplified and commented
# with Claude (Anthropic, Claude Opus 5.5, 2026). See README.md, "AI use".
"""The rule-based RunComfy score (0–100) and the preference warnings.

The score has four factors:
    distance     up to 30 points   close to the requested distance
    elevation    up to 30 points   climbing within the chosen range
    temperature  up to 15 points   close to 15 °C
    air quality  up to 15 points   low air pollution
"""

import settings
from helpers import metric_text, number


def elevation_text(hill_preference):
    """The climbing range of an elevation preference, e.g. "10–25 m per km"."""
    minimum, maximum = settings.HILL_LEVELS[hill_preference]["gain_per_km"]
    return f"{minimum}–{maximum} m per km"


def calculate_score(route, target_distance, hill_preference, temperature, aqi):
    """Score one route and explain the points of every factor.

    If weather or air data is missing, that factor is left out and the
    remaining points are scaled up to 100.
    """
    km = route["distance"]
    gain_per_km = route["elevation"] / km
    minimum, maximum = settings.HILL_LEVELS[hill_preference]["gain_per_km"]
    outside = max(0, minimum - gain_per_km, gain_per_km - maximum)  # m per km outside the range
    temperature = number(temperature)
    aqi = number(aqi)

    factors = [
        # Distance: 30 points if exact, minus 6 points per km too long or too short.
        {
            "name": "Distance",
            "points": max(0, 30 - abs(km - target_distance) * 6),
            "maximum": 30,
            "input": f"{km:.1f} km / target {target_distance:g} km",
            "formula": "max(0, 30 - |distance - target| × 6)",
        },
        # Elevation: 30 points inside the range, minus 1 point per m/km outside.
        {
            "name": "Elevation",
            "points": max(0, 30 - outside),
            "maximum": 30,
            "input": f"{gain_per_km:.1f} m per km; {hill_preference} = {elevation_text(hill_preference)}",
            "formula": "max(0, 30 - (climbing per km outside the range))",
        },
        # Temperature: 15 points at 15 °C, minus 1 point per degree warmer or colder.
        {
            "name": "Temperature",
            "points": None if temperature is None else max(0, 15 - abs(temperature - 15)),
            "maximum": 15,
            "input": metric_text(temperature, " °C"),
            "formula": "max(0, 15 - |temperature - 15|)",
        },
        # Air quality: 15 points up to an AQI of 20, then minus 0.3 points per AQI point.
        {
            "name": "Air quality",
            "points": None if aqi is None else max(0, 15 - max(0, aqi - 20) * 0.3),
            "maximum": 15,
            "input": f"European AQI: {metric_text(aqi)}",
            "formula": "max(0, 15 - (AQI above 20) × 0.3)",
        },
    ]

    # Leave out missing factors and scale the rest to 100.
    available = [factor for factor in factors if factor["points"] is not None]
    points = sum(factor["points"] for factor in available)
    maximum_points = sum(factor["maximum"] for factor in available)
    return {
        "score": round(points / maximum_points * 100),
        "points": points,
        "maximum": maximum_points,
        "factors": factors,
    }


def preference_warnings(route, target_distance, hill_preference):
    """Warn if a route does not match the request. Warnings do not change the score."""
    warnings = []

    km = route["distance"]
    tolerance = target_distance * settings.DISTANCE_TOLERANCE_PCT / 100
    if abs(km - target_distance) > tolerance:
        warnings.append(
            f"Distance: {km:.2f} km instead of {target_distance:g} km "
            f"(more than ±{settings.DISTANCE_TOLERANCE_PCT}% off)."
        )

    gain_per_km = route["elevation"] / km
    minimum, maximum = settings.HILL_LEVELS[hill_preference]["gain_per_km"]
    if not minimum <= gain_per_km <= maximum:
        warnings.append(
            f"Climbing: {gain_per_km:.1f} m per km, but {hill_preference} "
            f"means {elevation_text(hill_preference)}."
        )

    return warnings
