from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "2026.04-phase2-alignment"
VALIDATION_THRESHOLDS_VERSION = "v1-fixed"

VALIDATION_REASON_TOO_FEW_SAMPLES = "too_few_samples"
VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP = "non_monotonic_timestamp"
VALIDATION_REASON_NON_MONOTONIC_CURRENT_LAP_TIME = "non_monotonic_current_lap_time"
VALIDATION_REASON_MULTIPLE_LAP_NUMBERS = "multiple_lap_numbers"
VALIDATION_REASON_NO_FORWARD_DISTANCE = "no_forward_distance"
VALIDATION_REASON_PARTIAL_LAP_START = "partial_lap_start"
VALIDATION_REASON_PARTIAL_LAP_END = "partial_lap_end"
VALIDATION_REASON_MISSING_REQUIRED_SIGNALS = "missing_required_signals"

VALIDATION_REASON_CODES = (
    VALIDATION_REASON_TOO_FEW_SAMPLES,
    VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP,
    VALIDATION_REASON_NON_MONOTONIC_CURRENT_LAP_TIME,
    VALIDATION_REASON_MULTIPLE_LAP_NUMBERS,
    VALIDATION_REASON_NO_FORWARD_DISTANCE,
    VALIDATION_REASON_PARTIAL_LAP_START,
    VALIDATION_REASON_PARTIAL_LAP_END,
    VALIDATION_REASON_MISSING_REQUIRED_SIGNALS,
)

VALIDATION_REQUIRED_NUMERIC_COLUMNS = (
    "TimestampMS",
    "CurrentLap",
    "LapNumber",
    "Speed",
    "Accel",
    "Brake",
    "Clutch",
    "HandBrake",
    "Gear",
    "Steer",
)

LAP_CLOSE_REASON_LAP_ROLLOVER = "lap_rollover"
LAP_CLOSE_REASON_CAPTURE_END = "capture_end"

RAW_LAP_COLUMNS = [
    "IsRaceOn",
    "TimestampMS",
    "EngineMaxRpm",
    "EngineIdleRpm",
    "CurrentEngineRpm",
    "CarOrdinal",
    "PositionX",
    "PositionY",
    "PositionZ",
    "Speed",
    "Power",
    "Torque",
    "Boost",
    "DistanceTraveled",
    "BestLap",
    "LastLap",
    "CurrentLap",
    "CurrentRaceTime",
    "LapNumber",
    "Accel",
    "Brake",
    "Clutch",
    "HandBrake",
    "Gear",
    "Steer",
    "TrackOrdinal",
]

PROCESSED_LAP_COLUMNS = [
    "SchemaVersion",
    "SessionId",
    "LapNumber",
    "SampleIndex",
    "TimestampMS",
    "ElapsedTimeS",
    "DeltaTimeS",
    "PositionX",
    "PositionY",
    "PositionZ",
    "DistanceTraveledM",
    "CumulativeDistanceM",
    "NormalizedDistance",
    "TrackProgressM",
    "TrackProgressNorm",
    "AlignmentResidualM",
    "AlignmentUsedFallback",
    "SpeedMps",
    "SpeedKph",
    "EngineRpm",
    "Throttle",
    "Brake",
    "Clutch",
    "HandBrake",
    "Steering",
    "Gear",
    "Power",
    "Torque",
    "Boost",
    "LongitudinalAccelMps2",
    "ThrottleRatePerS",
    "BrakeRatePerS",
    "SteeringRatePerS",
    "SteeringSmoothness",
    "IsCoasting",
    "LapTimeS",
    "LapIsValid",
    "AlignmentIsUsable",
]

REFERENCE_LAP_COLUMNS = [
    "NormalizedDistance",
    "CumulativeDistanceM",
    "ElapsedTimeS",
    "SpeedMps",
    "SpeedKph",
    "Throttle",
    "Brake",
    "Steering",
    "EngineRpm",
    "Gear",
    "LongitudinalAccelMps2",
    "IsCoasting",
]

ALIGNED_LAP_COLUMNS = [
    "TrackProgressNorm",
    "TrackProgressM",
    "ElapsedTimeS",
    "SpeedMps",
    "SpeedKph",
    "Throttle",
    "Brake",
    "Steering",
    "EngineRpm",
    "Gear",
    "LongitudinalAccelMps2",
    "IsCoasting",
]

REFERENCE_PATH_COLUMNS = [
    "ReferenceSampleIndex",
    "ReferenceLapNumber",
    "PositionX",
    "PositionY",
    "PositionZ",
    "ReferenceDistanceM",
    "ReferenceProgressNorm",
]


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
    display_name: str | None
    schema_version: str
    sim: str
    created_at_utc: str
    capture_ip: str
    capture_port: int
    car_ordinal: int | None
    track_ordinal: int | None
    track_circuit: str | None
    track_layout: str | None
    track_location: str | None
    track_length_m: float | None
    total_laps: int
    lap_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LapValidationContext:
    close_reason: str | None = None
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    track_length_m: float | None = None


@dataclass(frozen=True)
class LapValidationResult:
    schema_version: str
    session_id: str
    lap_number: int
    lap_is_valid: bool
    status: str
    reason_codes: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    thresholds_version: str = VALIDATION_THRESHOLDS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
