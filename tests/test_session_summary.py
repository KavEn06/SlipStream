"""Unit tests for ``src.analysis.session_summary``."""

from __future__ import annotations

import unittest

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import CORNER_CARD_MIN_ACCUMULATED_LOSS_S, CORNER_CARDS_SESSION_CAP
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


def _corner_def(
    corner_id: int,
    start_m: float = 100.0,
    end_m: float = 200.0,
    sub_apex_distances_m: list[float] | None = None,
) -> CornerDefinition:
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
        sub_apex_distances_m=sub_apex_distances_m or [],
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


def _simple_summary(findings: list[Finding], n_corners: int = 2) -> SessionSummary:
    baselines = {
        i: _baseline(i, ref_lap=1, corner_time_s=5.0)
        for i in range(1, n_corners + 1)
    }
    return build_session_summary(
        per_corner_records={
            i: [_record(i, 1, 5.0), _record(i, 2, 5.5)]
            for i in range(1, n_corners + 1)
        },
        per_corner_baselines=baselines,
        straight_records=[_straight(1, 1)],
        findings_all=findings,
        corner_definitions=[
            _corner_def(i, start_m=100.0 * i, end_m=100.0 * i + 80.0)
            for i in range(1, n_corners + 1)
        ],
        per_lap_lap_times={1: 25.0, 2: 26.0},
        reference_length_m=5000.0,
    )


# ---------------------------------------------------------------------------
# Theoretical best lap
# ---------------------------------------------------------------------------


class TestTheoreticalBestLap(unittest.TestCase):
    def test_sums_best_corners_and_straights(self) -> None:
        # Corner 1 best = 5.0s, corner 2 best = 6.5s
        # Straight 1 best = 9.5s, straight 2 best = 8.0s
        # Theoretical best = 5.0 + 6.5 + 9.5 + 8.0 = 29.0s
        baselines = {
            1: _baseline(1, ref_lap=1, corner_time_s=5.0),
            2: _baseline(2, ref_lap=2, corner_time_s=6.5),
        }
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.0), _record(1, 2, 6.0)],
                2: [_record(2, 1, 7.0), _record(2, 2, 6.5)],
            },
            per_corner_baselines=baselines,
            straight_records=[
                _straight(1, lap_number=1, time_s=10.0),
                _straight(1, lap_number=2, time_s=9.5),
                _straight(2, lap_number=1, time_s=8.0),
                _straight(2, lap_number=2, time_s=8.5),
            ],
            findings_all=[_finding(1, 2, time_loss_s=1.0)],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 30.0, 2: 31.0},
            reference_length_m=5000.0,
        )
        self.assertAlmostEqual(summary.theoretical_best_lap_s, 29.0)

    def test_gap_to_actual_is_non_negative(self) -> None:
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0)]},
            per_corner_baselines={1: _baseline(1, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=[],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0},
            reference_length_m=5000.0,
        )
        self.assertGreaterEqual(summary.gap_to_theoretical_s, 0.0)

    def test_theoretical_leq_best_actual(self) -> None:
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.0), _record(1, 2, 5.5)],
                2: [_record(2, 1, 6.5), _record(2, 2, 6.0)],
            },
            per_corner_baselines={
                1: _baseline(1, ref_lap=1, corner_time_s=5.0),
                2: _baseline(2, ref_lap=2, corner_time_s=6.0),
            },
            straight_records=[_straight(1, 1, 10.0), _straight(1, 2, 9.0)],
            findings_all=[],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 21.5, 2: 20.5},
            reference_length_m=5000.0,
        )
        self.assertLessEqual(summary.theoretical_best_lap_s, summary.best_actual_lap_s)


# ---------------------------------------------------------------------------
# Corner cards
# ---------------------------------------------------------------------------


class TestCornerCards(unittest.TestCase):
    def test_one_card_per_corner_with_findings(self) -> None:
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.30),
            _finding(2, 2, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.15),
        ]
        summary = _simple_summary(findings)
        self.assertEqual(sorted(c.corner_id for c in summary.corner_cards), [1, 2])

    def test_no_card_for_corner_without_findings(self) -> None:
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.20)], n_corners=2)
        corner_ids = [c.corner_id for c in summary.corner_cards]
        self.assertIn(1, corner_ids)
        self.assertNotIn(2, corner_ids)

    def test_primary_issue_is_highest_ranking(self) -> None:
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.30, confidence=0.9),
            _finding(1, 3, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.10, confidence=0.5),
        ]
        card = _simple_summary(findings, n_corners=1).corner_cards[0]
        self.assertEqual(card.primary_detector, DETECTOR_EARLY_BRAKING)
        self.assertEqual(card.primary_issue, "Braking too early")

    def test_laps_affected_counts_findings(self) -> None:
        # 3 findings on corner 1 across 3 different laps.
        findings = [
            _finding(1, 2, time_loss_s=0.15),
            _finding(1, 3, time_loss_s=0.15),
            _finding(1, 4, time_loss_s=0.15),
        ]
        card = _simple_summary(findings, n_corners=1).corner_cards[0]
        self.assertEqual(card.laps_affected, 3)

    def test_time_left_is_average_across_findings(self) -> None:
        findings = [
            _finding(1, 2, time_loss_s=0.10),
            _finding(1, 3, time_loss_s=0.20),
            _finding(1, 4, time_loss_s=0.30),
        ]
        card = _simple_summary(findings, n_corners=1).corner_cards[0]
        self.assertAlmostEqual(card.time_left_s, 0.20)  # (0.10 + 0.20 + 0.30) / 3

    def test_systematic_corner_beats_single_outlier(self) -> None:
        # T1: 0.15s × 4 laps = 0.60s accumulated
        # T2: 0.25s × 1 lap  = 0.25s accumulated
        # T1 should rank higher despite lower per-lap loss.
        findings = [
            _finding(1, 2, time_loss_s=0.15),
            _finding(1, 3, time_loss_s=0.15),
            _finding(1, 4, time_loss_s=0.15),
            _finding(1, 5, time_loss_s=0.15),
            _finding(2, 2, time_loss_s=0.25),
        ]
        summary = _simple_summary(findings, n_corners=2)
        self.assertEqual(summary.corner_cards[0].corner_id, 1)

    def test_position_context_populated(self) -> None:
        card = _simple_summary([_finding(1, 2)]).corner_cards[0]
        self.assertIn("corner_start_m", card.position_context)
        self.assertIn("apex_m", card.position_context)
        self.assertIn("corner_end_m", card.position_context)
        self.assertGreater(card.apex_m, 0)

    def test_measurable_deltas_populated(self) -> None:
        for card in _simple_summary([_finding(1, 2), _finding(2, 2)]).corner_cards:
            self.assertGreater(len(card.measurable_deltas), 0)

    def test_cards_capped(self) -> None:
        n = CORNER_CARDS_SESSION_CAP + 5
        findings = [_finding(i, 2, time_loss_s=0.10 + i * 0.01) for i in range(1, n + 1)]
        summary = _simple_summary(findings, n_corners=n)
        self.assertLessEqual(len(summary.corner_cards), CORNER_CARDS_SESSION_CAP)

    def test_charts_to_inspect_matches_detector(self) -> None:
        card = _simple_summary([_finding(1, 2, DETECTOR_EARLY_BRAKING)], n_corners=1).corner_cards[0]
        self.assertIn("brake", card.charts_to_inspect)
        self.assertIn("speed", card.charts_to_inspect)

    def test_best_example_lap_from_baseline(self) -> None:
        for card in _simple_summary([_finding(1, 2), _finding(2, 2)]).corner_cards:
            self.assertEqual(card.best_example_lap, 1)


# ---------------------------------------------------------------------------
# Sub-corner apex resolution
# ---------------------------------------------------------------------------


class TestSubCornerApex(unittest.TestCase):
    def test_sub_corner_uses_sub_apex_distance(self) -> None:
        # Parent corner 8, sub-apexes at 2700m and 2800m.
        # Sub-corner 802 = parent 8, index 1 (0-based) → apex at 2800m.
        parent_def = _corner_def(
            8, start_m=2600.0, end_m=2900.0,
            sub_apex_distances_m=[2700.0, 2800.0],
        )
        findings = [_finding(802, 3, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={802: [_record(802, 1, 5.0), _record(802, 3, 5.5)]},
            per_corner_baselines={8: _baseline(8, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[parent_def],
            per_lap_lap_times={1: 16.0, 3: 17.0},
            reference_length_m=5000.0,
        )
        card = summary.corner_cards[0]
        self.assertAlmostEqual(card.apex_m, 2800.0)

    def test_sub_corner_first_apex(self) -> None:
        # Sub-corner 801 = parent 8, index 0 (0-based) → apex at 2700m.
        parent_def = _corner_def(
            8, start_m=2600.0, end_m=2900.0,
            sub_apex_distances_m=[2700.0, 2800.0],
        )
        findings = [_finding(801, 3, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={801: [_record(801, 1), _record(801, 3)]},
            per_corner_baselines={8: _baseline(8, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[parent_def],
            per_lap_lap_times={1: 16.0, 3: 17.0},
            reference_length_m=5000.0,
        )
        self.assertAlmostEqual(summary.corner_cards[0].apex_m, 2700.0)

    def test_sub_corner_falls_back_to_parent_center_when_index_missing(self) -> None:
        # sub_apex_distances_m is empty — fall back to center_distance_m.
        parent_def = _corner_def(8, start_m=2600.0, end_m=2900.0)
        findings = [_finding(802, 3, time_loss_s=0.20)]
        summary = build_session_summary(
            per_corner_records={802: [_record(802, 1), _record(802, 3)]},
            per_corner_baselines={8: _baseline(8, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[parent_def],
            per_lap_lap_times={1: 16.0, 3: 17.0},
            reference_length_m=5000.0,
        )
        self.assertAlmostEqual(summary.corner_cards[0].apex_m, 2750.0)  # center of 2600–2900


# ---------------------------------------------------------------------------
# Top themes
# ---------------------------------------------------------------------------


class TestTopThemes(unittest.TestCase):
    def _make_summary(self, findings: list[Finding]) -> SessionSummary:
        n = max(f.corner_id for f in findings)
        return build_session_summary(
            per_corner_records={
                i: [_record(i, 1, 5.0), _record(i, 2, 5.5)] for i in range(1, n + 1)
            },
            per_corner_baselines={i: _baseline(i, 1) for i in range(1, n + 1)},
            straight_records=[_straight(1, 1)],
            findings_all=findings,
            corner_definitions=[
                _corner_def(i, 100.0 * i, 100.0 * i + 80.0) for i in range(1, n + 1)
            ],
            per_lap_lap_times={1: 25.0, 2: 26.0},
            reference_length_m=5000.0,
        )

    def test_empty_findings_returns_empty_themes(self) -> None:
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1)]},
            per_corner_baselines={1: _baseline(1, 1)},
            straight_records=[_straight(1, 1)],
            findings_all=[],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0},
            reference_length_m=5000.0,
        )
        self.assertEqual(summary.top_themes, [])

    def test_top_theme_is_highest_accumulated_loss(self) -> None:
        # early_braking: 0.10 + 0.15 = 0.25s
        # exit_phase_loss: 0.20s
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(2, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.15),
            _finding(3, 2, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.20),
        ]
        themes = self._make_summary(findings).top_themes
        self.assertEqual(themes[0]["detector"], DETECTOR_EARLY_BRAKING)
        self.assertAlmostEqual(themes[0]["total_loss_s"], 0.25)

    def test_themes_ordered_by_total_loss(self) -> None:
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(2, 2, DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.30),
            _finding(3, 2, DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.20),
        ]
        themes = self._make_summary(findings).top_themes
        losses = [t["total_loss_s"] for t in themes]
        self.assertEqual(losses, sorted(losses, reverse=True))

    def test_capped_at_three_themes(self) -> None:
        detectors = [
            DETECTOR_EARLY_BRAKING,
            DETECTOR_EXIT_PHASE_LOSS,
            DETECTOR_OVER_SLOW_MID_CORNER,
            "late_braking",
            "weak_exit",
        ]
        findings = [
            _finding(i + 1, 2, detectors[i], time_loss_s=0.10 + i * 0.05)
            for i in range(5)
        ]
        themes = self._make_summary(findings).top_themes
        self.assertLessEqual(len(themes), 3)

    def test_theme_label_is_human_readable(self) -> None:
        findings = [_finding(1, 2, DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.30)]
        themes = self._make_summary(findings).top_themes
        self.assertEqual(themes[0]["label"], _DETECTOR_LABELS[DETECTOR_OVER_SLOW_MID_CORNER])

    def test_corner_count_counts_distinct_corners(self) -> None:
        # Same detector on 3 different corners.
        findings = [
            _finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(1, 3, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(2, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
            _finding(3, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.10),
        ]
        themes = self._make_summary(findings).top_themes
        # Laps 2 and 3 both fire on corner 1 — corner_count should be 3 unique corners.
        self.assertEqual(themes[0]["corner_count"], 3)


# ---------------------------------------------------------------------------
# Enriched ai_context
# ---------------------------------------------------------------------------


class TestEnrichedAiContext(unittest.TestCase):
    def test_ai_context_includes_track_position(self) -> None:
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0), _record(1, 2, 5.5)]},
            per_corner_baselines={1: _baseline(1, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.20)],
            corner_definitions=[_corner_def(1, start_m=150.0, end_m=250.0)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        ai = summary.corner_cards[0].ai_context
        self.assertIn("150", ai)   # corner start
        self.assertIn("250", ai)   # corner end
        self.assertIn("200", ai)   # apex (midpoint of 150–250)
        self.assertIn("left", ai)  # direction

    def test_ai_context_includes_brake_point(self) -> None:
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1), _record(1, 2)]},
            per_corner_baselines={1: _baseline(1, 1)},
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 2, DETECTOR_EARLY_BRAKING, time_loss_s=0.20)],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        ai = summary.corner_cards[0].ai_context
        self.assertIn("480", ai)  # candidate_brake_distance_m
        self.assertIn("500", ai)  # baseline_brake_distance_m

    def test_sub_corner_ai_context_uses_correct_apex(self) -> None:
        parent_def = _corner_def(
            8, start_m=2600.0, end_m=2900.0,
            sub_apex_distances_m=[2700.0, 2800.0],
        )
        summary = build_session_summary(
            per_corner_records={802: [_record(802, 1), _record(802, 3)]},
            per_corner_baselines={8: _baseline(8, ref_lap=1)},
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(802, 3, time_loss_s=0.20)],
            corner_definitions=[parent_def],
            per_lap_lap_times={1: 16.0, 3: 17.0},
            reference_length_m=5000.0,
        )
        ai = summary.corner_cards[0].ai_context
        self.assertIn("2800", ai)  # sub-apex at 2800m, not parent center at 2750m


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization(unittest.TestCase):
    def test_to_dict_roundtrip(self) -> None:
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.20)])
        payload = summary.to_dict()
        for key in (
            "theoretical_best_lap_s",
            "best_actual_lap_s",
            "corner_cards",
            "top_themes",
            "biggest_time_left_corners",
        ):
            self.assertIn(key, payload)
        card = payload["corner_cards"][0]
        self.assertIn("corner_id", card)
        self.assertIn("laps_affected", card)
        self.assertIn("position_context", card)
        self.assertIn("ai_context", card)

    def test_biggest_corners_include_laps_affected(self) -> None:
        findings = [
            _finding(1, 2, time_loss_s=0.10),
            _finding(1, 3, time_loss_s=0.10),
            _finding(2, 2, time_loss_s=0.40),
        ]
        payload = _simple_summary(findings).to_dict()
        # Corner 1 accumulated = 0.20, corner 2 = 0.40 → corner 2 first.
        biggest = payload["biggest_time_left_corners"]
        self.assertIn("laps_affected", biggest[0])


# ---------------------------------------------------------------------------
# Biggest time-left corners
# ---------------------------------------------------------------------------


class TestBiggestTimeLeftCorners(unittest.TestCase):
    def test_top_3_by_accumulated_loss(self) -> None:
        # Accumulated: T2=0.40, T4=0.30, T3=0.20, T1=0.10
        findings = [
            _finding(1, 2, time_loss_s=0.10),
            _finding(2, 2, time_loss_s=0.40),
            _finding(3, 2, time_loss_s=0.20),
            _finding(4, 2, time_loss_s=0.30),
        ]
        summary = build_session_summary(
            per_corner_records={
                i: [_record(i, 1, 5.0), _record(i, 2, 5.5)] for i in range(1, 5)
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
        self.assertEqual(biggest[0]["corner_id"], 2)
        self.assertEqual(biggest[1]["corner_id"], 4)
        self.assertEqual(biggest[2]["corner_id"], 3)


# ---------------------------------------------------------------------------
# Best-lap fields on CornerCard
# ---------------------------------------------------------------------------


class TestBestLapFieldsOnCard(unittest.TestCase):
    def test_best_lap_delta_populated(self) -> None:
        # Best lap is lap 1 (25.0s). Corner 1 baseline time = 5.0s.
        # Lap 1 corner time = 5.0s → delta = 0.0 (clamped to 0).
        # But lap 2 has a finding, so the card gets built for corner 1.
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.20)])
        card = summary.corner_cards[0]
        self.assertIsNotNone(card.best_lap_corner_time_s)
        self.assertIsNotNone(card.best_lap_delta_s)
        # Lap 1 at corner 1 = 5.0s, baseline = 5.0s → delta = 0.0
        self.assertAlmostEqual(card.best_lap_delta_s, 0.0)

    def test_best_lap_delta_positive_when_slower(self) -> None:
        # Best lap is lap 1 (25.0s). Corner 1 record on lap 1 = 5.5s,
        # baseline = 5.0s → delta = 0.5s.
        baselines = {1: _baseline(1, ref_lap=2, corner_time_s=5.0)}
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.5), _record(1, 2, 5.0)],
            },
            per_corner_baselines=baselines,
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 1, time_loss_s=0.50)],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 25.0, 2: 26.0},
            reference_length_m=5000.0,
        )
        card = summary.corner_cards[0]
        self.assertAlmostEqual(card.best_lap_corner_time_s, 5.5)
        self.assertAlmostEqual(card.best_lap_delta_s, 0.5)

    def test_best_lap_delta_none_when_no_record(self) -> None:
        # Corner 1 has no record for the best lap (lap 1).
        baselines = {1: _baseline(1, ref_lap=2, corner_time_s=5.0)}
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 2, 5.0), _record(1, 3, 5.5)],
            },
            per_corner_baselines=baselines,
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 3, time_loss_s=0.50)],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 25.0, 2: 26.0, 3: 27.0},
            reference_length_m=5000.0,
        )
        card = summary.corner_cards[0]
        self.assertIsNone(card.best_lap_corner_time_s)
        self.assertIsNone(card.best_lap_delta_s)


# ---------------------------------------------------------------------------
# Per best-lap corner breakdown
# ---------------------------------------------------------------------------


class TestPerBestLapCornerBreakdown(unittest.TestCase):
    def test_breakdown_populated(self) -> None:
        # Lap 1 is best. Corner 1: lap 1 = 5.2s, baseline = 5.0s → delta = 0.2.
        # Corner 2: lap 1 = 6.5s, baseline = 6.5s → delta = 0 (excluded).
        baselines = {
            1: _baseline(1, ref_lap=2, corner_time_s=5.0),
            2: _baseline(2, ref_lap=2, corner_time_s=6.5),
        }
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.2), _record(1, 2, 5.0)],
                2: [_record(2, 1, 6.5), _record(2, 2, 6.5)],
            },
            per_corner_baselines=baselines,
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 1, time_loss_s=0.20)],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 25.0, 2: 26.0},
            reference_length_m=5000.0,
        )
        breakdown = summary.per_best_lap_corner_breakdown
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["corner_id"], 1)
        self.assertAlmostEqual(breakdown[0]["delta_s"], 0.2)

    def test_breakdown_sorted_by_delta_descending(self) -> None:
        baselines = {
            1: _baseline(1, ref_lap=3, corner_time_s=5.0),
            2: _baseline(2, ref_lap=3, corner_time_s=6.0),
        }
        summary = build_session_summary(
            per_corner_records={
                1: [_record(1, 1, 5.1), _record(1, 3, 5.0)],
                2: [_record(2, 1, 6.3), _record(2, 3, 6.0)],
            },
            per_corner_baselines=baselines,
            straight_records=[_straight(1, 1)],
            findings_all=[
                _finding(1, 1, time_loss_s=0.10),
                _finding(2, 1, time_loss_s=0.30),
            ],
            corner_definitions=[_corner_def(1), _corner_def(2, 300.0, 400.0)],
            per_lap_lap_times={1: 25.0, 3: 27.0},
            reference_length_m=5000.0,
        )
        breakdown = summary.per_best_lap_corner_breakdown
        self.assertEqual(len(breakdown), 2)
        # Corner 2 delta (0.3) > corner 1 delta (0.1) → corner 2 first.
        self.assertEqual(breakdown[0]["corner_id"], 2)
        self.assertEqual(breakdown[1]["corner_id"], 1)

    def test_breakdown_excludes_clean_corners(self) -> None:
        baselines = {1: _baseline(1, ref_lap=1, corner_time_s=5.0)}
        summary = build_session_summary(
            per_corner_records={1: [_record(1, 1, 5.0), _record(1, 2, 5.5)]},
            per_corner_baselines=baselines,
            straight_records=[_straight(1, 1)],
            findings_all=[_finding(1, 2, time_loss_s=0.50)],
            corner_definitions=[_corner_def(1)],
            per_lap_lap_times={1: 16.0, 2: 17.0},
            reference_length_m=5000.0,
        )
        # Best lap is lap 1 (16.0s). Lap 1 at corner 1 = 5.0s = baseline → excluded.
        self.assertEqual(len(summary.per_best_lap_corner_breakdown), 0)

    def test_breakdown_in_serialization(self) -> None:
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.20)])
        payload = summary.to_dict()
        self.assertIn("per_best_lap_corner_breakdown", payload)


# ---------------------------------------------------------------------------
# Minimum accumulated loss gate
# ---------------------------------------------------------------------------


class TestMinAccumulatedLossGate(unittest.TestCase):
    def test_micro_loss_card_suppressed(self) -> None:
        # Single finding at 0.08s → accumulated = 0.08 < 0.10 → no card.
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.08)])
        self.assertEqual(len(summary.corner_cards), 0)

    def test_above_threshold_card_emitted(self) -> None:
        # Single finding at 0.12s → accumulated = 0.12 > 0.10 → card emitted.
        summary = _simple_summary([_finding(1, 2, time_loss_s=0.12)])
        self.assertEqual(len(summary.corner_cards), 1)

    def test_multi_lap_micro_loss_passes(self) -> None:
        # 3 findings × 0.04s avg = 0.12s accumulated > 0.10 → card emitted.
        findings = [
            _finding(1, 2, time_loss_s=0.04),
            _finding(1, 3, time_loss_s=0.04),
            _finding(1, 4, time_loss_s=0.04),
        ]
        summary = _simple_summary(findings, n_corners=1)
        self.assertEqual(len(summary.corner_cards), 1)


if __name__ == "__main__":
    unittest.main()
