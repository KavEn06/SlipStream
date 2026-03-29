from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.schemas import (
    LAP_CLOSE_REASON_CAPTURE_END,
    LapValidationContext,
    LapValidationResult,
    SCHEMA_VERSION,
    VALIDATION_REASON_MISSING_REQUIRED_SIGNALS,
    VALIDATION_REASON_MULTIPLE_LAP_NUMBERS,
    VALIDATION_REASON_NO_FORWARD_DISTANCE,
    VALIDATION_REASON_NON_MONOTONIC_CURRENT_LAP_TIME,
    VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP,
    VALIDATION_REASON_PARTIAL_LAP_END,
    VALIDATION_REASON_PARTIAL_LAP_START,
    VALIDATION_REASON_TOO_FEW_SAMPLES,
    VALIDATION_REQUIRED_NUMERIC_COLUMNS,
)


MIN_VALID_SAMPLE_COUNT = 20
MIN_FORWARD_DISTANCE_M = 50.0
MAX_VALID_PARTIAL_LAP_START_S = 2.0
MIN_CAPTURE_END_COMPLETION_RATIO = 0.95


def build_validation_context(session_metadata: dict[str, Any] | None, lap_number: int | None) -> LapValidationContext:
    if session_metadata is None:
        return LapValidationContext()

    track_length_m = _as_optional_float(session_metadata.get("track_length_m"))
    lap_entry: dict[str, Any] | None = None

    if lap_number is not None:
        lap_index = session_metadata.get("lap_index")
        if isinstance(lap_index, dict):
            candidate = lap_index.get(str(lap_number))
            if isinstance(candidate, dict):
                lap_entry = candidate

    if lap_entry is None:
        return LapValidationContext(track_length_m=track_length_m)

    return LapValidationContext(
        close_reason=_as_optional_str(lap_entry.get("close_reason")),
        first_timestamp_ms=_as_optional_int(lap_entry.get("first_timestamp_ms")),
        last_timestamp_ms=_as_optional_int(lap_entry.get("last_timestamp_ms")),
        track_length_m=track_length_m,
    )


def evaluate_lap_validation(
    raw_df: pd.DataFrame,
    processed_df: pd.DataFrame,
    session_id: str = "",
    lap_context: LapValidationContext | None = None,
    lap_number: int | None = None,
) -> LapValidationResult:
    context = lap_context or LapValidationContext()
    reason_codes: list[str] = []

    resolved_lap_number = lap_number if lap_number is not None else _resolve_lap_number(raw_df, processed_df)
    required_signal_failures = _find_missing_required_signals(raw_df)
    timestamp_series = pd.to_numeric(raw_df["TimestampMS"], errors="coerce")
    current_lap_series = pd.to_numeric(raw_df["CurrentLap"], errors="coerce")
    lap_number_series = pd.to_numeric(raw_df["LapNumber"], errors="coerce")

    timestamp_deltas = timestamp_series.dropna().reset_index(drop=True).diff().dropna()
    current_lap_deltas = current_lap_series.dropna().reset_index(drop=True).diff().dropna()
    final_cumulative_distance_m = float(processed_df["CumulativeDistanceM"].iloc[-1]) if not processed_df.empty else 0.0
    first_current_lap_s = _first_numeric_value(current_lap_series)
    distinct_lap_numbers = _distinct_lap_numbers(lap_number_series)
    end_progress_m = _resolve_end_progress_m(final_cumulative_distance_m)
    end_completion_ratio = _calculate_completion_ratio(end_progress_m, context.track_length_m)

    if len(raw_df) < MIN_VALID_SAMPLE_COUNT:
        reason_codes.append(VALIDATION_REASON_TOO_FEW_SAMPLES)
    if (timestamp_deltas <= 0).any():
        reason_codes.append(VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP)
    if (current_lap_deltas < 0).any():
        reason_codes.append(VALIDATION_REASON_NON_MONOTONIC_CURRENT_LAP_TIME)
    if len(distinct_lap_numbers) > 1:
        reason_codes.append(VALIDATION_REASON_MULTIPLE_LAP_NUMBERS)
    if final_cumulative_distance_m < MIN_FORWARD_DISTANCE_M:
        reason_codes.append(VALIDATION_REASON_NO_FORWARD_DISTANCE)
    if first_current_lap_s is not None and first_current_lap_s > MAX_VALID_PARTIAL_LAP_START_S:
        reason_codes.append(VALIDATION_REASON_PARTIAL_LAP_START)
    if context.close_reason == LAP_CLOSE_REASON_CAPTURE_END and (
        end_completion_ratio is None or end_completion_ratio < MIN_CAPTURE_END_COMPLETION_RATIO
    ):
        reason_codes.append(VALIDATION_REASON_PARTIAL_LAP_END)
    if required_signal_failures:
        reason_codes.append(VALIDATION_REASON_MISSING_REQUIRED_SIGNALS)

    lap_is_valid = len(reason_codes) == 0
    return LapValidationResult(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        lap_number=resolved_lap_number,
        lap_is_valid=lap_is_valid,
        status="valid" if lap_is_valid else "invalid",
        reason_codes=reason_codes,
        metrics={
            "sample_count": int(len(raw_df)),
            "final_cumulative_distance_m": final_cumulative_distance_m,
            "first_current_lap_s": first_current_lap_s,
            "min_timestamp_delta_ms": _min_numeric_value(timestamp_deltas),
            "min_current_lap_delta_s": _min_numeric_value(current_lap_deltas),
            "distinct_lap_numbers": distinct_lap_numbers,
            "close_reason": context.close_reason,
            "first_timestamp_ms": context.first_timestamp_ms,
            "last_timestamp_ms": context.last_timestamp_ms,
            "track_length_m": context.track_length_m,
            "end_progress_m": end_progress_m,
            "end_completion_ratio": end_completion_ratio,
            "missing_required_signal_columns": required_signal_failures,
        },
    )


def validation_sidecar_path(processed_csv_path: str | Path) -> Path:
    processed_path = Path(processed_csv_path)
    return processed_path.with_name(f"{processed_path.stem}.validation.json")


def write_validation_result(validation_result: LapValidationResult, processed_csv_path: str | Path) -> Path:
    sidecar_path = validation_sidecar_path(processed_csv_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(validation_result.to_dict(), indent=2), encoding="utf-8")
    return sidecar_path


def _find_missing_required_signals(raw_df: pd.DataFrame) -> list[str]:
    failed_columns: list[str] = []
    for column in VALIDATION_REQUIRED_NUMERIC_COLUMNS:
        coerced = pd.to_numeric(raw_df[column], errors="coerce")
        if coerced.isna().any():
            failed_columns.append(column)
    return failed_columns


def _resolve_end_progress_m(final_cumulative_distance_m: float) -> float:
    return final_cumulative_distance_m


def _calculate_completion_ratio(end_progress_m: float, track_length_m: float | None) -> float | None:
    if track_length_m is None or track_length_m <= 0:
        return None
    return end_progress_m / track_length_m


def _resolve_lap_number(raw_df: pd.DataFrame, processed_df: pd.DataFrame) -> int:
    if not processed_df.empty and "LapNumber" in processed_df.columns:
        return int(processed_df["LapNumber"].iloc[0])

    lap_number_series = pd.to_numeric(raw_df["LapNumber"], errors="coerce").dropna()
    if lap_number_series.empty:
        return 0
    return int(lap_number_series.iloc[0])


def _distinct_lap_numbers(series: pd.Series) -> list[int]:
    numeric_values = series.dropna()
    if numeric_values.empty:
        return []
    return sorted({int(value) for value in numeric_values.tolist()})


def _first_numeric_value(series: pd.Series) -> float | None:
    numeric_values = series.dropna()
    if numeric_values.empty:
        return None
    return float(numeric_values.iloc[0])


def _min_numeric_value(series: pd.Series) -> float | None:
    numeric_values = series.dropna()
    if numeric_values.empty:
        return None
    return float(numeric_values.min())


def _max_numeric_value(series: pd.Series) -> float | None:
    numeric_values = series.dropna()
    if numeric_values.empty:
        return None
    return float(numeric_values.max())


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
