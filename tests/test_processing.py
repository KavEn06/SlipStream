from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.processing.distance import (
    build_processed_lap_dataframe,
    calculate_distance_series,
    process_session,
    resample_processed_lap,
)
from src.schemas import PROCESSED_LAP_COLUMNS


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_raw_lap.csv"


class ProcessingTests(unittest.TestCase):
    def test_processed_lap_contains_canonical_columns_and_features(self) -> None:
        raw_df = pd.read_csv(FIXTURE_PATH)
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
        raw_df = pd.read_csv(FIXTURE_PATH)
        distance = calculate_distance_series(raw_df)
        processed_df = build_processed_lap_dataframe(raw_df)
        resampled_df = resample_processed_lap(processed_df, num_points=25)

        self.assertEqual(len(distance), len(raw_df))
        self.assertGreater(float(distance.iloc[-1]), 0.0)
        self.assertEqual(len(resampled_df), 25)
        self.assertAlmostEqual(float(resampled_df["NormalizedDistance"].iloc[0]), 0.0, places=6)
        self.assertAlmostEqual(float(resampled_df["NormalizedDistance"].iloc[-1]), 1.0, places=6)

    def test_process_session_writes_processed_laps_and_metadata(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        raw_session_dir = temp_root / "raw" / "session_fixture"
        raw_session_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE_PATH, raw_session_dir / "lap_001.csv")
        (raw_session_dir / "metadata.json").write_text(
            json.dumps({"session_id": "session_fixture", "track_ordinal": 110}, indent=2),
            encoding="utf-8",
        )

        try:
            written_paths = process_session(raw_session_dir, temp_root / "processed" / "session_fixture")
            self.assertEqual(len(written_paths), 1)
            self.assertTrue(written_paths[0].exists())

            processed_metadata = json.loads(
                (temp_root / "processed" / "session_fixture" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertIn("processed_schema_version", processed_metadata)
        finally:
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    unittest.main()
