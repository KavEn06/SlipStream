from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from src.core.telemetry import (
    DataSourceContract,
    LapContract,
    ProcessedTelemetryContract,
    SessionContract,
)
from src.db import models
from src.db.repositories import (
    CatalogRepository,
    DataSourceRepository,
    SessionRepository,
    TelemetryRepository,
)
from src.db.session import (
    create_database_engine,
    create_schema,
    create_session_factory,
    session_scope,
)
from src.ml.cli import build_parser
from src.ml.dataset import (
    ACTIONABLE_FEATURES,
    TelemetryDatasetBuilder,
    grouped_cv_splits,
    immutable_group_split,
)
from src.ml.evaluation import evaluate_predictions, evaluate_sklearn_model
from src.ml.experiment import ExperimentConfig, OfflineExperimentRunner
from src.ml.feedback import (
    OUTCOME_SCHEMA_VERSION,
    RATING_SCHEMA_VERSION,
    RecommendationOutcomeV1,
    RecommendationRatingV1,
    validate_feedback_schema,
)
from src.ml.registry import ModelRegistry, sha256_file
from src.ml.scenario import GuardedScenarioScorer, ScenarioModel
from src.ml.sklearn_model import PacePrediction, SklearnProfileModel
from src.ml.torch_model import TorchSequenceModel


def synthetic_dataset(laps: int = 10):
    frames = {}
    metadata = {}
    progress = np.linspace(0.0, 1.0, 48)
    for lap_index in range(laps):
        lap_key = "lap-{0}".format(lap_index)
        lap_time = 88.0 + lap_index * 0.7
        radius = 500.0
        throttle = np.clip(
            0.58 + 0.30 * np.cos(4.0 * np.pi * progress) - lap_index * 0.004,
            0.0,
            1.0,
        )
        brake = np.clip(0.75 * np.sin(4.0 * np.pi * progress), 0.0, 1.0)
        steering = 0.28 * np.sin(2.0 * np.pi * progress)
        speed = (
            42.0
            - 13.0 * np.maximum(np.sin(4.0 * np.pi * progress), 0.0)
            - lap_index * 0.12
        )
        frames[lap_key] = pd.DataFrame(
            {
                "TrackProgressNorm": progress,
                "NormalizedDistance": progress,
                "TrackProgressM": progress * 3100.0,
                "ElapsedTimeS": progress * lap_time,
                "SpeedMps": speed,
                "Throttle": throttle,
                "Brake": brake,
                "Steering": steering,
                "PositionX": radius * np.cos(2.0 * np.pi * progress),
                "PositionZ": radius * np.sin(2.0 * np.pi * progress),
                "LapTimeS": lap_time,
                "LapIsValid": 1,
                "LapNumber": lap_index + 1,
            }
        )
        metadata[lap_key] = {
            "session_key": "session-{0}".format(lap_index // 2),
            "lap_number": lap_index + 1,
            "lap_time_s": lap_time,
            "is_valid": True,
            "simulator": "Synthetic Sim",
            "track_key": "synthetic-track",
            "car_key": "synthetic-car",
            "track_length_m": 3100.0,
            "conditions": {
                "wetness": 0.0,
                "air_temp_c": 20.0 + lap_index * 0.1,
                "track_temp_c": 29.0 + lap_index * 0.1,
                "tyre_wear": min(lap_index * 0.01, 0.2),
            },
        }
    return TelemetryDatasetBuilder(grid_points=24, section_count=4).from_processed_laps(
        frames,
        metadata=metadata,
        source_revisions={"synthetic": "fixture-v1"},
    )


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = synthetic_dataset()

    def test_builder_creates_aligned_views_and_faster_lap_weights(self) -> None:
        self.assertEqual(self.dataset.effective_lap_count, 10)
        self.assertEqual(self.dataset.sample_row_count, 240)
        self.assertTrue(
            set(ACTIONABLE_FEATURES).issubset(self.dataset.section_frame.columns)
        )
        weights = self.dataset.lap_frame.set_index("lap_key")["sample_weight"]
        self.assertGreater(weights["lap-0"], weights["lap-9"])
        self.assertEqual(
            self.dataset.section_frame.groupby("lap_key").size().unique().tolist(),
            [4],
        )

    def test_immutable_session_holdout_and_grouped_cv_do_not_leak_rows(self) -> None:
        first = immutable_group_split(self.dataset, holdout_fraction=0.25)
        second = immutable_group_split(self.dataset, holdout_fraction=0.25)
        self.assertEqual(first, second)
        self.assertTrue(set(first.train_groups).isdisjoint(first.holdout_groups))
        self.assertTrue(
            set(first.train_lap_keys).isdisjoint(first.holdout_lap_keys)
        )
        train = self.dataset.subset(first.train_lap_keys)
        for training_keys, validation_keys in grouped_cv_splits(train, n_splits=2):
            self.assertTrue(set(training_keys).isdisjoint(validation_keys))
            train_sessions = set(
                train.lap_frame[
                    train.lap_frame["lap_key"].isin(training_keys)
                ]["session_key"]
            )
            validation_sessions = set(
                train.lap_frame[
                    train.lap_frame["lap_key"].isin(validation_keys)
                ]["session_key"]
            )
            self.assertTrue(train_sessions.isdisjoint(validation_sessions))

    def test_interval_calibration_metrics_use_all_profile_targets(self) -> None:
        samples = self.dataset.sample_frame.reset_index(drop=True)
        actual = samples[["throttle", "brake", "steering", "speed_mps"]].to_numpy(dtype=float)
        lower = actual.copy()
        upper = actual.copy()
        lower[::2] = actual[::2] + 1.0
        upper[::2] = actual[::2] + 2.0
        metrics = evaluate_predictions(
            self.dataset,
            profile_expected=actual,
            profile_lower=lower,
            profile_upper=upper,
            section_expected=self.dataset.section_frame["section_time_s"].to_numpy(dtype=float),
            lap_expected=self.dataset.lap_frame["lap_time_s"].to_numpy(dtype=float),
        )
        self.assertAlmostEqual(metrics["interval_coverage"], 0.5)
        for target in ("throttle", "brake", "steering", "speed_mps"):
            self.assertAlmostEqual(metrics["{0}_interval_coverage".format(target)], 0.5)
            self.assertAlmostEqual(metrics["{0}_mae".format(target)], 0.0)

    def test_database_builder_reads_processed_laps(self) -> None:
        engine = create_database_engine("sqlite+pysqlite:///:memory:")
        create_schema(engine)
        factory = create_session_factory(engine)
        try:
            with session_scope(factory) as database_session:
                source = DataSourceRepository(database_session).upsert(
                    DataSourceContract(
                        key="ml-db-fixture",
                        kind="test",
                        simulator="Synthetic Sim",
                        revision="abc123",
                    )
                )
                track = CatalogRepository(database_session).upsert_track(
                    identity_key="track:fixture",
                    simulator="Synthetic Sim",
                    circuit="Fixture",
                    length_m=3000.0,
                )
                car = CatalogRepository(database_session).upsert_car(
                    identity_key="car:fixture",
                    simulator="Synthetic Sim",
                    model="Fixture",
                )
                stored_session = SessionRepository(database_session).upsert_session(
                    source.id,
                    SessionContract(
                        external_id="ml-session",
                        simulator="Synthetic Sim",
                    ),
                    track_id=track.id,
                    car_id=car.id,
                )
                SessionRepository(database_session).add_condition(
                    stored_session.id,
                    scope="session",
                    origin="manual",
                    kind="track_temp_c",
                    value={"value": 31.5},
                )
                for lap_number in (1, 2):
                    lap = SessionRepository(database_session).upsert_lap(
                        stored_session.id,
                        LapContract(
                            lap_number=lap_number,
                            source_lap_key="lap-{0}".format(lap_number),
                            duration_s=90.0 + lap_number,
                            is_valid=True,
                        ),
                    )
                    samples = [
                        ProcessedTelemetryContract(
                            sample_index=index,
                            progress=float(progress),
                            elapsed_s=float(progress * (90.0 + lap_number)),
                            distance_m=float(progress * 3000.0),
                            speed_mps=35.0 - 3.0 * np.sin(progress * np.pi),
                            throttle=float(0.5 + 0.3 * np.cos(progress * 2 * np.pi)),
                            brake=float(max(0.0, np.sin(progress * 2 * np.pi))),
                            steering=float(0.2 * np.sin(progress * 2 * np.pi)),
                            features={
                                "PositionX": float(np.cos(progress * 2 * np.pi) * 400),
                                "PositionZ": float(np.sin(progress * 2 * np.pi) * 400),
                            },
                        )
                        for index, progress in enumerate(np.linspace(0.0, 1.0, 24))
                    ]
                    TelemetryRepository(database_session).bulk_upsert_processed(
                        lap.id, "fixture-v1", samples
                    )
                dataset = TelemetryDatasetBuilder(
                    grid_points=16, section_count=4
                ).from_database(database_session)
                self.assertEqual(dataset.effective_lap_count, 2)
                self.assertEqual(dataset.source_revisions["ml-db-fixture"], "abc123")
                self.assertTrue((dataset.sample_frame["track_temp_c"] == 31.5).all())
        finally:
            engine.dispose()


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = synthetic_dataset()

    def test_sklearn_model_predicts_bounded_profiles_pace_and_support(self) -> None:
        model = SklearnProfileModel(
            random_state=7,
            n_estimators=24,
            max_depth=8,
            min_samples_leaf=2,
        ).fit(self.dataset)
        prediction = model.predict_profiles(self.dataset.sample_frame)
        self.assertEqual(prediction.expected.shape, (240, 4))
        self.assertTrue(np.all(prediction.lower <= prediction.expected))
        self.assertTrue(np.all(prediction.expected <= prediction.upper))
        self.assertTrue(np.all((prediction.expected[:, 0] >= 0.0)))
        self.assertTrue(np.all((prediction.expected[:, 0] <= 1.0)))
        metrics = evaluate_sklearn_model(model, self.dataset)
        self.assertTrue(np.isfinite(metrics["composite_score"]))
        support = model.support_score(self.dataset.section_frame.iloc[:2])
        self.assertTrue(np.all((support >= 0.0) & (support <= 1.0)))

    def test_torch_sequence_model_trains_predicts_and_round_trips(self) -> None:
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("PyTorch is optional")
        train = self.dataset.subset(self.dataset.lap_keys[:8])
        validation = self.dataset.subset(self.dataset.lap_keys[8:])
        model = TorchSequenceModel(
            random_state=11,
            hidden_size=16,
            max_epochs=3,
            patience=2,
            batch_size=4,
            mc_passes=3,
        ).fit(train, validation)
        prediction = model.predict_dataset(validation)
        self.assertEqual(prediction.profiles.expected.shape, (48, 4))
        self.assertEqual(prediction.section_pace.expected.shape, (8,))
        self.assertEqual(prediction.lap_pace.expected.shape, (2,))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.pt"
            model.save(path)
            restored = TorchSequenceModel.load(path)
            restored_prediction = restored.predict_dataset(
                validation, include_uncertainty=False
            )
        self.assertEqual(restored_prediction.profiles.expected.shape, (48, 4))


class ExperimentRegistryTests(unittest.TestCase):
    def test_offline_runner_registers_metrics_predictions_and_loadable_champion(self) -> None:
        dataset = synthetic_dataset()
        engine = create_database_engine("sqlite+pysqlite:///:memory:")
        create_schema(engine)
        factory = create_session_factory(engine)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                with session_scope(factory) as database_session:
                    result = OfflineExperimentRunner(
                        Path(temporary),
                        config=ExperimentConfig(
                            seed=19,
                            cv_folds=2,
                            sklearn_search_budget=1,
                            include_torch=False,
                            sklearn_estimators=24,
                        ),
                    ).run(dataset, database_session)
                    self.assertEqual(result.sample_rows, 240)
                    self.assertEqual(result.effective_laps, 10)
                    champion = ModelRegistry(
                        database_session, Path(temporary)
                    ).champion_row()
                    self.assertIsNotNone(champion)
                    assert champion is not None
                    loaded = ModelRegistry(
                        database_session, Path(temporary)
                    ).load_champion()
                    self.assertIsInstance(loaded, SklearnProfileModel)
                    artifact_path = Path(champion.artifact_uri.replace("file://", ""))
                    self.assertEqual(sha256_file(artifact_path), champion.checksum)
                    metric_count = database_session.scalar(
                        select(func.count()).select_from(models.ModelMetric)
                    )
                    prediction_count = database_session.scalar(
                        select(func.count()).select_from(models.PredictionProfile)
                    )
                    self.assertGreater(metric_count, 0)
                    self.assertEqual(prediction_count, 1)
        finally:
            engine.dispose()

    def test_fixed_seed_reproduces_grouped_cv_and_holdout_metrics(self) -> None:
        dataset = synthetic_dataset()
        observed = []
        for _ in range(2):
            engine = create_database_engine("sqlite+pysqlite:///:memory:")
            create_schema(engine)
            factory = create_session_factory(engine)
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    with session_scope(factory) as database_session:
                        result = OfflineExperimentRunner(
                            Path(temporary),
                            config=ExperimentConfig(
                                seed=31,
                                cv_folds=2,
                                sklearn_search_budget=1,
                                include_torch=False,
                                sklearn_estimators=24,
                            ),
                        ).run(dataset, database_session)
                        observed.append(result)
            finally:
                engine.dispose()
        self.assertEqual(observed[0].split, observed[1].split)
        self.assertAlmostEqual(
            observed[0].candidates[0].cv_composite_score,
            observed[1].candidates[0].cv_composite_score,
            places=12,
        )
        self.assertEqual(
            observed[0].candidates[0].holdout_metrics,
            observed[1].candidates[0].holdout_metrics,
        )

    def test_cli_exposes_training_and_champion_commands(self) -> None:
        parser = build_parser()
        train = parser.parse_args(["train", "--no-torch"])
        champion = parser.parse_args(["champion"])
        self.assertEqual(train.command, "train")
        self.assertTrue(train.no_torch)
        self.assertEqual(champion.command, "champion")


class _ScenarioFamily:
    def __init__(self, lap_min_speed_penalty: float):
        self.lap_min_speed_penalty = lap_min_speed_penalty

    def predict_section_pace(self, sections):
        expected = (
            8.0
            + 0.4 * sections["brake_onset"].to_numpy()
            - 0.7 * sections["min_speed_ratio"].to_numpy()
            + 0.3 * sections["throttle_pickup"].to_numpy()
            + 0.4 * sections["coasting_fraction"].to_numpy()
            + 0.5 * sections["steering_instability"].to_numpy()
        )
        return PacePrediction(expected, expected - 0.02, expected + 0.02)

    def predict_lap_pace(self, sections):
        expected = np.asarray(
            [
                80.0
                + 0.2 * sections["brake_onset"].sum()
                + self.lap_min_speed_penalty * sections["min_speed_ratio"].sum()
                + 0.2 * sections["throttle_pickup"].sum()
                + 0.3 * sections["coasting_fraction"].sum()
                + 0.2 * sections["steering_instability"].sum()
            ]
        )
        return PacePrediction(expected, expected - 0.05, expected + 0.05)

    def support_score(self, sections):
        return np.full(len(sections), 0.9)

    def feature_bounds(self, track_key, car_key):
        return {feature: (0.0, 1.0) for feature in ACTIONABLE_FEATURES}

    def condition_ood_reasons(self, conditions):
        return []


class ScenarioAndFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = synthetic_dataset()
        cls.samples = cls.dataset.sample_frame[
            cls.dataset.sample_frame["lap_key"] == "lap-0"
        ].copy()
        cls.sections = cls.dataset.section_frame[
            cls.dataset.section_frame["lap_key"] == "lap-0"
        ].copy()
        cls.scorer = GuardedScenarioScorer(
            [
                ScenarioModel("family-a", "v1", _ScenarioFamily(1.5)),
                ScenarioModel("family-b", "v2", _ScenarioFamily(1.7)),
            ],
            maximum_disagreement=1.5,
        )

    def test_scenario_requires_support_agreement_and_whole_lap_veto(self) -> None:
        result = self.scorer.score(self.samples, self.sections, conditions={})
        min_speed = [
            assessment
            for assessment in result.assessments
            if assessment.feature == "min_speed_ratio"
        ]
        self.assertTrue(min_speed)
        self.assertTrue(
            all(item.rejection_reason == "whole_lap_veto" for item in min_speed)
        )
        self.assertTrue(result.recommendations)
        recommendation = result.recommendations[0]
        self.assertTrue(recommendation.recommendation_id.startswith("rec_"))
        self.assertTrue(
            recommendation.provenance["section_and_whole_lap_veto_passed"]
        )
        self.assertLessEqual(
            abs(recommendation.perturbation["magnitude"]),
            recommendation.provenance["human_achievable_bound"],
        )

    def test_unsupported_wet_condition_abstains_with_deterministic_fallback(self) -> None:
        first = self.scorer.score(
            self.samples, self.sections, conditions={"wetness": 0.8}
        )
        second = self.scorer.score(
            self.samples, self.sections, conditions={"wetness": 0.8}
        )
        self.assertTrue(first.abstained)
        self.assertFalse(first.recommendations[0].learned)
        self.assertEqual(
            first.recommendations[0].recommendation_id,
            second.recommendations[0].recommendation_id,
        )
        self.assertNotIn("wider", first.recommendations[0].cue.lower())

    def test_inconsistent_driver_receives_smaller_personalized_perturbations(self) -> None:
        consistent = self.sections.copy()
        inconsistent = self.sections.copy()
        consistent["driver_consistency"] = 0.0
        inconsistent["driver_consistency"] = 0.20
        consistent_result = self.scorer.score(self.samples, consistent, conditions={})
        inconsistent_result = self.scorer.score(self.samples, inconsistent, conditions={})

        def min_speed_magnitudes(result):
            return [
                abs(item.proposed_value - item.baseline_value)
                for item in result.assessments
                if item.feature == "min_speed_ratio"
            ]

        consistent_magnitudes = min_speed_magnitudes(consistent_result)
        inconsistent_magnitudes = min_speed_magnitudes(inconsistent_result)
        self.assertTrue(consistent_magnitudes)
        self.assertEqual(len(consistent_magnitudes), len(inconsistent_magnitudes))
        self.assertTrue(
            all(
                cautious < normal
                for normal, cautious in zip(
                    consistent_magnitudes, inconsistent_magnitudes
                )
            )
        )

    def test_feedback_contracts_are_versioned_and_not_training_eligible(self) -> None:
        outcome = RecommendationOutcomeV1(
            recommendation_id="rec_fixture",
            observed_lap_key="lap-2",
            comparable=True,
            whole_lap_delta_s=-0.2,
        ).to_contract()
        rating = RecommendationRatingV1(
            recommendation_id="rec_fixture",
            helpful=True,
        ).to_contract()
        self.assertEqual(outcome.schema_version, OUTCOME_SCHEMA_VERSION)
        self.assertEqual(rating.schema_version, RATING_SCHEMA_VERSION)
        self.assertFalse(outcome.payload["training_eligible"])
        self.assertFalse(rating.payload["training_eligible"])
        self.assertEqual(
            set(outcome.payload),
            {
                "observed_lap_key",
                "comparable",
                "section_delta_s",
                "whole_lap_delta_s",
                "comparison_context",
                "training_eligible",
            },
        )
        self.assertEqual(
            set(rating.payload),
            {"context", "training_eligible"},
        )
        validate_feedback_schema("1.0", "outcome")
        validate_feedback_schema("1.0", "rating")
        with self.assertRaises(ValueError):
            validate_feedback_schema("2.0", "rating")
        with self.assertRaises(ValueError):
            validate_feedback_schema("1.0", "unknown")


if __name__ == "__main__":
    unittest.main()
