from __future__ import annotations

import unittest

from sqlalchemy import event, inspect

from src.core.telemetry import (
    CanonicalTelemetrySample,
    DataSourceContract,
    LapContract,
    ModelVersionContract,
    SessionContract,
)
from src.db.repositories import (
    AnalysisRepository,
    DataSourceRepository,
    ModelRepository,
    RecommendationRepository,
    SessionRepository,
    TelemetryRepository,
)
from src.db.session import create_database_engine, create_schema, create_session_factory, session_scope
from src.ml.feedback import RecommendationOutcomeV1, RecommendationRatingV1


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite+pysqlite:///:memory:")
        create_schema(self.engine)
        self.factory = create_session_factory(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_schema_contains_milestone_tables(self) -> None:
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue(
            {
                "data_sources",
                "tracks",
                "cars",
                "sessions",
                "laps",
                "raw_telemetry_samples",
                "processed_telemetry_samples",
                "analysis_runs",
                "findings",
                "recommendations",
                "recommendation_outcomes",
                "recommendation_ratings",
                "model_versions",
                "model_metrics",
                "prediction_profiles",
            }.issubset(tables)
        )

    def test_native_sample_upsert_is_idempotent(self) -> None:
        with session_scope(self.factory) as database_session:
            source = DataSourceRepository(database_session).upsert(
                DataSourceContract(key="fixture", kind="test", simulator="Fixture Sim")
            )
            session_row = SessionRepository(database_session).upsert_session(
                source.id,
                SessionContract(external_id="session-1", simulator="Fixture Sim", sampling_hz=100.0),
            )
            lap = SessionRepository(database_session).upsert_lap(
                session_row.id,
                LapContract(lap_number=1, source_lap_key="lap-1"),
            )
            samples = [
                CanonicalTelemetrySample(
                    source_sample_key="sample-{0}".format(index),
                    native_timestamp_ns=index * 10_000_000,
                    sample_index=index,
                    simulator="Fixture Sim",
                    speed_mps=20.0 + index,
                )
                for index in range(3)
            ]
            repository = TelemetryRepository(database_session)
            lap_ids = {sample.source_sample_key: lap.id for sample in samples}
            first = repository.bulk_upsert_raw(
                source.id, session_row.id, samples, batch_size=2, lap_ids_by_sample_key=lap_ids
            )
            second = repository.bulk_upsert_raw(
                source.id, session_row.id, samples, batch_size=2, lap_ids_by_sample_key=lap_ids
            )
            third = repository.bulk_upsert_raw(
                source.id,
                session_row.id,
                samples,
                batch_size=2,
            )

            self.assertEqual((first.rows_inserted, first.rows_updated), (3, 0))
            self.assertEqual((second.rows_inserted, second.rows_updated), (0, 3))
            self.assertEqual((third.rows_inserted, third.rows_updated), (0, 3))
            self.assertEqual(repository.count_raw(source.id), 3)
            self.assertEqual(len(repository.list_raw_for_lap(lap.id)), 3)

    def test_native_sample_generator_is_consumed_in_set_based_bounded_batches(self) -> None:
        with session_scope(self.factory) as database_session:
            source = DataSourceRepository(database_session).upsert(
                DataSourceContract(key="bounded-fixture", kind="test", simulator="Fixture Sim")
            )
            session_row = SessionRepository(database_session).upsert_session(
                source.id,
                SessionContract(external_id="bounded-session", simulator="Fixture Sim"),
            )
            repository = TelemetryRepository(database_session)
            raw_insert_calls = []

            def record_insert(_connection, _cursor, statement, _parameters, _context, executemany):
                if statement.lstrip().upper().startswith("INSERT INTO RAW_TELEMETRY_SAMPLES"):
                    raw_insert_calls.append(bool(executemany))

            event.listen(self.engine, "before_cursor_execute", record_insert)
            try:
                def samples():
                    for index in range(5):
                        if index == 2:
                            # The first batch must already be persisted before
                            # the generator is asked for the third record.
                            self.assertEqual(repository.count_raw(source.id), 2)
                        yield CanonicalTelemetrySample(
                            source_sample_key="bounded-{0}".format(index),
                            native_timestamp_ns=index * 10_000_000,
                            sample_index=index,
                            simulator="Fixture Sim",
                        )

                result = repository.bulk_upsert_raw(
                    source.id,
                    session_row.id,
                    samples(),
                    batch_size=2,
                )
            finally:
                event.remove(self.engine, "before_cursor_execute", record_insert)

            self.assertEqual(result, type(result)(5, 5, 0))
            self.assertEqual(raw_insert_calls, [True, True, False])

    def test_model_version_and_metric_scaffolding_upserts(self) -> None:
        with session_scope(self.factory) as database_session:
            repository = ModelRepository(database_session)
            version = repository.upsert_version(
                ModelVersionContract(name="expected-input", version="fixture-v1", model_type="interface")
            )
            first = repository.upsert_metric(version.id, "validation", "mae", 1.5)
            second = repository.upsert_metric(version.id, "validation", "mae", 1.25)
            self.assertEqual(first.id, second.id)
            self.assertEqual(second.value, 1.25)

    def test_versioned_feedback_contracts_persist_without_becoming_training_data(self) -> None:
        with session_scope(self.factory) as database_session:
            source = DataSourceRepository(database_session).upsert(
                DataSourceContract(key="feedback-fixture", kind="test", simulator="Fixture Sim")
            )
            session_row = SessionRepository(database_session).upsert_session(
                source.id,
                SessionContract(external_id="feedback-session", simulator="Fixture Sim"),
            )
            run = AnalysisRepository(database_session).create_run(
                session_row.id,
                "fixture-analysis",
                status="completed",
            )
            repository = RecommendationRepository(database_session)
            recommendation = repository.upsert(
                "rec_fixture",
                run.id,
                "Observational fixture hypothesis",
                {"observational_not_causal": True},
            )
            outcome = RecommendationOutcomeV1(
                recommendation_id=recommendation.id,
                observed_lap_key="lap-2",
                comparable=True,
                whole_lap_delta_s=-0.1,
            ).to_contract()
            rating = RecommendationRatingV1(
                recommendation_id=recommendation.id,
                helpful=True,
            ).to_contract()
            stored_outcome = repository.add_outcome(
                outcome.recommendation_id,
                outcome.schema_version,
                outcome.payload,
            )
            stored_rating = repository.add_rating(
                rating.recommendation_id,
                rating.schema_version,
                helpful=rating.helpful,
                reason=rating.reason,
                payload=rating.payload,
            )
            self.assertEqual(stored_outcome.schema_version, "1.0")
            self.assertFalse(stored_outcome.payload["training_eligible"])
            self.assertEqual(stored_rating.helpful, True)
            self.assertFalse(stored_rating.payload["training_eligible"])


if __name__ == "__main__":
    unittest.main()
