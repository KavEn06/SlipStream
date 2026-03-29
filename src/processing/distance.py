from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from src.core.config import DEFAULT_RESAMPLE_POINTS, PROCESSED_DATA_ROOT, RAW_DATA_ROOT, get_session_paths
from src.core.schemas import PROCESSED_LAP_COLUMNS, RAW_LAP_COLUMNS, REFERENCE_LAP_COLUMNS, SCHEMA_VERSION
from src.core.schemas import LapValidationResult
from src.processing.alignment import align_session_laps
from src.processing.validation import build_validation_context, evaluate_lap_validation, write_validation_result


RAW_REQUIRED_COLUMNS = set(RAW_LAP_COLUMNS)
LAP_FILE_PATTERN = re.compile(r"lap_(\d+)\.csv$")
DISTANCE_SPIKE_RATIO = 3.0
DISTANCE_SPIKE_ABS_TOLERANCE_M = 5.0
DISTANCE_DIVERGENCE_RATIO = 0.15
DISCRETE_RESAMPLE_COLUMNS = {
    "Gear",
    "IsCoasting",
    "LapIsValid",
    "AlignmentUsedFallback",
    "AlignmentIsUsable",
}


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _fill_numeric_series(series: pd.Series, default: float = 0.0) -> pd.Series:
    return series.ffill().bfill().fillna(default)


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


def _distance_traveled_progress_series(df: pd.DataFrame) -> pd.Series:
    distance_traveled = pd.to_numeric(df["DistanceTraveled"], errors="coerce").ffill().bfill().fillna(0.0)
    distance_traveled = distance_traveled - float(distance_traveled.iloc[0])
    return distance_traveled.clip(lower=0.0)


def _geometric_step_distance_series(df: pd.DataFrame) -> pd.Series | None:
    position_columns = ["PositionX", "PositionY", "PositionZ"]
    position_df = df[position_columns].apply(pd.to_numeric, errors="coerce")
    finite_rows = position_df.notna().all(axis=1)
    if int(finite_rows.sum()) < 2:
        return None

    interpolated_positions = position_df.interpolate(method="linear", limit_direction="both")
    if interpolated_positions.isna().any().any():
        return None

    deltas = interpolated_positions.diff().fillna(0.0)
    return np.sqrt((deltas**2).sum(axis=1))


def calculate_distance_series(df: pd.DataFrame) -> pd.Series:
    position_columns = ["PositionX", "PositionY", "PositionZ"]
    _coerce_numeric(df, position_columns + ["DistanceTraveled"])
    distance_traveled_progress = _distance_traveled_progress_series(df)
    geometric_step_distance = _geometric_step_distance_series(df)

    if geometric_step_distance is None:
        return distance_traveled_progress

    distance_traveled_step = distance_traveled_progress.diff().fillna(0.0).clip(lower=0.0)
    positive_distance_steps = distance_traveled_step[distance_traveled_step > 0]
    median_distance_step = float(positive_distance_steps.median()) if not positive_distance_steps.empty else 0.0
    spike_threshold = np.maximum(
        distance_traveled_step * DISTANCE_SPIKE_RATIO + DISTANCE_SPIKE_ABS_TOLERANCE_M,
        median_distance_step * DISTANCE_SPIKE_RATIO + DISTANCE_SPIKE_ABS_TOLERANCE_M,
    )

    repaired_step_distance = geometric_step_distance.copy()
    suspicious_step_mask = repaired_step_distance > spike_threshold
    if suspicious_step_mask.any():
        repaired_step_distance = repaired_step_distance.where(~suspicious_step_mask, distance_traveled_step)
    repaired_step_distance = repaired_step_distance.fillna(distance_traveled_step).fillna(0.0)

    cumulative_distance = repaired_step_distance.cumsum()
    geometric_total_distance = float(cumulative_distance.iloc[-1])
    distance_traveled_total = float(distance_traveled_progress.iloc[-1])

    if geometric_total_distance <= 0:
        return distance_traveled_progress

    if distance_traveled_total > 0:
        total_distance_divergence_ratio = abs(geometric_total_distance - distance_traveled_total) / max(
            distance_traveled_total,
            1.0,
        )
        if total_distance_divergence_ratio > DISTANCE_DIVERGENCE_RATIO:
            return distance_traveled_progress

    return cumulative_distance


def _differentiate(series: pd.Series, delta_time_s: pd.Series) -> pd.Series:
    derivative = series.diff().fillna(0.0) / delta_time_s
    derivative.replace([np.inf, -np.inf], 0.0, inplace=True)
    return derivative.fillna(0.0)


def _build_processed_lap_dataframe_with_validation(
    raw_df: pd.DataFrame,
    session_id: str = "",
    session_metadata: dict[str, object] | None = None,
    lap_number: int | None = None,
) -> tuple[pd.DataFrame, LapValidationResult]:
    original_raw_df = raw_df.copy()
    validate_raw_lap_dataframe(original_raw_df)

    processed_input_df = original_raw_df.copy()
    _coerce_numeric(processed_input_df, RAW_LAP_COLUMNS)

    fill_columns = [column for column in RAW_LAP_COLUMNS if column not in {"PositionX", "PositionY", "PositionZ"}]
    for column in fill_columns:
        processed_input_df[column] = _fill_numeric_series(processed_input_df[column])

    processed_input_df["TimestampMS"] = processed_input_df["TimestampMS"].astype(int)
    processed_input_df["LapNumber"] = processed_input_df["LapNumber"].astype(int)
    processed_input_df["Gear"] = processed_input_df["Gear"].astype(int)

    elapsed_time_s = (processed_input_df["TimestampMS"] - int(processed_input_df["TimestampMS"].iloc[0])) / 1000.0
    delta_time_s = _safe_delta_time(elapsed_time_s)
    cumulative_distance_m = calculate_distance_series(processed_input_df)
    lap_distance_m = float(cumulative_distance_m.iloc[-1])

    if lap_distance_m <= 0:
        normalized_distance = pd.Series(0.0, index=processed_input_df.index, dtype=float)
    else:
        normalized_distance = cumulative_distance_m / lap_distance_m

    throttle = processed_input_df["Accel"].clip(lower=0.0, upper=255.0) / 255.0
    brake = processed_input_df["Brake"].clip(lower=0.0, upper=255.0) / 255.0
    clutch = processed_input_df["Clutch"].clip(lower=0.0, upper=255.0) / 255.0
    hand_brake = processed_input_df["HandBrake"].clip(lower=0.0, upper=255.0) / 255.0
    steering = processed_input_df["Steer"].clip(lower=-127.0, upper=127.0) / 127.0
    speed_mps = processed_input_df["Speed"].clip(lower=0.0)
    speed_kph = speed_mps * 3.6

    longitudinal_accel = _differentiate(speed_mps, delta_time_s)
    throttle_rate = _differentiate(throttle, delta_time_s)
    brake_rate = _differentiate(brake, delta_time_s)
    steering_rate = _differentiate(steering, delta_time_s)
    steering_smoothness = steering_rate.abs().rolling(window=5, min_periods=1).mean()
    is_coasting = (throttle <= 0.05) & (brake <= 0.05)

    lap_time_s = float(elapsed_time_s.iloc[-1])

    processed_df = pd.DataFrame(
        {
            "SchemaVersion": SCHEMA_VERSION,
            "SessionId": session_id,
            "LapNumber": processed_input_df["LapNumber"].astype(int),
            "SampleIndex": np.arange(len(processed_input_df), dtype=int),
            "TimestampMS": processed_input_df["TimestampMS"].astype(int),
            "ElapsedTimeS": elapsed_time_s,
            "DeltaTimeS": delta_time_s,
            "PositionX": processed_input_df["PositionX"],
            "PositionY": processed_input_df["PositionY"],
            "PositionZ": processed_input_df["PositionZ"],
            "DistanceTraveledM": processed_input_df["DistanceTraveled"].fillna(0.0).clip(lower=0.0),
            "CumulativeDistanceM": cumulative_distance_m,
            "NormalizedDistance": normalized_distance.clip(lower=0.0, upper=1.0),
            "TrackProgressM": np.nan,
            "TrackProgressNorm": np.nan,
            "AlignmentResidualM": np.nan,
            "AlignmentUsedFallback": 0,
            "SpeedMps": speed_mps,
            "SpeedKph": speed_kph,
            "EngineRpm": processed_input_df["CurrentEngineRpm"],
            "Throttle": throttle,
            "Brake": brake,
            "Clutch": clutch,
            "HandBrake": hand_brake,
            "Steering": steering,
            "Gear": processed_input_df["Gear"].astype(int),
            "Power": processed_input_df["Power"],
            "Torque": processed_input_df["Torque"],
            "Boost": processed_input_df["Boost"],
            "LongitudinalAccelMps2": longitudinal_accel,
            "ThrottleRatePerS": throttle_rate,
            "BrakeRatePerS": brake_rate,
            "SteeringRatePerS": steering_rate,
            "SteeringSmoothness": steering_smoothness,
            "IsCoasting": is_coasting.astype(int),
            "LapTimeS": lap_time_s,
            "LapIsValid": 0,
            "AlignmentIsUsable": 0,
        }
    )

    if lap_number is None:
        lap_number = _resolve_lap_number(original_raw_df)

    validation_context = build_validation_context(session_metadata, lap_number)
    validation_result = evaluate_lap_validation(
        original_raw_df,
        processed_df,
        session_id=session_id,
        lap_context=validation_context,
        lap_number=lap_number,
    )
    processed_df["LapIsValid"] = int(validation_result.lap_is_valid)

    return processed_df[PROCESSED_LAP_COLUMNS], validation_result


def build_processed_lap_dataframe(raw_df: pd.DataFrame, session_id: str = "") -> pd.DataFrame:
    processed_df, _ = _build_processed_lap_dataframe_with_validation(raw_df, session_id=session_id)
    return processed_df


def build_processed_lap_file(
    raw_csv_path: str | Path,
    processed_csv_path: str | Path | None = None,
    session_id: str = "",
    session_metadata: dict[str, object] | None = None,
) -> pd.DataFrame:
    raw_path = Path(raw_csv_path)
    processed_path = _resolve_processed_output_path(raw_path, processed_csv_path)
    raw_df = pd.read_csv(raw_path)
    metadata = session_metadata if session_metadata is not None else _load_session_metadata(raw_path.parent)
    resolved_session_id = _resolve_session_id(session_id, raw_path, metadata)
    lap_number = _resolve_lap_number(raw_df, raw_path)
    processed_df, validation_result = _build_processed_lap_dataframe_with_validation(
        raw_df,
        session_id=resolved_session_id,
        session_metadata=metadata,
        lap_number=lap_number,
    )
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    processed_df[PROCESSED_LAP_COLUMNS].to_csv(processed_path, index=False)
    write_validation_result(validation_result, processed_path)
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
        if column in DISCRETE_RESAMPLE_COLUMNS or series.dtype == bool or series.dropna().isin([0, 1]).all():
            interpolated = np.interp(grid, ordered_df["NormalizedDistance"], series.astype(float))
            resampled_df[column] = np.rint(interpolated).astype(int)
        else:
            resampled_df[column] = np.interp(grid, ordered_df["NormalizedDistance"], series.astype(float))

    return resampled_df


def load_processed_lap(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def process_session(raw_session_dir: str | Path, processed_session_dir: str | Path | None = None) -> list[Path]:
    raw_dir = Path(raw_session_dir)
    session_id = raw_dir.name
    if processed_session_dir is None:
        processed_dir = get_session_paths(session_id).processed_dir
    else:
        processed_dir = Path(processed_session_dir)

    _validate_session_processing_paths(raw_dir, processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    _clear_managed_processed_artifacts(processed_dir)
    written_paths: list[Path] = []
    session_metadata = _load_session_metadata(raw_dir)
    staged_laps: list[dict[str, object]] = []

    for raw_lap_path in sorted(raw_dir.glob("lap_*.csv")):
        raw_df = pd.read_csv(raw_lap_path)
        lap_number = _resolve_lap_number(raw_df, raw_lap_path)
        processed_df, validation_result = _build_processed_lap_dataframe_with_validation(
            raw_df,
            session_id=session_id,
            session_metadata=session_metadata,
            lap_number=lap_number,
        )
        resolved_lap_number = int(validation_result.lap_number)
        staged_laps.append(
            {
                "lap_number": resolved_lap_number,
                "processed_path": processed_dir / raw_lap_path.name,
                "processed_df": processed_df,
                "validation_result": validation_result,
            }
        )

    duplicate_lap_numbers = _find_duplicate_lap_numbers(staged_laps)
    if duplicate_lap_numbers:
        duplicate_list = ", ".join(str(lap_number) for lap_number in duplicate_lap_numbers)
        raise ValueError(f"Duplicate logical lap numbers detected during session processing: {duplicate_list}")

    processed_laps = {
        int(staged_lap["lap_number"]): staged_lap["processed_df"]
        for staged_lap in staged_laps
    }
    alignment_artifacts = align_session_laps(processed_laps)

    for staged_lap in staged_laps:
        lap_number = int(staged_lap["lap_number"])
        processed_path = Path(staged_lap["processed_path"])
        aligned_df = alignment_artifacts.aligned_laps.get(lap_number, staged_lap["processed_df"])
        validation_result = staged_lap["validation_result"]
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        aligned_df[PROCESSED_LAP_COLUMNS].to_csv(processed_path, index=False)
        write_validation_result(validation_result, processed_path)
        written_paths.append(processed_path)

    if alignment_artifacts.reference_path is not None:
        reference_path = processed_dir / "reference_path.csv"
        alignment_artifacts.reference_path.to_csv(reference_path, index=False)

    processed_metadata = _build_processed_session_metadata(
        session_id=session_id,
        session_metadata=session_metadata,
        total_laps=len(staged_laps),
        alignment_metadata=alignment_artifacts.metadata,
    )
    (processed_dir / "metadata.json").write_text(json.dumps(processed_metadata, indent=2), encoding="utf-8")

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
    parser = argparse.ArgumentParser(
        description="Build canonical processed laps from raw telemetry without overwriting raw inputs."
    )
    parser.add_argument("path", help="Raw session directory or raw lap CSV path.")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for a single lap or session. If omitted for a single lap, a safe derived path is used.",
    )
    return parser


def _load_session_metadata(session_path: str | Path) -> dict[str, object] | None:
    metadata_path = Path(session_path) / "metadata.json"
    if not metadata_path.exists():
        return None

    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resolve_lap_number(raw_df: pd.DataFrame, raw_csv_path: Path | None = None) -> int | None:
    lap_number_series = pd.to_numeric(raw_df["LapNumber"], errors="coerce").dropna()
    if not lap_number_series.empty:
        return int(lap_number_series.iloc[0])

    if raw_csv_path is not None:
        match = LAP_FILE_PATTERN.match(raw_csv_path.name)
        if match:
            return int(match.group(1))

    return None


def _resolve_processed_output_path(
    raw_csv_path: str | Path,
    processed_csv_path: str | Path | None = None,
) -> Path:
    raw_path = Path(raw_csv_path)

    if processed_csv_path is not None:
        processed_path = Path(processed_csv_path)
        if _paths_equal(raw_path, processed_path):
            raise ValueError("Processed output path must not overwrite the raw input file")
        return processed_path

    resolved_raw_path = raw_path.expanduser().resolve()
    resolved_raw_root = RAW_DATA_ROOT.resolve()
    try:
        relative_path = resolved_raw_path.relative_to(resolved_raw_root)
    except ValueError:
        return resolved_raw_path.with_name(f"{resolved_raw_path.stem}.processed.csv")

    return PROCESSED_DATA_ROOT.resolve() / relative_path


def _paths_equal(path_a: str | Path, path_b: str | Path) -> bool:
    return Path(path_a).expanduser().resolve() == Path(path_b).expanduser().resolve()


def _resolve_session_id(
    session_id: str,
    raw_csv_path: Path,
    session_metadata: dict[str, object] | None,
) -> str:
    if session_id:
        return session_id

    if session_metadata is not None:
        metadata_session_id = session_metadata.get("session_id")
        if metadata_session_id:
            return str(metadata_session_id)

    try:
        relative_path = raw_csv_path.expanduser().resolve().relative_to(RAW_DATA_ROOT.resolve())
    except ValueError:
        return ""

    if len(relative_path.parts) >= 2:
        return relative_path.parts[0]
    return ""


def _build_processed_session_metadata(
    session_id: str,
    session_metadata: dict[str, object] | None,
    total_laps: int,
    alignment_metadata: dict[str, object],
) -> dict[str, object]:
    processed_metadata = dict(session_metadata or {})
    processed_metadata["session_id"] = processed_metadata.get("session_id") or session_id
    processed_metadata["total_laps"] = int(processed_metadata.get("total_laps", total_laps) or total_laps)
    processed_metadata["processed_schema_version"] = SCHEMA_VERSION
    processed_metadata["alignment"] = alignment_metadata
    return processed_metadata


def _find_duplicate_lap_numbers(staged_laps: list[dict[str, object]]) -> list[int]:
    lap_number_counts: dict[int, int] = {}
    for staged_lap in staged_laps:
        lap_number = int(staged_lap["lap_number"])
        lap_number_counts[lap_number] = lap_number_counts.get(lap_number, 0) + 1

    return sorted(lap_number for lap_number, count in lap_number_counts.items() if count > 1)


def _clear_managed_processed_artifacts(processed_dir: Path) -> None:
    for path in processed_dir.glob("lap_*.csv"):
        path.unlink()
    for path in processed_dir.glob("*.validation.json"):
        path.unlink()

    for artifact_name in ("reference_path.csv", "metadata.json"):
        artifact_path = processed_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()


def _validate_session_processing_paths(raw_dir: Path, processed_dir: Path) -> None:
    if _paths_equal(raw_dir, processed_dir):
        raise ValueError("Processed session output directory must differ from the raw session directory")


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    input_path = Path(args.path)

    if input_path.is_dir():
        process_session(input_path, args.output)
    else:
        build_processed_lap_file(input_path, args.output)
