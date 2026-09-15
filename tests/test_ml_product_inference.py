from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.ml.inference import MLProductInferenceService
from src.ml.scenario import ScenarioModel
from src.ml.sklearn_model import PacePrediction, ProfilePrediction


class _ProductModel:
    grid_points = 16
    section_count = 4

    def __init__(self, support: float = 0.9):
        self.support = support

    def predict_profiles(self, samples, sections=None):
        expected = samples[
            ["throttle", "brake", "steering", "speed_mps"]
        ].to_numpy(dtype=float)
        width = np.asarray([0.04, 0.04, 0.03, 1.0], dtype=float)
        return ProfilePrediction(expected, expected - width, expected + width)

    def predict_section_pace(self, sections):
        expected = self._section_values(sections)
        return PacePrediction(expected, expected - 0.02, expected + 0.02)

    def predict_lap_pace(self, sections):
        expected = np.asarray([float(self._section_values(sections).sum())])
        return PacePrediction(expected, expected - 0.05, expected + 0.05)

    def support_score(self, sections):
        return np.full(len(sections), self.support)

    def feature_bounds(self, track_key, car_key):
        return {
            key: (0.0, 1.0)
            for key in (
                "brake_onset",
                "min_speed_ratio",
                "throttle_pickup",
                "coasting_fraction",
                "steering_instability",
            )
        }

    def condition_ood_reasons(self, conditions):
        return ["unsupported_wetness"] if conditions.get("wetness", 0) > 0.2 else []

    @staticmethod
    def _section_values(sections):
        return (
            8.0
            + 0.4 * sections["brake_onset"].to_numpy(dtype=float)
            - 0.7 * sections["min_speed_ratio"].to_numpy(dtype=float)
            + 0.3 * sections["throttle_pickup"].to_numpy(dtype=float)
            + 0.4 * sections["coasting_fraction"].to_numpy(dtype=float)
            + 0.5 * sections["steering_instability"].to_numpy(dtype=float)
        )


def _lap_frame(lap_number: int = 1) -> pd.DataFrame:
    progress = np.linspace(0.0, 1.0, 32)
    return pd.DataFrame(
        {
            "TrackProgressNorm": progress,
            "TrackProgressM": progress * 3000.0,
            "ElapsedTimeS": progress * 90.0,
            "SpeedMps": 35.0 - 6.0 * np.sin(progress * np.pi) ** 2,
            "Throttle": np.clip(0.7 + 0.2 * np.cos(progress * 4 * np.pi), 0, 1),
            "Brake": np.clip(np.sin(progress * 4 * np.pi), 0, 1),
            "Steering": 0.2 * np.sin(progress * 2 * np.pi),
            "PositionX": 400.0 * np.cos(progress * 2 * np.pi),
            "PositionZ": 400.0 * np.sin(progress * 2 * np.pi),
            "LapTimeS": 90.0,
            "LapNumber": lap_number,
            "LapIsValid": 1,
        }
    )


class ProductInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MLProductInferenceService(database_factory=None)
        self.model_context = {
            "id": 7,
            "name": "slipstream-pace-profile",
            "version": "fixture-v1",
            "family": "fixture",
            "status": "champion",
            "grid_points": 16,
            "section_count": 4,
            "provenance": "checksummed_registry_champion",
        }
        self.metadata = {
            "sim": "Fixture Sim",
            "track_circuit": "Fixture",
            "track_layout": "GP",
            "car_ordinal": 12,
            "track_length_m": 3000.0,
        }

    def test_no_registry_abstains_without_breaking_analysis_contract(self) -> None:
        result = self.service.infer(
            "session-fixture",
            {1: _lap_frame()},
            session_metadata=self.metadata,
        )
        self.assertTrue(result.abstained)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("model_registry_unavailable", result.abstention_reasons)
        self.assertEqual(result.expected_profiles, {})

    def test_supported_champion_produces_aligned_bands_and_guarded_ideas(self) -> None:
        with patch.object(
            self.service,
            "_load_champion",
            return_value=(_ProductModel(), self.model_context, None),
        ), patch.object(
            self.service,
            "_load_scenario_models",
            return_value=[
                ScenarioModel("sklearn", "fixture-v1", _ProductModel()),
                ScenarioModel("torch", "fixture-v1-torch", _ProductModel()),
            ],
        ):
            result = self.service.infer(
                "session-fixture",
                {1: _lap_frame()},
                session_metadata=self.metadata,
                conditions={"wetness": 0.0},
            )
        self.assertEqual(result.status, "available")
        self.assertFalse(result.abstained)
        profile = result.expected_profiles["1"]
        self.assertEqual(len(profile["points"]), 16)
        self.assertIn("speed", profile["points"][0])
        self.assertEqual(result.dataset["effective_laps"], 1)
        self.assertEqual(len(result.section_pace["1"]), 4)
        self.assertTrue(result.recommendations)
        self.assertFalse(result.recommendations[0]["seconds_saved_claimed"])
        self.assertTrue(result.recommendations[0]["recommendation_id"].startswith("rec_"))
        self.assertEqual(len(result.scenario["models_consulted"]), 2)

    def test_low_support_and_ood_conditions_abstain_clearly(self) -> None:
        with patch.object(
            self.service,
            "_load_champion",
            return_value=(_ProductModel(support=0.1), self.model_context, None),
        ):
            result = self.service.infer(
                "session-fixture",
                {1: _lap_frame()},
                session_metadata=self.metadata,
                conditions={"wetness": 0.5},
            )
        self.assertTrue(result.abstained)
        self.assertEqual(result.expected_profiles, {})
        self.assertIn("unsupported_wetness", result.abstention_reasons)
        self.assertTrue(result.scenario["abstained"])


if __name__ == "__main__":
    unittest.main()
