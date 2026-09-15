from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd
from sqlalchemy.orm import Session

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT, get_settings
from src.core.schemas import SCHEMA_VERSION
from src.core.telemetry import (
    DataSourceContract,
    LapContract,
    ProcessedTelemetryContract,
    SessionContract,
)
from src.db.repositories import (
    CatalogRepository,
    DataSourceRepository,
    SessionRepository,
    TelemetryRepository,
    UpsertResult,
)
from src.db.session import create_database_engine, create_session_factory, session_scope
from src.ingest.forza import map_forza_row


LAP_FILE_PATTERN = re.compile(r"lap_(\d+)\.csv$")


def _metadata(directory: Optional[Path]) -> Dict[str, Any]:
    if directory is None:
        return {}
    path = directory / "metadata.json"
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _lap_number(path: Path, frame: pd.DataFrame) -> int:
    for column in ("LapNumber", "lap_number"):
        if column in frame.columns and not frame.empty:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if not values.empty:
                return int(values.iloc[0])
    match = LAP_FILE_PATTERN.match(path.name)
    if not match:
        raise ValueError("Cannot determine lap number from {0}".format(path))
    return int(match.group(1))


def _optional_float(row: Mapping[str, Any], name: str) -> Optional[float]:
    value = row.get(name)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _optional_int(row: Mapping[str, Any], name: str) -> Optional[int]:
    value = _optional_float(row, name)
    return int(value) if value is not None else None


class ArtifactDirectoryImporter:
    def __init__(self, session: Session, source_key: str = "artifact:local-telemetry", batch_size: int = 5000):
        self.session = session
        self.source_key = source_key
        self.batch_size = batch_size

    def import_roots(
        self,
        raw_root: Optional[Path] = None,
        processed_root: Optional[Path] = None,
    ) -> List[Mapping[str, Any]]:
        raw_root = Path(raw_root) if raw_root is not None else None
        processed_root = Path(processed_root) if processed_root is not None else None
        session_ids = set()
        for root in (raw_root, processed_root):
            if root is not None and root.is_dir():
                session_ids.update(path.name for path in root.iterdir() if path.is_dir())
        reports = []
        for session_id in sorted(session_ids):
            raw_dir = raw_root / session_id if raw_root is not None and (raw_root / session_id).is_dir() else None
            processed_dir = (
                processed_root / session_id
                if processed_root is not None and (processed_root / session_id).is_dir()
                else None
            )
            reports.append(self.import_session(session_id, raw_dir=raw_dir, processed_dir=processed_dir))
        return reports

    def import_session(
        self,
        session_id: str,
        raw_dir: Optional[Path] = None,
        processed_dir: Optional[Path] = None,
    ) -> Mapping[str, Any]:
        raw_dir = Path(raw_dir) if raw_dir is not None else None
        processed_dir = Path(processed_dir) if processed_dir is not None else None
        metadata = _metadata(raw_dir) or _metadata(processed_dir)
        source_repository = DataSourceRepository(self.session)
        source = source_repository.upsert(
            DataSourceContract(
                key=self.source_key,
                kind="artifact_directory",
                simulator=str(metadata.get("sim") or "Forza Motorsport"),
                provider="local filesystem",
                provenance={
                    "raw_root": str(raw_dir.parent) if raw_dir else None,
                    "processed_root": str(processed_dir.parent) if processed_dir else None,
                },
            )
        )
        import_run = source_repository.start_import(source.id, "session:{0}".format(session_id))
        telemetry_session = self._upsert_session(source.id, session_id, metadata)
        raw_result = self._import_raw_laps(source.id, telemetry_session.id, session_id, raw_dir)
        processed_result = self._import_processed_laps(telemetry_session.id, processed_dir)
        combined = UpsertResult(
            rows_seen=raw_result.rows_seen + processed_result.rows_seen,
            rows_inserted=raw_result.rows_inserted + processed_result.rows_inserted,
            rows_updated=raw_result.rows_updated + processed_result.rows_updated,
        )
        report = {
            "status": "accepted",
            "session_id": session_id,
            "raw": raw_result.__dict__,
            "processed": processed_result.__dict__,
        }
        source_repository.finish_import(import_run, combined, report)
        return report

    def _upsert_session(self, source_id: int, session_id: str, metadata: Mapping[str, Any]):
        catalog = CatalogRepository(self.session)
        sessions = SessionRepository(self.session)
        simulator = str(metadata.get("sim") or "Forza Motorsport")
        track_id = None
        track_identity = metadata.get("track_ordinal") or metadata.get("track_circuit")
        if track_identity is not None:
            track = catalog.upsert_track(
                identity_key="forza:track:{0}".format(track_identity),
                simulator=simulator,
                external_id=str(metadata.get("track_ordinal")) if metadata.get("track_ordinal") is not None else None,
                circuit=str(metadata.get("track_circuit") or "Unknown track"),
                layout=metadata.get("track_layout"),
                location=metadata.get("track_location"),
                length_m=metadata.get("track_length_m"),
            )
            track_id = track.id
        car_id = None
        if metadata.get("car_ordinal") is not None:
            car = catalog.upsert_car(
                identity_key="forza:car:{0}".format(metadata["car_ordinal"]),
                simulator=simulator,
                external_id=str(metadata["car_ordinal"]),
                model="Forza car {0}".format(metadata["car_ordinal"]),
            )
            car_id = car.id
        return sessions.upsert_session(
            source_id,
            SessionContract(
                external_id=session_id,
                simulator=simulator,
                provenance={"artifact_metadata": dict(metadata)},
            ),
            track_id=track_id,
            car_id=car_id,
        )

    def _import_raw_laps(
        self,
        source_id: int,
        database_session_id: int,
        session_id: str,
        raw_dir: Optional[Path],
    ) -> UpsertResult:
        if raw_dir is None:
            return UpsertResult(0, 0, 0)
        sessions = SessionRepository(self.session)
        telemetry = TelemetryRepository(self.session)
        totals = [0, 0, 0]
        for lap_path in sorted(raw_dir.glob("lap_*.csv")):
            frame = pd.read_csv(lap_path)
            if frame.empty:
                continue
            lap_number = _lap_number(lap_path, frame)
            timestamps = pd.to_numeric(frame.get("TimestampMS"), errors="coerce").dropna()
            start_ns = int(timestamps.iloc[0] * 1_000_000) if not timestamps.empty else None
            end_ns = int(timestamps.iloc[-1] * 1_000_000) if not timestamps.empty else None
            duration = (end_ns - start_ns) / 1e9 if start_ns is not None and end_ns is not None else None
            lap = sessions.upsert_lap(
                database_session_id,
                LapContract(
                    lap_number=lap_number,
                    source_lap_key="lap:{0}".format(lap_number),
                    started_native_ns=start_ns,
                    ended_native_ns=end_ns,
                    duration_s=duration,
                    status="artifact",
                ),
            )
            samples = [
                map_forza_row(
                    row,
                    sample_index=index,
                    source_prefix="{0}:lap:{1}".format(session_id, lap_number),
                )
                for index, row in enumerate(frame.to_dict(orient="records"))
            ]
            lap_ids = {sample.source_sample_key: lap.id for sample in samples}
            result = telemetry.bulk_upsert_raw(
                source_id,
                database_session_id,
                samples,
                batch_size=self.batch_size,
                lap_ids_by_sample_key=lap_ids,
            )
            sessions.set_lap_sample_count(lap.id, len(samples))
            totals[0] += result.rows_seen
            totals[1] += result.rows_inserted
            totals[2] += result.rows_updated
        return UpsertResult(*totals)

    def _import_processed_laps(
        self,
        database_session_id: int,
        processed_dir: Optional[Path],
    ) -> UpsertResult:
        if processed_dir is None:
            return UpsertResult(0, 0, 0)
        sessions = SessionRepository(self.session)
        telemetry = TelemetryRepository(self.session)
        metadata = _metadata(processed_dir)
        processing_version = str(metadata.get("processed_schema_version") or SCHEMA_VERSION)
        totals = [0, 0, 0]
        for lap_path in sorted(processed_dir.glob("lap_*.csv")):
            frame = pd.read_csv(lap_path)
            if frame.empty:
                continue
            lap_number = _lap_number(lap_path, frame)
            elapsed = pd.to_numeric(frame.get("ElapsedTimeS"), errors="coerce").dropna()
            lap = sessions.upsert_lap(
                database_session_id,
                LapContract(
                    lap_number=lap_number,
                    source_lap_key="lap:{0}".format(lap_number),
                    duration_s=float(elapsed.iloc[-1]) if not elapsed.empty else None,
                    is_valid=bool(_optional_int(frame.iloc[0], "LapIsValid"))
                    if "LapIsValid" in frame.columns
                    else None,
                    status="processed_artifact",
                ),
            )
            records = []
            for fallback_index, row in enumerate(frame.to_dict(orient="records")):
                records.append(
                    ProcessedTelemetryContract(
                        sample_index=_optional_int(row, "SampleIndex") or fallback_index,
                        progress=_optional_float(row, "TrackProgressNorm")
                        if _optional_float(row, "TrackProgressNorm") is not None
                        else (_optional_float(row, "NormalizedDistance") or 0.0),
                        elapsed_s=_optional_float(row, "ElapsedTimeS") or 0.0,
                        distance_m=_optional_float(row, "TrackProgressM")
                        if _optional_float(row, "TrackProgressM") is not None
                        else _optional_float(row, "CumulativeDistanceM"),
                        speed_mps=_optional_float(row, "SpeedMps"),
                        throttle=_optional_float(row, "Throttle"),
                        brake=_optional_float(row, "Brake"),
                        steering=_optional_float(row, "Steering"),
                        gear=_optional_int(row, "Gear"),
                        engine_rpm=_optional_float(row, "EngineRpm"),
                        features={
                            "longitudinal_accel_mps2": _optional_float(row, "LongitudinalAccelMps2"),
                            "alignment_residual_m": _optional_float(row, "AlignmentResidualM"),
                        },
                    )
                )
            result = telemetry.bulk_upsert_processed(
                lap.id,
                processing_version,
                records,
                batch_size=self.batch_size,
            )
            if lap.sample_count == 0:
                sessions.set_lap_sample_count(lap.id, len(records))
            totals[0] += result.rows_seen
            totals[1] += result.rows_inserted
            totals[2] += result.rows_updated
        return UpsertResult(*totals)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import existing SlipStream raw and processed artifacts.")
    parser.add_argument("--raw-root", type=Path, default=RAW_DATA_ROOT)
    parser.add_argument("--processed-root", type=Path, default=PROCESSED_DATA_ROOT)
    parser.add_argument("--database-url", default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    settings = get_settings()
    engine = create_database_engine(args.database_url or settings.database_url)
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        reports = ArtifactDirectoryImporter(
            session,
            batch_size=settings.import_batch_size,
        ).import_roots(args.raw_root, args.processed_root)
        print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
