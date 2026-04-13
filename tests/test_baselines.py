"""Unit tests for ``src.analysis.baselines``."""

from __future__ import annotations

import unittest

from src.analysis.baselines import (
    CornerBaseline,
    build_per_corner_baselines,
    group_records_by_corner,
)
from src.analysis.corner_records import (
    BrakeEvent,
    CornerRecord,
    PhaseMetrics,
    ThrottleEvent,
)
from src.analysis.constants import BASELINE_ENTRY_SPEED_ADVANTAGE_KPH


def _make_phase(min_kph: float = 120.0, entry_kph: float = 180.0) -> PhaseMetrics:
    return PhaseMetrics(
        time_s=3.0,
        entry_speed_kph=entry_kph,
        exit_speed_kph=150.0,
        min_speed_kph=min_kph,
        min_speed_progress_norm=0.4,
    )


def _make_record(
    *,
    corner_id: int,
    lap_number: int,
    corner_time_s: float,
    alignment_used_fallback: bool = False,
    alignment_quality_m: float = 0.3,
    entry_kph: float = 180.0,
) -> CornerRecord:
    phase = _make_phase(entry_kph=entry_kph)
    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner_id,
        is_compound=False,
        alignment_quality_m=alignment_quality_m,
        alignment_used_fallback=alignment_used_fallback,
        corner_time_s=corner_time_s,
        entry=phase,
        apex=phase,
        exit=phase,
        brake=None,
        throttle=None,
        coasting_distance_m=0.0,
        gear_at_min_speed=3,
        min_speed_kph=phase.min_speed_kph,
        min_speed_progress_norm=phase.min_speed_progress_norm,
        corner_end_progress_norm=0.65,
        exit_steering_correction_count=0,
        sub_corner_records=[],
    )


class TestGroupRecordsByCorner(unittest.TestCase):
    def test_buckets_by_corner_id(self) -> None:
        records = [
            _make_record(corner_id=1, lap_number=1, corner_time_s=5.0),
            _make_record(corner_id=2, lap_number=1, corner_time_s=4.0),
            _make_record(corner_id=1, lap_number=2, corner_time_s=4.9),
        ]
        grouped = group_records_by_corner(records)
        self.assertEqual(set(grouped.keys()), {1, 2})
        self.assertEqual(len(grouped[1]), 2)
        self.assertEqual(len(grouped[2]), 1)

    def test_preserves_order_within_bucket(self) -> None:
        records = [
            _make_record(corner_id=1, lap_number=3, corner_time_s=5.0),
            _make_record(corner_id=1, lap_number=1, corner_time_s=5.0),
            _make_record(corner_id=1, lap_number=2, corner_time_s=5.0),
        ]
        grouped = group_records_by_corner(records)
        self.assertEqual([r.lap_number for r in grouped[1]], [3, 1, 2])


class TestBuildPerCornerBaselines(unittest.TestCase):
    def test_picks_fastest_corner_time(self) -> None:
        records = {
            1: [
                _make_record(corner_id=1, lap_number=1, corner_time_s=5.0),
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.8),
                _make_record(corner_id=1, lap_number=3, corner_time_s=4.9),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertIn(1, baselines)
        self.assertEqual(baselines[1].reference_lap_number, 2)
        self.assertAlmostEqual(baselines[1].reference_record.corner_time_s, 4.8)

    def test_tie_breaks_to_earliest_lap(self) -> None:
        records = {
            1: [
                _make_record(corner_id=1, lap_number=3, corner_time_s=5.0),
                _make_record(corner_id=1, lap_number=1, corner_time_s=5.0),
                _make_record(corner_id=1, lap_number=2, corner_time_s=5.0),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].reference_lap_number, 1)

    def test_skips_fallback_alignment_records(self) -> None:
        records = {
            1: [
                _make_record(
                    corner_id=1,
                    lap_number=1,
                    corner_time_s=4.5,
                    alignment_used_fallback=True,
                ),
                _make_record(corner_id=1, lap_number=2, corner_time_s=5.0),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].reference_lap_number, 2)
        self.assertAlmostEqual(baselines[1].reference_record.corner_time_s, 5.0)

    def test_omits_corner_with_all_fallback_laps(self) -> None:
        records = {
            1: [
                _make_record(
                    corner_id=1,
                    lap_number=1,
                    corner_time_s=4.5,
                    alignment_used_fallback=True,
                ),
                _make_record(
                    corner_id=1,
                    lap_number=2,
                    corner_time_s=4.6,
                    alignment_used_fallback=True,
                ),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertNotIn(1, baselines)

    def test_omits_corner_with_nonpositive_time(self) -> None:
        records = {
            1: [
                _make_record(corner_id=1, lap_number=1, corner_time_s=0.0),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertNotIn(1, baselines)

    def test_multiple_corners_independent_winners(self) -> None:
        records = {
            1: [
                _make_record(corner_id=1, lap_number=1, corner_time_s=5.0),
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.8),
            ],
            2: [
                _make_record(corner_id=2, lap_number=1, corner_time_s=3.5),
                _make_record(corner_id=2, lap_number=2, corner_time_s=3.9),
            ],
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].reference_lap_number, 2)
        self.assertEqual(baselines[2].reference_lap_number, 1)

    def test_candidate_lap_numbers_include_all_records(self) -> None:
        records = {
            1: [
                _make_record(
                    corner_id=1,
                    lap_number=1,
                    corner_time_s=5.0,
                    alignment_used_fallback=True,
                ),
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.8),
                _make_record(corner_id=1, lap_number=3, corner_time_s=4.9),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].candidate_lap_numbers, [1, 2, 3])

    def test_baseline_is_frozen_dataclass(self) -> None:
        records = {
            1: [_make_record(corner_id=1, lap_number=1, corner_time_s=5.0)],
        }
        baselines = build_per_corner_baselines(records)
        baseline = baselines[1]
        self.assertIsInstance(baseline, CornerBaseline)
        with self.assertRaises(Exception):
            baseline.corner_id = 99  # type: ignore[misc]


class TestBaselineEntrySpeedFilter(unittest.TestCase):
    def test_excludes_outlier_entry_speed_lap(self) -> None:
        """A lap with a large entry speed advantage must not become the baseline."""
        advantage = BASELINE_ENTRY_SPEED_ADVANTAGE_KPH + 1.0  # just over the limit
        records = {
            1: [
                # Lap 1 is fastest but arrived hot — should be excluded.
                _make_record(corner_id=1, lap_number=1, corner_time_s=4.5, entry_kph=180.0 + advantage),
                # Lap 2 is slightly slower but arrived at normal speed — should win.
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.8, entry_kph=180.0),
                _make_record(corner_id=1, lap_number=3, corner_time_s=5.0, entry_kph=180.0),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].reference_lap_number, 2)

    def test_normal_entry_variation_does_not_exclude(self) -> None:
        """Small entry speed differences (within threshold) do not affect selection."""
        records = {
            1: [
                # Lap 1 is fastest with a modest entry advantage — still eligible.
                _make_record(corner_id=1, lap_number=1, corner_time_s=4.5, entry_kph=183.0),
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.8, entry_kph=180.0),
            ]
        }
        baselines = build_per_corner_baselines(records)
        self.assertEqual(baselines[1].reference_lap_number, 1)

    def test_fallback_when_all_outliers(self) -> None:
        """If every usable lap would be excluded, fall back to the fastest among all."""
        advantage = BASELINE_ENTRY_SPEED_ADVANTAGE_KPH + 1.0
        records = {
            1: [
                _make_record(corner_id=1, lap_number=1, corner_time_s=4.5, entry_kph=180.0 + advantage),
                _make_record(corner_id=1, lap_number=2, corner_time_s=4.9, entry_kph=180.0 + advantage),
            ]
        }
        baselines = build_per_corner_baselines(records)
        # Falls back to fastest of all usable records.
        self.assertEqual(baselines[1].reference_lap_number, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
