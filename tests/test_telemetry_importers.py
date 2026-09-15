from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

from src.core.schemas import RAW_LAP_COLUMNS
from src.db import models
from src.db.repositories import TelemetryRepository
from src.db.session import create_database_engine, create_schema, create_session_factory, session_scope
from src.ingest.artifact_importer import ArtifactDirectoryImporter
from src.ingest.assetto_corsa import map_assetto_corsa_row
from src.ingest.huggingface_importer import HuggingFaceTelemetryImporter
from src.ingest.lap_reconstruction import reconstruct_laps
from src.ingest.manifests import EXPECTED_HF_ROWS, HF_SOURCE_MANIFESTS, HuggingFaceSourceManifest


def _circle_rows(laps: int = 3, sampling_hz: int = 10, lap_duration_s: int = 40):
    rows = []
    count = laps * sampling_hz * lap_duration_s + 1
    for index in range(count):
        timestamp = index / float(sampling_hz)
        angle = 2.0 * math.pi * timestamp / lap_duration_s
        rows.append(
            {
                "timestamp": timestamp,
                "lap_progress": 0.0,
                "completed_laps": 0,
                "pos_x": 100.0 * math.cos(angle),
                "pos_z": 100.0 * math.sin(angle),
                "speed_kmh": 90.0,
                "rpms": 5000,
                "gear": 4,
                "throttle": 0.7,
                "brake": 0.0,
                "clutch": 0.0,
                "steer_angle": 0.2,
                "g_lat": 0.8,
                "g_lon": 0.1,
            }
        )
    return rows


class AssettoCorsaMappingTests(unittest.TestCase):
    def test_pinned_manifests_match_verified_corpus_size(self) -> None:
        self.assertEqual(EXPECTED_HF_ROWS, 260031)
        self.assertEqual(
            sum(manifest.expected_rows for manifest in HF_SOURCE_MANIFESTS.values()),
            260031,
        )
        self.assertTrue(all(len(manifest.revision) == 40 for manifest in HF_SOURCE_MANIFESTS.values()))

    def test_canonical_mapping_converts_units_and_preserves_extras(self) -> None:
        sample = map_assetto_corsa_row(
            {
                "timestamp": 1.25,
                "speed_kmh": 180.0,
                "throttle": 75.0,
                "brake": 0.2,
                "steer_angle": math.pi / 2.0,
                "g_lat": 1.0,
                "pos_x": 10.0,
                "pos_z": 20.0,
                "tyre_core_fl": 88.0,
            },
            sample_index=5,
            source_prefix="fixture",
        )
        self.assertEqual(sample.native_timestamp_ns, 1_250_000_000)
        self.assertAlmostEqual(sample.speed_mps, 50.0)
        self.assertAlmostEqual(sample.throttle, 0.75)
        self.assertAlmostEqual(sample.steering, 0.5)
        self.assertAlmostEqual(sample.lateral_accel_mps2, 9.80665)
        self.assertEqual(sample.additional_fields["tyre_core_fl"], 88.0)

    def test_mapping_uses_sampling_rate_when_timestamp_is_missing(self) -> None:
        sample = map_assetto_corsa_row(
            {"speed_ms": 42.0, "gas": 0.4, "steering": -64},
            sample_index=25,
            source_prefix="fixture",
            sampling_hz=50.0,
        )
        self.assertEqual(sample.native_timestamp_ns, 500_000_000)
        self.assertAlmostEqual(sample.speed_mps, 42.0)
        self.assertAlmostEqual(sample.throttle, 0.4)
        self.assertAlmostEqual(sample.steering, -64 / 127.0)

    def test_constant_progress_reconstructs_directed_complete_laps(self) -> None:
        rows = _circle_rows()
        samples = list(
            map_assetto_corsa_row(row, index, "fixture", sampling_hz=10.0)
            for index, row in enumerate(rows)
        )
        result = reconstruct_laps(
            samples,
            min_lap_duration_s=30.0,
            minimum_samples=300,
        )
        self.assertEqual(result.method, "directed_position_crossing")
        self.assertGreaterEqual(len(result.laps), 2)
        self.assertTrue(result.quality_report["lap_progress_constant_or_missing"])
        self.assertGreater(sum(value is not None for value in result.projected_progress), 600)
        assigned = sum(lap.sample_count for lap in result.laps)
        self.assertEqual(
            assigned,
            sum(lap_number is not None for lap_number in result.lap_numbers),
        )
        self.assertEqual(
            result.quality_report["unlabeled_partial_rows"],
            len(samples) - assigned,
        )


class ImporterPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite+pysqlite:///:memory:")
        create_schema(self.engine)
        self.factory = create_session_factory(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_huggingface_rows_import_idempotently_without_network(self) -> None:
        rows = _circle_rows(laps=2)
        manifest = HuggingFaceSourceManifest(
            key="hf:fixture",
            repo_id="fixture/telemetry",
            revision="a" * 40,
            filename="telemetry.parquet",
            license="MIT",
            simulator="Assetto Corsa",
            sampling_hz=10.0,
            expected_rows=len(rows),
            track_id="fixture-track",
            track_name="Fixture Track",
            track_layout="GP",
            car_id="fixture-car",
            car_name="Fixture Car",
            source_laps=2,
        )
        with session_scope(self.factory) as database_session:
            importer = HuggingFaceTelemetryImporter(database_session, batch_size=127)
            first = importer.import_rows(manifest, rows)
            second = importer.import_rows(manifest, rows)
            count = TelemetryRepository(database_session).count_raw()
            session_count = database_session.scalar(
                select(func.count()).select_from(models.TelemetrySession)
            )
            lap_count = database_session.scalar(
                select(func.count()).select_from(models.Lap)
            )
            import_count = database_session.scalar(
                select(func.count()).select_from(models.ImportRun)
            )
            self.assertEqual(first.rows_inserted, len(rows))
            self.assertEqual(second.rows_updated, len(rows))
            self.assertEqual(count, len(rows))
            self.assertEqual(session_count, 1)
            self.assertEqual(lap_count, first.accepted_laps)
            self.assertEqual(import_count, 1)
            self.assertTrue(first.quality_report["row_count_matches_manifest"])
            self.assertGreaterEqual(first.accepted_laps, 1)

    def test_existing_raw_and_processed_artifacts_import_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            raw_dir = root / "raw" / "session_fixture"
            processed_dir = root / "processed" / "session_fixture"
            raw_dir.mkdir(parents=True)
            processed_dir.mkdir(parents=True)
            raw_rows = []
            for index in range(2):
                row = {column: 0 for column in RAW_LAP_COLUMNS}
                row.update(
                    {
                        "IsRaceOn": 1,
                        "TimestampMS": 1000 + index * 50,
                        "LapNumber": 1,
                        "Speed": 30.0,
                        "Accel": 128,
                        "Gear": 3,
                        "PositionX": float(index),
                        "PositionZ": float(index),
                    }
                )
                raw_rows.append(row)
            pd.DataFrame(raw_rows).to_csv(raw_dir / "lap_001.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "LapNumber": 1,
                        "SampleIndex": index,
                        "ElapsedTimeS": index * 0.05,
                        "NormalizedDistance": float(index),
                        "CumulativeDistanceM": float(index),
                        "SpeedMps": 30.0,
                        "Throttle": 0.5,
                        "Brake": 0.0,
                        "Steering": 0.0,
                        "Gear": 3,
                        "EngineRpm": 4000.0,
                        "LapIsValid": 1,
                    }
                    for index in range(2)
                ]
            ).to_csv(processed_dir / "lap_001.csv", index=False)

            with session_scope(self.factory) as database_session:
                importer = ArtifactDirectoryImporter(database_session, batch_size=1)
                first = importer.import_session(
                    "session_fixture", raw_dir=raw_dir, processed_dir=processed_dir
                )
                second = importer.import_session(
                    "session_fixture", raw_dir=raw_dir, processed_dir=processed_dir
                )
                self.assertEqual(first["raw"]["rows_inserted"], 2)
                self.assertEqual(first["processed"]["rows_inserted"], 2)
                self.assertEqual(second["raw"]["rows_updated"], 2)
                self.assertEqual(second["processed"]["rows_updated"], 2)
                self.assertEqual(TelemetryRepository(database_session).count_raw(), 2)


if __name__ == "__main__":
    unittest.main()
