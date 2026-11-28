# AI use: the original page was generated with ChatGPT (OpenAI, 2026).
# Generated with Claude (Anthropic, Claude Opus 5.5, 2026): the page layout,
# the sticky title, the location search, the running log (section 4), the time
# estimate and the GPX download. Claude also restructured and commented the file.
# See README.md, "AI use".
"""RunComfy AI: find a comfortable running loop in Switzerland.

This file is the web page. Streamlit runs it from top to bottom on every click:
    1. Page setup and session state
    2. Your run: starting point and preferences (left column)
    3. Find routes
    4. Your running log: machine learning (second tab)
    5. Map (right column)
    6. Results

The work behind the page is done in the other files:
    settings.py       definitions: fitness levels, elevation preferences, ...
    apis.py           Swiss location search, weather and air quality
    routing.py        running loops, their elevation gain and GPX export
    scoring.py        RunComfy score and warnings
    runtime_model.py  machine learning: personal run-time prediction
    swiss_map.js      the interactive swisstopo map (JavaScript)
"""

from pathlib import Path

import requests
import streamlit as st

import apis
import routing
import runtime_model
import scoring
import settings
from helpers import metric_text


# ==========================================
# 1. PAGE SETUP AND SESSION STATE
# ==========================================

# Browser tab title and icon; "wide" uses the full width of the window.
st.set_page_config(page_title="RunComfy AI", page_icon="🏃", layout="wide")

# The title stays at the top like a header while the rest of the page scrolls.
# A container with a key gets the CSS class "st-key-<key>"; Streamlit puts it
# inside a "layout wrapper". The CSS makes that wrapper "sticky": it stops
# 3.75rem from the top, right below Streamlit's own top bar. A light grey
# background sets it apart from the page and hides the text that scrolls under
# it. The small padding keeps the header only a little taller than the title.
st.html(f"""
<style>
[data-testid="stLayoutWrapper"]:has(> .st-key-page_header) {{
    position: sticky;
    top: 3.75rem;
    z-index: 999;
    background-color: var(--background-color);
    padding: 0 0.75rem;
}}
.st-key-page_header h1 {{
    font-size: 2.25rem;
    padding: 0.25rem 0;
}}
.st-key-page_header [data-testid="stMarkdownContainer"] {{
    margin-bottom: 0;
}}
</style>
""")
with st.container(key="page_header"):
    st.title("🏃 RunComfy AI")
st.caption("Find a comfortable running route in Switzerland.")

# Streamlit runs this file again from the top after every click (a "rerun").
# st.session_state keeps values between reruns. setdefault only sets a value
# the first time, when the page is opened.
st.session_state.setdefault("start", settings.DEFAULT_START)
st.session_state.setdefault("start_label", settings.DEFAULT_START_LABEL)
st.session_state.setdefault("start_revision", 0)  # counts start changes, for the map
st.session_state.setdefault("routes", [])


def set_start(location, label):
    """Use a new starting point. The old routes do not fit it, so remove them."""
    st.session_state.start = location
    st.session_state.start_label = label
    st.session_state.routes = []
    st.session_state.start_revision += 1


def use_search_result(location, label):
    """Search button: use the chosen match and empty the search box."""
    set_start(location, label)
    st.session_state.search = ""


# Page layout: two tabs. The first tab has two columns: inputs left, map right.
# Everything inside "with input_col:" is placed in the left column, and so on.
route_tab, log_tab = st.tabs(["🗺️ Find a route", "⏱️ My running log"])
input_col, map_col = route_tab.columns([2, 3], gap="large")


# ==========================================
# 2. YOUR RUN: STARTING POINT AND PREFERENCES
# ==========================================

with input_col:
    st.subheader("📍 Start")
    # The user types a place, swisstopo returns up to five matches, the user
    # picks one and clicks the button, which calls use_search_result().
    query = st.text_input(
        "Search a Swiss address or place",
        placeholder="e.g. Bahnhof Chur, St. Gallen, Zurich",
        max_chars=150,
        key="search",
    ).strip()
    if query:
        try:
            matches = apis.search_locations(query)  # {label: (lat, lon)}
        except (requests.RequestException, ValueError):
            matches = None  # the API did not answer

        if matches:
            choice = st.selectbox("Matches", list(matches))
            st.button(
                "📍 Use this location",
                on_click=use_search_result,
                args=(matches[choice], choice),
                width="stretch",
            )
        elif matches is None:
            st.warning("The Swiss location search is temporarily unavailable. Try again shortly.")
        else:
            st.warning("Location not found in Switzerland.")

    # The current start; lat and lon are used for the routes and the map.
    lat, lon = st.session_state.start
    st.markdown(f"**Starting at:** {st.session_state.start_label}")
    st.caption("Search above or click the map to choose another start.")

    # Each widget returns the user's current choice, e.g. fitness = "Beginner".
    st.subheader("🏃 Your run")
    fitness = st.radio(
        "Fitness level",
        list(settings.FITNESS_LEVELS),
        captions=[
            f"{level['description']} About {level['pace_min_per_km']} min per km."
            for level in settings.FITNESS_LEVELS.values()
        ],
        help="Gives a first time estimate for each route (until you have logged "
        f"{runtime_model.MIN_RUNS} runs, then your personal model takes over) "
        "and a hint when a distance is long for your level.",
    )
    distance = st.slider("Distance (km)", min_value=2, max_value=30, value=5)

    # Hint if the distance is longer than recommended for the fitness level.
    max_km = settings.FITNESS_LEVELS[fitness]["max_km"]
    if max_km is not None and distance > max_km:
        st.caption(f"⚠️ {distance} km is long for your fitness level ({fitness}: up to {max_km} km).")

    # The captions show the climbing for the chosen distance. The key keeps
    # the choice when the captions change with the distance.
    hill_preference = st.radio(
        "Elevation preference",
        list(settings.HILL_LEVELS),
        captions=[
            f"{hill['description']}: {hill['gain_per_km'][0] * distance}–"
            f"{hill['gain_per_km'][1] * distance} m uphill on {distance} km"
            for hill in settings.HILL_LEVELS.values()
        ],
        help="Measured in metres uphill per km, so a level means the same for every distance.",
        key="hill_preference",
    )
    time_available = st.number_input(
        "Time available (min)",
        min_value=0,
        max_value=600,
        value=0,
        step=5,
        help="Optional. 0 means no limit. Routes that take longer get a warning.",
    )


# ==========================================
# 3. FIND ROUTES
# ==========================================

# st.button is True only in the rerun right after the click.
with input_col:
    if st.button("🚀 Find running routes", type="primary", width="stretch"):
        st.session_state.routes = []  # remove the old results
        with st.spinner("Looking for running loops (about 10 seconds)..."):
            try:
                # 1. Up to three running loops from the routing service (routing.py).
                routes = routing.find_routes(lat, lon, distance)

                # 2. Current weather and air quality at the start (Open-Meteo).
                #    They are optional: without them, the score uses only the other factors.
                try:
                    weather = apis.get_weather(lat, lon)
                except (requests.RequestException, ValueError, KeyError):
                    weather = {}
                try:
                    air = apis.get_air_quality(lat, lon)
                except (requests.RequestException, ValueError, KeyError):
                    air = {}

                # 3. Score every route and check it against the preferences
                #    (scoring.py), then sort them: best score first.
                for route in routes:
                    route["scoring"] = scoring.calculate_score(
                        route, distance, hill_preference,
                        weather.get("temperature_2m"), air.get("european_aqi"),
                    )
                    route["warnings"] = scoring.preference_warnings(route, distance, hill_preference)
                routes.sort(key=lambda route: route["scoring"]["score"], reverse=True)

                # 4. Save the results. The map and the result cards read them
                #    in this and every following rerun.
                st.session_state.routes = routes
                st.session_state.weather = weather
                st.session_state.air = air
                st.session_state.result_title = (
                    f"🏆 Routes from {st.session_state.start_label} · {distance} km · {hill_preference}"
                )
                st.session_state.route_view = 0  # show all routes on the map
            except routing.RoutingUnavailable as error:
                st.error(str(error))  # e.g. no loop found
            except Exception as error:
                st.error(f"An error occurred: {error}")  # show it instead of crashing


# ==========================================
# 4. YOUR RUNNING LOG (MACHINE LEARNING)
# ==========================================
# Generated with Claude (Anthropic, Claude Opus 5.5, 2026).

with log_tab:
    st.caption(
        "Log your past runs, e.g. from your watch or Strava. A linear regression "
        "learns your personal pace from them and estimates how long each route "
        "will take you."
    )

    # The name decides whose runs are used: every runner gets their own model.
    runner = st.text_input("Your name", value="Me", max_chars=40).strip() or "Me"

    # A form sends all three values together when "Save run" is clicked.
    with st.expander("📒 Log a past run"):
        with st.form("log_run", clear_on_submit=True):
            log1, log2, log3 = st.columns(3)
            run_km = log1.number_input(
                "Distance (km)", min_value=0.5, max_value=100.0, value=5.0, step=0.1
            )
            run_gain = log2.number_input(
                "Elevation gain (m)", min_value=0, max_value=5000, value=50, step=10
            )
            run_time = log3.number_input(
                "Time (min)", min_value=1.0, max_value=900.0, value=30.0, step=0.5
            )
            if st.form_submit_button("Save run"):
                runtime_model.log_run(runner, run_km, run_gain, run_time)  # adds a row to runs.csv
                st.success(f"Run saved for {runner}.")

    # Machine learning (runtime_model.py), on every rerun so new runs count at once:
    #   load_runs    this runner's rows from runs.csv = the training data
    #   train_model  fits the linear regression: time = a × km + b × climbing + c
    #   test_error   average error on runs the model did not see (None if too few runs)
    my_runs = runtime_model.load_runs(runner)
    time_model = runtime_model.train_model(my_runs)
    model_error = runtime_model.test_error(my_runs)
    fitness_pace = settings.FITNESS_LEVELS[fitness]["pace_min_per_km"]

    if time_model is None:
        st.info(
            f"{runner} has logged {len(my_runs)} run(s). Until there are "
            f"{runtime_model.MIN_RUNS}, time estimates use the pace of your fitness "
            f"level ({fitness_pace} min per km, every {settings.CLIMB_M_PER_EXTRA_KM} m "
            "uphill counts as one extra km)."
        )
    else:
        # coef_ holds the learned a (per km) and b (per metre), intercept_ the constant c.
        per_km, per_meter = time_model.coef_
        st.success(
            f"**Your learned pace** (from {len(my_runs)} runs): "
            f"time ≈ {per_km:.1f} min per km + {per_meter * 100:.1f} min per 100 m "
            f"climbing {time_model.intercept_:+.1f} min"
        )

        if model_error is None:
            st.caption(
                f"Log {runtime_model.MIN_RUNS_FOR_TEST} runs to measure how accurate "
                "the model is."
            )
        else:
            # Is the model worth it? Compare it with a constant-pace baseline,
            # both tested on runs they did not see (cross-validation).
            baseline_error = runtime_model.test_error(my_runs, runtime_model.BASELINE_FEATURES)
            e1, e2 = st.columns(2)
            e1.metric(
                "Baseline: constant pace",
                f"±{baseline_error:.1f} min",
                help="Average error of a model that only uses the distance.",
            )
            e2.metric(
                "Your model: pace + climbing",
                f"±{model_error:.1f} min",
                delta=f"{model_error - baseline_error:+.1f} min vs. baseline",
                delta_color="inverse",  # a smaller error is better, so show it green
                help="Average error on runs the model did not see during training.",
            )

        chart_col, curve_col = st.columns(2)
        with chart_col:
            # Each logged run twice: the real time and the model's estimate.
            # Bigger dots = more climbing.
            st.write("**Real times vs. model estimates**")
            st.scatter_chart(
                runtime_model.chart_table(time_model, my_runs),
                x="distance_km",
                y="time_min",
                color="series",
                size="elevation_gain_m",
                x_label="Distance (km)",
                y_label="Time (min)",
                height=300,
            )
        with curve_col:
            # Does the model get better with more data?
            curve = runtime_model.learning_curve(my_runs)
            if len(curve) >= 2:
                st.write("**Learning curve:** does the model improve with more runs?")
                st.line_chart(
                    curve,
                    x="runs",
                    y="error_min",
                    x_label="Number of logged runs",
                    y_label="Average error (min)",
                    height=300,
                )


# ==========================================
# 5. MAP
# ==========================================

# Register the map: an HTML box, its size (CSS) and its code (swiss_map.js).
swiss_map = st.components.v2.component(
    "runcomfy_swiss_map",
    html='<div class="runcomfy-map" aria-label="swisstopo map"></div><div class="map-status" role="status"></div>',
    css=".runcomfy-map { width: 100%; height: min(75vh, 680px); min-height: 360px; }",
    js=Path(__file__).with_name("swiss_map.js").read_text(encoding="utf-8"),
    isolate_styles=False,
)

with map_col:
    # What the map needs for each route: its points, a colour and a label.
    route_colors = ("#087f5b", "#1554c4", "#8c239e")
    map_routes = [
        {
            "path": [point[:2] for point in route["coordinates"]],
            "color": route_colors[i],
            "label": f"Route {i + 1} · {route['distance']:.1f} km",
        }
        for i, route in enumerate(st.session_state.routes)
    ]

    # Let the user show all routes or only one.
    route_view = 0  # 0 = all routes, 1–3 = only that route
    if map_routes:
        route_view = st.radio(
            "Show on the map",
            range(len(map_routes) + 1),
            format_func=lambda index: f"Route {index}" if index else "All routes",
            horizontal=True,
            key="route_view",
        )

    # Python → map: the start, the routes and which route to show.
    # Map → Python: the point the user clicked (picker.point).
    # The revision changes with every new start, so an older click is ignored.
    revision = st.session_state.start_revision
    last_click = (st.session_state.get("shared_swiss_map") or {}).get("point")
    pending = last_click if last_click and last_click["revision"] == revision else None

    picker = swiss_map(
        key="shared_swiss_map",
        data={
            "center": {"lat": lat, "lng": lon},
            "revision": revision,
            "pending": pending,  # the clicked point stays visible as a blue dot
            "routes": map_routes,
            "routeView": route_view,
        },
        default={"point": None},
        on_point_change=lambda: None,
    )

    # The user clicked the map: offer the point as the new start.
    clicked = picker.point
    if clicked and clicked["revision"] == revision:
        if st.button(f"📍 Start here ({clicked['lat']:.4f}, {clicked['lng']:.4f})"):
            try:
                # swisstopo checks that the point lies inside Switzerland.
                if apis.is_swiss_location(clicked["lat"], clicked["lng"]):
                    set_start((clicked["lat"], clicked["lng"]), "Point chosen on the map")
                    st.rerun()  # run the page again so everything uses the new start
                else:
                    st.warning("Please choose a location in Switzerland.")
            except (requests.RequestException, ValueError) as error:
                st.error(f"Location check failed: {error}")


# ==========================================
# 6. RESULTS
# ==========================================

# Shown in every rerun as long as routes are saved (section 3).
if st.session_state.routes:
    with route_tab:
        routes = st.session_state.routes
        weather = st.session_state.weather
        air = st.session_state.air

        st.divider()
        st.subheader(st.session_state.result_title)  # the settings used for these routes
        # The current conditions at the start in one line.
        st.caption(
            f"🌤️ Now: {metric_text(weather.get('temperature_2m'), ' °C')} "
            f"(feels like {metric_text(weather.get('apparent_temperature'), ' °C')}) · "
            f"Air quality index {metric_text(air.get('european_aqi'), '', 0)} · "
            f"Wind {metric_text(weather.get('wind_speed_10m'), ' km/h')} · "
            f"Rain {metric_text(weather.get('precipitation'), ' mm')}"
        )

        # One card per route, side by side: zip pairs each route with a column.
        medals = ["🥇", "🥈", "🥉"]
        for i, (route, card_col) in enumerate(zip(routes, st.columns(3))):
            score = route["scoring"]

            # Time estimate: the personal model (section 4) if it exists,
            # otherwise the pace of the fitness level × (distance + climbing
            # as extra km), like the Swiss "Leistungskilometer".
            if time_model is not None:
                estimate = runtime_model.predict_minutes(time_model, route["distance"], route["elevation"])
                estimate_text = f"{estimate:.0f} min" + ("" if model_error is None else f" ±{model_error:.0f}")
                estimate_help = (
                    f"Learned from {runner}'s logged runs. ± is the model's average "
                    "error on runs it did not see."
                )
            else:
                extra_km = route["elevation"] / settings.CLIMB_M_PER_EXTRA_KM
                estimate = fitness_pace * (route["distance"] + extra_km)
                estimate_text = f"~{estimate:.0f} min"
                estimate_help = (
                    f"Rough estimate: {fitness_pace} min per km ({fitness}), and every "
                    f"{settings.CLIMB_M_PER_EXTRA_KM} m uphill counts as one extra km. "
                    f"Log {runtime_model.MIN_RUNS} runs for a personal estimate."
                )

            with card_col.container(border=True):  # a box with a border = one card
                st.markdown(f"### {medals[i]} Route {i + 1}")
                m1, m2 = st.columns(2)
                m1.metric("RunComfy Score", f"{score['score']}/100")
                m2.metric("⏱️ Your time", estimate_text, help=estimate_help)
                m1.metric("Distance", f"{route['distance']:.1f} km")
                m2.metric("Climbing", f"{route['elevation']:.0f} m")

                for message in route["warnings"]:
                    st.caption(f"⚠️ {message}")

                # Use the estimate to check whether the route fits the available time.
                if time_available:
                    if estimate > time_available:
                        st.caption(
                            f"⚠️ About {estimate - time_available:.0f} min longer than "
                            f"your available {time_available} min."
                        )
                    else:
                        st.caption(f"✅ Fits into your available {time_available} min.")

                # GPX works with Strava, Komoot, Garmin, Apple Watch apps and Google My Maps.
                st.download_button(
                    "⬇️ Download GPX",
                    data=routing.to_gpx(route, f"RunComfy Route {i + 1}"),
                    file_name=f"runcomfy-route-{i + 1}.gpx",
                    mime="application/gpx+xml",
                    key=f"gpx_{i}",
                    width="stretch",
                )

                # Explain the score: the points of each factor, with input and formula.
                with st.expander("How was it scored?"):
                    for factor in score["factors"]:
                        if factor["points"] is None:
                            st.write(f"**{factor['name']}: unavailable, left out**")
                        else:
                            st.write(f"**{factor['name']}: {factor['points']:.1f} / {factor['maximum']}**")
                        st.caption(f"{factor['input']} · {factor['formula']}")

                    if score["maximum"] == 100:
                        st.write(f"Total: {score['points']:.1f} / 100 → {score['score']}/100")
                    else:
                        st.write(
                            f"Total: {score['points']:.1f} / {score['maximum']}, "
                            f"scaled to 100 → {score['score']}/100"
                        )
                    st.caption("Warnings, feels-like temperature, wind and rain do not change the score.")

        # Sources of the data (we must cite other people's work).
        st.caption(
            "Scores are rule-based. Maps and elevation: © swisstopo. Routing: Valhalla, "
            "© OpenStreetMap contributors. Weather and air quality: Open-Meteo."
        )
