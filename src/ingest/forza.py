from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from src.core.telemetry import CanonicalTelemetrySample


def _number(row: Mapping[str, Any], key: str) -> Optional[float]:
    value = row.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _control(row: Mapping[str, Any], key: str, divisor: float) -> Optional[float]:
    value = _number(row, key)
    if value is None:
        return None
    return min(max(value / divisor, 0.0), 1.0)


def map_forza_row(
    row: Mapping[str, Any],
    sample_index: int,
    source_prefix: str,
) -> CanonicalTelemetrySample:
    timestamp_ms = int(_number(row, "TimestampMS") or 0)
    gear = _number(row, "Gear")
    lap_number = _number(row, "LapNumber")
    steering = _number(row, "Steer")
    return CanonicalTelemetrySample(
        source_sample_key="{0}:{1}:{2}".format(source_prefix, timestamp_ms, sample_index),
        native_timestamp_ns=timestamp_ms * 1_000_000,
        sample_index=sample_index,
        simulator="Forza Motorsport",
        position_x_m=_number(row, "PositionX"),
        position_y_m=_number(row, "PositionY"),
        position_z_m=_number(row, "PositionZ"),
        speed_mps=_number(row, "Speed"),
        throttle=_control(row, "Accel", 255.0),
        brake=_control(row, "Brake", 255.0),
        clutch=_control(row, "Clutch", 255.0),
        steering=max(min(steering / 127.0, 1.0), -1.0) if steering is not None else None,
        gear=int(gear) if gear is not None else None,
        engine_rpm=_number(row, "CurrentEngineRpm"),
        completed_laps=int(lap_number) if lap_number is not None else None,
        power_w=_number(row, "Power"),
        torque_nm=_number(row, "Torque"),
        boost_bar=_number(row, "Boost"),
        additional_fields={
            "distance_traveled_m": _number(row, "DistanceTraveled"),
            "current_lap_time_s": _number(row, "CurrentLap"),
            "current_race_time_s": _number(row, "CurrentRaceTime"),
            "track_ordinal": _number(row, "TrackOrdinal"),
            "car_ordinal": _number(row, "CarOrdinal"),
            "hand_brake": _control(row, "HandBrake", 255.0),
        },
        provenance={"canonical_mapping": "forza-data-out-v1"},
    )
