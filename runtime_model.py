# AI use: generated with Claude (Anthropic, Claude Opus 5.5, 2026).
# See README.md, "AI use".
"""Predict how long a runner needs for a route, learned from their own past runs.

Each row in runs.csv is one real run: who ran it, its distance, its
elevation gain and the time it took. For every runner, a linear regression
learns

    time = a × distance + b × elevation gain + c

from that runner's runs only, so the estimate matches their personal pace.
"""

from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_score

DATA_FILE = Path(__file__).parent / "runs.csv"
COLUMNS = ["runner", "distance_km", "elevation_gain_m", "time_min"]
FEATURES = ["distance_km", "elevation_gain_m"]  # model inputs
TARGET = "time_min"  # what the model predicts

# Baseline for comparison: a constant pace that ignores climbing. Our model
# is only worth using if it makes smaller errors than this simpler one.
BASELINE_FEATURES = ["distance_km"]

# A model with two inputs needs at least three runs to be fitted, and
# two more so that it can be tested on runs it has not seen.
MIN_RUNS = 3
MIN_RUNS_FOR_TEST = 5


def load_runs(runner):
    """Return all logged runs of one runner (an empty table if there are none)."""
    if not DATA_FILE.is_file():
        return pd.DataFrame(columns=COLUMNS)
    runs = pd.read_csv(DATA_FILE)
    return runs[runs["runner"] == runner]


def log_run(runner, distance_km, elevation_gain_m, time_min):
    """Append one run to runs.csv; the file is created with the first run."""
    row = pd.DataFrame(
        [[runner, distance_km, elevation_gain_m, time_min]], columns=COLUMNS
    )
    # mode="a" appends the row; the column names are written only for a new file.
    row.to_csv(DATA_FILE, mode="a", header=not DATA_FILE.is_file(), index=False)


def train_model(runs):
    """Fit the linear regression on the given runs (None if there are too few)."""
    if len(runs) < MIN_RUNS:
        return None
    # fit() finds the a, b and c with the smallest squared errors on these runs.
    return LinearRegression().fit(runs[FEATURES], runs[TARGET])


def predict_minutes(model, distance_km, elevation_gain_m):
    """Estimated running time in minutes for one route."""
    route = pd.DataFrame([[distance_km, elevation_gain_m]], columns=FEATURES)
    return float(model.predict(route)[0])


def test_error(runs, features=FEATURES):
    """Average error in minutes on runs the model did not see during training.

    Cross-validation: the runs are split into k groups. The model is trained
    k times on all groups but one and tested on the group it did not see.
    `features` chooses the inputs, so the same test also scores the baseline.
    Returns None while there are too few runs for a fair test.
    """
    if len(runs) < MIN_RUNS_FOR_TEST:
        return None
    # scikit-learn returns negative errors (higher = better), so we flip the sign.
    errors = -cross_val_score(
        LinearRegression(),
        runs[features],
        runs[TARGET],
        cv=min(5, len(runs)),
        scoring="neg_mean_absolute_error",
    )
    return float(errors.mean())


def learning_curve(runs):
    """Test error after the first 5, 6, 7 … runs, in the order they were logged.

    If the error goes down as runs are added, the model is learning from
    the data. Small ups and downs are normal with only a few runs.
    """
    sizes = range(MIN_RUNS_FOR_TEST, len(runs) + 1)
    return pd.DataFrame(
        {
            "runs": list(sizes),
            "error_min": [test_error(runs.iloc[:size]) for size in sizes],
        }
    )


def chart_table(model, runs):
    """Real and estimated times of the logged runs, for the chart in the app."""
    # A copy of the runs with the model's times; "series" decides the colour.
    estimated = runs.assign(**{TARGET: model.predict(runs[FEATURES])})
    return pd.concat(
        [runs.assign(series="Your real time"), estimated.assign(series="Model estimate")]
    )
