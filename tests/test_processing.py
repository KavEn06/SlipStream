from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT
from src.core.schemas import (
    LAP_CLOSE_REASON_CAPTURE_END,
    LAP_CLOSE_REASON_LAP_ROLLOVER,
    PROCESSED_LAP_COLUMNS,
    RAW_LAP_COLUMNS,
    VALIDATION_REASON_MISSING_REQUIRED_SIGNALS,
    VALIDATION_REASON_MULTIPLE_LAP_NUMBERS,
    VALIDATION_REASON_NO_FORWARD_DISTANCE,
    VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP,
    VALIDATION_REASON_PARTIAL_LAP_END,
    VALIDATION_REASON_PARTIAL_LAP_START,
    VALIDATION_REASON_TOO_FEW_SAMPLES,
)
from src.processing.distance import (
    build_processed_lap_dataframe,
    build_processed_lap_file,
    calculate_distance_series,
    process_session,
    resample_processed_lap,
)


def build_raw_lap_dataframe(
    sample_count: int = 25,
    lap_number: int = 1,
    start_timestamp_ms: int = 1000,
    timestamp_step_ms: int = 50,
    start_current_lap_s: float = 0.0,
    current_lap_step_s: float = 0.25,
    distance_step_m: float = 3.0,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for index in range(sample_count):
        distance_m = float(index * distance_step_m)
        rows.append(
            {
                "IsRaceOn": 1,
                "TimestampMS": start_timestamp_ms + (index * timestamp_step_ms),
                "EngineMaxRpm": 8000.0,
                "EngineIdleRpm": 900.0,
                "CurrentEngineRpm": 4200.0 + (index * 15.0),
                "CarOrdinal": 12,
                "PositionX": distance_m,
                "PositionY": 0.0,
                "PositionZ": float(index) * 0.2,
                "Speed": 30.0 + (index * 0.75),
                "Power": 150.0 + index,
                "Torque": 220.0,
                "Boost": 0.2,
                "DistanceTraveled": distance_m,
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
                "TrackOrdinal": 110,
            }
        )
    return pd.DataFrame(rows, columns=RAW_LAP_COLUMNS)


def build_session_metadata(
    lap_number: int = 1,
    close_reason: str = LAP_CLOSE_REASON_LAP_ROLLOVER,
    first_timestamp_ms: int = 1000,
    last_timestamp_ms: int = 2200,
    track_length_m: float | None = 4660.0,
) -> dict:
    return {
        "session_id": "session_fixture",
        "track_ordinal": 110,
        "track_circuit": "Circuit de Barcelona-Catalunya",
        "track_length_m": track_length_m,
        "lap_index": {
            str(lap_number): {
                "close_reason": close_reason,
                "first_timestamp_ms": first_timestamp_ms,
                "last_timestamp_ms": last_timestamp_ms,
            }
        },
    }


class ProcessingTests(unittest.TestCase):
    def test_processed_lap_contains_canonical_columns_and_features_for_valid_lap(self) -> None:
        raw_df = build_raw_lap_dataframe()
        processed_df = build_processed_lap_dataframe(raw_df, session_id="session_fixture")

        self.assertEqual(list(processed_df.columns), PROCESSED_LAP_COLUMNS)
        self.assertEqual(processed_df["SessionId"].iloc[0], "session_fixture")
        self.assertAlmostEqual(float(processed_df["NormalizedDistance"].iloc[-1]), 1.0, places=6)
        self.assertTrue((processed_df["Throttle"].between(0.0, 1.0)).all())
        self.assertTrue((processed_df["Brake"].between(0.0, 1.0)).all())
        self.assertTrue((processed_df["Steering"].between(-1.0, 1.0)).all())
        self.assertTrue((processed_df["CumulativeDistanceM"].diff().fillna(0.0) >= 0.0).all())
        self.assertGreater(float(processed_df["LongitudinalAccelMps2"].abs().max()), 0.0)
        self.assertTrue((processed_df["LapIsValid"] == 1).all())

    def test_distance_and_resampling_are_deterministic(self) -> None:
        raw_df = build_raw_lap_dataframe()
        distance = calculate_distance_series(raw_df.copy())
        processed_df = build_processed_lap_dataframe(raw_df)
        resampled_df = resample_processed_lap(processed_df, num_points=25)

        self.assertEqual(len(distance), len(raw_df))
        self.assertGreater(float(distance.iloc[-1]), 0.0)
        self.assertEqual(len(resampled_df), 25)
        self.assertAlmostEqual(float(resampled_df["NormalizedDistance"].iloc[0]), 0.0, places=6)
        self.assertAlmostEqual(float(resampled_df["NormalizedDistance"].iloc[-1]), 1.0, places=6)

    def test_valid_lap_file_writes_empty_validation_sidecar(self) -> None:
        raw_df = build_raw_lap_dataframe()
        metadata = build_session_metadata(last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]))

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 1).all())
            self.assertEqual(validation["status"], "valid")
            self.assertEqual(validation["reason_codes"], [])
            self.assertEqual(validation["lap_number"], 1)
        finally:
            shutil.rmtree(temp_root)

    def test_single_file_processing_without_output_uses_safe_derived_path(self) -> None:
        session_id = "session_test_single_file_safe_output"
        raw_dir = RAW_DATA_ROOT / session_id
        processed_dir = PROCESSED_DATA_ROOT / session_id
        raw_df = build_raw_lap_dataframe()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "lap_001.csv"
        raw_path.write_text(raw_df.to_csv(index=False), encoding="utf-8")
        original_contents = raw_path.read_text(encoding="utf-8")

        try:
            build_processed_lap_file(raw_path, session_id=session_id)

            processed_path = processed_dir / "lap_001.csv"
            self.assertTrue(processed_path.exists())
            self.assertTrue((processed_dir / "lap_001.validation.json").exists())
            self.assertEqual(raw_path.read_text(encoding="utf-8"), original_contents)
        finally:
            if raw_dir.exists():
                shutil.rmtree(raw_dir)
            if processed_dir.exists():
                shutil.rmtree(processed_dir)

    def test_explicit_output_path_must_not_overwrite_raw_input(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        raw_path = temp_root / "lap_001.csv"
        build_raw_lap_dataframe().to_csv(raw_path, index=False)

        try:
            with self.assertRaises(ValueError):
                build_processed_lap_file(raw_path, raw_path)
        finally:
            shutil.rmtree(temp_root)

    def test_partial_lap_start_is_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe(start_current_lap_s=3.5)

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_PARTIAL_LAP_START, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def test_partial_lap_end_is_marked_invalid_when_capture_ends_early(self) -> None:
        raw_df = build_raw_lap_dataframe()
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_CAPTURE_END,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
            self.assertEqual(validation["metrics"]["close_reason"], LAP_CLOSE_REASON_CAPTURE_END)
            self.assertLess(validation["metrics"]["end_completion_ratio"], 0.95)
        finally:
            shutil.rmtree(temp_root)

    def test_capture_end_lap_remains_valid_when_nearly_complete(self) -> None:
        raw_df = build_raw_lap_dataframe(distance_step_m=185.0)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_CAPTURE_END,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 1).all())
            self.assertNotIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
            self.assertGreaterEqual(validation["metrics"]["end_completion_ratio"], 0.95)
        finally:
            shutil.rmtree(temp_root)

    def test_capture_end_without_track_length_stays_conservatively_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe(distance_step_m=185.0)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_CAPTURE_END,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
            track_length_m=None,
        )

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
            self.assertIsNone(validation["metrics"]["track_length_m"])
            self.assertIsNone(validation["metrics"]["end_completion_ratio"])
        finally:
            shutil.rmtree(temp_root)

    def test_capture_end_completion_uses_lap_local_progress_not_session_distance(self) -> None:
        raw_df = build_raw_lap_dataframe(distance_step_m=185.0)
        raw_df["DistanceTraveled"] = raw_df["DistanceTraveled"] + 12000.0
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_CAPTURE_END,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 1).all())
            self.assertNotIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
            self.assertLess(validation["metrics"]["end_progress_m"], 5000.0)
            self.assertGreaterEqual(validation["metrics"]["end_completion_ratio"], 0.95)
        finally:
            shutil.rmtree(temp_root)

    def test_metadata_lookup_uses_csv_lap_number_before_filename(self) -> None:
        raw_df = build_raw_lap_dataframe(lap_number=2, distance_step_m=185.0)
        metadata = {
            "session_id": "session_fixture",
            "track_ordinal": 110,
            "track_circuit": "Circuit de Barcelona-Catalunya",
            "track_length_m": 4660.0,
            "lap_index": {
                "1": {
                    "close_reason": LAP_CLOSE_REASON_CAPTURE_END,
                    "first_timestamp_ms": 1000,
                    "last_timestamp_ms": int(raw_df["TimestampMS"].iloc[-1]),
                },
                "2": {
                    "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
                    "first_timestamp_ms": 1000,
                    "last_timestamp_ms": int(raw_df["TimestampMS"].iloc[-1]),
                },
            },
        }

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=metadata, raw_filename="lap_001.csv")
        try:
            self.assertTrue((processed_df["LapNumber"] == 2).all())
            self.assertEqual(validation["lap_number"], 2)
            self.assertEqual(validation["metrics"]["close_reason"], LAP_CLOSE_REASON_LAP_ROLLOVER)
            self.assertNotIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def test_non_monotonic_timestamp_is_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe()
        raw_df.loc[8, "TimestampMS"] = raw_df.loc[7, "TimestampMS"]

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def test_multiple_lap_numbers_in_one_file_are_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe()
        raw_df.loc[15:, "LapNumber"] = 2

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_MULTIPLE_LAP_NUMBERS, validation["reason_codes"])
            self.assertEqual(validation["metrics"]["distinct_lap_numbers"], [1, 2])
        finally:
            shutil.rmtree(temp_root)

    def test_low_sample_count_is_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe(sample_count=10, distance_step_m=6.0)

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_TOO_FEW_SAMPLES, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def test_no_forward_distance_is_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe(distance_step_m=1.0)

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_NO_FORWARD_DISTANCE, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def test_missing_required_signals_is_marked_invalid(self) -> None:
        raw_df = build_raw_lap_dataframe()
        raw_df = raw_df.astype({"Brake": "object"})
        raw_df.loc[5, "Brake"] = "not-a-number"

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_MISSING_REQUIRED_SIGNALS, validation["reason_codes"])
            self.assertIn("Brake", validation["metrics"]["missing_required_signal_columns"])
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_writes_processed_laps_metadata_and_validation_sidecars(self) -> None:
        raw_df = build_raw_lap_dataframe()
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        raw_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_CAPTURE_END,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            written_paths = process_session(raw_session_dir, processed_session_dir)
            self.assertEqual(len(written_paths), 1)
            self.assertTrue(written_paths[0].exists())
            self.assertTrue((processed_session_dir / "lap_001.validation.json").exists())

            validation = json.loads((processed_session_dir / "lap_001.validation.json").read_text(encoding="utf-8"))
            self.assertIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])

            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("processed_schema_version", processed_metadata)
            self.assertIn("lap_index", processed_metadata)
        finally:
            shutil.rmtree(temp_root)

    def test_standalone_processing_without_metadata_does_not_infer_partial_lap_end(self) -> None:
        raw_df = build_raw_lap_dataframe(start_current_lap_s=3.5)

        temp_root, processed_df, validation = self._process_raw_dataframe(raw_df, metadata=None)
        try:
            self.assertTrue((processed_df["LapIsValid"] == 0).all())
            self.assertIn(VALIDATION_REASON_PARTIAL_LAP_START, validation["reason_codes"])
            self.assertNotIn(VALIDATION_REASON_PARTIAL_LAP_END, validation["reason_codes"])
        finally:
            shutil.rmtree(temp_root)

    def _process_raw_dataframe(
        self,
        raw_df: pd.DataFrame,
        metadata: dict | None = None,
        session_id: str = "session_fixture",
        raw_filename: str = "lap_001.csv",
    ) -> tuple[Path, pd.DataFrame, dict]:
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / session_id
        processed_session_dir = temp_root / "processed" / session_id
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        processed_session_dir.mkdir(parents=True, exist_ok=True)

        raw_path = raw_session_dir / raw_filename
        processed_path = processed_session_dir / raw_filename
        raw_df.to_csv(raw_path, index=False)
        if metadata is not None:
            (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        processed_df = build_processed_lap_file(
            raw_path,
            processed_path,
            session_id=session_id,
            session_metadata=metadata,
        )
        validation = json.loads((processed_session_dir / f"{Path(raw_filename).stem}.validation.json").read_text(encoding="utf-8"))
        return temp_root, processed_df, validation


if __name__ == "__main__":
    unittest.main()
