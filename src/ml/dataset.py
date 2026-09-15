"""Leakage-safe, simulator-neutral datasets for telemetry models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import models


PROFILE_TARGETS = ("throttle", "brake", "steering", "speed_mps")
ACTIONABLE_FEATURES = (
    "brake_onset",
    "min_speed_ratio",
    "throttle_pickup",
    "coasting_fraction",
    "steering_instability",
)
SECTION_MODEL_FEATURES = (
    "section_index",
    "start_progress",
    "end_progress",
    "section_length_fraction",
    "mean_curvature",
    "max_curvature",
    "entry_speed_ratio",
    "apex_speed_ratio",
    "exit_speed_ratio",
    "brake_onset",
    "min_speed_ratio",
    "throttle_pickup",
    "brake_smoothness",
    "throttle_smoothness",
    "coasting_fraction",
    "steering_instability",
    "driver_consistency",
    "wetness",
    "air_temp_c",
    "track_temp_c",
    "tyre_wear",
)
PROFILE_NUMERIC_FEATURES = (
    "progress",
    "progress_sin",
    "progress_cos",
    "section_index",
    "section_progress",
    "curvature_abs",
    "cornerness",
    "track_length_m",
    "wetness",
    "air_temp_c",
    "track_temp_c",
    "tyre_wear",
)
CATEGORICAL_FEATURES = ("simulator", "track_key", "car_key")


@dataclass(frozen=True)
class GroupedSplit:
    train_lap_keys: Tuple[str, ...]
    holdout_lap_keys: Tuple[str, ...]
    train_groups: Tuple[str, ...]
    holdout_groups: Tuple[str, ...]
    group_kind: str
    salt: str


@dataclass
class LapDataset:
    """Three aligned views of the same independent whole-lap examples."""

    sample_frame: pd.DataFrame
    section_frame: pd.DataFrame
    lap_frame: pd.DataFrame
    grid_points: int
    section_count: int
    source_revisions: Mapping[str, str]

    @property
    def lap_keys(self) -> List[str]:
        return self.lap_frame["lap_key"].astype(str).tolist()

    @property
    def effective_lap_count(self) -> int:
        return len(self.lap_frame)

    @property
    def sample_row_count(self) -> int:
        return len(self.sample_frame)

    def subset(self, lap_keys: Iterable[str]) -> "LapDataset":
        selected = set(str(key) for key in lap_keys)
        return LapDataset(
            sample_frame=self.sample_frame[self.sample_frame["lap_key"].isin(selected)].reset_index(drop=True),
            section_frame=self.section_frame[self.section_frame["lap_key"].isin(selected)].reset_index(drop=True),
            lap_frame=self.lap_frame[self.lap_frame["lap_key"].isin(selected)].reset_index(drop=True),
            grid_points=self.grid_points,
            section_count=self.section_count,
            source_revisions=dict(self.source_revisions),
        )

    def validate(self) -> None:
        lap_keys = set(self.lap_keys)
        if not lap_keys:
            raise ValueError("ML dataset contains no complete laps")
        if set(self.sample_frame["lap_key"].astype(str)) != lap_keys:
            raise ValueError("Sample and lap views contain different lap keys")
        if set(self.section_frame["lap_key"].astype(str)) != lap_keys:
            raise ValueError("Section and lap views contain different lap keys")
        sample_counts = self.sample_frame.groupby("lap_key").size()
        section_counts = self.section_frame.groupby("lap_key").size()
        if not (sample_counts == self.grid_points).all():
            raise ValueError("Every lap must have exactly grid_points sample rows")
        if not (section_counts == self.section_count).all():
            raise ValueError("Every lap must have exactly section_count section rows")

    def fingerprint(self) -> str:
        columns = ["lap_key", "session_key", "track_key", "car_key", "lap_time_s"]
        payload = self.lap_frame[columns].sort_values("lap_key").to_dict("records")
        encoded = json.dumps(
            {
                "laps": payload,
                "grid_points": self.grid_points,
                "section_count": self.section_count,
                "source_revisions": dict(sorted(self.source_revisions.items())),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TelemetryDatasetBuilder:
    """Build model views from ORM rows, DataFrames, or processed exports."""

    def __init__(
        self,
        grid_points: int = 64,
        section_count: int = 8,
        valid_only: bool = True,
        minimum_progress_span: float = 0.85,
    ):
        if grid_points < 8:
            raise ValueError("grid_points must be at least 8")
        if section_count < 2 or section_count > grid_points // 2:
            raise ValueError("section_count must be between 2 and grid_points / 2")
        self.grid_points = int(grid_points)
        self.section_count = int(section_count)
        self.valid_only = bool(valid_only)
        self.minimum_progress_span = float(minimum_progress_span)

    def from_database(
        self,
        database_session: Session,
        processing_version: Optional[str] = None,
    ) -> LapDataset:
        statement = (
            select(
                models.ProcessedTelemetrySample,
                models.Lap,
                models.TelemetrySession,
                models.Track,
                models.Car,
                models.DataSource,
            )
            .join(models.Lap, models.ProcessedTelemetrySample.lap_id == models.Lap.id)
            .join(models.TelemetrySession, models.Lap.session_id == models.TelemetrySession.id)
            .outerjoin(models.Track, models.TelemetrySession.track_id == models.Track.id)
            .outerjoin(models.Car, models.TelemetrySession.car_id == models.Car.id)
            .join(models.DataSource, models.TelemetrySession.data_source_id == models.DataSource.id)
            .order_by(
                models.Lap.id,
                models.ProcessedTelemetrySample.processing_version,
                models.ProcessedTelemetrySample.sample_index,
            )
        )
        if processing_version is not None:
            statement = statement.where(models.ProcessedTelemetrySample.processing_version == processing_version)
        if self.valid_only:
            statement = statement.where(models.Lap.is_valid.is_(True))

        grouped: Dict[int, List[Any]] = {}
        for row in database_session.execute(statement).all():
            grouped.setdefault(int(row[1].id), []).append(row)
        session_conditions, lap_conditions = self._database_conditions(database_session)

        frames: Dict[str, pd.DataFrame] = {}
        metadata: Dict[str, Dict[str, Any]] = {}
        revisions: Dict[str, str] = {}
        for lap_id, rows in grouped.items():
            selected_rows = rows
            if processing_version is None:
                versions: Dict[str, List[Any]] = {}
                for row in rows:
                    versions.setdefault(str(row[0].processing_version), []).append(row)
                selected_version = max(
                    versions,
                    key=lambda version: max(int(item[0].id) for item in versions[version]),
                )
                selected_rows = versions[selected_version]

            first = selected_rows[0]
            lap, telemetry_session, track, car, source = first[1], first[2], first[3], first[4], first[5]
            lap_key = "db:{0}".format(lap_id)
            frames[lap_key] = pd.DataFrame([self._database_sample_record(item[0]) for item in selected_rows])
            conditions = dict(telemetry_session.conditions or {})
            conditions.update(session_conditions.get(int(telemetry_session.id), {}))
            conditions.update(lap_conditions.get(int(lap.id), {}))
            metadata[lap_key] = {
                "lap_db_id": int(lap.id),
                "session_db_id": int(telemetry_session.id),
                "session_key": str(telemetry_session.external_id),
                "lap_number": int(lap.lap_number),
                "lap_time_s": lap.duration_s,
                "is_valid": lap.is_valid,
                "simulator": telemetry_session.simulator,
                "track_key": track.identity_key if track is not None else "unknown-track",
                "car_key": car.identity_key if car is not None else "unknown-car",
                "track_length_m": track.length_m if track is not None else None,
                "conditions": conditions,
                "source_key": source.key,
            }
            if source.revision:
                revisions[str(source.key)] = str(source.revision)

        return self.from_processed_laps(frames, metadata=metadata, source_revisions=revisions)

    def from_processed_root(self, processed_root: Path) -> LapDataset:
        frames: Dict[str, pd.DataFrame] = {}
        metadata: Dict[str, Dict[str, Any]] = {}
        for session_dir in sorted(Path(processed_root).glob("*")):
            if not session_dir.is_dir():
                continue
            session_metadata = self._read_json(session_dir / "metadata.json")
            for lap_path in sorted(session_dir.glob("lap_*.csv")):
                lap_key = "{0}:{1}".format(session_dir.name, lap_path.stem)
                frame = pd.read_csv(lap_path)
                frames[lap_key] = frame
                metadata[lap_key] = {
                    "session_key": session_dir.name,
                    "lap_number": self._single_value(frame, "LapNumber"),
                    "lap_time_s": self._single_value(frame, "LapTimeS"),
                    "is_valid": self._single_value(frame, "LapIsValid"),
                    "simulator": session_metadata.get("sim", "unknown-simulator"),
                    "track_key": self._track_key(session_metadata),
                    "car_key": self._car_key(session_metadata),
                    "track_length_m": session_metadata.get("track_length_m"),
                    "conditions": session_metadata.get("conditions", {}),
                    "source_key": "processed-export",
                }
        return self.from_processed_laps(frames, metadata=metadata)

    def from_processed_laps(
        self,
        laps: Mapping[str, pd.DataFrame],
        metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
        source_revisions: Optional[Mapping[str, str]] = None,
    ) -> LapDataset:
        metadata = metadata or {}
        prepared: List[Tuple[Dict[str, Any], pd.DataFrame]] = []
        for supplied_key, frame in laps.items():
            lap_metadata = dict(metadata.get(str(supplied_key), {}))
            normalized = self._normalize_lap(str(supplied_key), frame, lap_metadata)
            if normalized is not None:
                prepared.append(normalized)
        if not prepared:
            raise ValueError("No complete, valid processed laps were available")

        capability_by_car: Dict[str, float] = {}
        for lap_metadata, frame in prepared:
            car_key = str(lap_metadata["car_key"])
            capability = float(np.nanpercentile(frame["speed_mps"], 99))
            capability_by_car[car_key] = max(capability_by_car.get(car_key, 0.0), capability, 1.0)

        consistency = self._session_consistency(prepared)
        sample_frames: List[pd.DataFrame] = []
        section_frames: List[pd.DataFrame] = []
        lap_records: List[Dict[str, Any]] = []
        for lap_metadata, frame in prepared:
            lap_key = str(lap_metadata["lap_key"])
            driver_consistency, lap_consistency = consistency[str(lap_metadata["session_key"])]
            sample_view = self._sample_view(lap_metadata, frame)
            section_view = self._section_view(
                lap_metadata,
                frame,
                capability_by_car[str(lap_metadata["car_key"])],
                driver_consistency,
                lap_consistency,
            )
            sample_frames.append(sample_view)
            section_frames.append(section_view)
            lap_records.append(
                self._lap_record(lap_metadata, section_view, driver_consistency, lap_consistency)
            )

        lap_frame = pd.DataFrame(lap_records)
        weights = self._faster_lap_weights(lap_frame)
        lap_frame["sample_weight"] = lap_frame["lap_key"].map(weights)
        sample_frame = pd.concat(sample_frames, ignore_index=True)
        section_frame = pd.concat(section_frames, ignore_index=True)
        sample_frame["sample_weight"] = sample_frame["lap_key"].map(weights)
        section_frame["sample_weight"] = section_frame["lap_key"].map(weights)

        dataset = LapDataset(
            sample_frame=sample_frame,
            section_frame=section_frame,
            lap_frame=lap_frame,
            grid_points=self.grid_points,
            section_count=self.section_count,
            source_revisions=dict(source_revisions or {}),
        )
        dataset.validate()
        return dataset

    @staticmethod
    def _database_conditions(
        database_session: Session,
    ) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, Dict[str, Any]]]:
        origin_priority = {"observed": 0, "inferred": 1, "manual": 2}
        rows = list(database_session.scalars(select(models.Condition)).all())
        rows.sort(
            key=lambda row: (
                origin_priority.get(str(row.origin), 1),
                int(row.id),
            )
        )
        by_session: Dict[int, Dict[str, Any]] = {}
        by_lap: Dict[int, Dict[str, Any]] = {}
        recognized = {
            "wetness",
            "track_wetness",
            "rain",
            "rain_intensity",
            "air_temp_c",
            "ambient_temp_c",
            "air_temperature",
            "track_temp_c",
            "road_temp_c",
            "track_temperature",
            "tyre_wear",
            "tire_wear",
            "max_tyre_wear",
        }
        for row in rows:
            target = (
                by_lap.setdefault(int(row.lap_id), {})
                if row.lap_id is not None
                else by_session.setdefault(int(row.session_id), {})
            )
            payload = dict(row.value or {})
            target[str(row.kind)] = payload.get("value", payload)
            for key in recognized.intersection(payload):
                target[key] = payload[key]
        return by_session, by_lap

    @staticmethod
    def _database_sample_record(sample: models.ProcessedTelemetrySample) -> Dict[str, Any]:
        record = dict(sample.features or {})
        record.update(
            {
                "SampleIndex": sample.sample_index,
                "TrackProgressNorm": sample.progress,
                "TrackProgressM": sample.distance_m,
                "ElapsedTimeS": sample.elapsed_s,
                "SpeedMps": sample.speed_mps,
                "Throttle": sample.throttle,
                "Brake": sample.brake,
                "Steering": sample.steering,
            }
        )
        return record

    def _normalize_lap(
        self,
        supplied_key: str,
        frame: pd.DataFrame,
        metadata: Mapping[str, Any],
    ) -> Optional[Tuple[Dict[str, Any], pd.DataFrame]]:
        if frame is None or len(frame) < 4:
            return None
        if self.valid_only:
            valid = metadata.get("is_valid", self._single_value(frame, "LapIsValid"))
            if valid is not None and not bool(int(float(valid))):
                return None

        progress = self._numeric(frame, "TrackProgressNorm")
        if progress.isna().all() or float(progress.max() - progress.min()) < self.minimum_progress_span:
            progress = self._numeric(frame, "NormalizedDistance")
        finite_progress = progress.replace([np.inf, -np.inf], np.nan).notna()
        if finite_progress.sum() < 4:
            return None
        source = frame.loc[finite_progress].copy()
        source["_progress"] = progress.loc[finite_progress].clip(0.0, 1.0)
        source = source.sort_values("_progress").drop_duplicates("_progress")
        if len(source) < 4 or float(source["_progress"].iloc[-1] - source["_progress"].iloc[0]) < self.minimum_progress_span:
            return None

        grid = np.linspace(0.0, 1.0, self.grid_points)
        normalized = pd.DataFrame({"progress": grid})
        aliases = {
            "elapsed_s": ("ElapsedTimeS",),
            "speed_mps": ("SpeedMps", "Speed"),
            "throttle": ("Throttle", "Accel"),
            "brake": ("Brake",),
            "steering": ("Steering", "Steer"),
            "distance_m": ("TrackProgressM", "CumulativeDistanceM", "DistanceTraveledM"),
            "position_x": ("PositionX", "position_x_m"),
            "position_z": ("PositionZ", "position_z_m"),
        }
        for target, candidates in aliases.items():
            values = self._first_numeric(source, candidates)
            if target in PROFILE_TARGETS and values.isna().all():
                return None
            normalized[target] = self._interpolate(source["_progress"], values, grid, default=0.0)

        normalized["throttle"] = normalized["throttle"].clip(0.0, 1.0)
        normalized["brake"] = normalized["brake"].clip(0.0, 1.0)
        normalized["steering"] = normalized["steering"].clip(-1.0, 1.0)
        normalized["speed_mps"] = normalized["speed_mps"].clip(lower=0.0)
        lap_time = metadata.get("lap_time_s", self._single_value(frame, "LapTimeS"))
        if lap_time is None or not np.isfinite(float(lap_time)) or float(lap_time) <= 0:
            lap_time = float(normalized["elapsed_s"].iloc[-1] - normalized["elapsed_s"].iloc[0])
        if lap_time <= 0:
            return None
        normalized["elapsed_s"] = (
            normalized["elapsed_s"] - float(normalized["elapsed_s"].iloc[0])
        ).clip(lower=0.0)
        if float(normalized["elapsed_s"].iloc[-1]) <= 0:
            normalized["elapsed_s"] = grid * float(lap_time)

        curvature = self._curvature(normalized["position_x"], normalized["position_z"], normalized["distance_m"])
        normalized["curvature_abs"] = curvature
        high = max(float(np.nanpercentile(curvature, 90)), 1e-6)
        normalized["cornerness"] = np.clip(curvature / high, 0.0, 2.0) / 2.0

        conditions = self._conditions(metadata.get("conditions"))
        track_length = metadata.get("track_length_m")
        if track_length is None or not self._finite_number(track_length):
            track_length = float(np.nanmax(normalized["distance_m"]))
        normalized_metadata = {
            "lap_key": supplied_key,
            "lap_db_id": metadata.get("lap_db_id"),
            "session_db_id": metadata.get("session_db_id"),
            "session_key": str(metadata.get("session_key") or supplied_key.split(":")[0]),
            "lap_number": int(metadata.get("lap_number") or 0),
            "lap_time_s": float(lap_time),
            "simulator": str(metadata.get("simulator") or "unknown-simulator"),
            "track_key": str(metadata.get("track_key") or "unknown-track"),
            "car_key": str(metadata.get("car_key") or "unknown-car"),
            "track_length_m": float(track_length) if self._finite_number(track_length) else 0.0,
            "source_key": str(metadata.get("source_key") or "processed-lap"),
        }
        normalized_metadata.update(conditions)
        return normalized_metadata, normalized

    def _sample_view(self, metadata: Mapping[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
        view = pd.DataFrame(
            {
                "lap_key": metadata["lap_key"],
                "session_key": metadata["session_key"],
                "lap_number": metadata.get("lap_number"),
                "lap_db_id": metadata.get("lap_db_id"),
                "session_db_id": metadata.get("session_db_id"),
                "simulator": metadata["simulator"],
                "track_key": metadata["track_key"],
                "car_key": metadata["car_key"],
                "progress": frame["progress"],
                "progress_sin": np.sin(2.0 * np.pi * frame["progress"]),
                "progress_cos": np.cos(2.0 * np.pi * frame["progress"]),
                "section_index": np.minimum(
                    (frame["progress"] * self.section_count).astype(int), self.section_count - 1
                ),
                "section_progress": (frame["progress"] * self.section_count) % 1.0,
                "curvature_abs": frame["curvature_abs"],
                "cornerness": frame["cornerness"],
                "track_length_m": metadata["track_length_m"],
                "wetness": metadata["wetness"],
                "air_temp_c": metadata["air_temp_c"],
                "track_temp_c": metadata["track_temp_c"],
                "tyre_wear": metadata["tyre_wear"],
                "throttle": frame["throttle"],
                "brake": frame["brake"],
                "steering": frame["steering"],
                "speed_mps": frame["speed_mps"],
            }
        )
        return view

    def _section_view(
        self,
        metadata: Mapping[str, Any],
        frame: pd.DataFrame,
        vehicle_speed_capability: float,
        driver_consistency: float,
        lap_consistency: float,
    ) -> pd.DataFrame:
        section_indices = np.minimum(
            (frame["progress"].to_numpy() * self.section_count).astype(int),
            self.section_count - 1,
        )
        records: List[Dict[str, Any]] = []
        for section_index in range(self.section_count):
            mask = section_indices == section_index
            section = frame.loc[mask].copy()
            if section.empty:
                nearest = min(
                    len(frame) - 1,
                    int(round((section_index + 0.5) * (len(frame) - 1) / self.section_count)),
                )
                section = frame.iloc[[nearest]].copy()
            start_progress = section_index / float(self.section_count)
            end_progress = (section_index + 1) / float(self.section_count)
            local = (section["progress"] - start_progress) / max(end_progress - start_progress, 1e-9)
            midpoint = local >= 0.5
            brake_active = section["brake"] >= 0.10
            throttle_active = (section["throttle"] >= 0.20) & midpoint
            speed_ratio = section["speed_mps"] / max(vehicle_speed_capability, 1.0)
            elapsed = section["elapsed_s"]
            duration = max(float(elapsed.iloc[-1] - elapsed.iloc[0]), 1e-4)
            steering_diff = np.diff(section["steering"].to_numpy(dtype=float))
            steering_instability = float(np.mean(np.abs(steering_diff))) if len(steering_diff) else 0.0
            brake_diff = np.diff(section["brake"].to_numpy(dtype=float))
            throttle_diff = np.diff(section["throttle"].to_numpy(dtype=float))
            coasting = (section["throttle"] <= 0.05) & (section["brake"] <= 0.05)
            records.append(
                {
                    "lap_key": metadata["lap_key"],
                    "session_key": metadata["session_key"],
                    "lap_number": metadata.get("lap_number"),
                    "lap_db_id": metadata.get("lap_db_id"),
                    "session_db_id": metadata.get("session_db_id"),
                    "simulator": metadata["simulator"],
                    "track_key": metadata["track_key"],
                    "car_key": metadata["car_key"],
                    "section_key": "s{0:02d}".format(section_index),
                    "section_index": section_index,
                    "section_phase": self._section_phase(section),
                    "start_progress": start_progress,
                    "end_progress": end_progress,
                    "section_length_fraction": 1.0 / self.section_count,
                    "mean_curvature": float(section["curvature_abs"].mean()),
                    "max_curvature": float(section["curvature_abs"].max()),
                    "entry_speed_ratio": float(speed_ratio.iloc[0]),
                    "min_speed_ratio": float(speed_ratio.min()),
                    "apex_speed_ratio": float(speed_ratio.min()),
                    "exit_speed_ratio": float(speed_ratio.iloc[-1]),
                    "brake_onset": self._first_local_progress(local, brake_active, 1.0),
                    "throttle_pickup": self._first_local_progress(local, throttle_active, 1.0),
                    "brake_smoothness": float(np.mean(np.abs(brake_diff))) if len(brake_diff) else 0.0,
                    "throttle_smoothness": (
                        float(np.mean(np.abs(throttle_diff))) if len(throttle_diff) else 0.0
                    ),
                    "coasting_fraction": float(coasting.mean()),
                    "steering_instability": steering_instability,
                    "mean_brake": float(section["brake"].mean()),
                    "mean_throttle": float(section["throttle"].mean()),
                    "section_time_s": duration,
                    "lap_time_s": metadata["lap_time_s"],
                    "lap_consistency": lap_consistency,
                    "driver_consistency": driver_consistency,
                    "track_length_m": metadata["track_length_m"],
                    "wetness": metadata["wetness"],
                    "air_temp_c": metadata["air_temp_c"],
                    "track_temp_c": metadata["track_temp_c"],
                    "tyre_wear": metadata["tyre_wear"],
                }
            )
        return pd.DataFrame(records)

    def _lap_record(
        self,
        metadata: Mapping[str, Any],
        sections: pd.DataFrame,
        driver_consistency: float,
        lap_consistency: float,
    ) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "lap_key": metadata["lap_key"],
            "session_key": metadata["session_key"],
            "lap_number": metadata.get("lap_number"),
            "lap_db_id": metadata.get("lap_db_id"),
            "session_db_id": metadata.get("session_db_id"),
            "simulator": metadata["simulator"],
            "track_key": metadata["track_key"],
            "car_key": metadata["car_key"],
            "lap_time_s": metadata["lap_time_s"],
            "driver_consistency": driver_consistency,
            "lap_consistency": lap_consistency,
            "track_length_m": metadata["track_length_m"],
            "wetness": metadata["wetness"],
            "air_temp_c": metadata["air_temp_c"],
            "track_temp_c": metadata["track_temp_c"],
            "tyre_wear": metadata["tyre_wear"],
        }
        for feature in ACTIONABLE_FEATURES:
            record["mean_{0}".format(feature)] = float(sections[feature].mean())
        for section_index, section in sections.sort_values("section_index").iterrows():
            resolved_index = int(section["section_index"])
            record["section_time_{0}".format(resolved_index)] = float(section["section_time_s"])
            for feature in ACTIONABLE_FEATURES:
                record["s{0}_{1}".format(resolved_index, feature)] = float(section[feature])
        return record

    @staticmethod
    def _session_consistency(
        prepared: Sequence[Tuple[Mapping[str, Any], pd.DataFrame]]
    ) -> Dict[str, Tuple[float, float]]:
        times: Dict[str, List[float]] = {}
        for metadata, _ in prepared:
            times.setdefault(str(metadata["session_key"]), []).append(float(metadata["lap_time_s"]))
        result: Dict[str, Tuple[float, float]] = {}
        for session_key, values in times.items():
            array = np.asarray(values, dtype=float)
            median = max(float(np.median(array)), 1e-6)
            driver_consistency = float(np.std(array) / median) if len(array) > 1 else 0.0
            for value in values:
                result["{0}:{1:.12g}".format(session_key, value)] = (
                    driver_consistency,
                    abs(float(value) - median) / median,
                )
            result[session_key] = (driver_consistency, float(np.mean(np.abs(array - median)) / median))
        return result

    @staticmethod
    def _faster_lap_weights(lap_frame: pd.DataFrame) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for _, group in lap_frame.groupby(["track_key", "car_key"], dropna=False):
            times = group["lap_time_s"].to_numpy(dtype=float)
            best = max(float(np.min(times)), 1e-6)
            raw = np.exp(-4.0 * np.maximum(times / best - 1.0, 0.0))
            raw = np.clip(raw, 0.35, 1.0)
            normalized = raw / max(float(np.mean(raw)), 1e-9)
            for lap_key, weight in zip(group["lap_key"], normalized):
                weights[str(lap_key)] = float(weight)
        return weights

    @staticmethod
    def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(np.nan, index=frame.index, dtype=float)
        return pd.to_numeric(frame[column], errors="coerce")

    @classmethod
    def _first_numeric(cls, frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
        for column in columns:
            if column in frame:
                values = pd.to_numeric(frame[column], errors="coerce")
                if not values.isna().all():
                    if column in ("Accel", "Brake") and float(values.abs().max()) > 1.5:
                        values = values / 255.0
                    if column == "Steer" and float(values.abs().max()) > 1.5:
                        values = values / 127.0
                    return values
        return pd.Series(np.nan, index=frame.index, dtype=float)

    @staticmethod
    def _interpolate(
        progress: pd.Series,
        values: pd.Series,
        grid: np.ndarray,
        default: float,
    ) -> np.ndarray:
        finite = progress.notna() & values.replace([np.inf, -np.inf], np.nan).notna()
        if finite.sum() == 0:
            return np.full(len(grid), default, dtype=float)
        if finite.sum() == 1:
            return np.full(len(grid), float(values.loc[finite].iloc[0]), dtype=float)
        return np.interp(
            grid,
            progress.loc[finite].to_numpy(dtype=float),
            values.loc[finite].to_numpy(dtype=float),
        )

    @staticmethod
    def _curvature(x: pd.Series, z: pd.Series, distance: pd.Series) -> np.ndarray:
        x_values = x.to_numpy(dtype=float)
        z_values = z.to_numpy(dtype=float)
        if not np.isfinite(x_values).all() or not np.isfinite(z_values).all():
            return np.zeros(len(x_values), dtype=float)
        distance_values = distance.to_numpy(dtype=float)
        if not np.isfinite(distance_values).all() or float(np.ptp(distance_values)) <= 0:
            distance_values = np.arange(len(x_values), dtype=float)
        dx = np.gradient(x_values, distance_values, edge_order=1)
        dz = np.gradient(z_values, distance_values, edge_order=1)
        ddx = np.gradient(dx, distance_values, edge_order=1)
        ddz = np.gradient(dz, distance_values, edge_order=1)
        denominator = np.power(dx * dx + dz * dz, 1.5)
        curvature = np.divide(
            np.abs(dx * ddz - dz * ddx),
            denominator,
            out=np.zeros_like(denominator),
            where=denominator > 1e-9,
        )
        curvature[~np.isfinite(curvature)] = 0.0
        cap = float(np.nanpercentile(curvature, 99)) if len(curvature) else 0.0
        return np.clip(curvature, 0.0, max(cap, 1e-6))

    @staticmethod
    def _first_local_progress(local: pd.Series, active: pd.Series, default: float) -> float:
        indices = np.flatnonzero(active.to_numpy(dtype=bool))
        return float(local.iloc[indices[0]]) if len(indices) else float(default)

    @staticmethod
    def _section_phase(section: pd.DataFrame) -> str:
        cornerness = float(section["cornerness"].mean())
        if cornerness < 0.15:
            return "straight"
        minimum_index = int(np.argmin(section["speed_mps"].to_numpy(dtype=float)))
        fraction = minimum_index / max(len(section) - 1, 1)
        if fraction < 0.35:
            return "exit"
        if fraction > 0.65:
            return "entry"
        return "apex"

    @staticmethod
    def _conditions(raw_conditions: Any) -> Dict[str, float]:
        conditions = dict(raw_conditions) if isinstance(raw_conditions, Mapping) else {}

        def value(keys: Sequence[str], default: float) -> float:
            for key in keys:
                raw = conditions.get(key)
                if raw is None:
                    continue
                if isinstance(raw, Mapping):
                    raw = raw.get("value")
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    continue
            return default

        wetness = value(("wetness", "track_wetness", "rain", "rain_intensity"), 0.0)
        return {
            "wetness": float(np.clip(wetness, 0.0, 1.0)),
            "air_temp_c": value(("air_temp_c", "ambient_temp_c", "air_temperature"), np.nan),
            "track_temp_c": value(("track_temp_c", "road_temp_c", "track_temperature"), np.nan),
            "tyre_wear": float(
                np.clip(value(("tyre_wear", "tire_wear", "max_tyre_wear"), 0.0), 0.0, 1.0)
            ),
        }

    @staticmethod
    def _single_value(frame: pd.DataFrame, column: str) -> Any:
        if column not in frame:
            return None
        values = frame[column].dropna()
        return values.iloc[-1] if not values.empty else None

    @staticmethod
    def _finite_number(value: Any) -> bool:
        try:
            return bool(np.isfinite(float(value)))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _track_key(metadata: Mapping[str, Any]) -> str:
        return "{0}:{1}".format(
            metadata.get("track_circuit") or metadata.get("track_ordinal") or "unknown-track",
            metadata.get("track_layout") or "default",
        )

    @staticmethod
    def _car_key(metadata: Mapping[str, Any]) -> str:
        return str(metadata.get("car_identity") or metadata.get("car_ordinal") or "unknown-car")


def immutable_group_split(
    dataset: LapDataset,
    holdout_fraction: float = 0.20,
    salt: str = "slipstream-holdout-v1",
    prefer_session: bool = True,
) -> GroupedSplit:
    """Assign immutable groups by hash so existing holdout membership never moves."""

    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must be between zero and one")
    lap_frame = dataset.lap_frame.copy()
    session_count = lap_frame["session_key"].nunique()
    group_kind = "session" if prefer_session and session_count >= 2 else "lap"
    group_column = "session_key" if group_kind == "session" else "lap_key"
    groups = sorted(lap_frame[group_column].astype(str).unique())
    if len(groups) < 2:
        raise ValueError("At least two independent laps or sessions are required for a holdout")

    scores = {group: _stable_fraction("{0}:{1}".format(salt, group)) for group in groups}
    holdout_groups = {group for group in groups if scores[group] < holdout_fraction}
    if not holdout_groups:
        holdout_groups = {min(groups, key=lambda group: scores[group])}
    if len(holdout_groups) == len(groups):
        holdout_groups.remove(max(groups, key=lambda group: scores[group]))
    train_groups = set(groups) - holdout_groups

    holdout_mask = lap_frame[group_column].astype(str).isin(holdout_groups)
    train_laps = tuple(sorted(lap_frame.loc[~holdout_mask, "lap_key"].astype(str)))
    holdout_laps = tuple(sorted(lap_frame.loc[holdout_mask, "lap_key"].astype(str)))
    return GroupedSplit(
        train_lap_keys=train_laps,
        holdout_lap_keys=holdout_laps,
        train_groups=tuple(sorted(train_groups)),
        holdout_groups=tuple(sorted(holdout_groups)),
        group_kind=group_kind,
        salt=salt,
    )


def grouped_cv_splits(
    dataset: LapDataset,
    lap_keys: Optional[Sequence[str]] = None,
    n_splits: int = 3,
    prefer_session: bool = True,
) -> List[Tuple[Tuple[str, ...], Tuple[str, ...]]]:
    """Return grouped folds as whole-lap keys; no adjacent rows can cross a fold."""

    from sklearn.model_selection import GroupKFold

    selected = dataset.lap_frame
    if lap_keys is not None:
        selected = selected[selected["lap_key"].isin(set(lap_keys))]
    if len(selected) < 2:
        raise ValueError("At least two laps are required for grouped cross-validation")
    use_sessions = prefer_session and selected["session_key"].nunique() >= 2
    groups = selected["session_key"].astype(str) if use_sessions else selected["lap_key"].astype(str)
    split_count = min(int(n_splits), int(groups.nunique()))
    if split_count < 2:
        raise ValueError("Grouped cross-validation requires at least two groups")
    folds: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = []
    keys = selected["lap_key"].astype(str).to_numpy()
    dummy = np.zeros((len(selected), 1), dtype=float)
    for train_indices, validation_indices in GroupKFold(n_splits=split_count).split(dummy, groups=groups):
        folds.append(
            (
                tuple(sorted(keys[train_indices].tolist())),
                tuple(sorted(keys[validation_indices].tolist())),
            )
        )
    return folds


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2 ** 64)
