from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select

from src.analysis.session_analysis import run
from src.api.routes import analysis as analysis_routes
from src.api.services import session_scanner
from src.core.schemas import LAP_CLOSE_REASON_LAP_ROLLOVER, SCHEMA_VERSION
from src.core.telemetry import DataSourceContract, LapContract, SessionContract
from src.db import models
from src.db.repositories import CatalogRepository, DataSourceRepository, SessionRepository, TelemetryRepository
from src.db.session import create_database_engine, create_schema, create_session_factory, session_scope
from src.ingest.forza import map_forza_row
from src.ingest.huggingface_importer import HuggingFaceTelemetryImporter
from src.ingest.manifests import HuggingFaceSourceManifest
from src.processing.distance import build_processed_lap_dataframe, process_session
from src.services.telemetry_store import SQLAlchemyTelemetryStore
from tests.test_processing import build_parallel_section_path_points, build_raw_lap_dataframe
from tests.test_telemetry_importers import _circle_rows


class DatabasePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp())
        self.raw_root = self.temp_root / "raw"
        self.processed_root = self.temp_root / "processed"
        self.raw_root.mkdir()
        self.processed_root.mkdir()
        self.session_id = "session_database_flow"
        self.engine = create_database_engine("sqlite+pysqlite:///:memory:")
        create_schema(self.engine)
        self.factory = create_session_factory(self.engine)
        self.store = SQLAlchemyTelemetryStore(self.factory)
        self.raw_frame = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=1,
            timestamp_step_ms=50,
        )
        self._seed_database()

    def tearDown(self) -> None:
        self.engine.dispose()
        shutil.rmtree(self.temp_root)

    def _seed_database(self) -> None:
        metadata = {
            "session_id": self.session_id,
            "schema_version": SCHEMA_VERSION,
            "sim": "Forza Motorsport",
            "track_ordinal": 110,
            "track_circuit": "Circuit de Barcelona-Catalunya",
            "track_layout": "Grand Prix",
            "track_location": "Barcelona, Spain",
            "lap_index": {
                "1": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": int(self.raw_frame["TimestampMS"].iloc[0]),
                    "last_timestamp_ms": int(self.raw_frame["TimestampMS"].iloc[-1]),
                }
            },
        }
        with session_scope(self.factory) as database_session:
            source = DataSourceRepository(database_session).upsert(
                DataSourceContract(key="db-flow", kind="test", simulator="Forza Motorsport")
            )
            track = CatalogRepository(database_session).upsert_track(
                identity_key="forza:track:110",
                simulator="Forza Motorsport",
                external_id="110",
                circuit=metadata["track_circuit"],
                layout=metadata["track_layout"],
                location=metadata["track_location"],
            )
            car = CatalogRepository(database_session).upsert_car(
                identity_key="forza:car:12",
                simulator="Forza Motorsport",
                external_id="12",
                model="Fixture Car",
            )
            stored_session = SessionRepository(database_session).upsert_session(
                source.id,
                SessionContract(
                    external_id=self.session_id,
                    simulator="Forza Motorsport",
                    sampling_hz=20.0,
                    provenance={"artifact_metadata": metadata},
                ),
                track_id=track.id,
                car_id=car.id,
            )
            lap = SessionRepository(database_session).upsert_lap(
                stored_session.id,
                LapContract(
                    lap_number=1,
                    source_lap_key="lap:1",
                    started_native_ns=int(self.raw_frame["TimestampMS"].iloc[0]) * 1_000_000,
                    ended_native_ns=int(self.raw_frame["TimestampMS"].iloc[-1]) * 1_000_000,
                    duration_s=float(self.raw_frame["CurrentLap"].iloc[-1]),
                    status="captured",
                    quality={"close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER},
                ),
            )
            samples = [
                map_forza_row(row, index, "{0}:lap:1".format(self.session_id))
                for index, row in enumerate(self.raw_frame.to_dict("records"))
            ]
            TelemetryRepository(database_session).bulk_upsert_raw(
                source.id,
                stored_session.id,
                samples,
                lap_ids_by_sample_key={sample.source_sample_key: lap.id for sample in samples},
            )
            SessionRepository(database_session).set_lap_sample_count(lap.id, len(samples))

    def _process_from_database(self) -> Path:
        virtual_raw_dir = self.raw_root / self.session_id
        processed_dir = self.processed_root / self.session_id
        self.assertFalse(virtual_raw_dir.exists())
        written = process_session(
            virtual_raw_dir,
            processed_dir,
            datastore=self.store,
        )
        self.assertEqual(len(written), 1)
        return processed_dir

    def test_database_raw_is_processed_persisted_and_exported(self) -> None:
        processed_dir = self._process_from_database()
        self.assertTrue((processed_dir / "lap_001.csv").is_file())
        self.assertTrue((processed_dir / "metadata.json").is_file())

        stored = self.store.load_processed_lap(self.session_id, 1)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(len(stored), len(self.raw_frame))
        self.assertTrue((stored["AlignmentIsUsable"] == 1).all())

        with patch.object(session_scanner, "get_default_telemetry_store", return_value=self.store), patch.multiple(
            session_scanner,
            RAW_DATA_ROOT=self.raw_root,
            PROCESSED_DATA_ROOT=self.processed_root,
        ):
            sessions = session_scanner.list_sessions()
            detail = session_scanner.get_session_detail(self.session_id)
            lap_payload = session_scanner.get_lap_data(self.session_id, 1, "processed")
            renamed = session_scanner.update_session_metadata(
                self.session_id,
                display_name="Database Session",
            )

        self.assertEqual([session["session_id"] for session in sessions], [self.session_id])
        self.assertTrue(detail["has_processed"])
        self.assertEqual(lap_payload["sampling"]["source_rows"], len(self.raw_frame))
        self.assertEqual(renamed["display_name"], "Database Session")

    def test_processed_session_write_rolls_back_as_one_transaction(self) -> None:
        processed = build_processed_lap_dataframe(self.raw_frame, session_id=self.session_id)
        with self.assertRaises(KeyError):
            self.store.persist_processed_laps(
                self.session_id,
                {1: processed, 2: processed},
                {"processed_schema_version": SCHEMA_VERSION},
                SCHEMA_VERSION,
            )
        self.assertIsNone(self.store.load_processed_lap(self.session_id, 1))

    def test_assetto_database_lap_without_vertical_position_processes(self) -> None:
        rows = _circle_rows(laps=2)
        manifest = HuggingFaceSourceManifest(
            key="hf:pipeline-fixture",
            repo_id="fixture/pipeline",
            revision="b" * 40,
            filename="telemetry.parquet",
            license="MIT",
            simulator="Assetto Corsa",
            sampling_hz=10.0,
            expected_rows=len(rows),
            track_id="fixture-circle",
            track_name="Fixture Circle",
            track_layout="GP",
            car_id="fixture-car",
            car_name="Fixture Car",
            source_laps=2,
        )
        with session_scope(self.factory) as database_session:
            summary = HuggingFaceTelemetryImporter(database_session).import_rows(manifest, rows)
        raw_frame = self.store.load_raw_lap(summary.session_external_id, 1)
        self.assertIsNotNone(raw_frame)
        assert raw_frame is not None
        self.assertTrue((raw_frame["PositionY"] == 0.0).all())

        processed_dir = self.processed_root / summary.session_external_id
        written = process_session(
            self.raw_root / summary.session_external_id,
            processed_dir,
            datastore=self.store,
        )
        self.assertEqual(len(written), 1)
        self.assertIsNotNone(self.store.load_processed_lap(summary.session_external_id, 1))

    def test_analysis_reads_database_samples_and_persists_run(self) -> None:
        processed_dir = self._process_from_database()
        # The analysis must prefer persisted samples over the exported lap.
        (processed_dir / "lap_001.csv").write_text("broken,column\nx,y\n", encoding="utf-8")
        result = run(
            self.session_id,
            processed_root=self.processed_root,
            write=True,
            strict_reconciliation=False,
            datastore=self.store,
        )
        self.assertEqual(result.session_id, self.session_id)
        self.assertTrue((processed_dir / "session_analysis.json").is_file())
        self.assertEqual(self.store.get_latest_analysis(self.session_id)["session_id"], self.session_id)

        with session_scope(self.factory) as database_session:
            run_count = database_session.scalar(select(func.count()).select_from(models.AnalysisRun))
            finding_count = database_session.scalar(select(func.count()).select_from(models.Finding))
        self.assertEqual(run_count, 1)
        self.assertEqual(finding_count, len(result.findings_all))

        with patch.object(analysis_routes, "get_default_telemetry_store", return_value=self.store), patch.object(
            session_scanner,
            "get_default_telemetry_store",
            return_value=self.store,
        ), patch.multiple(
            session_scanner,
            RAW_DATA_ROOT=self.raw_root,
            PROCESSED_DATA_ROOT=self.processed_root,
        ):
            payload = analysis_routes.get_session_analysis(self.session_id)
        self.assertEqual(payload["session_id"], self.session_id)

    def test_database_and_filesystem_delete_stay_in_sync(self) -> None:
        processed_dir = self._process_from_database()
        with patch.object(session_scanner, "get_default_telemetry_store", return_value=self.store), patch.multiple(
            session_scanner,
            RAW_DATA_ROOT=self.raw_root,
            PROCESSED_DATA_ROOT=self.processed_root,
        ):
            self.assertTrue(session_scanner.delete_lap(self.session_id, 1))
            detail = session_scanner.get_session_detail(self.session_id)
            self.assertEqual(detail["laps"], [])
            self.assertFalse((processed_dir / "lap_001.csv").exists())
            self.assertTrue(session_scanner.delete_session(self.session_id))
            self.assertIsNone(session_scanner.get_session_detail(self.session_id))

    def test_manual_conditions_and_health_surfaces_use_persisted_data(self) -> None:
        self._process_from_database()
        updated = self.store.update_session_conditions(
            self.session_id,
            {
                "wetness": 0.25,
                "track_temp_c": 18.5,
                "tyre_wear": 0.4,
            },
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["wetness"], 0.25)
        self.assertEqual(updated["track_temp_c"], 18.5)

        data_health = self.store.get_data_health()
        self.assertGreater(data_health["row_count"]["processed"], 0)
        self.assertEqual(data_health["effective_laps"], 1)
        self.assertTrue(data_health["source_imports"])

        model_health = self.store.get_model_health()
        self.assertEqual(model_health["status"], "fallback")
        self.assertIn(
            "no_registered_champion",
            model_health["fallback_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
