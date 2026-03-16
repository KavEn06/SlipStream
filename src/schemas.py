from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = "2026.03-phase1"

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


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
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
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class Finding:
    finding_type: str
    region_type: str
    start_norm_distance: float
    end_norm_distance: float
    metric: str
    observed: float
    reference: float
    delta: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

