from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from src.core.telemetry import CanonicalTelemetrySample


ASSETTO_CORSA_FIELD_ALIASES = {
    "timestamp": ("timestamp", "time", "session_time", "packet_time"),
    "position_x": ("pos_x", "position_x", "world_position_x"),
    "position_y": ("pos_y", "position_y", "world_position_y"),
    "position_z": ("pos_z", "position_z", "world_position_z"),
    "speed_kmh": ("speed_kmh", "speed_kph"),
    "speed_mps": ("speed_ms", "speed_mps"),
    "throttle": ("throttle", "gas"),
    "brake": ("brake",),
    "clutch": ("clutch",),
    "steering": ("steer", "steering"),
    "steer_angle": ("steer_angle", "steering_angle"),
    "gear": ("gear",),
    "engine_rpm": ("rpms", "rpm", "engine_rpm"),
    "heading": ("heading", "heading_rad", "yaw", "orientation_yaw"),
    "lap_progress": ("lap_progress", "normalized_car_position", "spline_position"),
    "completed_laps": ("completed_laps", "completed_lap", "lap_count"),
    "longitudinal_g": ("g_lon", "g_long", "accel_longitudinal_g"),
    "lateral_g": ("g_lat", "accel_lateral_g"),
    "yaw_rate": ("yaw_rate", "local_angular_velocity_y"),
    "power_w": ("power_w", "power"),
    "torque_nm": ("torque_nm", "torque"),
    "boost_bar": ("boost", "turbo_boost"),
}

CORE_SOURCE_FIELDS = frozenset(alias for aliases in ASSETTO_CORSA_FIELD_ALIASES.values() for alias in aliases)


def _present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def _first(row: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    for alias in aliases:
        value = row.get(alias)
        if _present(value):
            return value
    return None


def _float(value: Any) -> Optional[float]:
    if not _present(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _int(value: Any) -> Optional[int]:
    number = _float(value)
    return int(number) if number is not None else None


def _native_timestamp_ns(value: Any, sample_index: int, sampling_hz: float) -> int:
    number = _float(value)
    if number is None:
        return int(round(sample_index * 1_000_000_000.0 / sampling_hz))
    magnitude = abs(number)
    if magnitude >= 1e17:
        return int(round(number))
    if magnitude >= 1e14:
        return int(round(number * 1_000.0))
    if magnitude >= 1e11:
        return int(round(number * 1_000_000.0))
    return int(round(number * 1_000_000_000.0))


def _normalise_control(value: Any) -> Optional[float]:
    number = _float(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        return min(max(number, 0.0), 1.0)
    divisor = 100.0 if abs(number) <= 100.0 else 255.0
    return min(max(number / divisor, 0.0), 1.0)


def _normalise_steering(row: Mapping[str, Any]) -> Optional[float]:
    direct = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["steering"]))
    if direct is not None:
        if abs(direct) <= 1.0:
            return min(max(direct, -1.0), 1.0)
        return min(max(direct / 127.0, -1.0), 1.0)

    angle = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["steer_angle"]))
    if angle is None:
        return None
    # AC loggers commonly expose radians or steering-wheel degrees.
    divisor = math.pi if abs(angle) <= 2.0 * math.pi else 450.0
    return min(max(angle / divisor, -1.0), 1.0)


def _json_value(value: Any) -> Any:
    if not _present(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def map_assetto_corsa_row(
    row: Mapping[str, Any],
    sample_index: int,
    source_prefix: str,
    sampling_hz: float = 100.0,
) -> CanonicalTelemetrySample:
    timestamp = _first(row, ASSETTO_CORSA_FIELD_ALIASES["timestamp"])
    speed_mps = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["speed_mps"]))
    if speed_mps is None:
        speed_kmh = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["speed_kmh"]))
        speed_mps = speed_kmh / 3.6 if speed_kmh is not None else None

    longitudinal_g = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["longitudinal_g"]))
    lateral_g = _float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["lateral_g"]))
    additional_fields = {
        str(key): _json_value(value)
        for key, value in row.items()
        if str(key) not in CORE_SOURCE_FIELDS and _present(value)
    }
    return CanonicalTelemetrySample(
        source_sample_key="{0}:{1}".format(source_prefix, sample_index),
        native_timestamp_ns=_native_timestamp_ns(timestamp, sample_index, sampling_hz),
        sample_index=sample_index,
        simulator="Assetto Corsa",
        position_x_m=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["position_x"])),
        position_y_m=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["position_y"])),
        position_z_m=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["position_z"])),
        speed_mps=speed_mps,
        throttle=_normalise_control(_first(row, ASSETTO_CORSA_FIELD_ALIASES["throttle"])),
        brake=_normalise_control(_first(row, ASSETTO_CORSA_FIELD_ALIASES["brake"])),
        clutch=_normalise_control(_first(row, ASSETTO_CORSA_FIELD_ALIASES["clutch"])),
        steering=_normalise_steering(row),
        gear=_int(_first(row, ASSETTO_CORSA_FIELD_ALIASES["gear"])),
        engine_rpm=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["engine_rpm"])),
        heading_rad=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["heading"])),
        lap_progress=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["lap_progress"])),
        completed_laps=_int(_first(row, ASSETTO_CORSA_FIELD_ALIASES["completed_laps"])),
        longitudinal_accel_mps2=longitudinal_g * 9.80665 if longitudinal_g is not None else None,
        lateral_accel_mps2=lateral_g * 9.80665 if lateral_g is not None else None,
        yaw_rate_rad_s=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["yaw_rate"])),
        power_w=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["power_w"])),
        torque_nm=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["torque_nm"])),
        boost_bar=_float(_first(row, ASSETTO_CORSA_FIELD_ALIASES["boost_bar"])),
        additional_fields=additional_fields,
        provenance={"source_row_index": sample_index, "canonical_mapping": "assetto-corsa-v1"},
    )


def map_assetto_corsa_rows(
    rows: Iterable[Mapping[str, Any]],
    source_prefix: str,
    sampling_hz: float = 100.0,
    start_index: int = 0,
) -> Iterable[CanonicalTelemetrySample]:
    for offset, row in enumerate(rows):
        yield map_assetto_corsa_row(
            row,
            sample_index=start_index + offset,
            source_prefix=source_prefix,
            sampling_hz=sampling_hz,
        )
