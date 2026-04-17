from __future__ import annotations

import unittest

import pandas as pd

from src.processing.alignment import align_processed_lap, build_reference_path
from src.processing.distance import build_processed_lap_dataframe
from src.processing.track_outline import (
    TRACK_OUTLINE_MIN_WIDTH_M,
    TRACK_OUTLINE_SOURCE_SESSION_AGGREGATE,
    TRACK_OUTLINE_SOURCE_SYNTHETIC_REFERENCE_PATH,
    build_session_track_outline,
)


RAW_LAP_COLUMNS = [
    "IsRaceOn",
    "TimestampMS",
    "EngineMaxRpm",
    "EngineIdleRpm",
    "CurrentEngineRpm",
    "CarOrdinal",
    "PositionX",
    "PositionY",
    "PositionZ",
    "Speed",
    "Power",
    "Torque",
    "Boost",
    "DistanceTraveled",
    "BestLap",
    "LastLap",
    "CurrentLap",
    "CurrentRaceTime",
    "LapNumber",
    "Accel",
    "Brake",
    "Clutch",
    "HandBrake",
    "Gear",
    "Steer",
    "TrackOrdinal",
]


def build_raw_lap_dataframe(
    sample_count: int = 120,
    lap_number: int = 1,
    lateral_offset_z: float = 0.0,
    offset_start: int | None = None,
    offset_end: int | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for index in range(sample_count):
        base_z = float(index) * 0.2
        if offset_start is not None and offset_end is not None and offset_start <= index < offset_end:
            base_z += lateral_offset_z
        rows.append(
            {
                "IsRaceOn": 1,
                "TimestampMS": 1000 + (index * 50),
                "EngineMaxRpm": 8000.0,
                "EngineIdleRpm": 900.0,
                "CurrentEngineRpm": 4200.0 + (index * 15.0),
                "CarOrdinal": 12,
                "PositionX": float(index * 3.0),
                "PositionY": 0.0,
                "PositionZ": base_z,
                "Speed": 30.0 + (index * 0.75),
                "Power": 150.0 + index,
                "Torque": 220.0,
                "Boost": 0.2,
                "DistanceTraveled": float(index * 3.0),
                "BestLap": 85.0,
                "LastLap": 86.0,
                "CurrentLap": index * 0.25,
                "CurrentRaceTime": 50.0 + ((1000 + (index * 50)) / 1000.0),
                "LapNumber": lap_number,
                "Accel": min(255, 160 + (index * 2)),
                "Brake": max(0, 12 - min(index, 12)),
                "Clutch": 0,
                "HandBrake": 0,
                "Gear": 3 if index < (sample_count // 2) else 4,
                "Steer": max(-20, min(20, index - (sample_count // 2))),
                "TrackOrdinal": 110,
            }
        )
    return pd.DataFrame(rows, columns=RAW_LAP_COLUMNS)


class TrackOutlineTests(unittest.TestCase):
    def test_build_session_track_outline_aggregates_valid_laps(self) -> None:
        reference_processed = build_processed_lap_dataframe(
            build_raw_lap_dataframe(lap_number=1),
            session_id="outline_session",
        )
        peer_processed = build_processed_lap_dataframe(
            build_raw_lap_dataframe(
                lap_number=2,
                lateral_offset_z=2.2,
                offset_start=35,
                offset_end=85,
            ),
            session_id="outline_session",
        )

        reference_path = build_reference_path(reference_processed)
        aligned_reference, _ = align_processed_lap(reference_processed, reference_path)
        aligned_peer, _ = align_processed_lap(peer_processed, reference_path)

        outline = build_session_track_outline(
            session_id="outline_session",
            aligned_laps={1: aligned_reference, 2: aligned_peer},
            reference_path_df=reference_path,
        )

        self.assertIsNotNone(outline)
        assert outline is not None
        self.assertEqual(outline.source_kind, TRACK_OUTLINE_SOURCE_SESSION_AGGREGATE)
        self.assertEqual(outline.source_lap_numbers, [1, 2])
        self.assertEqual(outline.contributing_lap_count, 2)
        self.assertGreater(len(outline.points), 20)
        progress_norms = [point.progress_norm for point in outline.points]
        distance_m = [point.distance_m for point in outline.points]
        self.assertEqual(progress_norms, sorted(progress_norms))
        self.assertEqual(distance_m, sorted(distance_m))
        self.assertGreaterEqual(min(point.width_m for point in outline.points), TRACK_OUTLINE_MIN_WIDTH_M)

    def test_build_session_track_outline_falls_back_to_synthetic_reference_path(self) -> None:
        reference_processed = build_processed_lap_dataframe(
            build_raw_lap_dataframe(lap_number=1),
            session_id="outline_session",
        )
        reference_path = build_reference_path(reference_processed)
        aligned_reference, _ = align_processed_lap(reference_processed, reference_path)
        invalidated_reference = aligned_reference.copy()
        invalidated_reference["LapIsValid"] = 0

        outline = build_session_track_outline(
            session_id="outline_session",
            aligned_laps={1: invalidated_reference},
            reference_path_df=reference_path,
        )

        self.assertIsNotNone(outline)
        assert outline is not None
        self.assertEqual(outline.source_kind, TRACK_OUTLINE_SOURCE_SYNTHETIC_REFERENCE_PATH)
        self.assertEqual(outline.source_lap_numbers, [])
        self.assertEqual(outline.contributing_lap_count, 0)
        self.assertTrue(all(point.width_m == TRACK_OUTLINE_MIN_WIDTH_M for point in outline.points))


if __name__ == "__main__":
    unittest.main()
