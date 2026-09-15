from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.telemetry import DataSourceContract, LapContract, SessionContract
from src.db.repositories import (
    CatalogRepository,
    DataSourceRepository,
    SessionRepository,
    TelemetryRepository,
    UpsertResult,
)
from src.db.session import create_database_engine, create_session_factory, session_scope
from src.ingest.assetto_corsa import map_assetto_corsa_rows
from src.ingest.lap_reconstruction import reconstruct_laps
from src.ingest.manifests import HF_SOURCE_MANIFESTS, HuggingFaceSourceManifest


@dataclass(frozen=True)
class ImportSummary:
    source_key: str
    session_external_id: str
    rows_seen: int
    rows_inserted: int
    rows_updated: int
    accepted_laps: int
    quality_report: Mapping[str, Any]


class HuggingFaceTelemetryImporter:
    def __init__(
        self,
        session: Session,
        cache_root: Optional[Path] = None,
        batch_size: int = 5000,
        downloader: Optional[Callable[..., str]] = None,
    ):
        self.session = session
        self.cache_root = Path(cache_root or get_settings().import_cache_root)
        self.batch_size = batch_size
        self.downloader = downloader

    def download(self, manifest: HuggingFaceSourceManifest) -> Path:
        downloader = self.downloader
        if downloader is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RuntimeError(
                    "huggingface-hub is required for network imports; install requirements.txt"
                ) from exc
            downloader = hf_hub_download
        self.cache_root.mkdir(parents=True, exist_ok=True)
        resolved = downloader(
            repo_id=manifest.repo_id,
            filename=manifest.filename,
            revision=manifest.revision,
            repo_type="dataset",
            cache_dir=str(self.cache_root),
        )
        return Path(resolved)

    def import_manifest(
        self,
        manifest: HuggingFaceSourceManifest,
        parquet_path: Optional[Path] = None,
        quality_report_path: Optional[Path] = None,
    ) -> ImportSummary:
        source_path = Path(parquet_path) if parquet_path is not None else self.download(manifest)
        rows = self._read_parquet_rows(source_path)
        summary = self.import_rows(manifest, rows, source_path=source_path)
        report_path = quality_report_path
        if report_path is None:
            safe_key = manifest.key.replace(":", "_")
            report_path = self.cache_root / "quality" / "{0}.json".format(safe_key)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(dict(summary.quality_report), indent=2), encoding="utf-8")
        return summary

    def import_rows(
        self,
        manifest: HuggingFaceSourceManifest,
        rows: Iterable[Mapping[str, Any]],
        source_path: Optional[Path] = None,
    ) -> ImportSummary:
        source_repository = DataSourceRepository(self.session)
        catalog_repository = CatalogRepository(self.session)
        session_repository = SessionRepository(self.session)
        telemetry_repository = TelemetryRepository(self.session)
        source_sha256 = self._sha256(source_path) if source_path is not None and source_path.is_file() else None

        source = source_repository.upsert(
            DataSourceContract(
                key=manifest.key,
                kind="huggingface_dataset",
                simulator=manifest.simulator,
                provider="Hugging Face",
                dataset_name=manifest.repo_id,
                source_url=manifest.source_url,
                revision=manifest.revision,
                license=manifest.license,
                provenance={
                    "filename": manifest.filename,
                    "expected_rows": manifest.expected_rows,
                    "source_laps": manifest.source_laps,
                    "cached_file_sha256": source_sha256,
                },
            )
        )
        import_run = source_repository.start_import(source.id, manifest.revision)
        track = catalog_repository.upsert_track(
            identity_key="assetto-corsa:track:{0}".format(manifest.track_id),
            simulator=manifest.simulator,
            circuit=manifest.track_name,
            external_id=manifest.track_id,
            layout=manifest.track_layout,
        )
        car = catalog_repository.upsert_car(
            identity_key="assetto-corsa:car:{0}".format(manifest.car_id),
            simulator=manifest.simulator,
            external_id=manifest.car_id,
            model=manifest.car_name,
        )
        session_external_id = "{0}@{1}".format(manifest.key, manifest.revision)
        telemetry_session = session_repository.upsert_session(
            source.id,
            SessionContract(
                external_id=session_external_id,
                simulator=manifest.simulator,
                sampling_hz=manifest.sampling_hz,
                track_external_id=manifest.track_id,
                car_external_id=manifest.car_id,
                provenance={
                    "repo_id": manifest.repo_id,
                    "revision": manifest.revision,
                    "filename": manifest.filename,
                    "cached_path": str(source_path) if source_path else None,
                },
            ),
            track_id=track.id,
            car_id=car.id,
        )

        source_prefix = "{0}:{1}".format(manifest.key, manifest.revision)
        samples = list(
            map_assetto_corsa_rows(
                rows,
                source_prefix=source_prefix,
                sampling_hz=manifest.sampling_hz,
            )
        )
        reconstruction = reconstruct_laps(samples)
        lap_id_by_number: Dict[int, int] = {}
        for lap in reconstruction.laps:
            stored_lap = session_repository.upsert_lap(
                telemetry_session.id,
                LapContract(
                    lap_number=lap.lap_number,
                    source_lap_key="{0}:reconstructed:{1}".format(manifest.revision, lap.lap_number),
                    started_native_ns=lap.started_native_ns,
                    ended_native_ns=lap.ended_native_ns,
                    duration_s=lap.duration_s,
                    is_valid=True,
                    status="reconstructed",
                    quality={"method": reconstruction.method},
                ),
            )
            session_repository.set_lap_sample_count(stored_lap.id, lap.sample_count)
            lap_id_by_number[lap.lap_number] = stored_lap.id

        projected_samples = []
        lap_ids_by_sample_key = {}
        for sample, lap_number, progress in zip(
            samples, reconstruction.lap_numbers, reconstruction.projected_progress
        ):
            provenance = dict(sample.provenance)
            provenance["reported_lap_progress"] = sample.lap_progress
            provenance["lap_assignment"] = reconstruction.method if lap_number is not None else "unassigned"
            provenance["source_key"] = manifest.key
            provenance["source_revision"] = manifest.revision
            provenance["source_url"] = manifest.source_url
            projected_sample = replace(
                sample,
                lap_progress=progress if progress is not None else sample.lap_progress,
                provenance=provenance,
            )
            projected_samples.append(projected_sample)
            if lap_number is not None:
                lap_ids_by_sample_key[projected_sample.source_sample_key] = lap_id_by_number[lap_number]

        upsert_result = telemetry_repository.bulk_upsert_raw(
            data_source_id=source.id,
            session_id=telemetry_session.id,
            samples=projected_samples,
            batch_size=self.batch_size,
            lap_ids_by_sample_key=lap_ids_by_sample_key,
        )
        quality_report = self._build_quality_report(
            manifest=manifest,
            samples=projected_samples,
            reconstruction_report=reconstruction.quality_report,
            upsert_result=upsert_result,
        )
        quality_report["cached_file_sha256"] = source_sha256
        source_repository.finish_import(import_run, upsert_result, quality_report)
        return ImportSummary(
            source_key=manifest.key,
            session_external_id=session_external_id,
            rows_seen=upsert_result.rows_seen,
            rows_inserted=upsert_result.rows_inserted,
            rows_updated=upsert_result.rows_updated,
            accepted_laps=len(reconstruction.laps),
            quality_report=quality_report,
        )

    @staticmethod
    def _read_parquet_rows(path: Path) -> Iterable[Mapping[str, Any]]:
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to import Parquet files; install requirements.txt") from exc
        parquet_file = parquet.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=10000):
            for row in batch.to_pylist():
                yield row

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for block in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _build_quality_report(
        manifest: HuggingFaceSourceManifest,
        samples,
        reconstruction_report: Mapping[str, Any],
        upsert_result: UpsertResult,
    ) -> Dict[str, Any]:
        timestamps = [sample.native_timestamp_ns for sample in samples]
        non_monotonic = sum(
            current <= previous for previous, current in zip(timestamps, timestamps[1:])
        )
        missing_positions = sum(
            sample.position_x_m is None or sample.position_z_m is None for sample in samples
        )
        missing_inputs = sum(
            sample.throttle is None or sample.brake is None or sample.steering is None for sample in samples
        )
        row_count_matches = len(samples) == manifest.expected_rows
        reconstruction_status = reconstruction_report.get("status")
        status = "accepted"
        if not row_count_matches or non_monotonic or reconstruction_status != "accepted":
            status = "warning"
        return {
            "status": status,
            "source_key": manifest.key,
            "revision": manifest.revision,
            "expected_rows": manifest.expected_rows,
            "observed_rows": len(samples),
            "row_count_matches_manifest": row_count_matches,
            "non_monotonic_timestamp_count": non_monotonic,
            "missing_position_rows": missing_positions,
            "missing_core_input_rows": missing_inputs,
            "rows_inserted": upsert_result.rows_inserted,
            "rows_updated": upsert_result.rows_updated,
            "lap_reconstruction": dict(reconstruction_report),
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import pinned Assetto Corsa telemetry datasets.")
    parser.add_argument("source", choices=sorted(list(HF_SOURCE_MANIFESTS) + ["all"]))
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--parquet", type=Path, default=None, help="Local Parquet override for one source.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    settings = get_settings()
    engine = create_database_engine(args.database_url or settings.database_url)
    factory = create_session_factory(engine)
    source_names = sorted(HF_SOURCE_MANIFESTS) if args.source == "all" else [args.source]
    if args.parquet is not None and len(source_names) != 1:
        raise ValueError("--parquet can only be used with one source")
    with session_scope(factory) as session:
        importer = HuggingFaceTelemetryImporter(
            session,
            cache_root=settings.import_cache_root,
            batch_size=settings.import_batch_size,
        )
        for source_name in source_names:
            summary = importer.import_manifest(HF_SOURCE_MANIFESTS[source_name], parquet_path=args.parquet)
            print(json.dumps(dict(summary.quality_report), indent=2))


if __name__ == "__main__":
    main()
