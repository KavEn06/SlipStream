from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import DEFAULT_RESAMPLE_POINTS, get_session_paths
from src.core.schemas import PROCESSED_LAP_COLUMNS, RAW_LAP_COLUMNS, REFERENCE_LAP_COLUMNS, SCHEMA_VERSION


RAW_REQUIRED_COLUMNS = set(RAW_LAP_COLUMNS)


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def validate_raw_lap_dataframe(df: pd.DataFrame) -> None:
    missing_columns = sorted(RAW_REQUIRED_COLUMNS - set(df.columns))
    if missing_columns:
        raise ValueError(f"Raw lap is missing required columns: {missing_columns}")

    if len(df) < 2:
        raise ValueError("Raw lap must contain at least two samples")


def _safe_delta_time(elapsed_time_s: pd.Series) -> pd.Series:
    delta_time = elapsed_time_s.diff().fillna(0.0)
    positive_samples = delta_time[delta_time > 0]
    fallback_dt = float(positive_samples.median()) if not positive_samples.empty else 0.05
    delta_time = delta_time.mask(delta_time <= 0, fallback_dt)
    return delta_time


def calculate_distance_series(df: pd.DataFrame) -> pd.Series:
    position_columns = ["PositionX", "PositionY", "PositionZ"]
    _coerce_numeric(df, position_columns + ["DistanceTraveled"])

    if df[position_columns].notna().all().all():
        deltas = df[position_columns].diff().fillna(0.0)
        step_distance = np.sqrt((deltas**2).sum(axis=1))
        cumulative_distance = step_distance.cumsum()
        if float(cumulative_distance.iloc[-1]) > 0:
            return cumulative_distance

    distance_traveled = df["DistanceTraveled"].fillna(method="ffill").fillna(0.0)
    distance_traveled = distance_traveled - float(distance_traveled.iloc[0])
    return distance_traveled.clip(lower=0.0)


def _differentiate(series: pd.Series, delta_time_s: pd.Series) -> pd.Series:
    derivative = series.diff().fillna(0.0) / delta_time_s
    derivative.replace([np.inf, -np.inf], 0.0, inplace=True)
    return derivative.fillna(0.0)


def build_processed_lap_dataframe(raw_df: pd.DataFrame, session_id: str = "") -> pd.DataFrame:
    raw_df = raw_df.copy()
    validate_raw_lap_dataframe(raw_df)
    _coerce_numeric(raw_df, RAW_LAP_COLUMNS)

    raw_df["TimestampMS"] = raw_df["TimestampMS"].astype(int)
    raw_df["LapNumber"] = raw_df["LapNumber"].astype(int)
    raw_df["Gear"] = raw_df["Gear"].astype(int)

    elapsed_time_s = (raw_df["TimestampMS"] - int(raw_df["TimestampMS"].iloc[0])) / 1000.0
    delta_time_s = _safe_delta_time(elapsed_time_s)
    cumulative_distance_m = calculate_distance_series(raw_df)
    lap_distance_m = float(cumulative_distance_m.iloc[-1])

    if lap_distance_m <= 0:
        normalized_distance = pd.Series(np.linspace(0.0, 1.0, len(raw_df)), index=raw_df.index)
    else:
        normalized_distance = cumulative_distance_m / lap_distance_m

    throttle = raw_df["Accel"].clip(lower=0.0, upper=255.0) / 255.0
    brake = raw_df["Brake"].clip(lower=0.0, upper=255.0) / 255.0
    clutch = raw_df["Clutch"].clip(lower=0.0, upper=255.0) / 255.0
    hand_brake = raw_df["HandBrake"].clip(lower=0.0, upper=255.0) / 255.0
    steering = raw_df["Steer"].clip(lower=-127.0, upper=127.0) / 127.0
    speed_mps = raw_df["Speed"].clip(lower=0.0)
    speed_kph = speed_mps * 3.6

    longitudinal_accel = _differentiate(speed_mps, delta_time_s)
    throttle_rate = _differentiate(throttle, delta_time_s)
    brake_rate = _differentiate(brake, delta_time_s)
    steering_rate = _differentiate(steering, delta_time_s)
    steering_smoothness = steering_rate.abs().rolling(window=5, min_periods=1).mean()
    is_coasting = (throttle <= 0.05) & (brake <= 0.05)

    lap_time_s = float(elapsed_time_s.iloc[-1])
    lap_is_valid = lap_distance_m > 0.0 and lap_time_s > 0.0 and len(raw_df) >= 5

    processed_df = pd.DataFrame(
        {
            "SchemaVersion": SCHEMA_VERSION,
            "SessionId": session_id,
            "LapNumber": raw_df["LapNumber"].astype(int),
            "SampleIndex": np.arange(len(raw_df), dtype=int),
            "TimestampMS": raw_df["TimestampMS"].astype(int),
            "ElapsedTimeS": elapsed_time_s,
            "DeltaTimeS": delta_time_s,
            "PositionX": raw_df["PositionX"],
            "PositionY": raw_df["PositionY"],
            "PositionZ": raw_df["PositionZ"],
            "DistanceTraveledM": raw_df["DistanceTraveled"].clip(lower=0.0),
            "CumulativeDistanceM": cumulative_distance_m,
            "NormalizedDistance": normalized_distance.clip(lower=0.0, upper=1.0),
            "SpeedMps": speed_mps,
            "SpeedKph": speed_kph,
            "EngineRpm": raw_df["CurrentEngineRpm"],
            "Throttle": throttle,
            "Brake": brake,
            "Clutch": clutch,
            "HandBrake": hand_brake,
            "Steering": steering,
            "Gear": raw_df["Gear"].astype(int),
            "Power": raw_df["Power"],
            "Torque": raw_df["Torque"],
            "Boost": raw_df["Boost"],
            "LongitudinalAccelMps2": longitudinal_accel,
            "ThrottleRatePerS": throttle_rate,
            "BrakeRatePerS": brake_rate,
            "SteeringRatePerS": steering_rate,
            "SteeringSmoothness": steering_smoothness,
            "IsCoasting": is_coasting.astype(int),
            "LapTimeS": lap_time_s,
            "LapIsValid": int(lap_is_valid),
        }
    )

    return processed_df[PROCESSED_LAP_COLUMNS]


def build_processed_lap_file(
    raw_csv_path: str | Path,
    processed_csv_path: str | Path | None = None,
    session_id: str = "",
) -> pd.DataFrame:
    raw_path = Path(raw_csv_path)
    processed_path = Path(processed_csv_path) if processed_csv_path else raw_path
    raw_df = pd.read_csv(raw_path)
    processed_df = build_processed_lap_dataframe(raw_df, session_id=session_id)
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    processed_df.to_csv(processed_path, index=False)
    return processed_df


def resample_processed_lap(
    processed_df: pd.DataFrame,
    num_points: int = DEFAULT_RESAMPLE_POINTS,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    if num_points < 2:
        raise ValueError("num_points must be at least 2")

    ordered_df = processed_df.sort_values("NormalizedDistance").drop_duplicates(subset="NormalizedDistance")
    grid = np.linspace(0.0, 1.0, num_points)
    selected_columns = columns or REFERENCE_LAP_COLUMNS

    resampled_df = pd.DataFrame({"NormalizedDistance": grid})
    for column in selected_columns:
        if column == "NormalizedDistance":
            continue

        series = ordered_df[column]
        if series.dtype == bool or series.dropna().isin([0, 1]).all():
            interpolated = np.interp(grid, ordered_df["NormalizedDistance"], series.astype(float))
            resampled_df[column] = np.rint(interpolated).astype(int)
        else:
            resampled_df[column] = np.interp(grid, ordered_df["NormalizedDistance"], series.astype(float))

    return resampled_df


def load_processed_lap(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def process_session(raw_session_dir: str | Path, processed_session_dir: str | Path | None = None) -> list[Path]:
    raw_dir = Path(raw_session_dir)
    if processed_session_dir is None:
        session_id = raw_dir.name
        processed_dir = get_session_paths(session_id).processed_dir
    else:
        processed_dir = Path(processed_session_dir)

    processed_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    session_id = raw_dir.name

    for raw_lap_path in sorted(raw_dir.glob("lap_*.csv")):
        processed_lap_path = processed_dir / raw_lap_path.name
        build_processed_lap_file(raw_lap_path, processed_lap_path, session_id=session_id)
        written_paths.append(processed_lap_path)

    metadata_path = raw_dir / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["processed_schema_version"] = SCHEMA_VERSION
        (processed_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return written_paths


def calculate_distance(raw_csv_path: str | Path) -> pd.Series:
    raw_df = pd.read_csv(raw_csv_path)
    validate_raw_lap_dataframe(raw_df)
    return calculate_distance_series(raw_df)


def resample(lap_path: str | Path, interval: float = 0.0025) -> pd.DataFrame:
    if interval <= 0 or interval >= 1:
        raise ValueError("interval must be between 0 and 1")

    processed_df = build_processed_lap_dataframe(pd.read_csv(lap_path))
    num_points = int(round(1.0 / interval)) + 1
    return resample_processed_lap(processed_df, num_points=num_points)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build canonical processed laps from raw telemetry.")
    parser.add_argument("path", help="Raw session directory or raw lap CSV path.")
    parser.add_argument("--output", default=None, help="Optional output path for a single lap or session.")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    input_path = Path(args.path)

    if input_path.is_dir():
        process_session(input_path, args.output)
    else:
        build_processed_lap_file(input_path, args.output)
