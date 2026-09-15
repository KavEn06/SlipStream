from __future__ import annotations

from functools import lru_cache
import math
from typing import Any, Dict, List, Mapping, Optional, Protocol

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.core.config import get_settings
from src.core.schemas import PROCESSED_LAP_COLUMNS, RAW_LAP_COLUMNS, SCHEMA_VERSION
from src.core.telemetry import ProcessedTelemetryContract
from src.db import models
from src.db.repositories import (
    AnalysisRepository,
    CatalogRepository,
    ModelRepository,
    RecommendationRepository,
    SessionRepository,
    TelemetryRepository,
)
from src.db.session import create_database_engine, create_session_factory, session_scope


class TelemetryDatastore(Protocol):
    def list_sessions(self) -> List[Dict[str, Any]]: ...
    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def get_lap_number_mapping(self, session_id: str) -> Dict[str, Dict[int, int]]: ...
    def get_processing_metadata(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def has_raw_session(self, session_id: str) -> bool: ...
    def load_raw_lap(self, session_id: str, lap_number: int, display_number: bool = False) -> Optional[pd.DataFrame]: ...
    def load_processed_lap(
        self, session_id: str, lap_number: int, display_number: bool = False
    ) -> Optional[pd.DataFrame]: ...
    def persist_processed_laps(
        self,
        session_id: str,
        laps: Mapping[int, pd.DataFrame],
        processed_metadata: Mapping[str, Any],
        processing_version: str,
    ) -> int: ...
    def persist_analysis(
        self,
        session_id: str,
        analysis_version: str,
        payload: Mapping[str, Any],
        findings: List[Mapping[str, Any]],
    ) -> int: ...
    def get_latest_analysis(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def get_session_conditions(self, session_id: str) -> Dict[str, Any]: ...
    def update_session_conditions(
        self, session_id: str, conditions: Mapping[str, Any]
    ) -> Optional[Dict[str, Any]]: ...
    def get_model_health(self) -> Dict[str, Any]: ...
    def get_data_health(self) -> Dict[str, Any]: ...


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _display_mapping(lap_numbers: List[int]) -> Dict[str, Dict[int, int]]:
    stored = sorted(set(int(number) for number in lap_numbers))
    offset = 1 if 0 in stored else 0
    stored_to_display = {number: number + offset for number in stored}
    return {
        "stored_to_display": stored_to_display,
        "display_to_stored": {display: number for number, display in stored_to_display.items()},
    }


def _integer_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class SQLAlchemyTelemetryStore:
    """Database-backed service boundary used by processing, analysis, and API reads."""

    def __init__(self, factory: sessionmaker):
        self.factory = factory

    def list_sessions(self) -> List[Dict[str, Any]]:
        with session_scope(self.factory) as database_session:
            rows = SessionRepository(database_session).list_all()
            external_ids = list(dict.fromkeys(row.external_id for row in rows))
        details = [self.get_session_detail(external_id) for external_id in external_ids]
        return [self._summary(detail) for detail in details if detail is not None]

    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            telemetry = TelemetryRepository(database_session)
            catalog = CatalogRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return None
            laps = sessions.list_laps(row.id)
            track = catalog.get_track(row.track_id)
            car = catalog.get_car(row.car_id)
            metadata = self._metadata(row)
            mapping = _display_mapping([lap.lap_number for lap in laps])
            lap_details = []
            has_any_processed = False
            for lap in laps:
                has_raw = telemetry.has_raw_for_lap(lap.id)
                has_processed = telemetry.has_processed_for_lap(lap.id)
                has_any_processed = has_any_processed or has_processed
                lap_details.append(
                    {
                        "lap_number": mapping["stored_to_display"][lap.lap_number],
                        "has_raw": has_raw,
                        "has_processed": has_processed,
                        "lap_time_s": lap.duration_s,
                        "is_valid": lap.is_valid if has_processed else None,
                    }
                )
            created_at = row.started_at or row.created_at
            return {
                "session_id": row.external_id,
                "display_name": row.display_name or metadata.get("display_name"),
                "created_at_utc": created_at.isoformat() if created_at is not None else None,
                "sim": row.simulator,
                "track_circuit": track.circuit if track is not None else metadata.get("track_circuit"),
                "track_layout": track.layout if track is not None else metadata.get("track_layout"),
                "track_location": track.location if track is not None else metadata.get("track_location"),
                "track_length_m": track.length_m if track is not None else metadata.get("track_length_m"),
                "car_ordinal": _integer_or_none(car.external_id) if car is not None else metadata.get("car_ordinal"),
                "total_laps": len(laps),
                "has_processed": has_any_processed,
                "schema_version": metadata.get("schema_version"),
                "processed_schema_version": metadata.get("processed_schema_version"),
                "notes": row.notes or metadata.get("notes", ""),
                "laps": lap_details,
            }

    def get_lap_number_mapping(self, session_id: str) -> Dict[str, Dict[int, int]]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return {"stored_to_display": {}, "display_to_stored": {}}
            return _display_mapping([lap.lap_number for lap in sessions.list_laps(row.id)])

    def get_processing_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            catalog = CatalogRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return None
            metadata = self._metadata(row)
            source_lap_index = metadata.get("lap_index")
            if not isinstance(source_lap_index, dict):
                source_lap_index = {}
            track = catalog.get_track(row.track_id)
            car = catalog.get_car(row.car_id)
            laps = sessions.list_laps(row.id)
            metadata.update(
                {
                    "session_id": row.external_id,
                    "display_name": row.display_name or metadata.get("display_name"),
                    "sim": row.simulator,
                    "track_circuit": track.circuit if track is not None else metadata.get("track_circuit"),
                    "track_layout": track.layout if track is not None else metadata.get("track_layout"),
                    "track_location": track.location if track is not None else metadata.get("track_location"),
                    "track_length_m": track.length_m if track is not None else metadata.get("track_length_m"),
                    "car_ordinal": _integer_or_none(car.external_id) if car is not None else metadata.get("car_ordinal"),
                    "total_laps": len(laps),
                    "lap_index": {
                        str(lap.lap_number): {
                            "close_reason": (lap.quality or {}).get("close_reason")
                            or (
                                source_lap_index.get(str(lap.lap_number), {}).get("close_reason")
                                if isinstance(source_lap_index.get(str(lap.lap_number)), dict)
                                else None
                            ),
                            "first_timestamp_ms": (
                                lap.started_native_ns // 1_000_000
                                if lap.started_native_ns is not None
                                else None
                            ),
                            "last_timestamp_ms": (
                                lap.ended_native_ns // 1_000_000
                                if lap.ended_native_ns is not None
                                else None
                            ),
                        }
                        for lap in laps
                    },
                }
            )
            return metadata

    def has_raw_session(self, session_id: str) -> bool:
        detail = self.get_session_detail(session_id)
        return bool(detail and any(lap["has_raw"] for lap in detail["laps"]))

    def load_raw_lap(
        self,
        session_id: str,
        lap_number: int,
        display_number: bool = False,
    ) -> Optional[pd.DataFrame]:
        with session_scope(self.factory) as database_session:
            resolved = self._resolve_lap(database_session, session_id, lap_number, display_number)
            if resolved is None:
                return None
            session_row, lap = resolved
            samples = TelemetryRepository(database_session).list_raw_for_lap(lap.id)
            if not samples:
                return None
            catalog = CatalogRepository(database_session)
            track = catalog.get_track(session_row.track_id)
            car = catalog.get_car(session_row.car_id)
            first_ns = samples[0].native_timestamp_ns
            rows = []
            for sample in samples:
                additional = dict(sample.additional_fields or {})
                elapsed_s = (sample.native_timestamp_ns - first_ns) / 1e9
                rows.append(
                    {
                        "IsRaceOn": 1,
                        "TimestampMS": int(sample.native_timestamp_ns // 1_000_000),
                        "EngineMaxRpm": additional.get("engine_max_rpm", 0.0),
                        "EngineIdleRpm": additional.get("engine_idle_rpm", 0.0),
                        "CurrentEngineRpm": sample.engine_rpm or 0.0,
                        "CarOrdinal": _integer_or_none(car.external_id) if car is not None else 0,
                        "PositionX": sample.position_x_m,
                        "PositionY": sample.position_y_m if sample.position_y_m is not None else 0.0,
                        "PositionZ": sample.position_z_m,
                        "Speed": sample.speed_mps or 0.0,
                        "Power": sample.power_w or 0.0,
                        "Torque": sample.torque_nm or 0.0,
                        "Boost": sample.boost_bar or 0.0,
                        "DistanceTraveled": additional.get("distance_traveled_m", 0.0),
                        "BestLap": additional.get("best_lap_time_s", 0.0),
                        "LastLap": additional.get("last_lap_time_s", lap.duration_s or 0.0),
                        "CurrentLap": additional.get("current_lap_time_s", elapsed_s),
                        "CurrentRaceTime": additional.get("current_race_time_s", elapsed_s),
                        "LapNumber": lap.lap_number,
                        "Accel": round((sample.throttle or 0.0) * 255.0),
                        "Brake": round((sample.brake or 0.0) * 255.0),
                        "Clutch": round((sample.clutch or 0.0) * 255.0),
                        "HandBrake": round(float(additional.get("hand_brake") or 0.0) * 255.0),
                        "Gear": sample.gear or 0,
                        "Steer": round((sample.steering or 0.0) * 127.0),
                        "TrackOrdinal": _integer_or_none(track.external_id) if track is not None else 0,
                    }
                )
            return pd.DataFrame(rows, columns=RAW_LAP_COLUMNS)

    def load_processed_lap(
        self,
        session_id: str,
        lap_number: int,
        display_number: bool = False,
    ) -> Optional[pd.DataFrame]:
        with session_scope(self.factory) as database_session:
            resolved = self._resolve_lap(database_session, session_id, lap_number, display_number)
            if resolved is None:
                return None
            _, lap = resolved
            samples = TelemetryRepository(database_session).list_processed_for_lap(lap.id)
            if not samples:
                return None
            records = []
            for sample in samples:
                record = dict(sample.features or {})
                record.update(
                    {
                        "SampleIndex": sample.sample_index,
                        "TrackProgressNorm": sample.progress,
                        "TrackProgressM": sample.distance_m,
                        "ElapsedTimeS": sample.elapsed_s,
                        "SpeedMps": sample.speed_mps,
                        "SpeedKph": sample.speed_mps * 3.6 if sample.speed_mps is not None else None,
                        "Throttle": sample.throttle,
                        "Brake": sample.brake,
                        "Steering": sample.steering,
                        "Gear": sample.gear,
                        "EngineRpm": sample.engine_rpm,
                        "LapNumber": lap.lap_number,
                        "LapTimeS": lap.duration_s,
                        "LapIsValid": int(lap.is_valid) if lap.is_valid is not None else None,
                    }
                )
                records.append(record)
            frame = pd.DataFrame(records)
            for column in PROCESSED_LAP_COLUMNS:
                if column not in frame.columns:
                    frame[column] = None
            return frame[PROCESSED_LAP_COLUMNS]

    def persist_processed_laps(
        self,
        session_id: str,
        laps: Mapping[int, pd.DataFrame],
        processed_metadata: Mapping[str, Any],
        processing_version: str = SCHEMA_VERSION,
    ) -> int:
        written = 0
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            telemetry = TelemetryRepository(database_session)
            session_row = sessions.get_by_external_id_any(session_id)
            if session_row is None:
                raise KeyError("Database session not found: {0}".format(session_id))
            for lap_number, frame in laps.items():
                lap = sessions.get_lap_by_number(session_row.id, int(lap_number))
                if lap is None:
                    raise KeyError("Database lap not found: {0}/{1}".format(session_id, lap_number))
                contracts = [self._processed_contract(row, index) for index, row in enumerate(frame.to_dict("records"))]
                telemetry.replace_processed(
                    lap.id,
                    processing_version,
                    contracts,
                    batch_size=get_settings().import_batch_size,
                )
                lap.duration_s = self._last_number(frame, "LapTimeS")
                lap.is_valid = self._last_bool(frame, "LapIsValid")
                lap.status = "processed"
                lap.sample_count = max(lap.sample_count, len(frame))
                written += len(frame)
            provenance = dict(session_row.provenance or {})
            provenance["processed_metadata"] = dict(processed_metadata)
            session_row.provenance = provenance
        return written

    def update_session_metadata(self, session_id: str, display_name: Optional[str]) -> bool:
        with session_scope(self.factory) as database_session:
            return SessionRepository(database_session).update_metadata(session_id, display_name) > 0

    def delete_session(self, session_id: str) -> bool:
        with session_scope(self.factory) as database_session:
            return SessionRepository(database_session).delete_by_external_id(session_id) > 0

    def delete_lap(self, session_id: str, display_lap_number: int) -> bool:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            rows = sessions.list_by_external_id(session_id)
            deleted = False
            for row in rows:
                mapping = _display_mapping([lap.lap_number for lap in sessions.list_laps(row.id)])
                stored = mapping["display_to_stored"].get(display_lap_number)
                if stored is not None:
                    deleted = sessions.delete_lap_by_number(row.id, stored) or deleted
            return deleted

    def persist_analysis(
        self,
        session_id: str,
        analysis_version: str,
        payload: Mapping[str, Any],
        findings: List[Mapping[str, Any]],
    ) -> int:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            session_row = sessions.get_by_external_id_any(session_id)
            if session_row is None:
                raise KeyError("Database session not found: {0}".format(session_id))
            analysis = AnalysisRepository(database_session)
            run = analysis.create_run(
                session_id=session_row.id,
                analysis_version=analysis_version,
                configuration={
                    "detectors": dict(payload.get("detector_configuration") or {}),
                    "ml_model": dict(
                        (payload.get("ml_context") or {}).get("model") or {}
                    ),
                },
                quality_report=payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {},
                result_payload=payload,
                status="completed",
            )
            laps_by_number = {lap.lap_number: lap for lap in sessions.list_laps(session_row.id)}
            for finding in findings:
                lap = laps_by_number.get(_integer_or_none(finding.get("lap_number")))
                analysis.upsert_finding(
                    analysis_run_id=run.id,
                    finding_key=str(finding.get("finding_id")),
                    detector=str(finding.get("detector") or "unknown"),
                    category=str(finding.get("severity") or "unknown"),
                    payload=finding,
                    lap_id=lap.id if lap is not None else None,
                    section_key=str(finding.get("corner_id")) if finding.get("corner_id") is not None else None,
                    confidence=float(finding["confidence"]) if finding.get("confidence") is not None else None,
                )
            ml_context = (
                dict(payload.get("ml_context") or {})
                if isinstance(payload.get("ml_context"), Mapping)
                else {}
            )
            model_context = (
                dict(ml_context.get("model") or {})
                if isinstance(ml_context.get("model"), Mapping)
                else {}
            )
            model_version_id = _integer_or_none(model_context.get("id"))
            if model_version_id is not None:
                model_repository = ModelRepository(database_session)
                expected_profiles = ml_context.get("expected_profiles")
                if isinstance(expected_profiles, Mapping):
                    for lap_number_raw, profile in expected_profiles.items():
                        lap_number = _integer_or_none(lap_number_raw)
                        lap = laps_by_number.get(lap_number)
                        if not isinstance(profile, Mapping):
                            continue
                        model_repository.upsert_prediction(
                            model_version_id=model_version_id,
                            profile_key="{0}:lap:{1}".format(
                                session_id, lap_number_raw
                            ),
                            values=profile,
                            session_id=session_row.id,
                            lap_id=lap.id if lap is not None else None,
                            metadata={
                                "purpose": "product-inference",
                                "analysis_run_id": run.id,
                                "advisory": True,
                            },
                        )
                recommendation_repository = RecommendationRepository(
                    database_session
                )
                recommendations = ml_context.get("recommendations")
                if isinstance(recommendations, list):
                    for recommendation in recommendations:
                        if not isinstance(recommendation, Mapping):
                            continue
                        recommendation_id = recommendation.get(
                            "recommendation_id"
                        )
                        if not recommendation_id:
                            continue
                        recommendation_repository.upsert(
                            recommendation_id=str(recommendation_id),
                            analysis_run_id=run.id,
                            hypothesis=str(
                                recommendation.get("hypothesis")
                                or "Guarded scenario idea"
                            ),
                            payload=recommendation,
                            model_version_id=model_version_id,
                            section_key=(
                                str(recommendation.get("section_key"))
                                if recommendation.get("section_key") is not None
                                else None
                            ),
                            driver_baseline=(
                                recommendation.get("driver_baseline")
                                if isinstance(
                                    recommendation.get("driver_baseline"),
                                    Mapping,
                                )
                                else {}
                            ),
                        )
            return run.id

    def get_latest_analysis(self, session_id: str) -> Optional[Dict[str, Any]]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return None
            run = AnalysisRepository(database_session).latest_for_session(row.id)
            return dict(run.result_payload) if run is not None and run.result_payload else None

    def get_session_conditions(self, session_id: str) -> Dict[str, Any]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return {}
            resolved = dict(row.conditions or {})
            condition_rows = list(
                database_session.scalars(
                    select(models.Condition)
                    .where(models.Condition.session_id == row.id)
                    .order_by(models.Condition.id)
                ).all()
            )
            origin_priority = {"observed": 0, "inferred": 1, "manual": 2}
            condition_rows.sort(
                key=lambda value: (
                    origin_priority.get(str(value.origin), 1),
                    int(value.id),
                )
            )
            for condition in condition_rows:
                if condition.lap_id is not None:
                    continue
                value = dict(condition.value or {})
                resolved[str(condition.kind)] = value.get("value", value)
            return resolved

    def update_session_conditions(
        self,
        session_id: str,
        conditions: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        with session_scope(self.factory) as database_session:
            sessions = SessionRepository(database_session)
            row = sessions.get_by_external_id_any(session_id)
            if row is None:
                return None
            merged = dict(row.conditions or {})
            for kind, value in conditions.items():
                merged[str(kind)] = value
                existing = database_session.scalar(
                    select(models.Condition)
                    .where(
                        models.Condition.session_id == row.id,
                        models.Condition.lap_id.is_(None),
                        models.Condition.origin == "manual",
                        models.Condition.kind == str(kind),
                    )
                    .order_by(models.Condition.id.desc())
                    .limit(1)
                )
                payload = {"value": value}
                if existing is None:
                    sessions.add_condition(
                        row.id,
                        scope="session",
                        origin="manual",
                        kind=str(kind),
                        value=payload,
                    )
                else:
                    existing.value = payload
            row.conditions = merged
        return self.get_session_conditions(session_id)

    def get_model_health(self) -> Dict[str, Any]:
        with session_scope(self.factory) as database_session:
            versions = list(
                database_session.scalars(
                    select(models.ModelVersion).order_by(
                        models.ModelVersion.created_at.desc(),
                        models.ModelVersion.id.desc(),
                    )
                ).all()
            )
            metrics = list(
                database_session.scalars(
                    select(models.ModelMetric).order_by(models.ModelMetric.id)
                ).all()
            )
            metrics_by_version: Dict[int, List[Dict[str, Any]]] = {}
            for metric in metrics:
                metrics_by_version.setdefault(int(metric.model_version_id), []).append(
                    {
                        "split": str(metric.split),
                        "name": str(metric.name),
                        "value": float(metric.value),
                    }
                )
            fallback_reasons: List[str] = []
            champions = [row for row in versions if row.status == "champion"]
            if not champions:
                fallback_reasons.append("no_registered_champion")
            elif not champions[0].artifact_uri or not champions[0].checksum:
                fallback_reasons.append("champion_artifact_metadata_incomplete")
            return {
                "status": "ready" if not fallback_reasons else "fallback",
                "champion": (
                    self._model_health_row(champions[0], metrics_by_version)
                    if champions
                    else None
                ),
                "challengers": [
                    self._model_health_row(row, metrics_by_version)
                    for row in versions
                    if row.status != "champion"
                ],
                "fallback_reasons": fallback_reasons,
            }

    def get_data_health(self) -> Dict[str, Any]:
        with session_scope(self.factory) as database_session:
            raw_rows = int(
                database_session.scalar(
                    select(func.count()).select_from(models.RawTelemetrySample)
                )
                or 0
            )
            processed_rows = int(
                database_session.scalar(
                    select(func.count()).select_from(
                        models.ProcessedTelemetrySample
                    )
                )
                or 0
            )
            effective_laps = int(
                database_session.scalar(
                    select(
                        func.count(
                            func.distinct(models.ProcessedTelemetrySample.lap_id)
                        )
                    )
                    .select_from(models.ProcessedTelemetrySample)
                    .join(
                        models.Lap,
                        models.ProcessedTelemetrySample.lap_id == models.Lap.id,
                    )
                    .where(models.Lap.is_valid.is_(True))
                )
                or 0
            )
            sources = list(
                database_session.scalars(
                    select(models.DataSource).order_by(models.DataSource.id)
                ).all()
            )
            import_runs = list(
                database_session.scalars(
                    select(models.ImportRun).order_by(
                        models.ImportRun.created_at.desc(),
                        models.ImportRun.id.desc(),
                    )
                ).all()
            )
            return {
                "row_count": {
                    "raw": raw_rows,
                    "processed": processed_rows,
                    "total": raw_rows + processed_rows,
                },
                "effective_laps": effective_laps,
                "source_imports": [
                    {
                        "source_id": int(source.id),
                        "key": str(source.key),
                        "kind": str(source.kind),
                        "simulator": str(source.simulator),
                        "revision": source.revision,
                        "imports": [
                            {
                                "import_key": str(import_run.import_key),
                                "status": str(import_run.status),
                                "rows_seen": int(import_run.rows_seen),
                                "rows_inserted": int(import_run.rows_inserted),
                                "rows_updated": int(import_run.rows_updated),
                                "error": import_run.error,
                            }
                            for import_run in import_runs
                            if import_run.data_source_id == source.id
                        ],
                    }
                    for source in sources
                ],
                "fallback_reasons": (
                    [] if effective_laps > 0 else ["no_effective_processed_laps"]
                ),
            }

    @staticmethod
    def _model_health_row(
        row: models.ModelVersion,
        metrics_by_version: Mapping[int, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "name": str(row.name),
            "version": str(row.version),
            "family": str(row.model_type),
            "status": str(row.status),
            "metrics": list(metrics_by_version.get(int(row.id), [])),
            "compatibility": dict(row.compatibility or {}),
            "source_revisions": dict(row.source_revisions or {}),
        }

    @staticmethod
    def _metadata(row: models.TelemetrySession) -> Dict[str, Any]:
        provenance = dict(row.provenance or {})
        metadata: Dict[str, Any] = {}
        for key in ("artifact_metadata", "live_capture_metadata", "processed_metadata"):
            value = provenance.get(key)
            if isinstance(value, dict):
                metadata.update(value)
        return metadata

    @staticmethod
    def _summary(detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "session_id": detail["session_id"],
            "display_name": detail.get("display_name"),
            "created_at_utc": detail.get("created_at_utc"),
            "track_circuit": detail.get("track_circuit"),
            "track_layout": detail.get("track_layout"),
            "track_location": detail.get("track_location"),
            "car_ordinal": detail.get("car_ordinal"),
            "total_laps": detail.get("total_laps", 0),
            "has_processed": detail.get("has_processed", False),
        }

    @staticmethod
    def _resolve_lap(database_session, session_id: str, lap_number: int, display_number: bool):
        sessions = SessionRepository(database_session)
        row = sessions.get_by_external_id_any(session_id)
        if row is None:
            return None
        resolved_number = lap_number
        if display_number:
            mapping = _display_mapping([lap.lap_number for lap in sessions.list_laps(row.id)])
            resolved_number = mapping["display_to_stored"].get(lap_number)
            if resolved_number is None:
                return None
        lap = sessions.get_lap_by_number(row.id, int(resolved_number))
        return (row, lap) if lap is not None else None

    @staticmethod
    def _processed_contract(row: Mapping[str, Any], fallback_index: int) -> ProcessedTelemetryContract:
        features = {str(key): _json_value(value) for key, value in row.items()}
        sample_index = _integer_or_none(row.get("SampleIndex"))
        progress = row.get("TrackProgressNorm")
        if progress is None or pd.isna(progress):
            progress = row.get("NormalizedDistance", 0.0)
        distance = row.get("TrackProgressM")
        if distance is None or pd.isna(distance):
            distance = row.get("CumulativeDistanceM")
        return ProcessedTelemetryContract(
            sample_index=sample_index if sample_index is not None else fallback_index,
            progress=float(progress or 0.0),
            elapsed_s=float(row.get("ElapsedTimeS") or 0.0),
            distance_m=float(distance) if distance is not None and not pd.isna(distance) else None,
            speed_mps=float(row["SpeedMps"]) if row.get("SpeedMps") is not None and not pd.isna(row["SpeedMps"]) else None,
            throttle=float(row["Throttle"]) if row.get("Throttle") is not None and not pd.isna(row["Throttle"]) else None,
            brake=float(row["Brake"]) if row.get("Brake") is not None and not pd.isna(row["Brake"]) else None,
            steering=float(row["Steering"]) if row.get("Steering") is not None and not pd.isna(row["Steering"]) else None,
            gear=_integer_or_none(row.get("Gear")),
            engine_rpm=float(row["EngineRpm"]) if row.get("EngineRpm") is not None and not pd.isna(row["EngineRpm"]) else None,
            features=features,
        )

    @staticmethod
    def _last_number(frame: pd.DataFrame, column: str) -> Optional[float]:
        if column not in frame.columns:
            return None
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(values.iloc[-1]) if not values.empty else None

    @classmethod
    def _last_bool(cls, frame: pd.DataFrame, column: str) -> Optional[bool]:
        value = cls._last_number(frame, column)
        return bool(int(value)) if value is not None else None


@lru_cache(maxsize=1)
def get_default_telemetry_store() -> Optional[SQLAlchemyTelemetryStore]:
    settings = get_settings()
    try:
        engine = create_database_engine(settings.database_url)
        return SQLAlchemyTelemetryStore(create_session_factory(engine))
    except Exception:
        return None
