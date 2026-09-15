from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from fastapi.params import Query
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import ValidationError

from src.api.app import app
from src.api.models import (
    DataHealthResponse,
    ExpectedInputProfile,
    ManualConditionUpdateRequest,
    ModelHealthResponse,
)
from src.api.routes.laps import get_lap
from src.api.routes import ml as ml_routes


class ApiAppTests(unittest.TestCase):
    def test_app_registers_gzip_middleware_with_expected_minimum_size(self) -> None:
        gzip_middlewares = [middleware for middleware in app.user_middleware if middleware.cls is GZipMiddleware]

        self.assertEqual(len(gzip_middlewares), 1)
        self.assertEqual(gzip_middlewares[0].kwargs.get("minimum_size"), 1000)

    def test_lap_route_declares_review_query_params_with_expected_validation(self) -> None:
        signature = inspect.signature(get_lap)
        data_type_query = signature.parameters["data_type"].default
        view_query = signature.parameters["view"].default
        max_points_query = signature.parameters["max_points"].default

        self.assertIsInstance(data_type_query, Query)
        self.assertIsInstance(view_query, Query)
        self.assertIsInstance(max_points_query, Query)

        self.assertEqual(data_type_query.default, "processed")
        self.assertEqual(view_query.default, "full")
        self.assertEqual(max_points_query.default, 1000)
        self.assertIn("^(raw|processed)$", repr(data_type_query.metadata))
        self.assertIn("^(full|review)$", repr(view_query.metadata))
        self.assertIn("ge=100", repr(max_points_query.metadata))
        self.assertIn("le=5000", repr(max_points_query.metadata))

    def test_app_registers_compare_routes(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/compare/laps/candidates", paths)
        self.assertIn("/api/compare/laps", paths)

    def test_app_registers_analysis_routes(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/sessions/{session_id}/analyze", paths)
        self.assertIn("/api/sessions/{session_id}/analysis", paths)
        self.assertIn("/api/sessions/{session_id}/conditions", paths)
        self.assertIn("/api/ml/model-health", paths)
        self.assertIn("/api/ml/data-health", paths)

    def test_app_registers_track_outline_route(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/sessions/{session_id}/track-outline", paths)

    def test_condition_request_enforces_ranges_and_only_returns_supplied_values(self) -> None:
        request = ManualConditionUpdateRequest(wetness=0.25, track_temp_c=32.0)
        self.assertEqual(
            request.supplied(),
            {"wetness": 0.25, "track_temp_c": 32.0},
        )
        with self.assertRaises(ValidationError):
            ManualConditionUpdateRequest(wetness=1.01)
        with self.assertRaises(ValidationError):
            ManualConditionUpdateRequest(track_temp_c=101.0)

    def test_expected_profile_model_accepts_nullable_calibrated_bands(self) -> None:
        profile = ExpectedInputProfile(
            lap_number=2,
            support=0.8,
            points=[
                {
                    "progress_norm": 0.5,
                    "throttle": {"expected": 0.6, "lower": 0.5, "upper": 0.7},
                    "brake": {"expected": None, "lower": None, "upper": None},
                    "steering": {"expected": -0.1, "lower": -0.2, "upper": 0.0},
                    "speed": {"expected": 120.0, "lower": 115.0, "upper": 125.0},
                }
            ],
        )
        self.assertEqual(profile.points[0].speed.upper, 125.0)
        self.assertIsNone(profile.points[0].brake.expected)

    def test_ml_health_routes_return_contract_valid_fallbacks_without_database(self) -> None:
        with patch.object(ml_routes, "get_default_telemetry_store", return_value=None):
            model = ModelHealthResponse(**ml_routes.get_model_health())
            data = DataHealthResponse(**ml_routes.get_data_health())
        self.assertEqual(model.status, "fallback")
        self.assertIn("database_unavailable", model.fallback_reasons)
        self.assertEqual(data.row_count["total"], 0)
        self.assertIn("database_unavailable", data.fallback_reasons)


if __name__ == "__main__":
    unittest.main()
