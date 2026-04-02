from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pandas as pd

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT


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
    all_lap_numbers = sorted(set(raw_lap_files) | set(processed_lap_files))

    laps = []
    for lap_num in all_lap_numbers:
        metadata_lap_time_s = _read_metadata_lap_time(metadata, lap_num)
        lap_info: dict = {
            "lap_number": lap_num,
            "has_raw": lap_num in raw_lap_files,
            "has_processed": lap_num in processed_lap_files,
            "lap_time_s": metadata_lap_time_s,
            "is_valid": None,
        }
        if lap_num in processed_lap_files:
            try:
                lap_info.update(_read_processed_lap_summary(processed_lap_files[lap_num]))
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
        "total_laps": len(all_lap_numbers),
        "has_processed": len(processed_lap_files) > 0,
        "schema_version": metadata.get("schema_version"),
        "processed_schema_version": metadata.get("processed_schema_version"),
        "notes": metadata.get("notes", ""),
        "laps": laps,
    }


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


def get_lap_data(session_id: str, lap_number: int, data_type: str) -> dict | None:
    base_dir = RAW_DATA_ROOT if data_type == "raw" else PROCESSED_DATA_ROOT
    lap_file = base_dir / session_id / f"lap_{lap_number:03d}.csv"

    if not lap_file.exists():
        return None

    df = pd.read_csv(lap_file)
    return {
        "session_id": session_id,
        "lap_number": lap_number,
        "data_type": data_type,
        "columns": list(df.columns),
        "records": df.to_dict(orient="records"),
    }


def delete_session(session_id: str) -> bool:
    deleted = False
    for directory in (RAW_DATA_ROOT / session_id, PROCESSED_DATA_ROOT / session_id):
        if directory.exists():
            shutil.rmtree(directory)
            deleted = True
    return deleted


def delete_lap(session_id: str, lap_number: int) -> bool:
    deleted = False
    for root in (RAW_DATA_ROOT, PROCESSED_DATA_ROOT):
        session_dir = root / session_id
        lap_path = session_dir / f"lap_{lap_number:03d}.csv"
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


def _read_last_numeric_value(series: pd.Series) -> float | None:
    numeric_values = pd.to_numeric(series, errors="coerce").dropna()
    if numeric_values.empty:
        return None

    return float(numeric_values.iloc[-1])


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


def _remove_empty_session_dir(directory: Path) -> None:
    if not directory.exists():
        return
    lap_count = _count_laps(directory)
    metadata_path = directory / "metadata.json"
    if lap_count == 0 and metadata_path.exists():
        metadata_path.unlink()
    if directory.exists() and not any(directory.iterdir()):
        directory.rmdir()
