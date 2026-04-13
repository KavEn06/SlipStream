"""Unit tests for ``src.analysis.session_summary``."""

from __future__ import annotations

import unittest

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import CORNER_CARDS_SESSION_CAP
from src.analysis.corner_records import CornerRecord, PhaseMetrics, StraightRecord
from src.analysis.detectors import (
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_OVER_SLOW_MID_CORNER,
)
from src.analysis.findings import Finding
from src.analysis.session_summary import (
    CornerCard,
    SessionSummary,
    _DETECTOR_LABELS,
    build_session_summary,
)
from src.processing.segmentation import CornerDefinition


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _phase(time_s: float = 2.0) -> PhaseMetrics:
    return PhaseMetrics(
        time_s=time_s,
        entry_speed_kph=180.0,
        exit_speed_kph=150.0,
        min_speed_kph=100.0,
        min_speed_progress_norm=0.42,
    )


def _record(corner_id: int, lap_number: int, corner_time_s: float = 6.0) -> CornerRecord:
    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner_id,
        is_compound=False,
        alignment_quality_m=0.3,
        alignment_used_fallback=False,
        corner_time_s=corner_time_s,
        entry=_phase(),
        apex=_phase(),
        exit=_phase(),
        brake=None,
        throttle=None,
        coasting_distance_m=0.0,
        gear_at_min_speed=3,
        min_speed_kph=100.0,
        min_speed_progress_norm=0.42,
        corner_end_progress_norm=0.65,
        exit_steering_correction_count=0,
        sub_corner_records=[],
    )


def _baseline(corner_id: int, ref_lap: int, corner_time_s: float = 5.0) -> CornerBaseline:
    return CornerBaseline(
        corner_id=corner_id,
        reference_lap_number=ref_lap,
        reference_record=_record(corner_id, ref_lap, corner_time_s),
        candidate_lap_numbers=[ref_lap, ref_lap + 1],
    )


def _straight(straight_id: int, lap_number: int, time_s: float = 10.0) -> StraightRecord:
    return StraightRecord(
        straight_id=straight_id,
        lap_number=lap_number,
        time_s=time_s,
        entry_speed_kph=200.0,
        exit_speed_kph=180.0,
    )


def _corner_def(corner_id: int, start_m: float = 100.0, end_m: float = 200.0) -> CornerDefinition:
    return CornerDefinition(
        corner_id=corner_id,
        track_corner_key=f"c{corner_id}",
        start_progress_norm=start_m / 5000.0,
        end_progress_norm=end_m / 5000.0,
        center_progress_norm=(start_m + end_m) / 2 / 5000.0,
        start_distance_m=start_m,
        end_distance_m=end_m,
        center_distance_m=(start_m + end_m) / 2,
        approach_start_distance_m=max(0.0, start_m - 80.0),
        entry_end_progress_norm=(start_m + (end_m - start_m) * 0.3) / 5000.0,
        exit_start_progress_norm=(start_m + (end_m - start_m) * 0.7) / 5000.0,
        length_m=end_m - start_m,
        peak_curvature=0.02,
        mean_curvature=0.01,
        direction="left",
        is_compound=False,
    )


def _finding(
    corner_id: int,
    lap_number: int,
    detector: str = DETECTOR_EARLY_BRAKING,
    time_loss_s: float = 0.25,
    confidence: float = 0.8,
) -> Finding:
    metrics = {
        "brake_point_delta_m": -15.0,
        "candidate_brake_distance_m": 480.0,
        "baseline_brake_distance_m": 500.0,
        "exit_speed_delta_kph": -3.0,
        "entry_speed_delta_kph": 0.0,
        "brake_steering_overlap_m": 5.0,
        "baseline_brake_steering_overlap_m": 3.0,
        "trail_brake_depth_m": 8.0,
        "baseline_trail_brake_depth_m": 1.0,
        "min_speed_delta_kph": -5.0,
        "candidate_min_speed_kph": 95.0,
        "baseline_min_speed_kph": 100.0,
        "coasting_delta_m": 2.0,
        "exit_full_throttle_fraction": 0.6,
        "baseline_exit_full_throttle_fraction": 0.8,
        "exit_full_throttle_fraction_delta": 0.2,
        "throttle_pickup_delay_m": 12.0,
        "candidate_pickup_distance_from_min_speed_m": 22.0,
        "baseline_pickup_distance_from_min_speed_m": 10.0,
        "exit_steering_correction_count": 6,
        "baseline_exit_steering_correction_count": 1,
        "correction_count_delta": 5,
        "corner_time_delta_s": time_loss_s,
    }
    return Finding(
        finding_id=f"f{corner_id}{lap_number}",
        corner_id=corner_id,
        lap_number=lap_number,
        detector=detector,
        severity="moderate",
        confidence=confidence,
        time_loss_s=time_loss_s,
        templated_text=f"T{corner_id}: test finding text",
        ai_context=f"[Finding] Test | T{corner_id} | Lap {lap_number}\n",
        evidence_refs=[],
        metrics_snapshot=metrics,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestTheoreticalBestLap(unittest.TestCase):
    def test_sums_best_corners_and_straights(self) -> None:
        # 2 corners, 2 straights, 2 laps.
        # Corner 1: lap 1 = 5.0s, lap 2 = 6.0s → baseline picks 5.0s
        # Corner 2: lap 1 = 7.0s, lap 2 = 6.5s → baseline picks 6.5s
        # Straight 1: lap 1 = 10.0s, lap 2 = 9.5s → best 9.5s
        # Straight 2: lap 1 = 8.0s, lap 2 = 8.5s → best 8.0s
        # Theoretical best = 5.0 + 6.5 + 9.5 + 8.0 = 29.0s
        baselines = {
            1: _baseline(1, ref_lap=1, corner_time_s=5.0),
            2: _baseline(2, ref_lap=2, corner_time_s=6.5),
        }
        straights = [
            _straight(1, lap_number=1, time_s=10.0),
            _straight(1, lap_number=2, time_s=9.5),
            _straight(2, lap_number=1, time_s=8.0),
            _straight(2, lap_number=2, time_s=8.5),
        ]
        records = {
            1: [_record(1, 1, 5.0), _record(1, 2, 6.0)],
            2: [_record(2, 1, 7.0), _record(2, 2, 6.5)],
        }
        summary = build_session_summary(
            per_corner_records=records,
            per_corner_baselines=baselines,
            straight_records=straights,
            findings_all=[_finding(1, 2, time_loss_s=1.0)],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 30.0, 2: 31.0},
            reference_length_m=5000.0,
        )
        self.assertAlmostEqual(summary.theoretical_best_lap_s, 29.0)

    def test_gap_to_actual_is_non_negative(self) -> None:
        baselines = {1: _baseline(1, ref_lap=1, corner_time_s=5.0)}
        straights = [_straight(1, 1, 10.0)]
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0)]},
            per_corner_baselines=baselines,
            straight_records=straights,
            findings_all=[],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0},
            reference_length_m=5000.0,
        )
        self.assertGreaterEqual(summary.gap_to_theoretical_s, 0.0)

    def test_theoretical_leq_best_actual(self) -> None:
        baselines = {
            1: _baseline(1, ref_lap=1, corner_time_s=5.0),
            2: _baseline(2, ref_lap=2, corner_time_s=6.0),
        }
        straights = [
            _straight(1, 1, 10.0),
            _straight(1, 2, 9.0),
        ]
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.0), _record(1, 2, 5.5)],
                2: [_record(2, 1, 6.5), _record(2, 2, 6.0)],
            },
            per_corner_baselines=baselines,
            straight_records=straights,
            findings_all=[],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 21.5, 2: 20.5},
            reference_length_m=5000.0,
        )
        self.assertLessEqual(
            summary.theoretical_best_lap_s, summary.best_actual_lap_s
        )


class TestCornerCards(unittest.TestCase):
    def _build_summary(
        self,
        findings: list[Finding] | None = None,
        n_corners: int = 2,
    ) -> SessionSummary:
        if findings is None:
            findings = [
                _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.30, confidence=0.9),
                _finding(2, 2, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.15, confidence=0.8),
            ]
        baselines = {
            i: _baseline(i, ref_lap=1, corner_time_s=5.0)
            for i in range(1, n_corners + 1)
        }
        straights = [_straight(1, 1, 10.0)]
        corner_defs = [
            _corner_def(i, start_m=100.0 * i, end_m=100.0 * i + 80.0)
            for i in range(1, n_corners + 1)
        ]
        records = {
            i: [_record(i, 1, 5.0), _record(i, 2, 5.5)]
            for i in range(1, n_corners + 1)
        }
        return build_session_summary(
            per_corner_records=records,
            per_corner_baselines=baselines,
            straight_records=straights,
            findings_all=findings,
            corner_definitions=corner_defs,
            per_lap_lap_times={1: 25.0, 2: 26.0},
            reference_length_m=5000.0,
        )

    def test_one_card_per_corner_with_findings(self) -> None:
        summary = self._build_summary()
        corner_ids = [c.corner_id for c in summary.corner_cards]
        self.assertEqual(sorted(corner_ids), [1, 2])

    def test_no_card_for_corner_without_findings(self) -> None:
        # Only corner 1 has a finding, corner 2 does not.
        summary = self._build_summary(
            findings=[_finding(1, 2, time_loss_s=0.20)],
            n_corners=2,
        )
        corner_ids = [c.corner_id for c in summary.corner_cards]
        self.assertIn(1, corner_ids)
        self.assertNotIn(2, corner_ids)

    def test_primary_issue_is_highest_ranking(self) -> None:
        # Two findings on same corner: one high-ranking, one low.
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.30, confidence=0.9),
            _finding(1, 3, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.10, confidence=0.5),
        ]
        summary = self._build_summary(findings=findings, n_corners=1)
        card = summary.corner_cards[0]
        self.assertEqual(card.primary_detector, DETECTOR_EARLY_BRAKING)
        self.assertEqual(card.primary_issue, "Braking too early")

    def test_position_context_populated(self) -> None:
        summary = self._build_summary()
        card = summary.corner_cards[0]
        self.assertIn("corner_start_m", card.position_context)
        self.assertIn("apex_m", card.position_context)
        self.assertIn("corner_end_m", card.position_context)
        self.assertGreater(card.apex_m, 0)
        self.assertGreater(card.corner_start_m, 0)

    def test_measurable_deltas_populated(self) -> None:
        summary = self._build_summary()
        for card in summary.corner_cards:
            self.assertGreater(len(card.measurable_deltas), 0)
            for delta in card.measurable_deltas:
                self.assertIsInstance(delta, str)

    def test_cards_ordered_by_time_left(self) -> None:
        findings = [
            _finding(1, 2, time_loss_s=0.10),
            _finding(2, 2, time_loss_s=0.30),
            _finding(3, 2, time_loss_s=0.20),
        ]
        summary = self._build_summary(findings=findings, n_corners=3)
        time_lefts = [c.time_left_s for c in summary.corner_cards]
        self.assertEqual(time_lefts, sorted(time_lefts, reverse=True))

    def test_cards_capped(self) -> None:
        n = CORNER_CARDS_SESSION_CAP + 5
        findings = [
            _finding(i, 2, time_loss_s=0.10 + i * 0.01) for i in range(1, n + 1)
        ]
        summary = self._build_summary(findings=findings, n_corners=n)
        self.assertLessEqual(len(summary.corner_cards), CORNER_CARDS_SESSION_CAP)

    def test_charts_to_inspect_matches_detector(self) -> None:
        summary = self._build_summary(
            findings=[_finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.20)],
            n_corners=1,
        )
        card = summary.corner_cards[0]
        self.assertIn("brake", card.charts_to_inspect)
        self.assertIn("speed", card.charts_to_inspect)

    def test_best_example_lap_from_baseline(self) -> None:
        summary = self._build_summary()
        for card in summary.corner_cards:
            self.assertEqual(card.best_example_lap, 1)


class TestSessionTheme(unittest.TestCase):
    def test_theme_is_detector_with_most_accumulated_loss(self) -> None:
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(2, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.15),
            _finding(3, 2, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.20),
        ]
        summary = build_session_summary(
            per_corner_records={
                i: [_record(i, 1, 5.0), _record(i, 2, 5.5)]
                for i in range(1, 4)
            },
            per_corner_baselines={
                i: _baseline(i, ref_lap=1) for i in range(1, 4)
            },
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[
                _corner_def(i, 100.0 * i, 100.0 * i + 80.0) for i in range(1, 4)
            ],
            per_lap_lap_times={1: 25.0, 2: 26.0},
            reference_length_m=5000.0,
        )
        # early_braking total = 0.25, exit_phase_loss total = 0.20
        self.assertEqual(summary.main_repeated_theme, "Braking too early")
        self.assertAlmostEqual(summary.main_repeated_theme_total_loss_s, 0.25)

    def test_theme_label_is_human_readable(self) -> None:
        findings = [_finding(1, 2, DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.30)]
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1), _record(1, 2)]},
            per_corner_baselines={1: _baseline(1, 1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        self.assertEqual(
            summary.main_repeated_theme,
            _DETECTOR_LABELS[DETECTOR_OVER_SLOW_MID_CORNER],
        )

    def test_no_findings_gives_no_issues(self) -> None:
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1)]},
            per_corner_baselines={1: _baseline(1, 1)},
            straight_records=[_straight(1, 1)],
            findings_all=[],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0},
            reference_length_m=5000.0,
        )
        self.assertEqual(summary.main_repeated_theme, "No issues detected")
        self.assertAlmostEqual(summary.main_repeated_theme_total_loss_s, 0.0)


class TestEnrichedAiContext(unittest.TestCase):
    def test_ai_context_includes_track_position(self) -> None:
        findings = [_finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0), _record(1, 2, 5.5)]},
            per_corner_baselines={1: _baseline(1, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[_corner_def(1, start_m=150.0, end_m=250.0)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        card = summary.corner_cards[0]
        self.assertIn("150", card.ai_context)  # corner start
        self.assertIn("250", card.ai_context)  # corner end
        self.assertIn("200", card.ai_context)  # apex (midpoint)
        self.assertIn("left", card.ai_context)  # direction

    def test_ai_context_includes_brake_point_for_braking_detector(self) -> None:
        findings = [_finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1), _record(1, 2)]},
            per_corner_baselines={1: _baseline(1, 1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        card = summary.corner_cards[0]
        # metrics has candidate_brake_distance_m=480 and baseline=500
        self.assertIn("480", card.ai_context)
        self.assertIn("500", card.ai_context)


class TestSerialization(unittest.TestCase):
    def test_to_dict_roundtrip(self) -> None:
        findings = [_finding(1, 2, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0), _record(1, 2, 5.5)]},
            per_corner_baselines={1: _baseline(1, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        payload = summary.to_dict()
        self.assertIn("theoretical_best_lap_s", payload)
        self.assertIn("best_actual_lap_s", payload)
        self.assertIn("corner_cards", payload)
        self.assertIn("main_repeated_theme", payload)
        self.assertIsInstance(payload["corner_cards"], list)
        self.assertGreater(len(payload["corner_cards"]), 0)
        card = payload["corner_cards"][0]
        self.assertIn("corner_id", card)
        self.assertIn("position_context", card)
        self.assertIn("ai_context", card)


class TestBiggestTimeLeftCorners(unittest.TestCase):
    def test_top_3_biggest(self) -> None:
        findings = [
            _finding(1, 2, time_loss_s=0.10),
            _finding(2, 2, time_loss_s=0.40),
            _finding(3, 2, time_loss_s=0.20),
            _finding(4, 2, time_loss_s=0.30),
        ]
        summary = build_session_summary(
            per_corner_records={
                i: [_record(i, 1, 5.0), _record(i, 2, 5.5)]
                for i in range(1, 5)
            },
            per_corner_baselines={i: _baseline(i, 1) for i in range(1, 5)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[
                _corner_def(i, 100.0 * i, 100.0 * i + 80.0) for i in range(1, 5)
            ],
            per_lap_lap_times={1: 30.0, 2: 32.0},
            reference_length_m=5000.0,
        )
        biggest = summary.biggest_time_left_corners
        self.assertEqual(len(biggest), 3)
        # Ordered by time_left_s descending.
        self.assertEqual(biggest[0]["corner_id"], 2)
        self.assertAlmostEqual(biggest[0]["time_left_s"], 0.40)
        self.assertEqual(biggest[1]["corner_id"], 4)
        self.assertEqual(biggest[2]["corner_id"], 3)


if __name__ == "__main__":
    unittest.main()
