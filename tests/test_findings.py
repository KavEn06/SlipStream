"""Unit tests for ``src.analysis.findings``."""

from __future__ import annotations

import unittest

from src.analysis.constants import (
    ALIGNMENT_QUALITY_GOOD_M,
    ALIGNMENT_QUALITY_POOR_M,
    CONFIDENCE_MIN,
    COST_SIGNIFICANCE_CEIL_S,
    COST_SIGNIFICANCE_FLOOR_S,
    FINDINGS_PER_CORNER_CAP,
    FINDINGS_SESSION_TOP_CAP,
    SEVERITY_MAJOR_S,
    SEVERITY_MINOR_S,
    SEVERITY_MODERATE_S,
)
from src.analysis.corner_records import CornerRecord, PhaseMetrics
from src.analysis.detectors import (
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_LATE_BRAKING,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_STEERING_INSTABILITY,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
    DETECTOR_WEAK_EXIT,
    DetectorHit,
)
from src.analysis.findings import (
    Finding,
    FindingSet,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    build_findings,
    classify_severity,
    compute_confidence,
)


def _make_record(
    *, corner_id: int, lap_number: int, alignment_quality_m: float = 0.3
) -> CornerRecord:
    phase = PhaseMetrics(
        time_s=2.0,
        entry_speed_kph=180.0,
        exit_speed_kph=150.0,
        min_speed_kph=100.0,
        min_speed_progress_norm=0.42,
    )
    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner_id,
        is_compound=False,
        alignment_quality_m=alignment_quality_m,
        alignment_used_fallback=False,
        corner_time_s=6.0,
        entry=phase,
        apex=phase,
        exit=phase,
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


def _make_hit(
    *,
    detector: str,
    corner_id: int = 1,
    lap_number: int = 2,
    time_loss_s: float = 0.25,
    pattern_strength: float = 0.8,
    metrics: dict | None = None,
) -> DetectorHit:
    default_metrics = {
        "brake_point_delta_m": -15.0,
        "candidate_brake_distance_m": 480.0,
        "baseline_brake_distance_m": 500.0,
        "exit_speed_delta_kph": -3.0,
        "entry_speed_delta_kph": 0.0,
        "trail_brake_depth_m": 8.0,
        "baseline_trail_brake_depth_m": 1.0,
        "min_speed_delta_kph": -5.0,
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
    if metrics:
        default_metrics.update(metrics)
    return DetectorHit(
        detector=detector,
        corner_id=corner_id,
        lap_number=lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=default_metrics,
        evidence_refs=[{"column": "Brake", "progress_start": 0.3, "progress_end": 0.4}],
    )


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


class TestClassifySeverity(unittest.TestCase):
    def test_minor_boundary(self) -> None:
        self.assertEqual(classify_severity(SEVERITY_MINOR_S), SEVERITY_MINOR)
        self.assertEqual(
            classify_severity(SEVERITY_MINOR_S + 0.001), SEVERITY_MINOR
        )

    def test_moderate_boundary(self) -> None:
        self.assertEqual(classify_severity(SEVERITY_MODERATE_S), SEVERITY_MODERATE)
        self.assertEqual(
            classify_severity(SEVERITY_MODERATE_S - 0.001), SEVERITY_MINOR
        )

    def test_major_boundary(self) -> None:
        self.assertEqual(classify_severity(SEVERITY_MAJOR_S), SEVERITY_MAJOR)
        self.assertEqual(
            classify_severity(SEVERITY_MAJOR_S + 0.1), SEVERITY_MAJOR
        )

    def test_below_minor_defaults_to_minor(self) -> None:
        # Below the minor gate — callers should use the detector gate to
        # avoid emitting here; severity still classifies as minor.
        self.assertEqual(classify_severity(0.0), SEVERITY_MINOR)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestComputeConfidence(unittest.TestCase):
    def test_high_pattern_cost_and_alignment_gives_high_confidence(self) -> None:
        c = compute_confidence(
            pattern_strength=1.0,
            time_loss_s=COST_SIGNIFICANCE_CEIL_S,
            alignment_quality_m=0.0,
        )
        self.assertAlmostEqual(c, 1.0, places=6)

    def test_below_cost_floor_is_zero(self) -> None:
        c = compute_confidence(
            pattern_strength=1.0,
            time_loss_s=COST_SIGNIFICANCE_FLOOR_S - 0.01,
            alignment_quality_m=0.0,
        )
        self.assertAlmostEqual(c, 0.0, places=6)

    def test_poor_alignment_zeros_confidence(self) -> None:
        c = compute_confidence(
            pattern_strength=1.0,
            time_loss_s=COST_SIGNIFICANCE_CEIL_S,
            alignment_quality_m=ALIGNMENT_QUALITY_POOR_M + 0.1,
        )
        self.assertAlmostEqual(c, 0.0, places=6)

    def test_pattern_strength_zero_zeros_confidence(self) -> None:
        c = compute_confidence(
            pattern_strength=0.0,
            time_loss_s=COST_SIGNIFICANCE_CEIL_S,
            alignment_quality_m=0.0,
        )
        self.assertAlmostEqual(c, 0.0, places=6)

    def test_monotonic_in_time_loss(self) -> None:
        low = compute_confidence(
            pattern_strength=0.8,
            time_loss_s=0.10,
            alignment_quality_m=0.3,
        )
        high = compute_confidence(
            pattern_strength=0.8,
            time_loss_s=0.30,
            alignment_quality_m=0.3,
        )
        self.assertGreater(high, low)


# ---------------------------------------------------------------------------
# build_findings: confidence gate, per-corner cap, session cap
# ---------------------------------------------------------------------------


class TestBuildFindings(unittest.TestCase):
    def _records(self, corner_ids: list[int], lap_numbers: list[int]) -> dict:
        return {
            cid: [
                _make_record(corner_id=cid, lap_number=lap) for lap in lap_numbers
            ]
            for cid in corner_ids
        }

    def test_low_confidence_hits_dropped(self) -> None:
        records = self._records([1], [2])
        hit = _make_hit(
            detector=DETECTOR_EARLY_BRAKING,
            time_loss_s=0.06,
            pattern_strength=0.05,
        )
        result = build_findings([hit], records)
        self.assertEqual(result.findings_top, [])
        self.assertEqual(result.findings_all, [])

    def test_single_finding_emitted(self) -> None:
        records = self._records([1], [2])
        hit = _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.30)
        result = build_findings([hit], records)
        self.assertEqual(len(result.findings_top), 1)
        self.assertEqual(len(result.findings_all), 1)
        finding = result.findings_top[0]
        self.assertEqual(finding.detector, DETECTOR_EARLY_BRAKING)
        self.assertEqual(finding.severity, SEVERITY_MAJOR)
        self.assertGreater(finding.confidence, CONFIDENCE_MIN)
        self.assertIn("T1", finding.templated_text)

    def test_per_corner_cap_enforced(self) -> None:
        records = self._records([1], [2])
        # Three hits on the same (corner, lap) — three distinct detectors
        # with no mutual suppression. Cap = 2.
        hits = [
            _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.40),
            _make_hit(detector=DETECTOR_TRAIL_BRAKE_PAST_APEX, time_loss_s=0.35),
            _make_hit(detector=DETECTOR_STEERING_INSTABILITY, time_loss_s=0.30),
        ]
        result = build_findings(hits, records)
        self.assertEqual(len(result.findings_all), FINDINGS_PER_CORNER_CAP)
        kept_detectors = {f.detector for f in result.findings_all}
        self.assertEqual(
            kept_detectors,
            {DETECTOR_EARLY_BRAKING, DETECTOR_TRAIL_BRAKE_PAST_APEX},
        )

    def test_session_top_cap(self) -> None:
        corners = list(range(1, 10))
        records = self._records(corners, [2])
        # Use time losses well above the confidence gate so every hit
        # survives and we're testing the cap, not the confidence filter.
        hits = [
            _make_hit(
                detector=DETECTOR_EARLY_BRAKING,
                corner_id=cid,
                time_loss_s=0.35 + 0.01 * cid,
            )
            for cid in corners
        ]
        result = build_findings(hits, records)
        self.assertEqual(len(result.findings_top), FINDINGS_SESSION_TOP_CAP)
        self.assertEqual(len(result.findings_all), len(corners))
        # Top 5 should be the largest-time-loss ones (cid 9..5).
        top_corner_ids = [f.corner_id for f in result.findings_top]
        self.assertEqual(top_corner_ids, [9, 8, 7, 6, 5])

    def test_missing_record_is_skipped(self) -> None:
        records = self._records([1], [2])
        hit = _make_hit(
            detector=DETECTOR_EARLY_BRAKING, corner_id=99, time_loss_s=0.3
        )
        result = build_findings([hit], records)
        self.assertEqual(result.findings_top, [])

    def test_deterministic_finding_id(self) -> None:
        records = self._records([1], [2])
        hit = _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.3)
        r1 = build_findings([hit], records)
        r2 = build_findings([hit], records)
        self.assertEqual(
            r1.findings_top[0].finding_id, r2.findings_top[0].finding_id
        )


# ---------------------------------------------------------------------------
# Mutual suppression
# ---------------------------------------------------------------------------


class TestMutualSuppression(unittest.TestCase):
    def test_trail_brake_suppresses_over_slow(self) -> None:
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_TRAIL_BRAKE_PAST_APEX, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_TRAIL_BRAKE_PAST_APEX, detectors)
        self.assertNotIn(DETECTOR_OVER_SLOW_MID_CORNER, detectors)

    def test_over_slow_does_not_suppress_exit_loss(self) -> None:
        # over_slow and exit_phase_loss are independent phases (apex vs exit).
        # They may validly co-exist; over_slow must NOT eat exit_phase_loss.
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.35),
            _make_hit(detector=DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.35),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_OVER_SLOW_MID_CORNER, detectors)
        self.assertIn(DETECTOR_EXIT_PHASE_LOSS, detectors)

    def test_early_braking_suppresses_over_slow(self) -> None:
        # early_braking is the root cause; over_slow is a downstream symptom.
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_EARLY_BRAKING, detectors)
        self.assertNotIn(DETECTOR_OVER_SLOW_MID_CORNER, detectors)

    def test_early_braking_suppresses_exit_loss(self) -> None:
        # early_braking explains the full entry→apex→exit chain.
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_EARLY_BRAKING, detectors)
        self.assertNotIn(DETECTOR_EXIT_PHASE_LOSS, detectors)

    def test_late_braking_suppresses_over_slow(self) -> None:
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_LATE_BRAKING, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_OVER_SLOW_MID_CORNER, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_LATE_BRAKING, detectors)
        self.assertNotIn(DETECTOR_OVER_SLOW_MID_CORNER, detectors)

    def test_late_braking_suppresses_exit_loss(self) -> None:
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_LATE_BRAKING, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_LATE_BRAKING, detectors)
        self.assertNotIn(DETECTOR_EXIT_PHASE_LOSS, detectors)

    def test_exit_phase_loss_suppresses_weak_exit(self) -> None:
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_EXIT_PHASE_LOSS, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_WEAK_EXIT, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_EXIT_PHASE_LOSS, detectors)
        self.assertNotIn(DETECTOR_WEAK_EXIT, detectors)

    def test_steering_instability_independent(self) -> None:
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(detector=DETECTOR_EARLY_BRAKING, time_loss_s=0.3),
            _make_hit(detector=DETECTOR_STEERING_INSTABILITY, time_loss_s=0.3),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_EARLY_BRAKING, detectors)
        self.assertIn(DETECTOR_STEERING_INSTABILITY, detectors)

    def test_suppression_does_not_cross_laps(self) -> None:
        records = {
            1: [
                _make_record(corner_id=1, lap_number=2),
                _make_record(corner_id=1, lap_number=3),
            ]
        }
        hits = [
            _make_hit(
                detector=DETECTOR_TRAIL_BRAKE_PAST_APEX,
                lap_number=2,
                time_loss_s=0.3,
            ),
            _make_hit(
                detector=DETECTOR_OVER_SLOW_MID_CORNER,
                lap_number=3,
                time_loss_s=0.3,
            ),
        ]
        result = build_findings(hits, records)
        detectors = {(f.detector, f.lap_number) for f in result.findings_all}
        self.assertIn((DETECTOR_TRAIL_BRAKE_PAST_APEX, 2), detectors)
        self.assertIn((DETECTOR_OVER_SLOW_MID_CORNER, 3), detectors)

    def test_early_and_late_braking_mutually_suppress(self) -> None:
        """If both early and late braking fire on the same corner+lap, only the
        higher-ranking one survives (they are mutually exclusive by definition)."""
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        # early_brake has higher pattern_strength → higher ranking key → survives.
        hits = [
            _make_hit(
                detector=DETECTOR_EARLY_BRAKING,
                time_loss_s=0.3,
                pattern_strength=0.9,
            ),
            _make_hit(
                detector=DETECTOR_LATE_BRAKING,
                time_loss_s=0.3,
                pattern_strength=0.5,
            ),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertIn(DETECTOR_EARLY_BRAKING, detectors)
        self.assertNotIn(DETECTOR_LATE_BRAKING, detectors)

    def test_early_late_suppression_keeps_stronger_one(self) -> None:
        """When late braking has higher strength, early braking is dropped."""
        records = {1: [_make_record(corner_id=1, lap_number=2)]}
        hits = [
            _make_hit(
                detector=DETECTOR_EARLY_BRAKING,
                time_loss_s=0.3,
                pattern_strength=0.4,
            ),
            _make_hit(
                detector=DETECTOR_LATE_BRAKING,
                time_loss_s=0.3,
                pattern_strength=0.8,
            ),
        ]
        result = build_findings(hits, records)
        detectors = {f.detector for f in result.findings_all}
        self.assertNotIn(DETECTOR_EARLY_BRAKING, detectors)
        self.assertIn(DETECTOR_LATE_BRAKING, detectors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
