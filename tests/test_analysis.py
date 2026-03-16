from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.analysis.comparison import (
    build_reference_lap,
    compare_lap_to_reference,
    session_consistency_metrics,
)
from src.analysis.segmentation import segment_lap
from src.processing.distance import build_processed_lap_dataframe


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_raw_lap.csv"


class AnalysisTests(unittest.TestCase):
    def test_segmentation_emits_driving_regions(self) -> None:
        processed_lap = build_processed_lap_dataframe(pd.read_csv(FIXTURE_PATH))
        segments = segment_lap(processed_lap)

        self.assertFalse(segments.empty)
        self.assertIn("straight", set(segments["RegionType"]))
        self.assertIn("apex", set(segments["RegionType"]))

    def test_reference_builders_and_findings_work_on_processed_laps(self) -> None:
        baseline = build_processed_lap_dataframe(pd.read_csv(FIXTURE_PATH))
        slower = baseline.copy()
        slower["SpeedMps"] = slower["SpeedMps"] * 0.92
        slower["SpeedKph"] = slower["SpeedMps"] * 3.6
        slower["ElapsedTimeS"] = slower["ElapsedTimeS"] * 1.08
        slower["LapTimeS"] = float(slower["ElapsedTimeS"].iloc[-1])
        slower["IsCoasting"] = slower["IsCoasting"].astype(int)

        reference_pb = build_reference_lap([baseline, slower], mode="personal_best", num_points=60)
        reference_avg = build_reference_lap([baseline, slower], mode="session_average", num_points=60)
        reference_sector = build_reference_lap([baseline, slower], mode="best_sector", num_points=60)
        findings = compare_lap_to_reference(slower, reference_pb, segments=segment_lap(slower), num_points=60)

        self.assertEqual(reference_pb["ReferenceMode"].iloc[0], "personal_best")
        self.assertEqual(reference_avg["ReferenceMode"].iloc[0], "session_average")
        self.assertEqual(reference_sector["ReferenceMode"].iloc[0], "best_sector")
        self.assertFalse(findings.empty)
        self.assertIn("time_loss", set(findings["finding_type"]))
        self.assertIn("minimum_speed", set(findings["finding_type"]))

    def test_session_consistency_metrics_report_variation(self) -> None:
        baseline = build_processed_lap_dataframe(pd.read_csv(FIXTURE_PATH))
        slower = baseline.copy()
        slower["ElapsedTimeS"] = slower["ElapsedTimeS"] * 1.05
        slower["LapTimeS"] = float(slower["ElapsedTimeS"].iloc[-1])

        metrics = session_consistency_metrics([baseline, slower])
        self.assertEqual(metrics["lap_count"], 2.0)
        self.assertGreater(metrics["lap_time_std_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
