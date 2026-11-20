# Source code generated with the assistance of Google Gemini (2026)
# Purpose: Self-learning Machine Learning model for personalized route & shoe matching

from pathlib import Path
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

DATA_FILE = Path(__file__).parent / "route_preferences.csv"

INITIAL_DATA = [
    ["Road", "Asphalt", "Dry", "Morning", 8.0, 1],
    ["Road", "Asphalt", "Dry", "Evening", 10.0, 1],
    ["Road", "Asphalt", "Wet/Rain", "Afternoon", 5.0, 1],
    ["Road", "Trail", "Wet/Rain", "Morning", 35.0, 0],
    ["Road", "Trail", "Dry", "Afternoon", 40.0, 0],
    ["Road", "Gravel", "Wet/Rain", "Evening", 25.0, 0],
    ["Trail", "Trail", "Wet/Rain", "Morning", 35.0, 1],
    ["Trail", "Trail", "Dry", "Afternoon", 45.0, 1],
    ["Trail", "Gravel", "Wet/Rain", "Morning", 20.0, 1],
    ["Trail", "Asphalt", "Dry", "Evening", 5.0, 0],
    ["Cushioned", "Asphalt", "Dry", "Morning", 12.0, 1],
    ["Cushioned", "Gravel", "Dry", "Afternoon", 18.0, 1],
    ["Cushioned", "Trail", "Wet/Rain", "Evening", 38.0, 0],
]

COLUMNS = ["shoe", "surface", "weather_cond", "time_of_day", "gain_per_km", "liked"]


def load_data() -> pd.DataFrame:
    if not DATA_FILE.is_file():
        df = pd.DataFrame(INITIAL_DATA, columns=COLUMNS)
        df.to_csv(DATA_FILE, index=False)
    return pd.read_csv(DATA_FILE)


def train_model():
    df = load_data()
    X = pd.get_dummies(df[["shoe", "surface", "weather_cond", "time_of_day", "gain_per_km"]])
    y = df["liked"]

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    return model, X.columns, len(df)


def predict_match_probability(
    shoe: str,
    surface: str,
    weather_cond: str,
    time_of_day: str,
    gain_per_km: float,
) -> tuple[int, int]:
    model, feature_cols, sample_count = train_model()

    input_df = pd.DataFrame(
        [[shoe, surface, weather_cond, time_of_day, gain_per_km]],
        columns=["shoe", "surface", "weather_cond", "time_of_day", "gain_per_km"],
    )
    input_encoded = pd.get_dummies(input_df).reindex(columns=feature_cols, fill_value=0)

    classes = list(model.classes_)
    prob = (
        model.predict_proba(input_encoded)[0][classes.index(1)]
        if 1 in classes
        else 0.0
    )
    return round(prob * 100), sample_count


def log_feedback(
    shoe: str,
    surface: str,
    weather_cond: str,
    time_of_day: str,
    gain_per_km: float,
    liked: int,
):
    df = load_data()
    new_row = pd.DataFrame(
        [[shoe, surface, weather_cond, time_of_day, round(gain_per_km, 1), liked]],
        columns=COLUMNS,
    )
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)