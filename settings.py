# AI use: written with Claude (Anthropic, Claude Opus 5.5, 2026).
# See README.md, "AI use".
"""All definitions and fixed values of RunComfy in one place.

Change a value here and the whole app uses it.
"""

# Starting point until the user picks one: St. Gallen.
DEFAULT_START = (47.4245, 9.3767)
DEFAULT_START_LABEL = "St. Gallen"

# Fitness level = how often, how far and how fast you usually run.
# pace_min_per_km  gives a first time estimate for every route, until the
#                  running log has enough runs for the machine-learning
#                  model (runtime_model.py).
# max_km           a longer distance gets a hint below the distance slider
#                  (None = no limit).
FITNESS_LEVELS = {
    "Beginner": {
        "description": "You run now and then, usually up to 5 km.",
        "pace_min_per_km": 7,
        "max_km": 8,
    },
    "Intermediate": {
        "description": "You run every week, usually 5–10 km.",
        "pace_min_per_km": 6,
        "max_km": 15,
    },
    "Advanced": {
        "description": "You train several times a week, often more than 10 km.",
        "pace_min_per_km": 5,
        "max_km": None,
    },
}

# Climbing in the first time estimate, like the Swiss "Leistungskilometer":
# this many metres uphill take about as long as one extra km on the flat.
CLIMB_M_PER_EXTRA_KM = 100

# Elevation preference = metres uphill per km of the route (min, max).
# Per km, so that the levels mean the same for every distance.
HILL_LEVELS = {
    "Flat": {"description": "Hardly any hills", "gain_per_km": (0, 10)},
    "Moderate": {"description": "Some short climbs", "gain_per_km": (10, 25)},
    "Hilly": {"description": "Many climbs", "gain_per_km": (25, 50)},
}

# A route may be this much longer or shorter than requested without a warning.
DISTANCE_TOLERANCE_PCT = 10

# Share of a loop that may be run twice: the way from the start to the loop
# and back. Higher values find more loops. Detours into dead ends are never
# allowed (see is_running_loop in routing.py).
MAX_REPEATED_SHARE = 0.15
