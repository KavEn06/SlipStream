from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    simulator: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    dataset_name: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    revision: Mapped[Optional[str]] = mapped_column(String(128))
    license: Mapped[Optional[str]] = mapped_column(String(128))
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ImportRun(TimestampMixin, Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    rows_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    quality_report: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("data_source_id", "import_key", name="uq_import_source_key"),)


class Track(TimestampMixin, Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    simulator: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    circuit: Mapped[str] = mapped_column(String(255), nullable=False)
    layout: Mapped[Optional[str]] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    length_m: Mapped[Optional[float]] = mapped_column(Float)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


class Car(TimestampMixin, Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    simulator: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    make: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    car_class: Mapped[Optional[str]] = mapped_column(String(128))
    metadata_json: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


class TelemetrySession(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    simulator: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"), index=True)
    car_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cars.id", ondelete="SET NULL"), index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sampling_hz: Mapped[Optional[float]] = mapped_column(Float)
    conditions: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="uq_session_source_external"),
        Index("ix_sessions_track_car", "track_id", "car_id"),
    )


class Lap(TimestampMixin, Base):
    __tablename__ = "laps"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_lap_key: Mapped[str] = mapped_column(String(255), nullable=False)
    started_native_ns: Mapped[Optional[int]] = mapped_column(BigInteger)
    ended_native_ns: Mapped[Optional[int]] = mapped_column(BigInteger)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="observed")
    quality: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("session_id", "source_lap_key", name="uq_lap_session_source_key"),
        Index("ix_laps_session_number", "session_id", "lap_number"),
    )


class RawTelemetrySample(Base):
    __tablename__ = "raw_telemetry_samples"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    lap_id: Mapped[Optional[int]] = mapped_column(ForeignKey("laps.id", ondelete="SET NULL"))
    source_sample_key: Mapped[str] = mapped_column(String(255), nullable=False)
    native_timestamp_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    simulator: Mapped[str] = mapped_column(String(128), nullable=False)
    position_x_m: Mapped[Optional[float]] = mapped_column(Float)
    position_y_m: Mapped[Optional[float]] = mapped_column(Float)
    position_z_m: Mapped[Optional[float]] = mapped_column(Float)
    speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    throttle: Mapped[Optional[float]] = mapped_column(Float)
    brake: Mapped[Optional[float]] = mapped_column(Float)
    clutch: Mapped[Optional[float]] = mapped_column(Float)
    steering: Mapped[Optional[float]] = mapped_column(Float)
    gear: Mapped[Optional[int]] = mapped_column(Integer)
    engine_rpm: Mapped[Optional[float]] = mapped_column(Float)
    heading_rad: Mapped[Optional[float]] = mapped_column(Float)
    lap_progress: Mapped[Optional[float]] = mapped_column(Float)
    completed_laps: Mapped[Optional[int]] = mapped_column(Integer)
    longitudinal_accel_mps2: Mapped[Optional[float]] = mapped_column(Float)
    lateral_accel_mps2: Mapped[Optional[float]] = mapped_column(Float)
    yaw_rate_rad_s: Mapped[Optional[float]] = mapped_column(Float)
    power_w: Mapped[Optional[float]] = mapped_column(Float)
    torque_nm: Mapped[Optional[float]] = mapped_column(Float)
    boost_bar: Mapped[Optional[float]] = mapped_column(Float)
    additional_fields: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("data_source_id", "source_sample_key", name="uq_raw_source_sample"),
        Index("ix_raw_session_lap_time", "session_id", "lap_id", "native_timestamp_ns"),
        Index("ix_raw_lap_sample", "lap_id", "sample_index"),
    )


class ProcessedTelemetrySample(Base):
    __tablename__ = "processed_telemetry_samples"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    lap_id: Mapped[int] = mapped_column(ForeignKey("laps.id", ondelete="CASCADE"), nullable=False)
    raw_sample_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_telemetry_samples.id", ondelete="SET NULL")
    )
    processing_version: Mapped[str] = mapped_column(String(128), nullable=False)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False)
    elapsed_s: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    throttle: Mapped[Optional[float]] = mapped_column(Float)
    brake: Mapped[Optional[float]] = mapped_column(Float)
    steering: Mapped[Optional[float]] = mapped_column(Float)
    gear: Mapped[Optional[int]] = mapped_column(Integer)
    engine_rpm: Mapped[Optional[float]] = mapped_column(Float)
    features: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("lap_id", "processing_version", "sample_index", name="uq_processed_lap_version_sample"),
        Index("ix_processed_lap_progress", "lap_id", "progress"),
    )


class Condition(TimestampMixin, Base):
    __tablename__ = "conditions"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    lap_id: Mapped[Optional[int]] = mapped_column(ForeignKey("laps.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AnalysisRun(TimestampMixin, Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    quality_report: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    lap_id: Mapped[Optional[int]] = mapped_column(ForeignKey("laps.id", ondelete="SET NULL"))
    finding_key: Mapped[str] = mapped_column(String(255), nullable=False)
    detector: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    section_key: Mapped[Optional[str]] = mapped_column(String(128))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "finding_key", name="uq_finding_run_key"),
    )


class ModelVersion(TimestampMixin, Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="challenger")
    artifact_uri: Mapped[Optional[str]] = mapped_column(Text)
    checksum: Mapped[Optional[str]] = mapped_column(String(128))
    source_revisions: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    feature_definition: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    compatibility: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)


class ModelMetric(TimestampMixin, Base):
    __tablename__ = "model_metrics"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    split: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("model_version_id", "split", "name", name="uq_metric_model_split_name"),
    )


class PredictionProfile(TimestampMixin, Base):
    __tablename__ = "prediction_profiles"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    lap_id: Mapped[Optional[int]] = mapped_column(ForeignKey("laps.id", ondelete="CASCADE"))
    profile_key: Mapped[str] = mapped_column(String(255), nullable=False)
    section_key: Mapped[Optional[str]] = mapped_column(String(128))
    values: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("model_version_id", "profile_key", name="uq_prediction_model_key"),
        Index("ix_prediction_lap_section", "lap_id", "section_key"),
    )


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[Optional[int]] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    lap_id: Mapped[Optional[int]] = mapped_column(ForeignKey("laps.id", ondelete="SET NULL"))
    model_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    section_key: Mapped[Optional[str]] = mapped_column(String(128))
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    driver_baseline: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class RecommendationOutcome(TimestampMixin, Base):
    __tablename__ = "recommendation_outcomes"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class RecommendationRating(TimestampMixin, Base):
    __tablename__ = "recommendation_ratings"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    helpful: Mapped[Optional[bool]] = mapped_column(Boolean)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
