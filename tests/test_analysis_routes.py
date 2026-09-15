from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src.api.routes import analysis as analysis_routes
from src.api.models import ManualConditionUpdateRequest, RecommendationRatingRequest
from src.api.services import session_scanner


class AnalysisRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp())
        self.raw_root = self.temp_root / "raw"
        self.processed_root = self.temp_root / "processed"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def test_get_session_analysis_normalizes_zero_based_lap_numbers_for_output(self) -> None:
        session_id = "session_analysis_zero_based"
        raw_dir = self.raw_root / session_id
        processed_dir = self.processed_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

        (raw_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "lap_index": {
                        "0": {"first_timestamp_ms": 1000, "last_timestamp_ms": 2000},
                        "1": {"first_timestamp_ms": 3000, "last_timestamp_ms": 4000},
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (processed_dir / "lap_000.csv").write_text("LapTimeS\n80.0\n", encoding="utf-8")
        (processed_dir / "lap_001.csv").write_text("LapTimeS\n81.0\n", encoding="utf-8")
        (processed_dir / "track_outline.json").write_text(
            json.dumps(
                {
                    "outline_version": "test-outline",
                    "session_id": session_id,
                    "source_kind": "session_aggregate",
                    "reference_lap_number": 1,
                    "reference_length_m": 4300.0,
                    "sample_spacing_m": 1.0,
                    "source_lap_numbers": [0, 1],
                    "contributing_lap_count": 2,
                    "points": [
                        {
                            "progress_norm": 0.0,
                            "distance_m": 0.0,
                            "center_x": 0.0,
                            "center_z": 0.0,
                            "left_x": -4.5,
                            "left_z": 0.0,
                            "right_x": 4.5,
                            "right_z": 0.0,
                            "width_m": 9.0,
                        },
                        {
                            "progress_norm": 1.0,
                            "distance_m": 4300.0,
                            "center_x": 100.0,
                            "center_z": 0.0,
                            "left_x": 95.5,
                            "left_z": 0.0,
                            "right_x": 104.5,
                            "right_z": 0.0,
                            "width_m": 9.0,
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (processed_dir / "session_analysis.json").write_text(
            json.dumps(
                {
                    "analysis_version": "test-analysis",
                    "session_id": session_id,
                    "reference_lap_number": 1,
                    "analyzed_at_utc": "2026-04-12T00:00:00Z",
                    "reference_length_m": 4300.0,
                    "corner_definitions": [],
                    "per_corner_records": {
                        "8": [
                            {
                                "lap_number": 0,
                                "corner_id": 8,
                                "sub_corner_records": [{"lap_number": 1, "corner_id": 81}],
                            }
                        ]
                    },
                    "per_corner_baselines": {
                        "8": {
                            "reference_lap_number": 1,
                            "reference_record": {
                                "lap_number": 1,
                                "corner_id": 8,
                                "sub_corner_records": [],
                            },
                            "candidate_lap_numbers": [0, 1],
                        }
                    },
                    "straight_records": [{"straight_id": 1, "lap_number": 0}],
                    "findings_top": [
                        {
                            "finding_id": "finding-top",
                            "corner_id": 8,
                            "lap_number": 0,
                            "detector": "over_slow_mid_corner",
                            "severity": "major",
                            "confidence": 0.9,
                            "time_loss_s": 0.2,
                            "templated_text": "Top finding",
                            "evidence_refs": [],
                            "metrics_snapshot": {},
                        }
                    ],
                    "findings_all": [
                        {
                            "finding_id": "finding-all",
                            "corner_id": 8,
                            "lap_number": 1,
                            "detector": "early_braking",
                            "severity": "moderate",
                            "confidence": 0.7,
                            "time_loss_s": 0.1,
                            "templated_text": "All finding",
                            "evidence_refs": [],
                            "metrics_snapshot": {},
                        }
                    ],
                    "lap_time_delta_reconciliation": {
                        "0": {
                            "sum_corner_delta_s": 0.1,
                            "sum_straight_delta_s": 0.2,
                            "actual_lap_delta_s": 0.3,
                            "residual_s": 0.0,
                            "reference_lap_number": 1,
                        }
                    },
                    "quality_report": {
                        "usable_lap_numbers": [0, 1],
                        "per_lap": {
                            "0": {"corner_count": 14},
                            "1": {"corner_count": 14},
                        },
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with self._patch_data_roots():
            payload = analysis_routes.get_session_analysis(session_id)

        self.assertEqual(payload["reference_lap_number"], 2)
        self.assertEqual(payload["findings_top"][0]["lap_number"], 1)
        self.assertEqual(payload["findings_all"][0]["lap_number"], 2)
        self.assertEqual(payload["straight_records"][0]["lap_number"], 1)
        self.assertEqual(payload["per_corner_records"]["8"][0]["lap_number"], 1)
        self.assertEqual(
            payload["per_corner_records"]["8"][0]["sub_corner_records"][0]["lap_number"],
            2,
        )
        self.assertEqual(payload["per_corner_baselines"]["8"]["reference_lap_number"], 2)
        self.assertEqual(
            payload["per_corner_baselines"]["8"]["reference_record"]["lap_number"],
            2,
        )
        self.assertEqual(
            payload["per_corner_baselines"]["8"]["candidate_lap_numbers"],
            [1, 2],
        )
        self.assertIn("1", payload["lap_time_delta_reconciliation"])
        self.assertNotIn("0", payload["lap_time_delta_reconciliation"])
        self.assertEqual(
            payload["lap_time_delta_reconciliation"]["1"]["reference_lap_number"],
            2,
        )
        self.assertEqual(payload["quality_report"]["usable_lap_numbers"], [1, 2])
        self.assertEqual(sorted(payload["quality_report"]["per_lap"].keys()), ["1", "2"])
        self.assertIsNotNone(payload["track_outline"])
        self.assertEqual(payload["track_outline"]["reference_lap_number"], 2)
        self.assertEqual(payload["track_outline"]["source_lap_numbers"], [1, 2])

    def test_manual_conditions_round_trip_for_filesystem_session(self) -> None:
        session_id = "session_conditions"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True)
        (processed_dir / "metadata.json").write_text(
            json.dumps({"session_id": session_id, "conditions": {"wetness": 0.0}}),
            encoding="utf-8",
        )
        with self._patch_data_roots(), patch.object(
            analysis_routes,
            "get_default_telemetry_store",
            return_value=None,
        ):
            updated = analysis_routes.update_session_conditions(
                session_id,
                ManualConditionUpdateRequest(
                    wetness=0.4,
                    track_temp_c=17.5,
                    tyre_wear=0.2,
                ),
            )
            loaded = analysis_routes.get_session_conditions(session_id)

        self.assertEqual(updated["conditions"]["wetness"], 0.4)
        self.assertEqual(loaded["conditions"]["track_temp_c"], 17.5)
        self.assertEqual(loaded["conditions"]["tyre_wear"], 0.2)

    def test_filesystem_recommendation_rating_round_trip_stays_training_ineligible(self) -> None:
        session_id = "session_ratings"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True)
        recommendation_id = "rec_fixture_idea"
        (processed_dir / "session_analysis.json").write_text(
            json.dumps(
                {
                    "analysis_version": "test-analysis",
                    "session_id": session_id,
                    "reference_lap_number": 1,
                    "analyzed_at_utc": "2026-09-15T00:00:00Z",
                    "ml_context": {
                        "status": "abstained",
                        "recommendations": [
                            {
                                "recommendation_id": recommendation_id,
                                "section_key": "section-3",
                                "feature": "brake_onset",
                                "hypothesis": "Earlier braking is associated with stronger laps.",
                                "cue": "Begin braking slightly earlier.",
                                "learned": True,
                                "confidence": 0.6,
                                "non_quantified_idea": True,
                                "seconds_saved_claimed": False,
                            }
                        ],
                    },
                    "findings_top": [
                        {
                            "finding_id": "finding-rated",
                            "corner_id": 3,
                            "lap_number": 1,
                            "detector": "late_braking",
                            "severity": "moderate",
                            "confidence": 0.7,
                            "time_loss_s": 0.12,
                            "templated_text": "Late braking",
                            "scenario_recommendation": {
                                "recommendation_id": recommendation_id,
                                "section_key": "section-3",
                                "feature": "brake_onset",
                                "hypothesis": "Earlier braking is associated with stronger laps.",
                                "cue": "Begin braking slightly earlier.",
                                "learned": True,
                                "confidence": 0.6,
                                "non_quantified_idea": True,
                                "seconds_saved_claimed": False,
                            },
                        }
                    ],
                    "findings_all": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with self._patch_data_roots(), patch.object(
            analysis_routes,
            "get_default_telemetry_store",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as get_error:
                analysis_routes.get_recommendation_rating(session_id, recommendation_id)
            self.assertEqual(get_error.exception.status_code, 404)
            stored = analysis_routes.rate_recommendation(
                session_id,
                recommendation_id,
                RecommendationRatingRequest(
                    helpful=True, reason="  earlier brake felt better  "
                ),
            )
            loaded = analysis_routes.get_recommendation_rating(
                session_id, recommendation_id
            )
            analysis = analysis_routes.get_session_analysis(session_id)

        self.assertEqual(stored["helpful"], True)
        self.assertEqual(stored["reason"], "earlier brake felt better")
        self.assertFalse(stored["training_eligible"])
        self.assertEqual(loaded["recommendation_id"], recommendation_id)
        self.assertEqual(
            analysis["findings_top"][0]["scenario_recommendation"]["rating"]["helpful"],
            True,
        )
        self.assertFalse(
            analysis["ml_context"]["recommendations"][0]["rating"]["training_eligible"]
        )
        self.assertTrue((processed_dir / "recommendation_ratings.json").is_file())

    def _patch_data_roots(self):
        stack = ExitStack()
        stack.enter_context(
            patch.multiple(
                session_scanner,
                RAW_DATA_ROOT=self.raw_root,
                PROCESSED_DATA_ROOT=self.processed_root,
            )
        )
        stack.enter_context(
            patch.object(
                analysis_routes,
                "PROCESSED_DATA_ROOT",
                self.processed_root,
            )
        )
        return stack


if __name__ == "__main__":
    unittest.main()
