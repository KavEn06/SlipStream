from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT
from src.core.schemas import (
    ALIGNED_LAP_COLUMNS,
    LAP_CLOSE_REASON_CAPTURE_END,
    LAP_CLOSE_REASON_LAP_ROLLOVER,
    PROCESSED_LAP_COLUMNS,
    RAW_LAP_COLUMNS,
    REFERENCE_PATH_COLUMNS,
    VALIDATION_REASON_MISSING_REQUIRED_SIGNALS,
    VALIDATION_REASON_MULTIPLE_LAP_NUMBERS,
    VALIDATION_REASON_NO_FORWARD_DISTANCE,
    VALIDATION_REASON_NON_MONOTONIC_TIMESTAMP,
    VALIDATION_REASON_PARTIAL_LAP_END,
    VALIDATION_REASON_PARTIAL_LAP_START,
    VALIDATION_REASON_TOO_FEW_SAMPLES,
)
from src.processing.alignment import (
    ALIGNMENT_STATUS_COMPLETE,
    ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY,
    ALIGNMENT_STATUS_SKIPPED_NO_VALID_LAPS,
    align_processed_lap,
    build_reference_path,
    resample_aligned_lap,
    select_reference_lap,
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
    path_points: list[tuple[float, float, float]] | None = None,
    distance_offset_m: float = 0.0,
) -> pd.DataFrame:
    if path_points is None:
        path_points = [
            (float(index * distance_step_m), 0.0, float(index) * 0.2)
            for index in range(sample_count)
        ]
    else:
        sample_count = len(path_points)

    cumulative_distance_m = _cumulative_distance_for_points(path_points) + float(distance_offset_m)
    rows: list[dict[str, float | int]] = []
    for index, point in enumerate(path_points):
        rows.append(
            {
                "IsRaceOn": 1,
                "TimestampMS": start_timestamp_ms + (index * timestamp_step_ms),
                "EngineMaxRpm": 8000.0,
                "EngineIdleRpm": 900.0,
                "CurrentEngineRpm": 4200.0 + (index * 15.0),
                "CarOrdinal": 12,
                "PositionX": float(point[0]),
                "PositionY": float(point[1]),
                "PositionZ": float(point[2]),
                "Speed": 30.0 + (index * 0.75),
                "Power": 150.0 + index,
                "Torque": 220.0,
                "Boost": 0.2,
                "DistanceTraveled": float(cumulative_distance_m[index]),
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


def build_parallel_section_path_points() -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for x_pos in range(0, 51):
        points.append((float(x_pos), 0.0, 0.0))
    for y_pos in range(1, 11):
        points.append((50.0, float(y_pos), 0.0))
    for x_pos in range(49, -1, -1):
        points.append((float(x_pos), 10.0, 0.0))
    return points


def offset_path_points(
    path_points: list[tuple[float, float, float]],
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
    start_index: int = 0,
    end_index: int | None = None,
) -> list[tuple[float, float, float]]:
    adjusted_points = list(path_points)
    slice_end = len(adjusted_points) if end_index is None else end_index
    for index in range(start_index, slice_end):
        point = adjusted_points[index]
        adjusted_points[index] = (point[0] + dx, point[1] + dy, point[2] + dz)
    return adjusted_points


def sparsify_xyz(
    raw_df: pd.DataFrame,
    keep_indices: list[int],
) -> pd.DataFrame:
    sparse_df = raw_df.copy()
    all_indices = set(range(len(sparse_df)))
    keep_index_set = {index for index in keep_indices if 0 <= index < len(sparse_df)}
    drop_indices = sorted(all_indices - keep_index_set)
    sparse_df.loc[drop_indices, ["PositionX", "PositionY", "PositionZ"]] = np.nan
    return sparse_df


def _cumulative_distance_for_points(path_points: list[tuple[float, float, float]]) -> np.ndarray:
    point_array = np.asarray(path_points, dtype=float)
    point_deltas = np.diff(point_array, axis=0, prepend=point_array[[0]])
    step_distance = np.sqrt((point_deltas**2).sum(axis=1))
    step_distance[0] = 0.0
    return np.cumsum(step_distance)


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
        self.assertTrue(processed_df["TrackProgressM"].isna().all())
        self.assertTrue((processed_df["AlignmentIsUsable"] == 0).all())

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

    def test_distance_normalization_repairs_single_xyz_spike(self) -> None:
        raw_df = build_raw_lap_dataframe()
        raw_df.loc[12, ["PositionX", "PositionY", "PositionZ"]] = [2500.0, 1200.0, 800.0]

        distance = calculate_distance_series(raw_df.copy())
        expected_total_distance = float(raw_df["DistanceTraveled"].iloc[-1] - raw_df["DistanceTraveled"].iloc[0])

        self.assertLess(abs(float(distance.iloc[-1]) - expected_total_distance), 1.0)

    def test_distance_normalization_does_not_fallback_entire_lap_for_single_missing_xyz_sample(self) -> None:
        raw_df = build_raw_lap_dataframe()
        baseline_total_distance = float(calculate_distance_series(raw_df.copy()).iloc[-1])
        raw_df["DistanceTraveled"] = raw_df["DistanceTraveled"] * 1.08
        raw_df.loc[12, ["PositionX", "PositionY", "PositionZ"]] = np.nan

        distance = calculate_distance_series(raw_df.copy())

        self.assertLess(abs(float(distance.iloc[-1]) - baseline_total_distance), 1.0)
        self.assertGreater(abs(float(distance.iloc[-1]) - float(raw_df["DistanceTraveled"].iloc[-1])), 1.0)

    def test_zero_distance_lap_keeps_normalized_distance_at_zero(self) -> None:
        stationary_points = [(0.0, 0.0, 0.0) for _ in range(25)]
        raw_df = build_raw_lap_dataframe(path_points=stationary_points)
        raw_df["DistanceTraveled"] = 0.0

        processed_df = build_processed_lap_dataframe(raw_df)

        self.assertTrue((processed_df["NormalizedDistance"] == 0.0).all())

    def test_resampled_processed_lap_keeps_gear_discrete(self) -> None:
        raw_df = build_raw_lap_dataframe()
        processed_df = build_processed_lap_dataframe(raw_df)

        resampled_df = resample_processed_lap(processed_df, num_points=40)

        gear_values = set(pd.to_numeric(resampled_df["Gear"], errors="coerce").dropna().astype(int).tolist())
        self.assertEqual(gear_values, {3, 4})
        self.assertTrue(np.allclose(resampled_df["Gear"], np.rint(resampled_df["Gear"])))

    def test_select_reference_lap_prefers_fastest_valid_lap(self) -> None:
        slower_lap = build_processed_lap_dataframe(build_raw_lap_dataframe(lap_number=1, timestamp_step_ms=60))
        faster_lap = build_processed_lap_dataframe(build_raw_lap_dataframe(lap_number=2, timestamp_step_ms=40))
        invalid_lap = build_processed_lap_dataframe(build_raw_lap_dataframe(lap_number=3, start_current_lap_s=3.5))

        reference_lap_number = select_reference_lap({1: slower_lap, 2: faster_lap, 3: invalid_lap})

        self.assertEqual(reference_lap_number, 2)

    def test_build_reference_path_cleans_and_resamples_to_fixed_spacing(self) -> None:
        path_points = build_parallel_section_path_points()
        noisy_path_points = list(path_points)
        noisy_path_points.insert(12, noisy_path_points[12])
        noisy_path_points.insert(13, noisy_path_points[13])
        raw_df = build_raw_lap_dataframe(path_points=noisy_path_points)
        processed_df = build_processed_lap_dataframe(raw_df)

        reference_path = build_reference_path(processed_df)
        reference_distance = pd.to_numeric(reference_path["ReferenceDistanceM"], errors="coerce")
        reference_step = reference_distance.diff().dropna()

        self.assertEqual(list(reference_path.columns), REFERENCE_PATH_COLUMNS)
        self.assertGreater(len(reference_path), 100)
        self.assertTrue((reference_step > 0).all())
        self.assertAlmostEqual(float(reference_step.iloc[0]), 1.0, places=6)
        self.assertTrue((reference_step.iloc[:-1].round(6) == 1.0).all())
        self.assertLessEqual(float(reference_step.iloc[-1]), 1.0)
        self.assertAlmostEqual(float(reference_path["ReferenceProgressNorm"].iloc[0]), 0.0, places=6)
        self.assertAlmostEqual(float(reference_path["ReferenceProgressNorm"].iloc[-1]), 1.0, places=6)

    def test_identical_lap_aligns_without_fallback_and_is_usable(self) -> None:
        path_points = build_parallel_section_path_points()
        processed_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=path_points))
        reference_path = build_reference_path(processed_df)

        aligned_df, diagnostics = align_processed_lap(processed_df, reference_path)

        self.assertTrue((aligned_df["AlignmentUsedFallback"] == 0).all())
        self.assertTrue((aligned_df["AlignmentIsUsable"] == 1).all())
        self.assertEqual(diagnostics.alignment_method, "projection_only")
        self.assertGreaterEqual(float(diagnostics.coverage_span_ratio), 0.95)
        self.assertAlmostEqual(float(aligned_df["TrackProgressM"].iloc[0]), 0.0, places=3)
        self.assertAlmostEqual(
            float(aligned_df["TrackProgressM"].iloc[-1]),
            float(reference_path["ReferenceDistanceM"].iloc[-1]),
            places=3,
        )

    def test_lap_with_moderate_line_variation_aligns_and_resamples(self) -> None:
        reference_points = build_parallel_section_path_points()
        comparison_points = offset_path_points(reference_points, dy=0.75, start_index=55, end_index=95)
        reference_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=reference_points))
        comparison_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=comparison_points, lap_number=2))
        reference_path = build_reference_path(reference_df)

        aligned_df, diagnostics = align_processed_lap(comparison_df, reference_path)
        resampled_df = resample_aligned_lap(aligned_df, num_points=30)

        self.assertTrue((aligned_df["AlignmentIsUsable"] == 1).all())
        self.assertLess(float(diagnostics.fallback_ratio), 0.10)
        self.assertEqual(list(resampled_df.columns), ALIGNED_LAP_COLUMNS)
        self.assertAlmostEqual(float(resampled_df["TrackProgressNorm"].iloc[0]), 0.0, places=6)
        self.assertAlmostEqual(float(resampled_df["TrackProgressNorm"].iloc[-1]), 1.0, places=6)

    def test_parallel_section_alignment_uses_local_search_window(self) -> None:
        path_points = build_parallel_section_path_points()
        comparison_points = offset_path_points(path_points, dy=0.4, start_index=70, end_index=95)
        reference_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=path_points))
        comparison_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=comparison_points, lap_number=2))
        reference_path = build_reference_path(reference_df)

        aligned_df, diagnostics = align_processed_lap(comparison_df, reference_path)

        self.assertTrue((aligned_df["TrackProgressM"].diff().fillna(0.0) >= 0.0).all())
        self.assertTrue((aligned_df["AlignmentIsUsable"] == 1).all())
        self.assertGreater(float(aligned_df["TrackProgressM"].iloc[75]), 70.0)
        self.assertLess(float(diagnostics.fallback_ratio), 0.10)

    def test_noisy_region_triggers_fallback_only_for_affected_samples(self) -> None:
        path_points = build_parallel_section_path_points()
        noisy_points = offset_path_points(path_points, dy=40.0, start_index=48, end_index=50)
        reference_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=path_points))
        noisy_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=noisy_points, lap_number=2))
        reference_path = build_reference_path(reference_df)

        aligned_df, diagnostics = align_processed_lap(noisy_df, reference_path)

        fallback_mask = aligned_df["AlignmentUsedFallback"].astype(int)
        self.assertGreater(int(fallback_mask.sum()), 0)
        self.assertLess(int(fallback_mask.sum()), 5)
        self.assertEqual(diagnostics.alignment_method, "hybrid_fallback")
        self.assertTrue((aligned_df["AlignmentIsUsable"] == 1).all())

    def test_long_contiguous_fallback_run_marks_lap_not_alignment_usable(self) -> None:
        path_points = [(float(index), 0.0, 0.0) for index in range(201)]
        noisy_points = offset_path_points(path_points, dy=40.0, start_index=80, end_index=98)
        reference_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=path_points))
        noisy_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=noisy_points, lap_number=2))
        reference_path = build_reference_path(reference_df)

        aligned_df, diagnostics = align_processed_lap(noisy_df, reference_path)

        self.assertLess(float(diagnostics.fallback_ratio), 0.10)
        self.assertGreater(float(diagnostics.longest_fallback_run_ratio), 0.05)
        self.assertTrue((aligned_df["AlignmentIsUsable"] == 0).all())

    def test_alignment_coverage_gate_uses_progress_span_ratio(self) -> None:
        reference_points = build_parallel_section_path_points()
        partial_points = reference_points[:80]
        reference_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=reference_points))
        partial_df = build_processed_lap_dataframe(build_raw_lap_dataframe(path_points=partial_points, lap_number=2))
        reference_path = build_reference_path(reference_df)

        aligned_df, diagnostics = align_processed_lap(partial_df, reference_path)

        self.assertLess(float(diagnostics.coverage_span_ratio), 0.95)
        self.assertTrue((aligned_df["AlignmentIsUsable"] == 0).all())

    def test_resample_aligned_lap_rejects_laps_that_are_not_alignment_usable(self) -> None:
        processed_df = build_processed_lap_dataframe(build_raw_lap_dataframe())

        with self.assertRaises(ValueError):
            resample_aligned_lap(processed_df)

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
            processed_df = build_processed_lap_file(raw_path)

            processed_path = processed_dir / "lap_001.csv"
            self.assertTrue(processed_path.exists())
            self.assertTrue((processed_dir / "lap_001.validation.json").exists())
            self.assertEqual(raw_path.read_text(encoding="utf-8"), original_contents)
            self.assertFalse((processed_dir / "reference_path.csv").exists())
            self.assertEqual(processed_df["SessionId"].iloc[0], session_id)
            self.assertTrue(processed_df["TrackProgressM"].isna().all())
            self.assertTrue((processed_df["AlignmentIsUsable"] == 0).all())
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

    def test_process_session_writes_aligned_laps_reference_path_and_alignment_metadata(self) -> None:
        reference_points = build_parallel_section_path_points()
        raw_df = build_raw_lap_dataframe(path_points=reference_points, lap_number=1, timestamp_step_ms=40)
        slower_df = build_raw_lap_dataframe(
            path_points=offset_path_points(reference_points, dy=0.6, start_index=55, end_index=95),
            lap_number=2,
            timestamp_step_ms=55,
        )
        invalid_df = build_raw_lap_dataframe(path_points=reference_points[:80], lap_number=3, start_current_lap_s=3.5)
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        raw_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        slower_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        invalid_df.to_csv(raw_session_dir / "lap_003.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(slower_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(slower_df["TimestampMS"].iloc[-1]),
        }
        metadata["lap_index"]["3"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(invalid_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(invalid_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 3
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            written_paths = process_session(raw_session_dir, processed_session_dir)
            self.assertEqual(len(written_paths), 3)
            self.assertTrue(all(path.exists() for path in written_paths))
            self.assertTrue((processed_session_dir / "lap_001.validation.json").exists())
            self.assertTrue((processed_session_dir / "reference_path.csv").exists())

            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("processed_schema_version", processed_metadata)
            self.assertIn("lap_index", processed_metadata)
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_COMPLETE)
            self.assertEqual(processed_metadata["alignment"]["reference_lap_number"], 1)
            self.assertEqual(processed_metadata["alignment"]["aligned_lap_count"], 2)
            self.assertEqual(processed_metadata["alignment"]["excluded_lap_count"], 1)
            self.assertTrue(processed_metadata["alignment"]["laps"]["1"]["is_usable"])
            self.assertTrue(processed_metadata["alignment"]["laps"]["2"]["is_usable"])
            self.assertFalse(processed_metadata["alignment"]["laps"]["3"]["is_usable"])

            aligned_reference = pd.read_csv(processed_session_dir / "lap_001.csv")
            aligned_invalid = pd.read_csv(processed_session_dir / "lap_003.csv")
            self.assertTrue((aligned_reference["AlignmentIsUsable"] == 1).all())
            self.assertTrue((aligned_invalid["AlignmentIsUsable"] == 0).all())
            self.assertTrue(aligned_invalid["TrackProgressM"].isna().all())
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_with_single_valid_lap_aligns_reference_to_itself(self) -> None:
        raw_df = build_raw_lap_dataframe(path_points=build_parallel_section_path_points(), lap_number=1)
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        raw_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            processed_lap = pd.read_csv(processed_session_dir / "lap_001.csv")
            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertTrue((processed_lap["AlignmentIsUsable"] == 1).all())
            self.assertTrue((processed_lap["AlignmentUsedFallback"] == 0).all())
            self.assertEqual(processed_metadata["alignment"]["reference_lap_number"], 1)
            self.assertEqual(processed_metadata["alignment"]["aligned_lap_count"], 1)
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_skips_fastest_valid_lap_without_reference_geometry(self) -> None:
        bad_reference_df = build_raw_lap_dataframe(lap_number=1, timestamp_step_ms=40)
        bad_reference_df[["PositionX", "PositionY", "PositionZ"]] = np.nan
        usable_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=2,
            timestamp_step_ms=55,
        )
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        bad_reference_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        usable_reference_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(bad_reference_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue((processed_session_dir / "reference_path.csv").exists())
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_COMPLETE)
            self.assertEqual(processed_metadata["alignment"]["reference_lap_number"], 2)
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_skips_sparse_fastest_valid_lap_for_reference_selection(self) -> None:
        sparse_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=1,
            timestamp_step_ms=40,
        )
        sparse_reference_df = sparsify_xyz(sparse_reference_df, keep_indices=[0, 20, 40, 60, 80])
        usable_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=2,
            timestamp_step_ms=55,
        )
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        sparse_reference_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        usable_reference_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(sparse_reference_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            aligned_sparse = pd.read_csv(processed_session_dir / "lap_001.csv")
            aligned_usable = pd.read_csv(processed_session_dir / "lap_002.csv")

            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_COMPLETE)
            self.assertEqual(processed_metadata["alignment"]["reference_lap_number"], 2)
            self.assertTrue((aligned_sparse["AlignmentIsUsable"] == 0).all())
            self.assertTrue((aligned_usable["AlignmentIsUsable"] == 1).all())
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_rejects_output_dir_equal_to_raw_dir_without_mutation(self) -> None:
        raw_df = build_raw_lap_dataframe()
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_session_dir / "lap_001.csv"
        raw_df.to_csv(raw_path, index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(raw_df["TimestampMS"].iloc[-1]),
        )
        metadata_path = raw_session_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        original_raw_contents = raw_path.read_text(encoding="utf-8")
        original_metadata_contents = metadata_path.read_text(encoding="utf-8")

        try:
            with self.assertRaisesRegex(ValueError, "must differ from the raw session directory"):
                process_session(raw_session_dir, raw_session_dir)

            self.assertTrue(raw_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertEqual(raw_path.read_text(encoding="utf-8"), original_raw_contents)
            self.assertEqual(metadata_path.read_text(encoding="utf-8"), original_metadata_contents)
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_skips_fastest_lap_with_contiguous_geometry_gap_for_reference_selection(self) -> None:
        corrupted_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=1,
            timestamp_step_ms=40,
        )
        corrupted_reference_df.loc[40:60, ["PositionX", "PositionY", "PositionZ"]] = np.nan
        usable_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=2,
            timestamp_step_ms=55,
        )
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        corrupted_reference_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        usable_reference_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(corrupted_reference_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(usable_reference_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            aligned_corrupted = pd.read_csv(processed_session_dir / "lap_001.csv")
            aligned_usable = pd.read_csv(processed_session_dir / "lap_002.csv")

            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_COMPLETE)
            self.assertEqual(processed_metadata["alignment"]["reference_lap_number"], 2)
            self.assertTrue((aligned_corrupted["AlignmentIsUsable"] == 0).all())
            self.assertTrue((aligned_usable["AlignmentIsUsable"] == 1).all())
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_skips_alignment_when_no_valid_lap_can_form_reference_geometry(self) -> None:
        bad_reference_df = build_raw_lap_dataframe(lap_number=1)
        slower_bad_reference_df = build_raw_lap_dataframe(lap_number=2, timestamp_step_ms=60)
        bad_reference_df[["PositionX", "PositionY", "PositionZ"]] = np.nan
        slower_bad_reference_df[["PositionX", "PositionY", "PositionZ"]] = np.nan
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        bad_reference_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        slower_bad_reference_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(bad_reference_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(slower_bad_reference_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(slower_bad_reference_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            written_paths = process_session(raw_session_dir, processed_session_dir)
            self.assertEqual(len(written_paths), 2)
            self.assertFalse((processed_session_dir / "reference_path.csv").exists())

            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            aligned_one = pd.read_csv(processed_session_dir / "lap_001.csv")
            aligned_two = pd.read_csv(processed_session_dir / "lap_002.csv")
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY)
            self.assertIsNone(processed_metadata["alignment"]["reference_lap_number"])
            self.assertEqual(processed_metadata["alignment"]["aligned_lap_count"], 0)
            self.assertEqual(processed_metadata["alignment"]["excluded_lap_count"], 2)
            self.assertTrue((aligned_one["AlignmentIsUsable"] == 0).all())
            self.assertTrue((aligned_two["AlignmentIsUsable"] == 0).all())
            self.assertTrue(aligned_one["TrackProgressM"].isna().all())
            self.assertTrue(aligned_two["TrackProgressM"].isna().all())
            self.assertTrue((processed_session_dir / "lap_001.validation.json").exists())
            self.assertTrue((processed_session_dir / "lap_002.validation.json").exists())
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_skips_alignment_when_only_contiguous_gap_candidates_exist(self) -> None:
        bad_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=1,
        )
        slower_bad_reference_df = build_raw_lap_dataframe(
            path_points=build_parallel_section_path_points(),
            lap_number=2,
            timestamp_step_ms=60,
        )
        bad_reference_df.loc[35:55, ["PositionX", "PositionY", "PositionZ"]] = np.nan
        slower_bad_reference_df.loc[45:65, ["PositionX", "PositionY", "PositionZ"]] = np.nan
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        bad_reference_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        slower_bad_reference_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(bad_reference_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(slower_bad_reference_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(slower_bad_reference_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            written_paths = process_session(raw_session_dir, processed_session_dir)
            self.assertEqual(len(written_paths), 2)
            self.assertFalse((processed_session_dir / "reference_path.csv").exists())

            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            aligned_one = pd.read_csv(processed_session_dir / "lap_001.csv")
            aligned_two = pd.read_csv(processed_session_dir / "lap_002.csv")
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY)
            self.assertIsNone(processed_metadata["alignment"]["reference_lap_number"])
            self.assertEqual(processed_metadata["alignment"]["aligned_lap_count"], 0)
            self.assertTrue((aligned_one["AlignmentIsUsable"] == 0).all())
            self.assertTrue((aligned_two["AlignmentIsUsable"] == 0).all())
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_raises_before_writing_when_duplicate_logical_lap_numbers_exist(self) -> None:
        first_df = build_raw_lap_dataframe(lap_number=2, timestamp_step_ms=40)
        second_df = build_raw_lap_dataframe(
            path_points=offset_path_points(build_parallel_section_path_points(), dy=0.5, start_index=40, end_index=80),
            lap_number=2,
            timestamp_step_ms=55,
        )
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        first_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        second_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            lap_number=2,
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(first_df["TimestampMS"].iloc[-1]),
        )
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            with self.assertRaisesRegex(ValueError, "Duplicate logical lap numbers"):
                process_session(raw_session_dir, processed_session_dir)

            self.assertFalse((processed_session_dir / "metadata.json").exists())
            self.assertFalse((processed_session_dir / "reference_path.csv").exists())
            self.assertEqual(list(processed_session_dir.glob("lap_*.csv")), [])
            self.assertEqual(list(processed_session_dir.glob("*.validation.json")), [])
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_clears_stale_reference_artifact_on_rerun_without_reference_geometry(self) -> None:
        good_df = build_raw_lap_dataframe(path_points=build_parallel_section_path_points(), lap_number=1)
        rerun_df = build_raw_lap_dataframe(lap_number=1)
        rerun_df[["PositionX", "PositionY", "PositionZ"]] = np.nan
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        good_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(good_df["TimestampMS"].iloc[-1]),
        )
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            self.assertTrue((processed_session_dir / "reference_path.csv").exists())

            rerun_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
            process_session(raw_session_dir, processed_session_dir)

            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertFalse((processed_session_dir / "reference_path.csv").exists())
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY)
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_clears_stale_processed_artifacts_before_duplicate_guard_failure(self) -> None:
        first_df = build_raw_lap_dataframe(lap_number=1, timestamp_step_ms=40)
        second_df = build_raw_lap_dataframe(
            path_points=offset_path_points(build_parallel_section_path_points(), dy=0.5, start_index=40, end_index=80),
            lap_number=2,
            timestamp_step_ms=55,
        )
        duplicate_df = second_df.copy()
        duplicate_df["LapNumber"] = 1
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        first_df.to_csv(raw_session_dir / "lap_001.csv", index=False)
        second_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
        metadata = build_session_metadata(
            close_reason=LAP_CLOSE_REASON_LAP_ROLLOVER,
            last_timestamp_ms=int(first_df["TimestampMS"].iloc[-1]),
        )
        metadata["lap_index"]["2"] = {
            "close_reason": LAP_CLOSE_REASON_LAP_ROLLOVER,
            "first_timestamp_ms": int(second_df["TimestampMS"].iloc[0]),
            "last_timestamp_ms": int(second_df["TimestampMS"].iloc[-1]),
        }
        metadata["total_laps"] = 2
        (raw_session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        try:
            process_session(raw_session_dir, processed_session_dir)
            self.assertTrue((processed_session_dir / "metadata.json").exists())
            self.assertTrue((processed_session_dir / "reference_path.csv").exists())

            duplicate_df.to_csv(raw_session_dir / "lap_002.csv", index=False)
            with self.assertRaisesRegex(ValueError, "Duplicate logical lap numbers"):
                process_session(raw_session_dir, processed_session_dir)

            self.assertFalse((processed_session_dir / "metadata.json").exists())
            self.assertFalse((processed_session_dir / "reference_path.csv").exists())
            self.assertEqual(list(processed_session_dir.glob("lap_*.csv")), [])
            self.assertEqual(list(processed_session_dir.glob("*.validation.json")), [])
        finally:
            shutil.rmtree(temp_root)

    def test_process_session_with_no_valid_laps_skips_alignment_cleanly(self) -> None:
        invalid_df = build_raw_lap_dataframe(start_current_lap_s=3.5)
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        processed_session_dir = temp_root / "processed" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        invalid_df.to_csv(raw_session_dir / "lap_001.csv", index=False)

        try:
            process_session(raw_session_dir, processed_session_dir)
            processed_lap = pd.read_csv(processed_session_dir / "lap_001.csv")
            processed_metadata = json.loads((processed_session_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertFalse((processed_session_dir / "reference_path.csv").exists())
            self.assertTrue(processed_lap["TrackProgressM"].isna().all())
            self.assertTrue((processed_lap["AlignmentIsUsable"] == 0).all())
            self.assertEqual(processed_metadata["alignment"]["status"], ALIGNMENT_STATUS_SKIPPED_NO_VALID_LAPS)
            self.assertEqual(processed_metadata["alignment"]["aligned_lap_count"], 0)
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
