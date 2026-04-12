from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT

LAP_VIEW_FULL = "full"
LAP_VIEW_REVIEW = "review"
REVIEW_X_KEYS = {
    "processed": "ElapsedTimeS",
    "raw": "CurrentLap",
}
COMPARE_MAX_LAPS = 6
COMPARE_MAX_POINTS = 800
COMPARE_X_KEY = "TrackProgressNorm"
REVIEW_COLUMNS = {
    "processed": [
        "ElapsedTimeS",
        "NormalizedDistance",
        "CumulativeDistanceM",
        "PositionX",
        "PositionY",
        "PositionZ",
        "SpeedKph",
        "Throttle",
        "Brake",
        "Steering",
    ],
    "raw": ["CurrentLap", "Speed", "Accel", "Brake", "Steer"],
}
COMPARE_COLUMNS = [
    "TrackProgressNorm",
    "TrackProgressM",
    "ElapsedTimeS",
    "PositionX",
    "PositionY",
    "PositionZ",
    "SpeedKph",
    "Brake",
    "Steering",
]


def list_sessions() -> list[dict]:
    session_ids: set[str] = set()
    for root in (RAW_DATA_ROOT, PROCESSED_DATA_ROOT):
        if root.exists():
            session_ids.update(d.name for d in root.iterdir() if d.is_dir())

    sessions = []
    for session_id in sorted(session_ids, reverse=True):
        raw_dir = RAW_DATA_ROOT / session_id
        processed_dir = PROCESSED_DATA_ROOT / session_id
        metadata = _load_metadata(raw_dir) or _load_metadata(processed_dir) or {}
        raw_laps = _count_laps(raw_dir)
        processed_laps = _count_laps(processed_dir)

        sessions.append(
            {
                "session_id": session_id,
                "display_name": _normalize_display_name(metadata.get("display_name")),
                "created_at_utc": metadata.get("created_at_utc"),
                "track_circuit": metadata.get("track_circuit"),
                "track_layout": metadata.get("track_layout"),
                "track_location": metadata.get("track_location"),
                "car_ordinal": metadata.get("car_ordinal"),
                "total_laps": max(raw_laps, processed_laps, metadata.get("total_laps", 0)),
                "has_processed": processed_laps > 0,
            }
        )

    return sessions


def get_session_detail(session_id: str) -> dict | None:
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id

    if not raw_dir.exists() and not processed_dir.exists():
        return None

    raw_meta = _load_metadata(raw_dir) or {}
    processed_meta = _load_metadata(processed_dir) or {}
    metadata = {**raw_meta, **processed_meta}

    raw_lap_files = _get_lap_files(raw_dir)
    processed_lap_files = _get_lap_files(processed_dir)
    lap_number_mapping = _build_session_lap_number_mapping(raw_lap_files, processed_lap_files, metadata)
    all_stored_lap_numbers = sorted(lap_number_mapping["stored_to_display"])

    laps = []
    for stored_lap_number in all_stored_lap_numbers:
        display_lap_number = lap_number_mapping["stored_to_display"][stored_lap_number]
        metadata_lap_time_s = _read_metadata_lap_time(metadata, stored_lap_number)
        lap_info: dict = {
            "lap_number": display_lap_number,
            "has_raw": stored_lap_number in raw_lap_files,
            "has_processed": stored_lap_number in processed_lap_files,
            "lap_time_s": metadata_lap_time_s,
            "is_valid": None,
        }
        if stored_lap_number in processed_lap_files:
            try:
                lap_info.update(_read_processed_lap_summary(processed_lap_files[stored_lap_number]))
            except Exception:
                pass

        laps.append(lap_info)

    return {
        "session_id": session_id,
        "display_name": _normalize_display_name(metadata.get("display_name")),
        "created_at_utc": metadata.get("created_at_utc"),
        "sim": metadata.get("sim"),
        "track_circuit": metadata.get("track_circuit"),
        "track_layout": metadata.get("track_layout"),
        "track_location": metadata.get("track_location"),
        "track_length_m": metadata.get("track_length_m"),
        "car_ordinal": metadata.get("car_ordinal"),
        "total_laps": len(all_stored_lap_numbers),
        "has_processed": len(processed_lap_files) > 0,
        "schema_version": metadata.get("schema_version"),
        "processed_schema_version": metadata.get("processed_schema_version"),
        "notes": metadata.get("notes", ""),
        "laps": laps,
    }


def get_session_lap_number_mapping(session_id: str) -> dict[str, dict[int, int]]:
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id
    metadata = (_load_metadata(raw_dir) or {}) | (_load_metadata(processed_dir) or {})
    return _build_session_lap_number_mapping(
        _get_lap_files(raw_dir),
        _get_lap_files(processed_dir),
        metadata,
    )


def update_session_metadata(session_id: str, *, display_name: str | None) -> dict | None:
    updated = False
    normalized_display_name = _normalize_display_name(display_name)

    for directory in (RAW_DATA_ROOT / session_id, PROCESSED_DATA_ROOT / session_id):
        if not directory.exists():
            continue

        metadata_path = directory / "metadata.json"
        metadata = _load_metadata(directory) or {"session_id": session_id}

        if normalized_display_name is None:
            metadata.pop("display_name", None)
        else:
            metadata["display_name"] = normalized_display_name

        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        updated = True

    if not updated:
        return None

    return get_session_detail(session_id)


def get_lap_data(
    session_id: str,
    lap_number: int,
    data_type: str,
    *,
    view: str = LAP_VIEW_FULL,
    max_points: int = 1000,
) -> dict | None:
    base_dir = RAW_DATA_ROOT if data_type == "raw" else PROCESSED_DATA_ROOT
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id
    metadata = (_load_metadata(raw_dir) or {}) | (_load_metadata(processed_dir) or {})
    lap_number_mapping = _build_session_lap_number_mapping(
        _get_lap_files(raw_dir),
        _get_lap_files(processed_dir),
        metadata,
    )
    stored_lap_number = lap_number_mapping["display_to_stored"].get(lap_number)
    if stored_lap_number is None:
        return None

    lap_file = base_dir / session_id / f"lap_{stored_lap_number:03d}.csv"

    if not lap_file.exists():
        return None

    df = pd.read_csv(lap_file)
    summary = _build_lap_data_summary(df, data_type)
    x_key = REVIEW_X_KEYS[data_type]

    if view == LAP_VIEW_REVIEW:
        result_df = _build_review_lap_dataframe(df, data_type, max_points)
        returned_columns = list(result_df.columns)
        returned_max_points: int | None = max_points
    else:
        result_df = df
        returned_columns = list(df.columns)
        returned_max_points = None

    return {
        "session_id": session_id,
        "lap_number": lap_number,
        "data_type": data_type,
        "columns": returned_columns,
        "records": result_df.to_dict(orient="records"),
        "summary": summary,
        "sampling": {
            "view": view,
            "source_rows": int(len(df)),
            "returned_rows": int(len(result_df)),
            "max_points": returned_max_points,
            "x_key": x_key,
        },
    }


def get_compare_candidates(session_id: str) -> dict:
    seed_detail = get_session_detail(session_id)
    if seed_detail is None:
        raise FileNotFoundError(f"Session not found: {session_id}")

    track_key = _resolve_track_key(seed_detail)
    if track_key is None:
        raise ValueError("Seed session is missing usable track metadata")

    candidate_sessions: list[dict] = []
    for session in list_sessions():
        session_track_key = _resolve_track_key(session)
        if session_track_key != track_key:
            continue

        eligible_laps = _get_eligible_compare_laps(session["session_id"])
        if not eligible_laps:
            continue

        candidate_sessions.append(
            {
                "session_id": session["session_id"],
                "display_name": session.get("display_name"),
                "created_at_utc": session.get("created_at_utc"),
                "track_circuit": session.get("track_circuit"),
                "track_layout": session.get("track_layout"),
                "track_location": session.get("track_location"),
                "laps": eligible_laps,
            }
        )

    return {
        "seed_session_id": session_id,
        "track_circuit": seed_detail["track_circuit"],
        "track_layout": seed_detail["track_layout"],
        "track_location": seed_detail.get("track_location"),
        "sessions": candidate_sessions,
    }


def build_lap_overlay(
    selections: list[dict[str, object]],
    reference_lap: dict[str, object],
) -> dict:
    normalized_selections = [_normalize_overlay_selection(selection) for selection in selections]
    if not normalized_selections:
        raise ValueError("Select at least one lap to compare")
    if len(normalized_selections) > COMPARE_MAX_LAPS:
        raise ValueError(f"Select at most {COMPARE_MAX_LAPS} laps to compare")

    selection_keys = [(selection["session_id"], selection["lap_number"]) for selection in normalized_selections]
    if len(set(selection_keys)) != len(selection_keys):
        raise ValueError("Duplicate lap selections are not allowed")

    normalized_reference = _normalize_overlay_selection(reference_lap)
    if (normalized_reference["session_id"], normalized_reference["lap_number"]) not in set(selection_keys):
        raise ValueError("Reference lap must be included in the selected laps")

    reference_session_detail = get_session_detail(normalized_reference["session_id"])
    if reference_session_detail is None:
        raise FileNotFoundError(f"Reference session not found: {normalized_reference['session_id']}")

    track_key = _resolve_track_key(reference_session_detail)
    if track_key is None:
        raise ValueError("Reference session is missing usable track metadata")

    overlay_series: list[dict[str, object]] = []
    for selection in normalized_selections:
        session_detail = get_session_detail(selection["session_id"])
        if session_detail is None:
            raise FileNotFoundError(f"Session not found: {selection['session_id']}")

        if _resolve_track_key(session_detail) != track_key:
            raise ValueError(
                f"Lap {selection['lap_number']} from {selection['session_id']} does not match the reference track"
            )

        processed_df = _load_compare_processed_lap(selection["session_id"], selection["lap_number"])
        overlay_df = _build_compare_lap_dataframe(processed_df, max_points=COMPARE_MAX_POINTS)
        overlay_series.append(
            {
                "session_id": selection["session_id"],
                "display_name": session_detail.get("display_name"),
                "lap_number": selection["lap_number"],
                "lap_time_s": _read_series_last_numeric_value(processed_df, "LapTimeS"),
                "records": overlay_df.to_dict(orient="records"),
            }
        )

    reference_selection = {
        "session_id": normalized_reference["session_id"],
        "lap_number": normalized_reference["lap_number"],
    }
    return {
        "track_circuit": reference_session_detail["track_circuit"],
        "track_layout": reference_session_detail["track_layout"],
        "track_location": reference_session_detail.get("track_location"),
        "reference_lap": reference_selection,
        "segmentation": get_track_segmentation(normalized_reference["session_id"]),
        "series": overlay_series,
    }


def delete_session(session_id: str) -> bool:
    deleted = False
    for directory in (RAW_DATA_ROOT / session_id, PROCESSED_DATA_ROOT / session_id):
        if directory.exists():
            shutil.rmtree(directory)
            deleted = True
    return deleted


def delete_lap(session_id: str, lap_number: int) -> bool:
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id
    metadata = (_load_metadata(raw_dir) or {}) | (_load_metadata(processed_dir) or {})
    lap_number_mapping = _build_session_lap_number_mapping(
        _get_lap_files(raw_dir),
        _get_lap_files(processed_dir),
        metadata,
    )
    stored_lap_number = lap_number_mapping["display_to_stored"].get(lap_number)
    if stored_lap_number is None:
        return False

    deleted = False
    for root in (RAW_DATA_ROOT, PROCESSED_DATA_ROOT):
        session_dir = root / session_id
        lap_path = session_dir / f"lap_{stored_lap_number:03d}.csv"
        if lap_path.exists():
            lap_path.unlink()
            deleted = True
            _refresh_metadata_total_laps(session_dir)
            _remove_empty_session_dir(session_dir)
    return deleted


def _load_metadata(directory: Path) -> dict | None:
    path = directory / "metadata.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_display_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _count_laps(directory: Path) -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob("lap_*.csv")))


def _get_lap_files(directory: Path) -> dict[int, Path]:
    if not directory.exists():
        return {}
    files: dict[int, Path] = {}
    for path in directory.glob("lap_*.csv"):
        match = re.match(r"lap_(\d+)\.csv", path.name)
        if match:
            files[int(match.group(1))] = path
    return files


def _build_session_lap_number_mapping(
    raw_lap_files: dict[int, Path],
    processed_lap_files: dict[int, Path],
    metadata: dict | None,
) -> dict[str, dict[int, int]]:
    stored_lap_numbers = sorted(set(raw_lap_files) | set(processed_lap_files) | set(_metadata_lap_numbers(metadata)))
    display_offset = 1 if 0 in stored_lap_numbers else 0

    stored_to_display = {
        stored_lap_number: stored_lap_number + display_offset
        for stored_lap_number in stored_lap_numbers
    }
    display_to_stored = {
        display_lap_number: stored_lap_number
        for stored_lap_number, display_lap_number in stored_to_display.items()
    }
    return {
        "stored_to_display": stored_to_display,
        "display_to_stored": display_to_stored,
    }


def _metadata_lap_numbers(metadata: dict | None) -> list[int]:
    if not isinstance(metadata, dict):
        return []

    lap_index = metadata.get("lap_index")
    if not isinstance(lap_index, dict):
        return []

    lap_numbers: list[int] = []
    for key in lap_index:
        try:
            lap_numbers.append(int(key))
        except (TypeError, ValueError):
            continue
    return lap_numbers


def _read_processed_lap_summary(path: Path) -> dict[str, float | bool | None]:
    df = pd.read_csv(path)
    is_valid: bool | None = None

    if "LapIsValid" in df.columns:
        lap_valid_value = _read_last_numeric_value(df["LapIsValid"])
        if lap_valid_value is not None:
            is_valid = bool(int(lap_valid_value))

    return {
        "is_valid": is_valid,
    }


def _build_lap_data_summary(df: pd.DataFrame, data_type: str) -> dict[str, float | bool | None]:
    if data_type == "processed":
        lap_time_s = _read_series_last_numeric_value(df, "LapTimeS")
        lap_is_valid = _read_series_last_bool_value(df, "LapIsValid")
    else:
        lap_time_s = _read_series_last_numeric_value(df, "CurrentLap")
        if lap_time_s is None:
            lap_time_s = _read_series_last_numeric_value(df, "LapTimeS")
        lap_is_valid = _read_series_last_bool_value(df, "LapIsValid")

    return {
        "lap_time_s": lap_time_s,
        "lap_is_valid": lap_is_valid,
    }


def _build_review_lap_dataframe(df: pd.DataFrame, data_type: str, max_points: int) -> pd.DataFrame:
    selected_columns = [column for column in REVIEW_COLUMNS[data_type] if column in df.columns]
    if not selected_columns:
        return df.iloc[0:0].copy()

    review_df = df[selected_columns].copy()
    x_key = REVIEW_X_KEYS[data_type]
    if x_key not in review_df.columns or review_df.empty:
        return review_df.reset_index(drop=True)

    review_df["_review_x"] = pd.to_numeric(review_df[x_key], errors="coerce")
    review_df = review_df.dropna(subset=["_review_x"]).sort_values("_review_x").drop_duplicates(subset="_review_x")
    review_df = review_df.reset_index(drop=True)

    if review_df.empty or len(review_df) <= max_points:
        return review_df.drop(columns="_review_x", errors="ignore").reset_index(drop=True)

    sampled_indices = _choose_downsample_indices(review_df["_review_x"].to_numpy(dtype=float), max_points)
    return review_df.iloc[sampled_indices].drop(columns="_review_x", errors="ignore").reset_index(drop=True)


def _build_compare_lap_dataframe(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    missing_columns = [column for column in COMPARE_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Processed lap is missing compare columns: {missing_columns}")

    compare_df = df[COMPARE_COLUMNS].copy()
    compare_df["_compare_x"] = pd.to_numeric(compare_df[COMPARE_X_KEY], errors="coerce")
    compare_df = (
        compare_df.dropna(subset=["_compare_x"])
        .sort_values("_compare_x")
        .drop_duplicates(subset="_compare_x")
        .reset_index(drop=True)
    )
    if compare_df.empty:
        raise ValueError("Processed lap does not contain usable aligned progress samples")

    if len(compare_df) > max_points:
        sampled_indices = _choose_downsample_indices(compare_df["_compare_x"].to_numpy(dtype=float), max_points)
        compare_df = compare_df.iloc[sampled_indices].reset_index(drop=True)

    return compare_df.drop(columns="_compare_x", errors="ignore").reset_index(drop=True)


def _choose_downsample_indices(x_values: np.ndarray, max_points: int) -> list[int]:
    if len(x_values) <= max_points:
        return list(range(len(x_values)))

    target_values = np.linspace(float(x_values[0]), float(x_values[-1]), num=max_points)
    candidate_indices: list[int] = [0]

    for target in target_values[1:-1]:
        right_index = int(np.searchsorted(x_values, target, side="left"))
        right_index = min(max(right_index, 0), len(x_values) - 1)
        left_index = max(right_index - 1, 0)
        chosen_index = min(
            (left_index, right_index),
            key=lambda index: (abs(float(x_values[index]) - float(target)), index),
        )
        candidate_indices.append(chosen_index)

    candidate_indices.append(len(x_values) - 1)
    return list(dict.fromkeys(candidate_indices))


def _read_last_numeric_value(series: pd.Series) -> float | None:
    numeric_values = pd.to_numeric(series, errors="coerce").dropna()
    if numeric_values.empty:
        return None

    return float(numeric_values.iloc[-1])


def _read_series_last_numeric_value(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    return _read_last_numeric_value(df[column])


def _read_series_last_bool_value(df: pd.DataFrame, column: str) -> bool | None:
    numeric_value = _read_series_last_numeric_value(df, column)
    if numeric_value is None:
        return None
    return bool(int(numeric_value))


def _get_eligible_compare_laps(session_id: str) -> list[dict[str, float | int | None]]:
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id
    metadata = (_load_metadata(raw_dir) or {}) | (_load_metadata(processed_dir) or {})
    raw_lap_files = _get_lap_files(raw_dir)
    processed_lap_files = _get_lap_files(processed_dir)
    lap_number_mapping = _build_session_lap_number_mapping(raw_lap_files, processed_lap_files, metadata)

    eligible_laps: list[dict[str, float | int | None]] = []
    for stored_lap_number in sorted(processed_lap_files):
        lap_summary = _read_processed_compare_lap_summary(processed_lap_files[stored_lap_number])
        if not lap_summary["alignment_is_usable"]:
            continue

        eligible_laps.append(
            {
                "lap_number": lap_number_mapping["stored_to_display"].get(stored_lap_number, stored_lap_number),
                "lap_time_s": lap_summary["lap_time_s"],
            }
        )

    return eligible_laps


def _read_processed_compare_lap_summary(path: Path) -> dict[str, float | bool | None]:
    df = pd.read_csv(
        path,
        usecols=lambda column: column in {"AlignmentIsUsable", "LapTimeS"},
    )
    return {
        "lap_time_s": _read_series_last_numeric_value(df, "LapTimeS"),
        "alignment_is_usable": _read_series_last_bool_value(df, "AlignmentIsUsable") is True,
    }


def _normalize_overlay_selection(selection: dict[str, object]) -> dict[str, int | str]:
    session_id = selection.get("session_id")
    lap_number = selection.get("lap_number")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Lap selections require a session_id")
    try:
        parsed_lap_number = int(lap_number)
    except (TypeError, ValueError) as exc:
        raise ValueError("Lap selections require a numeric lap_number") from exc
    return {
        "session_id": session_id.strip(),
        "lap_number": parsed_lap_number,
    }


def _load_compare_processed_lap(session_id: str, display_lap_number: int) -> pd.DataFrame:
    raw_dir = RAW_DATA_ROOT / session_id
    processed_dir = PROCESSED_DATA_ROOT / session_id
    if not processed_dir.exists():
        raise FileNotFoundError(f"Processed session not found: {session_id}")

    metadata = (_load_metadata(raw_dir) or {}) | (_load_metadata(processed_dir) or {})
    lap_number_mapping = _build_session_lap_number_mapping(
        _get_lap_files(raw_dir),
        _get_lap_files(processed_dir),
        metadata,
    )
    stored_lap_number = lap_number_mapping["display_to_stored"].get(display_lap_number)
    if stored_lap_number is None:
        raise ValueError(f"Lap {display_lap_number} not found in session {session_id}")

    lap_path = processed_dir / f"lap_{stored_lap_number:03d}.csv"
    if not lap_path.exists():
        raise FileNotFoundError(f"Processed lap file not found for lap {display_lap_number} in {session_id}")

    df = pd.read_csv(lap_path)
    if _read_series_last_bool_value(df, "AlignmentIsUsable") is not True:
        raise ValueError(f"Lap {display_lap_number} in {session_id} is not alignment-usable")
    return df


def _normalize_track_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_track_key(metadata: dict | None) -> tuple[str, str] | None:
    if not isinstance(metadata, dict):
        return None

    track_circuit = _normalize_track_value(metadata.get("track_circuit"))
    track_layout = _normalize_track_value(metadata.get("track_layout"))
    if track_circuit is None or track_layout is None:
        return None
    return (track_circuit, track_layout)


def _read_metadata_lap_time(
    metadata: dict | None,
    lap_number: int,
) -> float | None:
    if not isinstance(metadata, dict):
        return None

    lap_index = metadata.get("lap_index")
    if not isinstance(lap_index, dict):
        return None

    lap_entry = lap_index.get(str(lap_number))
    if not isinstance(lap_entry, dict):
        return None

    first_timestamp_ms = lap_entry.get("first_timestamp_ms")
    last_timestamp_ms = lap_entry.get("last_timestamp_ms")

    try:
        if first_timestamp_ms is None or last_timestamp_ms is None:
            return None

        return max(0.0, (float(last_timestamp_ms) - float(first_timestamp_ms)) / 1000.0)
    except (TypeError, ValueError):
        return None


def _refresh_metadata_total_laps(directory: Path) -> None:
    metadata_path = directory / "metadata.json"
    if not metadata_path.exists():
        return
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["total_laps"] = _count_laps(directory)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    except Exception:
        return


def get_track_segmentation(session_id: str) -> dict | None:
    processed_dir = PROCESSED_DATA_ROOT / session_id
    seg_path = processed_dir / "track_segmentation.json"
    if not seg_path.exists():
        return None
    try:
        return json.loads(seg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _remove_empty_session_dir(directory: Path) -> None:
    if not directory.exists():
        return
    lap_count = _count_laps(directory)
    metadata_path = directory / "metadata.json"
    if lap_count == 0 and metadata_path.exists():
        metadata_path.unlink()
    if directory.exists() and not any(directory.iterdir()):
        directory.rmdir()
