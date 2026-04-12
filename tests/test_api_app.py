from __future__ import annotations

import inspect
import unittest

from fastapi.params import Query
from fastapi.middleware.gzip import GZipMiddleware

from src.api.app import app
from src.api.routes.laps import get_lap


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


if __name__ == "__main__":
    unittest.main()
