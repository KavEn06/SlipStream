from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.core.telemetry import (
    CanonicalTelemetrySample,
    DataSourceContract,
    LapContract,
    ModelVersionContract,
    ProcessedTelemetryContract,
    SessionContract,
)
from src.db import models


@dataclass(frozen=True)
class UpsertResult:
    rows_seen: int
    rows_inserted: int
    rows_updated: int


def _record(value: Any) -> Dict[str, Any]:
    if is_dataclass(value):
        return dict(asdict(value))
    return dict(value)


def _record_batches(items: Iterable[Any], size: int) -> Iterator[List[Dict[str, Any]]]:
    """Yield bounded record batches without materializing the input iterable."""

    if size <= 0:
        raise ValueError("batch_size must be positive")
    batch: List[Dict[str, Any]] = []
    for item in items:
        batch.append(_record(item))
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _upsert_statement(
    session: Session,
    model: Any,
    conflict_columns: Iterable[str],
    update_columns: Iterable[str],
    preserve_on_null: Iterable[str] = (),
) -> Any:
    """Build the native set-based upsert used by supported database targets."""

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise NotImplementedError(
            "Bulk upsert supports PostgreSQL and SQLite, not {0}".format(dialect)
        )
    statement = insert(model)
    preserve = set(preserve_on_null)
    return statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_={
            column: (
                func.coalesce(
                    getattr(statement.excluded, column),
                    getattr(model, column),
                )
                if column in preserve
                else getattr(statement.excluded, column)
            )
            for column in update_columns
        },
    )


def _set_columns(instance: Any, values: Mapping[str, Any], allowed: Iterable[str]) -> None:
    for name in allowed:
        if name in values:
            setattr(instance, name, values[name])


class DataSourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, source: DataSourceContract) -> models.DataSource:
        row = self.session.scalar(select(models.DataSource).where(models.DataSource.key == source.key))
        values = _record(source)
        if row is None:
            row = models.DataSource(**values)
            self.session.add(row)
        else:
            _set_columns(
                row,
                values,
                ("kind", "simulator", "provider", "dataset_name", "source_url", "revision", "license", "provenance"),
            )
        self.session.flush()
        return row

    def get_by_key(self, key: str) -> Optional[models.DataSource]:
        return self.session.scalar(select(models.DataSource).where(models.DataSource.key == key))

    def start_import(self, data_source_id: int, import_key: str) -> models.ImportRun:
        row = self.session.scalar(
            select(models.ImportRun).where(
                models.ImportRun.data_source_id == data_source_id,
                models.ImportRun.import_key == import_key,
            )
        )
        if row is None:
            row = models.ImportRun(data_source_id=data_source_id, import_key=import_key)
            self.session.add(row)
        else:
            row.status = "running"
            row.error = None
        self.session.flush()
        return row

    def finish_import(
        self,
        import_run: models.ImportRun,
        result: UpsertResult,
        quality_report: Mapping[str, Any],
        status: str = "completed",
        error: Optional[str] = None,
    ) -> models.ImportRun:
        import_run.status = status
        import_run.rows_seen = result.rows_seen
        import_run.rows_inserted = result.rows_inserted
        import_run.rows_updated = result.rows_updated
        import_run.quality_report = dict(quality_report)
        import_run.error = error
        self.session.flush()
        return import_run


class CatalogRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_track(
        self,
        identity_key: str,
        simulator: str,
        circuit: str,
        external_id: Optional[str] = None,
        layout: Optional[str] = None,
        location: Optional[str] = None,
        length_m: Optional[float] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> models.Track:
        row = self.session.scalar(select(models.Track).where(models.Track.identity_key == identity_key))
        values = {
            "simulator": simulator,
            "external_id": external_id,
            "circuit": circuit,
            "layout": layout,
            "location": location,
            "length_m": length_m,
            "metadata_json": dict(metadata or {}),
        }
        if row is None:
            row = models.Track(identity_key=identity_key, **values)
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row

    def upsert_car(
        self,
        identity_key: str,
        simulator: str,
        model: str,
        external_id: Optional[str] = None,
        make: Optional[str] = None,
        car_class: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> models.Car:
        row = self.session.scalar(select(models.Car).where(models.Car.identity_key == identity_key))
        values = {
            "simulator": simulator,
            "external_id": external_id,
            "make": make,
            "model": model,
            "car_class": car_class,
            "metadata_json": dict(metadata or {}),
        }
        if row is None:
            row = models.Car(identity_key=identity_key, **values)
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row

    def get_track(self, track_id: Optional[int]) -> Optional[models.Track]:
        return self.session.get(models.Track, track_id) if track_id is not None else None

    def get_car(self, car_id: Optional[int]) -> Optional[models.Car]:
        return self.session.get(models.Car, car_id) if car_id is not None else None


class SessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_session(
        self,
        data_source_id: int,
        contract: SessionContract,
        track_id: Optional[int] = None,
        car_id: Optional[int] = None,
    ) -> models.TelemetrySession:
        row = self.session.scalar(
            select(models.TelemetrySession).where(
                models.TelemetrySession.data_source_id == data_source_id,
                models.TelemetrySession.external_id == contract.external_id,
            )
        )
        values = {
            "simulator": contract.simulator,
            "sampling_hz": contract.sampling_hz,
            "started_at": contract.started_at,
            "track_id": track_id,
            "car_id": car_id,
            "conditions": dict(contract.conditions),
            "provenance": dict(contract.provenance),
        }
        if row is None:
            row = models.TelemetrySession(
                data_source_id=data_source_id,
                external_id=contract.external_id,
                **values,
            )
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row

    def get_by_external_id(self, data_source_id: int, external_id: str) -> Optional[models.TelemetrySession]:
        return self.session.scalar(
            select(models.TelemetrySession).where(
                models.TelemetrySession.data_source_id == data_source_id,
                models.TelemetrySession.external_id == external_id,
            )
        )

    def list_all(self) -> List[models.TelemetrySession]:
        return list(
            self.session.scalars(
                select(models.TelemetrySession).order_by(
                    models.TelemetrySession.started_at.desc(),
                    models.TelemetrySession.created_at.desc(),
                    models.TelemetrySession.id.desc(),
                )
            ).all()
        )

    def list_by_external_id(self, external_id: str) -> List[models.TelemetrySession]:
        return list(
            self.session.scalars(
                select(models.TelemetrySession)
                .where(models.TelemetrySession.external_id == external_id)
                .order_by(models.TelemetrySession.updated_at.desc(), models.TelemetrySession.id.desc())
            ).all()
        )

    def get_by_external_id_any(self, external_id: str) -> Optional[models.TelemetrySession]:
        rows = self.list_by_external_id(external_id)
        return rows[0] if rows else None

    def update_metadata(
        self,
        external_id: str,
        display_name: Optional[str],
    ) -> int:
        rows = self.list_by_external_id(external_id)
        for row in rows:
            row.display_name = display_name
        self.session.flush()
        return len(rows)

    def delete_by_external_id(self, external_id: str) -> int:
        rows = self.list_by_external_id(external_id)
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)

    def list_laps(self, session_id: int) -> List[models.Lap]:
        return list(
            self.session.scalars(
                select(models.Lap)
                .where(models.Lap.session_id == session_id)
                .order_by(models.Lap.lap_number, models.Lap.id)
            ).all()
        )

    def get_lap_by_number(self, session_id: int, lap_number: int) -> Optional[models.Lap]:
        return self.session.scalar(
            select(models.Lap)
            .where(models.Lap.session_id == session_id, models.Lap.lap_number == lap_number)
            .order_by(models.Lap.id)
            .limit(1)
        )

    def delete_lap_by_number(self, session_id: int, lap_number: int) -> bool:
        row = self.get_lap_by_number(session_id, lap_number)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def upsert_lap(self, session_id: int, contract: LapContract) -> models.Lap:
        row = self.session.scalar(
            select(models.Lap).where(
                models.Lap.session_id == session_id,
                models.Lap.source_lap_key == contract.source_lap_key,
            )
        )
        values = _record(contract)
        if row is None:
            row = models.Lap(session_id=session_id, **values)
            self.session.add(row)
        else:
            _set_columns(
                row,
                values,
                (
                    "lap_number",
                    "started_native_ns",
                    "ended_native_ns",
                    "duration_s",
                    "is_valid",
                    "status",
                    "quality",
                ),
            )
        self.session.flush()
        return row

    def set_lap_sample_count(self, lap_id: int, sample_count: int) -> None:
        row = self.session.get(models.Lap, lap_id)
        if row is None:
            raise KeyError("Unknown lap id: {0}".format(lap_id))
        row.sample_count = sample_count
        self.session.flush()

    def add_condition(
        self,
        session_id: int,
        scope: str,
        origin: str,
        kind: str,
        value: Mapping[str, Any],
        lap_id: Optional[int] = None,
    ) -> models.Condition:
        row = models.Condition(
            session_id=session_id,
            lap_id=lap_id,
            scope=scope,
            origin=origin,
            kind=kind,
            value=dict(value),
        )
        self.session.add(row)
        self.session.flush()
        return row


class TelemetryRepository:
    RAW_COLUMNS = (
        "native_timestamp_ns",
        "sample_index",
        "simulator",
        "lap_id",
        "position_x_m",
        "position_y_m",
        "position_z_m",
        "speed_mps",
        "throttle",
        "brake",
        "clutch",
        "steering",
        "gear",
        "engine_rpm",
        "heading_rad",
        "lap_progress",
        "completed_laps",
        "longitudinal_accel_mps2",
        "lateral_accel_mps2",
        "yaw_rate_rad_s",
        "power_w",
        "torque_nm",
        "boost_bar",
        "additional_fields",
        "provenance",
    )
    PROCESSED_COLUMNS = (
        "raw_sample_id",
        "sample_index",
        "progress",
        "elapsed_s",
        "distance_m",
        "speed_mps",
        "throttle",
        "brake",
        "steering",
        "gear",
        "engine_rpm",
        "features",
    )

    def __init__(self, session: Session):
        self.session = session

    def bulk_upsert_raw(
        self,
        data_source_id: int,
        session_id: int,
        samples: Iterable[CanonicalTelemetrySample],
        batch_size: int = 5000,
        lap_ids_by_sample_key: Optional[Mapping[str, int]] = None,
        default_lap_id: Optional[int] = None,
    ) -> UpsertResult:
        rows_seen = 0
        operations = 0
        count_statement = (
            select(func.count())
            .select_from(models.RawTelemetrySample)
            .where(models.RawTelemetrySample.data_source_id == data_source_id)
        )
        count_before = int(self.session.scalar(count_statement) or 0)
        statement = _upsert_statement(
            self.session,
            models.RawTelemetrySample,
            ("data_source_id", "source_sample_key"),
            ("session_id",) + self.RAW_COLUMNS,
            preserve_on_null=("lap_id",),
        )
        for batch in _record_batches(samples, batch_size):
            rows_seen += len(batch)
            if lap_ids_by_sample_key:
                for values in batch:
                    values["lap_id"] = lap_ids_by_sample_key.get(
                        str(values["source_sample_key"])
                    )
            elif default_lap_id is not None:
                for values in batch:
                    values["lap_id"] = default_lap_id
            deduplicated = {str(item["source_sample_key"]): item for item in batch}
            payloads = [
                {
                    "data_source_id": data_source_id,
                    "session_id": session_id,
                    "source_sample_key": source_sample_key,
                    **{
                        name: values.get(name)
                        for name in self.RAW_COLUMNS
                    },
                }
                for source_sample_key, values in deduplicated.items()
            ]
            self.session.execute(statement, payloads)
            operations += len(payloads)
            self.session.flush()
        count_after = int(self.session.scalar(count_statement) or 0)
        inserted = max(count_after - count_before, 0)
        return UpsertResult(
            rows_seen=rows_seen,
            rows_inserted=inserted,
            rows_updated=max(operations - inserted, 0),
        )

    def bulk_upsert_processed(
        self,
        lap_id: int,
        processing_version: str,
        samples: Iterable[ProcessedTelemetryContract],
        batch_size: int = 5000,
    ) -> UpsertResult:
        rows_seen = 0
        operations = 0
        count_statement = (
            select(func.count())
            .select_from(models.ProcessedTelemetrySample)
            .where(
                models.ProcessedTelemetrySample.lap_id == lap_id,
                models.ProcessedTelemetrySample.processing_version
                == processing_version,
            )
        )
        count_before = int(self.session.scalar(count_statement) or 0)
        statement = _upsert_statement(
            self.session,
            models.ProcessedTelemetrySample,
            ("lap_id", "processing_version", "sample_index"),
            self.PROCESSED_COLUMNS,
            preserve_on_null=("raw_sample_id",),
        )
        for batch in _record_batches(samples, batch_size):
            rows_seen += len(batch)
            deduplicated = {int(item["sample_index"]): item for item in batch}
            payloads = [
                {
                    "lap_id": lap_id,
                    "processing_version": processing_version,
                    **{
                        name: values.get(name)
                        for name in self.PROCESSED_COLUMNS
                    },
                }
                for _, values in deduplicated.items()
            ]
            self.session.execute(statement, payloads)
            operations += len(payloads)
            self.session.flush()
        count_after = int(self.session.scalar(count_statement) or 0)
        inserted = max(count_after - count_before, 0)
        return UpsertResult(
            rows_seen=rows_seen,
            rows_inserted=inserted,
            rows_updated=max(operations - inserted, 0),
        )

    def replace_processed(
        self,
        lap_id: int,
        processing_version: str,
        samples: Iterable[ProcessedTelemetryContract],
        batch_size: int = 5000,
    ) -> UpsertResult:
        self.session.execute(
            delete(models.ProcessedTelemetrySample).where(
                models.ProcessedTelemetrySample.lap_id == lap_id,
                models.ProcessedTelemetrySample.processing_version == processing_version,
            )
        )
        self.session.flush()
        return self.bulk_upsert_processed(lap_id, processing_version, samples, batch_size=batch_size)

    def list_raw_for_lap(self, lap_id: int) -> List[models.RawTelemetrySample]:
        return list(
            self.session.scalars(
                select(models.RawTelemetrySample)
                .where(models.RawTelemetrySample.lap_id == lap_id)
                .order_by(
                    models.RawTelemetrySample.native_timestamp_ns,
                    models.RawTelemetrySample.sample_index,
                    models.RawTelemetrySample.id,
                )
            ).all()
        )

    def latest_processing_version(self, lap_id: int) -> Optional[str]:
        return self.session.scalar(
            select(models.ProcessedTelemetrySample.processing_version)
            .where(models.ProcessedTelemetrySample.lap_id == lap_id)
            .order_by(models.ProcessedTelemetrySample.id.desc())
            .limit(1)
        )

    def list_processed_for_lap(
        self,
        lap_id: int,
        processing_version: Optional[str] = None,
    ) -> List[models.ProcessedTelemetrySample]:
        version = processing_version or self.latest_processing_version(lap_id)
        if version is None:
            return []
        return list(
            self.session.scalars(
                select(models.ProcessedTelemetrySample)
                .where(
                    models.ProcessedTelemetrySample.lap_id == lap_id,
                    models.ProcessedTelemetrySample.processing_version == version,
                )
                .order_by(
                    models.ProcessedTelemetrySample.sample_index,
                    models.ProcessedTelemetrySample.id,
                )
            ).all()
        )

    def has_raw_for_lap(self, lap_id: int) -> bool:
        count = self.session.scalar(
            select(func.count())
            .select_from(models.RawTelemetrySample)
            .where(models.RawTelemetrySample.lap_id == lap_id)
        )
        return bool(count)

    def has_processed_for_lap(self, lap_id: int) -> bool:
        count = self.session.scalar(
            select(func.count())
            .select_from(models.ProcessedTelemetrySample)
            .where(models.ProcessedTelemetrySample.lap_id == lap_id)
        )
        return bool(count)

    def count_raw(self, data_source_id: Optional[int] = None) -> int:
        statement = select(func.count()).select_from(models.RawTelemetrySample)
        if data_source_id is not None:
            statement = statement.where(models.RawTelemetrySample.data_source_id == data_source_id)
        return int(self.session.scalar(statement) or 0)


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(
        self,
        session_id: int,
        analysis_version: str,
        configuration: Optional[Mapping[str, Any]] = None,
        quality_report: Optional[Mapping[str, Any]] = None,
        result_payload: Optional[Mapping[str, Any]] = None,
        status: str = "running",
    ) -> models.AnalysisRun:
        row = models.AnalysisRun(
            session_id=session_id,
            analysis_version=analysis_version,
            configuration=dict(configuration or {}),
            quality_report=dict(quality_report or {}),
            result_payload=dict(result_payload or {}),
            status=status,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest_for_session(self, session_id: int) -> Optional[models.AnalysisRun]:
        return self.session.scalar(
            select(models.AnalysisRun)
            .where(models.AnalysisRun.session_id == session_id)
            .order_by(models.AnalysisRun.created_at.desc(), models.AnalysisRun.id.desc())
            .limit(1)
        )

    def list_findings(self, analysis_run_id: int) -> List[models.Finding]:
        return list(
            self.session.scalars(
                select(models.Finding)
                .where(models.Finding.analysis_run_id == analysis_run_id)
                .order_by(models.Finding.id)
            ).all()
        )

    def upsert_finding(
        self,
        analysis_run_id: int,
        finding_key: str,
        detector: str,
        category: str,
        payload: Mapping[str, Any],
        lap_id: Optional[int] = None,
        section_key: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> models.Finding:
        row = self.session.scalar(
            select(models.Finding).where(
                models.Finding.analysis_run_id == analysis_run_id,
                models.Finding.finding_key == finding_key,
            )
        )
        values = {
            "detector": detector,
            "category": category,
            "payload": dict(payload),
            "lap_id": lap_id,
            "section_key": section_key,
            "confidence": confidence,
        }
        if row is None:
            row = models.Finding(analysis_run_id=analysis_run_id, finding_key=finding_key, **values)
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row


class RecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        recommendation_id: str,
        analysis_run_id: int,
        hypothesis: str,
        payload: Mapping[str, Any],
        **optional: Any,
    ) -> models.Recommendation:
        row = self.session.get(models.Recommendation, recommendation_id)
        values = {
            "analysis_run_id": analysis_run_id,
            "hypothesis": hypothesis,
            "payload": dict(payload),
            "finding_id": optional.get("finding_id"),
            "lap_id": optional.get("lap_id"),
            "model_version_id": optional.get("model_version_id"),
            "section_key": optional.get("section_key"),
            "driver_baseline": dict(optional.get("driver_baseline") or {}),
        }
        if row is None:
            row = models.Recommendation(id=recommendation_id, **values)
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row

    def add_outcome(
        self, recommendation_id: str, schema_version: str, payload: Mapping[str, Any]
    ) -> models.RecommendationOutcome:
        row = models.RecommendationOutcome(
            recommendation_id=recommendation_id,
            schema_version=schema_version,
            payload=dict(payload),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_rating(
        self,
        recommendation_id: str,
        schema_version: str,
        helpful: Optional[bool] = None,
        reason: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> models.RecommendationRating:
        row = models.RecommendationRating(
            recommendation_id=recommendation_id,
            schema_version=schema_version,
            helpful=helpful,
            reason=reason,
            payload=dict(payload or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row


class ModelRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_version(self, contract: ModelVersionContract, **optional: Any) -> models.ModelVersion:
        row = self.session.scalar(
            select(models.ModelVersion).where(
                models.ModelVersion.name == contract.name,
                models.ModelVersion.version == contract.version,
            )
        )
        values = _record(contract)
        values.update(
            {
                "status": optional.get("status", "challenger"),
                "checksum": optional.get("checksum"),
                "metadata_json": dict(optional.get("metadata") or {}),
            }
        )
        if row is None:
            row = models.ModelVersion(**values)
            self.session.add(row)
        else:
            _set_columns(row, values, values.keys())
        self.session.flush()
        return row

    def upsert_metric(
        self,
        model_version_id: int,
        split: str,
        name: str,
        value: float,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> models.ModelMetric:
        row = self.session.scalar(
            select(models.ModelMetric).where(
                models.ModelMetric.model_version_id == model_version_id,
                models.ModelMetric.split == split,
                models.ModelMetric.name == name,
            )
        )
        if row is None:
            row = models.ModelMetric(
                model_version_id=model_version_id,
                split=split,
                name=name,
                value=value,
                metadata_json=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.value = value
            row.metadata_json = dict(metadata or {})
        self.session.flush()
        return row

    def upsert_prediction(
        self,
        model_version_id: int,
        profile_key: str,
        values: Mapping[str, Any],
        session_id: Optional[int] = None,
        lap_id: Optional[int] = None,
        section_key: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> models.PredictionProfile:
        row = self.session.scalar(
            select(models.PredictionProfile).where(
                models.PredictionProfile.model_version_id == model_version_id,
                models.PredictionProfile.profile_key == profile_key,
            )
        )
        payload = {
            "values": dict(values),
            "session_id": session_id,
            "lap_id": lap_id,
            "section_key": section_key,
            "metadata_json": dict(metadata or {}),
        }
        if row is None:
            row = models.PredictionProfile(
                model_version_id=model_version_id,
                profile_key=profile_key,
                **payload,
            )
            self.session.add(row)
        else:
            _set_columns(row, payload, payload.keys())
        self.session.flush()
        return row
