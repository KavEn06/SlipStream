"""Simulator-neutral contracts used at ingestion and persistence boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional


CANONICAL_TELEMETRY_VERSION = "1.0"


@dataclass(frozen=True)
class DataSourceContract:
    key: str
    kind: str
    simulator: str
    provider: Optional[str] = None
    dataset_name: Optional[str] = None
    source_url: Optional[str] = None
    revision: Optional[str] = None
    license: Optional[str] = None
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionContract:
    external_id: str
    simulator: str
    sampling_hz: Optional[float] = None
    started_at: Optional[datetime] = None
    track_external_id: Optional[str] = None
    car_external_id: Optional[str] = None
    conditions: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LapContract:
    lap_number: int
    source_lap_key: str
    started_native_ns: Optional[int] = None
    ended_native_ns: Optional[int] = None
    duration_s: Optional[float] = None
    is_valid: Optional[bool] = None
    status: str = "observed"
    quality: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalTelemetrySample:
    """One native-rate sample; units are SI except normalized controls."""

    source_sample_key: str
    native_timestamp_ns: int
    sample_index: int
    simulator: str
    position_x_m: Optional[float] = None
    position_y_m: Optional[float] = None
    position_z_m: Optional[float] = None
    speed_mps: Optional[float] = None
    throttle: Optional[float] = None
    brake: Optional[float] = None
    clutch: Optional[float] = None
    steering: Optional[float] = None
    gear: Optional[int] = None
    engine_rpm: Optional[float] = None
    heading_rad: Optional[float] = None
    lap_progress: Optional[float] = None
    completed_laps: Optional[int] = None
    longitudinal_accel_mps2: Optional[float] = None
    lateral_accel_mps2: Optional[float] = None
    yaw_rate_rad_s: Optional[float] = None
    power_w: Optional[float] = None
    torque_nm: Optional[float] = None
    boost_bar: Optional[float] = None
    additional_fields: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProcessedTelemetryContract:
    sample_index: int
    progress: float
    elapsed_s: float
    distance_m: Optional[float] = None
    speed_mps: Optional[float] = None
    throttle: Optional[float] = None
    brake: Optional[float] = None
    steering: Optional[float] = None
    gear: Optional[int] = None
    engine_rpm: Optional[float] = None
    features: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConditionContract:
    scope: str
    kind: str
    value: Mapping[str, Any]
    origin: str = "observed"


@dataclass(frozen=True)
class FindingContract:
    detector: str
    category: str
    payload: Mapping[str, Any]
    lap_id: Optional[int] = None
    section_key: Optional[str] = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class RecommendationContract:
    recommendation_id: str
    hypothesis: str
    payload: Mapping[str, Any]
    lap_id: Optional[int] = None
    section_key: Optional[str] = None
    model_version_id: Optional[int] = None
    driver_baseline: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecommendationOutcomeContract:
    recommendation_id: str
    schema_version: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class RecommendationRatingContract:
    recommendation_id: str
    schema_version: str
    helpful: Optional[bool] = None
    reason: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelVersionContract:
    name: str
    version: str
    model_type: str
    artifact_uri: Optional[str] = None
    source_revisions: Mapping[str, Any] = field(default_factory=dict)
    compatibility: Mapping[str, Any] = field(default_factory=dict)
    feature_definition: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionProfileContract:
    profile_key: str
    values: List[Mapping[str, Any]]
    lap_id: Optional[int] = None
    section_key: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
