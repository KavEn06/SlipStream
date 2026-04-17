from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.api.services import session_scanner
from src.core.schemas import LAP_CLOSE_REASON_LAP_ROLLOVER, RAW_LAP_COLUMNS
from src.processing.distance import build_processed_lap_dataframe


def build_raw_lap_dataframe(
    sample_count: int = 25,
    lap_number: int = 1,
    start_timestamp_ms: int = 1000,
    timestamp_step_ms: int = 50,
    start_current_lap_s: float = 0.0,
    current_lap_step_s: float = 0.25,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for index in range(sample_count):
        rows.append(
            {
                "IsRaceOn": 1,
                "TimestampMS": start_timestamp_ms + (index * timestamp_step_ms),
                "EngineMaxRpm": 8000.0,
                "EngineIdleRpm": 900.0,
                "CurrentEngineRpm": 4200.0 + (index * 15.0),
                "CarOrdinal": 12,
                "PositionX": float(index * 3.0),
                "PositionY": 0.0,
                "PositionZ": float(index) * 0.2,
                "Speed": 30.0 + (index * 0.75),
                "Power": 150.0 + index,
                "Torque": 220.0,
                "Boost": 0.2,
                "DistanceTraveled": float(index * 3.0),
                "BestLap": 85.0,
                "LastLap": 86.0,
                "CurrentLap": start_current_lap_s + (index * current_lap_step_s),
                "CurrentRaceTime": 50.0 + ((start_timestamp_ms + (index * timestamp_step_ms)) / 1000.0),
                "LapNumber": lap_number,
                "Accel": min(255, 160 + (index * 2)),
                "Brake": max(0, 12 - index),
                "Clutch": 0,
                "HandBrake": 0,
                "Gear": 3 if index < (sample_count // 2) else 4,
                "Steer": max(-20, min(20, index - (sample_count // 2))),
                "TrackOrdinal": 0,
            }
        )
    return pd.DataFrame(rows, columns=RAW_LAP_COLUMNS)


class SessionScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp())
        self.raw_root = self.temp_root / "raw"
        self.processed_root = self.temp_root / "processed"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def test_raw_only_session_detail_uses_metadata_lap_time_and_leaves_validity_unknown(self) -> None:
        session_id = "session_raw_only"
        session_dir = self.raw_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe()
        raw_df.to_csv(session_dir / "lap_001.csv", index=False)
        self._write_metadata(
            session_dir,
            track_circuit="Rio de Janeiro",
            track_layout="Full Circuit",
            track_location="Rio de Janeiro, Brazil",
            first_timestamp_ms=int(raw_df["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        with self._patch_data_roots():
            detail = session_scanner.get_session_detail(session_id)

        self.assertIsNotNone(detail)
        self.assertEqual(detail["track_layout"], "Full Circuit")
        self.assertEqual(detail["track_location"], "Rio de Janeiro, Brazil")
        self.assertFalse(detail["has_processed"])
        self.assertEqual(len(detail["laps"]), 1)
        self.assertAlmostEqual(detail["laps"][0]["lap_time_s"], 1.2, places=6)
        self.assertIsNone(detail["laps"][0]["is_valid"])

    def test_raw_only_session_detail_does_not_infer_invalidity_before_processing(self) -> None:
        session_id = "session_raw_invalid"
        session_dir = self.raw_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(start_current_lap_s=3.5)
        raw_df.to_csv(session_dir / "lap_001.csv", index=False)
        self._write_metadata(
            session_dir,
            track_circuit="Rio de Janeiro",
            track_layout="Full Circuit",
            track_location="Rio de Janeiro, Brazil",
            first_timestamp_ms=int(raw_df["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        with self._patch_data_roots():
            detail = session_scanner.get_session_detail(session_id)

        self.assertIsNotNone(detail)
        self.assertAlmostEqual(detail["laps"][0]["lap_time_s"], 1.2, places=6)
        self.assertIsNone(detail["laps"][0]["is_valid"])

    def test_update_session_metadata_persists_display_name_for_raw_and_processed(self) -> None:
        session_id = "session_renameable"
        raw_dir = self.raw_root / session_id
        processed_dir = self.processed_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

        self._write_metadata(
            raw_dir,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=1000,
            last_timestamp_ms=2200,
        )
        self._write_metadata(
            processed_dir,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=1000,
            last_timestamp_ms=2200,
        )

        with self._patch_data_roots():
            detail = session_scanner.update_session_metadata(
                session_id,
                display_name="Evening Suzuka Run",
            )

        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["display_name"], "Evening Suzuka Run")
        self.assertEqual(
            json.loads((raw_dir / "metadata.json").read_text(encoding="utf-8"))["display_name"],
            "Evening Suzuka Run",
        )
        self.assertEqual(
            json.loads((processed_dir / "metadata.json").read_text(encoding="utf-8"))["display_name"],
            "Evening Suzuka Run",
        )

        with self._patch_data_roots():
            cleared_detail = session_scanner.update_session_metadata(
                session_id,
                display_name="   ",
            )

        self.assertIsNotNone(cleared_detail)
        assert cleared_detail is not None
        self.assertIsNone(cleared_detail["display_name"])
        self.assertNotIn(
            "display_name",
            json.loads((raw_dir / "metadata.json").read_text(encoding="utf-8")),
        )
        self.assertNotIn(
            "display_name",
            json.loads((processed_dir / "metadata.json").read_text(encoding="utf-8")),
        )

    def test_processed_session_detail_uses_metadata_lap_time_before_csv_summary(self) -> None:
        session_id = "session_processed_summary"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            {
                "LapTimeS": [float("nan"), 19.876],
                "LapIsValid": [float("nan"), 1],
            }
        ).to_csv(processed_dir / "lap_001.csv", index=False)
        self._write_metadata(
            processed_dir,
            track_circuit="Silverstone",
            track_layout="Grand Prix",
            track_location="Silverstone, UK",
            first_timestamp_ms=1000,
            last_timestamp_ms=82234,
        )

        with self._patch_data_roots():
            detail = session_scanner.get_session_detail(session_id)

        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["laps"]), 1)
        self.assertAlmostEqual(detail["laps"][0]["lap_time_s"], 81.234, places=6)
        self.assertTrue(detail["laps"][0]["is_valid"])

    def test_session_detail_falls_back_to_metadata_lap_time_when_summary_is_missing(self) -> None:
        session_id = "session_metadata_fallback"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            {
                "LapTimeS": [float("nan"), float("nan")],
                "LapIsValid": [1, 1],
            }
        ).to_csv(processed_dir / "lap_001.csv", index=False)
        self._write_metadata(
            processed_dir,
            track_circuit="Silverstone",
            track_layout="Grand Prix",
            track_location="Silverstone, UK",
            first_timestamp_ms=1000,
            last_timestamp_ms=83123,
        )

        with self._patch_data_roots():
            detail = session_scanner.get_session_detail(session_id)

        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["laps"]), 1)
        self.assertAlmostEqual(detail["laps"][0]["lap_time_s"], 82.123, places=6)

    def test_session_detail_normalizes_zero_based_lap_numbers_for_output(self) -> None:
        session_id = "session_zero_based_output"
        raw_dir = self.raw_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)

        first_lap_df = build_raw_lap_dataframe(lap_number=0)
        second_lap_df = build_raw_lap_dataframe(lap_number=1, start_timestamp_ms=3000)
        first_lap_df.to_csv(raw_dir / "lap_000.csv", index=False)
        second_lap_df.to_csv(raw_dir / "lap_001.csv", index=False)
        metadata = {
            "session_id": session_id,
            "schema_version": "test-schema",
            "sim": "Forza Motorsport 7",
            "lap_index": {
                "0": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": int(first_lap_df["TimestampMS"].iloc[0]),
                    "last_timestamp_ms": int(first_lap_df["TimestampMS"].iloc[-1]),
                },
                "1": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": int(second_lap_df["TimestampMS"].iloc[0]),
                    "last_timestamp_ms": int(second_lap_df["TimestampMS"].iloc[-1]),
                },
            },
        }
        (raw_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        with self._patch_data_roots():
            detail = session_scanner.get_session_detail(session_id)

        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual([lap["lap_number"] for lap in detail["laps"]], [1, 2])

    def test_get_lap_data_resolves_display_lap_number_to_zero_based_file(self) -> None:
        session_id = "session_zero_based_get"
        raw_dir = self.raw_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(lap_number=0)
        raw_df.to_csv(raw_dir / "lap_000.csv", index=False)
        metadata = {
            "session_id": session_id,
            "lap_index": {
                "0": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": int(raw_df["TimestampMS"].iloc[0]),
                    "last_timestamp_ms": int(raw_df["TimestampMS"].iloc[-1]),
                },
            },
        }
        (raw_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        with self._patch_data_roots():
            result = session_scanner.get_lap_data(session_id, 1, "raw")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["lap_number"], 1)
        self.assertEqual(len(result["records"]), len(raw_df))
        self.assertAlmostEqual(float(result["records"][0]["CurrentLap"]), float(raw_df["CurrentLap"].iloc[0]), places=6)

    def test_delete_lap_resolves_display_lap_number_to_zero_based_file(self) -> None:
        session_id = "session_zero_based_delete"
        raw_dir = self.raw_root / session_id
        processed_dir = self.processed_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(lap_number=0)
        processed_df = build_processed_lap_dataframe(raw_df, session_id=session_id)
        raw_df.to_csv(raw_dir / "lap_000.csv", index=False)
        processed_df.to_csv(processed_dir / "lap_000.csv", index=False)
        metadata = {
            "session_id": session_id,
            "total_laps": 1,
            "lap_index": {
                "0": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": int(raw_df["TimestampMS"].iloc[0]),
                    "last_timestamp_ms": int(raw_df["TimestampMS"].iloc[-1]),
                },
            },
        }
        (raw_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (processed_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        with self._patch_data_roots():
            deleted = session_scanner.delete_lap(session_id, 1)

        self.assertTrue(deleted)
        self.assertFalse((raw_dir / "lap_000.csv").exists())
        self.assertFalse((processed_dir / "lap_000.csv").exists())

    def test_get_processed_lap_data_full_view_returns_full_rows_with_summary_and_sampling(self) -> None:
        session_id = "session_processed_full_view"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(sample_count=250)
        processed_df = build_processed_lap_dataframe(raw_df, session_id=session_id)
        processed_df.to_csv(processed_dir / "lap_001.csv", index=False)

        with self._patch_data_roots():
            result = session_scanner.get_lap_data(
                session_id,
                1,
                "processed",
                view=session_scanner.LAP_VIEW_FULL,
                max_points=200,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["columns"], list(processed_df.columns))
        self.assertEqual(len(result["records"]), len(processed_df))
        self.assertEqual(result["sampling"]["view"], session_scanner.LAP_VIEW_FULL)
        self.assertEqual(result["sampling"]["source_rows"], len(processed_df))
        self.assertEqual(result["sampling"]["returned_rows"], len(processed_df))
        self.assertIsNone(result["sampling"]["max_points"])
        self.assertEqual(result["sampling"]["x_key"], "ElapsedTimeS")
        self.assertAlmostEqual(result["summary"]["lap_time_s"], float(processed_df["LapTimeS"].iloc[-1]), places=6)
        self.assertTrue(result["summary"]["lap_is_valid"])

    def test_get_processed_lap_data_review_view_downsamples_and_uses_full_summary(self) -> None:
        session_id = "session_processed_review_view"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(sample_count=2500, current_lap_step_s=0.02)
        processed_df = build_processed_lap_dataframe(raw_df, session_id=session_id)
        processed_df["LapTimeS"] = float("nan")
        processed_df.loc[len(processed_df) - 1, "LapTimeS"] = 91.234
        processed_df.to_csv(processed_dir / "lap_001.csv", index=False)

        with self._patch_data_roots():
            result = session_scanner.get_lap_data(
                session_id,
                1,
                "processed",
                view=session_scanner.LAP_VIEW_REVIEW,
                max_points=200,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result["columns"],
            [
                "ElapsedTimeS",
                "NormalizedDistance",
                "CumulativeDistanceM",
                "PositionX",
                "PositionY",
                "PositionZ",
                "SpeedKph",
                "Throttle",
                "Brake",
                "Steering",
            ],
        )
        self.assertLessEqual(len(result["records"]), 200)
        self.assertEqual(result["sampling"]["view"], session_scanner.LAP_VIEW_REVIEW)
        self.assertEqual(result["sampling"]["source_rows"], len(processed_df))
        self.assertEqual(result["sampling"]["returned_rows"], len(result["records"]))
        self.assertEqual(result["sampling"]["max_points"], 200)
        self.assertEqual(result["sampling"]["x_key"], "ElapsedTimeS")
        self.assertAlmostEqual(result["summary"]["lap_time_s"], 91.234, places=6)
        self.assertTrue(result["summary"]["lap_is_valid"])
        self.assertAlmostEqual(float(result["records"][0]["ElapsedTimeS"]), 0.0, places=6)
        self.assertAlmostEqual(
            float(result["records"][-1]["ElapsedTimeS"]),
            float(processed_df["ElapsedTimeS"].iloc[-1]),
            places=6,
        )

    def test_get_raw_lap_data_review_view_returns_raw_chart_columns_and_summary(self) -> None:
        session_id = "session_raw_review_view"
        raw_dir = self.raw_root / session_id
        raw_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe(sample_count=2500, current_lap_step_s=0.02)
        raw_df.to_csv(raw_dir / "lap_001.csv", index=False)

        with self._patch_data_roots():
            result = session_scanner.get_lap_data(
                session_id,
                1,
                "raw",
                view=session_scanner.LAP_VIEW_REVIEW,
                max_points=150,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["columns"], ["CurrentLap", "Speed", "Accel", "Brake", "Steer"])
        self.assertLessEqual(len(result["records"]), 150)
        self.assertEqual(result["sampling"]["view"], session_scanner.LAP_VIEW_REVIEW)
        self.assertEqual(result["sampling"]["source_rows"], len(raw_df))
        self.assertEqual(result["sampling"]["returned_rows"], len(result["records"]))
        self.assertEqual(result["sampling"]["max_points"], 150)
        self.assertEqual(result["sampling"]["x_key"], "CurrentLap")
        self.assertAlmostEqual(result["summary"]["lap_time_s"], float(raw_df["CurrentLap"].iloc[-1]), places=6)
        self.assertIsNone(result["summary"]["lap_is_valid"])
        self.assertAlmostEqual(float(result["records"][0]["CurrentLap"]), float(raw_df["CurrentLap"].iloc[0]), places=6)
        self.assertAlmostEqual(float(result["records"][-1]["CurrentLap"]), float(raw_df["CurrentLap"].iloc[-1]), places=6)

    def test_get_compare_candidates_filters_to_same_track_and_alignment_usable_laps(self) -> None:
        seed_session_id = "session_compare_seed"
        usable_peer_session_id = "session_compare_peer"
        unusable_peer_session_id = "session_compare_unusable"
        other_track_session_id = "session_compare_other_track"

        for session_id in (
            seed_session_id,
            usable_peer_session_id,
            unusable_peer_session_id,
            other_track_session_id,
        ):
            (self.processed_root / session_id).mkdir(parents=True, exist_ok=True)

        seed_raw = build_raw_lap_dataframe(sample_count=250)
        peer_raw = build_raw_lap_dataframe(sample_count=220)
        unusable_raw = build_raw_lap_dataframe(sample_count=210)
        other_track_raw = build_raw_lap_dataframe(sample_count=215)

        self._build_aligned_processed_df(seed_raw, seed_session_id).to_csv(
            self.processed_root / seed_session_id / "lap_001.csv",
            index=False,
        )
        self._build_aligned_processed_df(peer_raw, usable_peer_session_id).to_csv(
            self.processed_root / usable_peer_session_id / "lap_001.csv",
            index=False,
        )
        self._build_aligned_processed_df(unusable_raw, unusable_peer_session_id, alignment_usable=False).to_csv(
            self.processed_root / unusable_peer_session_id / "lap_001.csv",
            index=False,
        )
        self._build_aligned_processed_df(other_track_raw, other_track_session_id).to_csv(
            self.processed_root / other_track_session_id / "lap_001.csv",
            index=False,
        )

        self._write_metadata(
            self.processed_root / seed_session_id,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=int(seed_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(seed_raw["TimestampMS"].iloc[-1]),
        )
        self._write_metadata(
            self.processed_root / usable_peer_session_id,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=int(peer_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(peer_raw["TimestampMS"].iloc[-1]),
        )
        self._write_metadata(
            self.processed_root / unusable_peer_session_id,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=int(unusable_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(unusable_raw["TimestampMS"].iloc[-1]),
        )
        self._write_metadata(
            self.processed_root / other_track_session_id,
            track_circuit="Silverstone",
            track_layout="Grand Prix",
            track_location="Silverstone, UK",
            first_timestamp_ms=int(other_track_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(other_track_raw["TimestampMS"].iloc[-1]),
        )

        with self._patch_data_roots():
            result = session_scanner.get_compare_candidates(seed_session_id)

        self.assertEqual(result["track_circuit"], "Suzuka Circuit")
        self.assertEqual(result["track_layout"], "Grand Prix")
        self.assertEqual(
            {session["session_id"] for session in result["sessions"]},
            {seed_session_id, usable_peer_session_id},
        )
        self.assertEqual(result["sessions"][0]["laps"][0]["lap_number"], 1)

    def test_build_lap_overlay_returns_downsampled_same_track_series_and_reference_segmentation(self) -> None:
        reference_session_id = "session_compare_overlay_ref"
        peer_session_id = "session_compare_overlay_peer"

        for session_id in (reference_session_id, peer_session_id):
            (self.processed_root / session_id).mkdir(parents=True, exist_ok=True)

        reference_raw = build_raw_lap_dataframe(sample_count=2500, current_lap_step_s=0.02)
        peer_raw = build_raw_lap_dataframe(sample_count=2400, current_lap_step_s=0.021)

        reference_processed = self._build_aligned_processed_df(reference_raw, reference_session_id)
        reference_processed.to_csv(
            self.processed_root / reference_session_id / "lap_001.csv",
            index=False,
        )
        self._build_aligned_processed_df(peer_raw, peer_session_id).to_csv(
            self.processed_root / peer_session_id / "lap_001.csv",
            index=False,
        )

        self._write_metadata(
            self.processed_root / reference_session_id,
            track_circuit="Circuit de Barcelona-Catalunya",
            track_layout="Grand Prix",
            track_location="Barcelona, Spain",
            first_timestamp_ms=int(reference_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(reference_raw["TimestampMS"].iloc[-1]),
        )
        self._write_metadata(
            self.processed_root / peer_session_id,
            track_circuit="Circuit de Barcelona-Catalunya",
            track_layout="Grand Prix",
            track_location="Barcelona, Spain",
            first_timestamp_ms=int(peer_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(peer_raw["TimestampMS"].iloc[-1]),
        )
        (self.processed_root / reference_session_id / "track_segmentation.json").write_text(
            json.dumps(
                {
                    "segmentation_version": "test-segmentation",
                    "reference_lap_number": 1,
                    "reference_length_m": 4660.0,
                    "corners": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.processed_root / reference_session_id / "track_outline.json").write_text(
            json.dumps(
                {
                    "outline_version": "test-outline",
                    "session_id": reference_session_id,
                    "source_kind": "session_aggregate",
                    "reference_lap_number": 1,
                    "reference_length_m": 4660.0,
                    "sample_spacing_m": 1.0,
                    "source_lap_numbers": [1],
                    "contributing_lap_count": 1,
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
                            "distance_m": 4660.0,
                            "center_x": 100.0,
                            "center_z": 20.0,
                            "left_x": 95.5,
                            "left_z": 20.0,
                            "right_x": 104.5,
                            "right_z": 20.0,
                            "width_m": 9.0,
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with self._patch_data_roots():
            result = session_scanner.build_lap_overlay(
                selections=[
                    {"session_id": reference_session_id, "lap_number": 1},
                    {"session_id": peer_session_id, "lap_number": 1},
                ],
                reference_lap={"session_id": reference_session_id, "lap_number": 1},
            )

        self.assertEqual(result["track_circuit"], "Circuit de Barcelona-Catalunya")
        self.assertEqual(result["reference_lap"]["session_id"], reference_session_id)
        self.assertIsNotNone(result["segmentation"])
        self.assertIsNotNone(result["track_outline"])
        self.assertEqual(result["track_outline"]["source_kind"], "session_aggregate")
        self.assertEqual(result["track_outline"]["source_lap_numbers"], [1])
        self.assertEqual(len(result["series"]), 2)
        self.assertEqual(list(result["series"][0]["records"][0].keys()), session_scanner.COMPARE_COLUMNS)
        self.assertLessEqual(len(result["series"][0]["records"]), session_scanner.COMPARE_MAX_POINTS)
        self.assertAlmostEqual(float(result["series"][0]["records"][0]["TrackProgressNorm"]), 0.0, places=6)
        self.assertAlmostEqual(float(result["series"][0]["records"][-1]["TrackProgressNorm"]), 1.0, places=6)
        self.assertAlmostEqual(float(result["series"][0]["records"][0]["ElapsedTimeS"]), 0.0, places=6)
        self.assertAlmostEqual(
            float(result["series"][0]["records"][-1]["ElapsedTimeS"]),
            float(reference_processed["ElapsedTimeS"].iloc[-1]),
            places=6,
        )

    def test_build_lap_overlay_rejects_cross_track_mixes(self) -> None:
        reference_session_id = "session_compare_cross_track_ref"
        other_track_session_id = "session_compare_cross_track_other"

        for session_id in (reference_session_id, other_track_session_id):
            (self.processed_root / session_id).mkdir(parents=True, exist_ok=True)

        reference_raw = build_raw_lap_dataframe()
        other_track_raw = build_raw_lap_dataframe()

        self._build_aligned_processed_df(reference_raw, reference_session_id).to_csv(
            self.processed_root / reference_session_id / "lap_001.csv",
            index=False,
        )
        self._build_aligned_processed_df(other_track_raw, other_track_session_id).to_csv(
            self.processed_root / other_track_session_id / "lap_001.csv",
            index=False,
        )

        self._write_metadata(
            self.processed_root / reference_session_id,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=int(reference_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(reference_raw["TimestampMS"].iloc[-1]),
        )
        self._write_metadata(
            self.processed_root / other_track_session_id,
            track_circuit="Silverstone",
            track_layout="Grand Prix",
            track_location="Silverstone, UK",
            first_timestamp_ms=int(other_track_raw["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(other_track_raw["TimestampMS"].iloc[-1]),
        )

        with self._patch_data_roots():
            with self.assertRaisesRegex(ValueError, "does not match the reference track"):
                session_scanner.build_lap_overlay(
                    selections=[
                        {"session_id": reference_session_id, "lap_number": 1},
                        {"session_id": other_track_session_id, "lap_number": 1},
                    ],
                    reference_lap={"session_id": reference_session_id, "lap_number": 1},
                )

    def test_build_lap_overlay_rejects_duplicate_and_invalid_reference_selections(self) -> None:
        session_id = "session_compare_duplicates"
        processed_dir = self.processed_root / session_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        raw_df = build_raw_lap_dataframe()
        self._build_aligned_processed_df(raw_df, session_id).to_csv(
            processed_dir / "lap_001.csv",
            index=False,
        )
        self._write_metadata(
            processed_dir,
            track_circuit="Suzuka Circuit",
            track_layout="Grand Prix",
            track_location="Suzuka, Japan",
            first_timestamp_ms=int(raw_df["TimestampMS"].iloc[0]),
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        with self._patch_data_roots():
            with self.assertRaisesRegex(ValueError, "Duplicate lap selections"):
                session_scanner.build_lap_overlay(
                    selections=[
                        {"session_id": session_id, "lap_number": 1},
                        {"session_id": session_id, "lap_number": 1},
                    ],
                    reference_lap={"session_id": session_id, "lap_number": 1},
                )

        with self._patch_data_roots():
            with self.assertRaisesRegex(ValueError, "Reference lap must be included"):
                session_scanner.build_lap_overlay(
                    selections=[{"session_id": session_id, "lap_number": 1}],
                    reference_lap={"session_id": session_id, "lap_number": 2},
                )

    def _build_aligned_processed_df(
        self,
        raw_df: pd.DataFrame,
        session_id: str,
        *,
        alignment_usable: bool = True,
    ) -> pd.DataFrame:
        processed_df = build_processed_lap_dataframe(raw_df, session_id=session_id)
        processed_df["TrackProgressNorm"] = processed_df["NormalizedDistance"]
        processed_df["TrackProgressM"] = processed_df["CumulativeDistanceM"]
        processed_df["AlignmentIsUsable"] = 1 if alignment_usable else 0
        return processed_df

    def _write_metadata(
        self,
        session_dir: Path,
        *,
        track_circuit: str,
        track_layout: str,
        track_location: str,
        first_timestamp_ms: int,
        last_timestamp_ms: int,
    ) -> None:
        metadata = {
            "session_id": session_dir.name,
            "schema_version": "test-schema",
            "sim": "Forza Motorsport",
            "created_at_utc": "2026-04-01T00:00:00+00:00",
            "capture_ip": "127.0.0.1",
            "capture_port": 5300,
            "car_ordinal": 12,
            "track_ordinal": 0,
            "track_circuit": track_circuit,
            "track_layout": track_layout,
            "track_location": track_location,
            "track_length_m": 4660.0,
            "total_laps": 1,
            "lap_index": {
                "1": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": first_timestamp_ms,
                    "last_timestamp_ms": last_timestamp_ms,
                }
            },
            "notes": "",
        }
        (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _patch_data_roots(self):
        return patch.multiple(
            session_scanner,
            RAW_DATA_ROOT=self.raw_root,
            PROCESSED_DATA_ROOT=self.processed_root,
        )


if __name__ == "__main__":
    unittest.main()
