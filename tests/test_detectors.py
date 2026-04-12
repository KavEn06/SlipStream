"""Unit tests for ``src.analysis.detectors``.

Each detector has at least:
  - One positive case that should emit a hit.
  - One negative case where a telemetry gate blocks it.
  - One false-positive suppression case.

The universal gate is tested once at the top of the file.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import TIME_LOSS_GATE_S
from src.analysis.corner_records import (
    BrakeEvent,
    CornerRecord,
    PhaseMetrics,
    ThrottleEvent,
)
from src.analysis.detectors import (
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_LATE_BRAKING,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_STEERING_INSTABILITY,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
    DETECTOR_WEAK_EXIT,
    DetectorHit,
    detect_early_braking,
    detect_exit_phase_loss,
    detect_late_braking,
    detect_over_slow_mid_corner,
    detect_steering_instability,
    detect_trail_brake_past_apex,
    detect_weak_exit,
    run_all_detectors,
    universal_gate,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _phase(
    *,
    time_s: float = 2.0,
    entry_kph: float = 180.0,
    exit_kph: float = 150.0,
    min_kph: float = 100.0,
    min_progress: float = 0.42,
) -> PhaseMetrics:
    return PhaseMetrics(
        time_s=time_s,
        entry_speed_kph=entry_kph,
        exit_speed_kph=exit_kph,
        min_speed_kph=min_kph,
        min_speed_progress_norm=min_progress,
    )


def _brake(
    *,
    init_dist_m: float = 500.0,
    init_progress: float = 0.28,
    release_dist_m: float = 580.0,
    release_progress: float = 0.38,
    release_brake: float = 0.5,
    release_rate: float = 2.0,
    peak_brake: float = 0.85,
    peak_decel: float = -10.0,
    avg_decel: float = -7.0,
    trail_end_progress: float = 0.40,
    trail_depth_m: float = 1.5,
    overlap_m: float = 10.0,
) -> BrakeEvent:
    return BrakeEvent(
        initiation_progress_norm=init_progress,
        initiation_distance_m=init_dist_m,
        initiation_speed_kph=180.0,
        release_progress_norm=release_progress,
        release_distance_m=release_dist_m,
        release_brake_value=release_brake,
        release_rate_per_s=release_rate,
        peak_brake=peak_brake,
        peak_decel_mps2=peak_decel,
        avg_decel_mps2=avg_decel,
        trail_brake_end_progress_norm=trail_end_progress,
        trail_brake_depth_m=trail_depth_m,
        brake_steering_overlap_m=overlap_m,
    )


def _throttle(
    *,
    pickup_progress: float = 0.46,
    pickup_kph: float = 105.0,
    pickup_dist_from_min: float = 15.0,
    full_progress: float | None = 0.52,
    exit_full_fraction: float = 0.7,
    dip: bool = False,
) -> ThrottleEvent:
    return ThrottleEvent(
        pickup_progress_norm=pickup_progress,
        pickup_speed_kph=pickup_kph,
        pickup_distance_from_min_speed_m=pickup_dist_from_min,
        full_throttle_progress_norm=full_progress,
        exit_full_throttle_fraction=exit_full_fraction,
        throttle_dip_detected=dip,
    )


def _record(
    *,
    lap_number: int = 2,
    corner_id: int = 1,
    is_compound: bool = False,
    alignment_used_fallback: bool = False,
    alignment_quality_m: float = 0.3,
    corner_time_s: float = 6.0,
    entry: PhaseMetrics | None = None,
    apex: PhaseMetrics | None = None,
    exit_phase: PhaseMetrics | None = None,
    brake: BrakeEvent | None = None,
    throttle: ThrottleEvent | None = None,
    exit_steering_correction_count: int = 0,
) -> CornerRecord:
    entry = entry or _phase(min_kph=160.0, min_progress=0.30, entry_kph=200.0, exit_kph=140.0)
    apex = apex or _phase(min_kph=100.0, min_progress=0.42)
    exit_phase = exit_phase or _phase(min_kph=140.0, min_progress=0.55, entry_kph=140.0, exit_kph=180.0)
    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner_id,
        is_compound=is_compound,
        alignment_quality_m=alignment_quality_m,
        alignment_used_fallback=alignment_used_fallback,
        corner_time_s=corner_time_s,
        entry=entry,
        apex=apex,
        exit=exit_phase,
        brake=brake if brake is not None else _brake(),
        throttle=throttle if throttle is not None else _throttle(),
        coasting_distance_m=0.0,
        gear_at_min_speed=3,
        min_speed_kph=apex.min_speed_kph,
        min_speed_progress_norm=apex.min_speed_progress_norm,
        exit_steering_correction_count=exit_steering_correction_count,
        sub_corner_records=[],
    )


def _baseline_from(record: CornerRecord) -> CornerBaseline:
    return CornerBaseline(
        corner_id=record.corner_id,
        reference_lap_number=record.lap_number,
        reference_record=record,
        candidate_lap_numbers=[record.lap_number],
    )


# ---------------------------------------------------------------------------
# Universal gate
# ---------------------------------------------------------------------------


class TestUniversalGate(unittest.TestCase):
    def test_passes_when_candidate_slower_and_clean(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        cand = _record(lap_number=2, corner_time_s=6.3)
        delta = universal_gate(cand, _baseline_from(base))
        self.assertIsNotNone(delta)
        assert delta is not None
        self.assertAlmostEqual(delta, 0.3, places=6)

    def test_blocks_baseline_lap(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        self.assertIsNone(universal_gate(base, _baseline_from(base)))

    def test_blocks_fallback_alignment(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        cand = _record(lap_number=2, corner_time_s=6.3, alignment_used_fallback=True)
        self.assertIsNone(universal_gate(cand, _baseline_from(base)))

    def test_blocks_poor_alignment_quality(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        cand = _record(lap_number=2, corner_time_s=6.3, alignment_quality_m=3.0)
        self.assertIsNone(universal_gate(cand, _baseline_from(base)))

    def test_blocks_time_loss_below_gate(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        cand = _record(lap_number=2, corner_time_s=6.0 + TIME_LOSS_GATE_S / 2)
        self.assertIsNone(universal_gate(cand, _baseline_from(base)))

    def test_run_all_returns_empty_when_gate_blocks(self) -> None:
        base = _record(lap_number=1, corner_time_s=6.0)
        cand = _record(lap_number=2, corner_time_s=6.01)
        self.assertEqual(run_all_detectors(cand, _baseline_from(base)), [])


# ---------------------------------------------------------------------------
# Early braking
# ---------------------------------------------------------------------------


class TestEarlyBraking(unittest.TestCase):
    def _base_and_candidate(self, **cand_overrides) -> tuple[CornerRecord, CornerRecord]:
        base = _record(
            lap_number=1,
            corner_time_s=6.0,
            brake=_brake(init_dist_m=500.0, avg_decel=-7.0),
            exit_phase=_phase(min_kph=140.0, entry_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=480.0, avg_decel=-6.5),  # 20 m earlier
            exit_phase=_phase(min_kph=135.0, entry_kph=135.0, exit_kph=170.0, min_progress=0.55),
            **cand_overrides,
        )
        return base, cand

    def test_fires_when_brake_earlier_and_exit_slower(self) -> None:
        base, cand = self._base_and_candidate()
        hit = detect_early_braking(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_EARLY_BRAKING)
        self.assertLess(hit.metrics_snapshot["brake_point_delta_m"], -7.0)
        self.assertGreater(hit.pattern_strength, 0.0)

    def test_blocked_when_brake_point_not_early_enough(self) -> None:
        base = _record(lap_number=1, brake=_brake(init_dist_m=500.0))
        cand = _record(lap_number=2, corner_time_s=6.3, brake=_brake(init_dist_m=495.0))
        self.assertIsNone(
            detect_early_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_when_exit_speed_gained(self) -> None:
        base = _record(
            lap_number=1,
            brake=_brake(init_dist_m=500.0),
            exit_phase=_phase(exit_kph=170.0, entry_kph=140.0, min_kph=135.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=480.0),
            exit_phase=_phase(exit_kph=185.0, entry_kph=140.0, min_kph=140.0),
        )
        self.assertIsNone(
            detect_early_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_when_candidate_arrived_hotter(self) -> None:
        base = _record(lap_number=1, brake=_brake(init_dist_m=500.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=480.0),
            entry=_phase(entry_kph=210.0, min_kph=190.0, exit_kph=150.0),
        )
        self.assertIsNone(
            detect_early_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Trail brake past apex
# ---------------------------------------------------------------------------


class TestTrailBrakePastApex(unittest.TestCase):
    def test_fires_when_trail_deep_and_min_speed_low(self) -> None:
        base = _record(
            lap_number=1,
            brake=_brake(trail_depth_m=-5.0),  # released 5m before apex (normal)
            apex=_phase(min_kph=110.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=8.0),  # held 8m past apex (problematic)
            apex=_phase(min_kph=106.0),
        )
        hit = detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_TRAIL_BRAKE_PAST_APEX)

    def test_blocked_when_trail_depth_below_threshold(self) -> None:
        base = _record(lap_number=1, brake=_brake(trail_depth_m=1.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=3.0),
            apex=_phase(min_kph=95.0),
        )
        self.assertIsNone(
            detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_min_speed_not_lower(self) -> None:
        base = _record(lap_number=1, brake=_brake(trail_depth_m=1.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=8.0),
            apex=_phase(min_kph=110.0),
        )
        self.assertIsNone(
            detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_when_baseline_also_trails_deep(self) -> None:
        base = _record(lap_number=1, brake=_brake(trail_depth_m=7.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=8.0),
            apex=_phase(min_kph=95.0),
        )
        self.assertIsNone(
            detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_not_fired_when_released_before_apex(self) -> None:
        """Negative trail_depth_m means released before apex — should not fire."""
        base = _record(
            lap_number=1,
            brake=_brake(trail_depth_m=-5.0),
            apex=_phase(min_kph=110.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=-3.0),  # released 3m before apex
            apex=_phase(min_kph=106.0),
        )
        self.assertIsNone(
            detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_fires_genuinely_past_apex(self) -> None:
        """Positive trail_depth_m > threshold with lower min speed should fire."""
        base = _record(
            lap_number=1,
            brake=_brake(trail_depth_m=-2.0),  # baseline released before apex
            apex=_phase(min_kph=110.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(trail_depth_m=10.0),  # held 10m past apex
            apex=_phase(min_kph=105.0),
        )
        hit = detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_TRAIL_BRAKE_PAST_APEX)
        self.assertGreater(hit.pattern_strength, 0.0)

    def test_skipped_on_compound_corner(self) -> None:
        base = _record(
            lap_number=1, is_compound=True, brake=_brake(trail_depth_m=1.0)
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            is_compound=True,
            brake=_brake(trail_depth_m=8.0),
            apex=_phase(min_kph=95.0),
        )
        self.assertIsNone(
            detect_trail_brake_past_apex(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Late braking
# ---------------------------------------------------------------------------


class TestLateBraking(unittest.TestCase):
    def test_fires_when_brake_later_and_apex_slower(self) -> None:
        base = _record(
            lap_number=1,
            corner_time_s=6.0,
            brake=_brake(init_dist_m=500.0, avg_decel=-7.0),
            apex=_phase(min_kph=110.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=510.0, avg_decel=-7.0),  # 10m later
            apex=_phase(min_kph=105.0),  # -5 kph apex
            exit_phase=_phase(entry_kph=130.0, min_kph=130.0, exit_kph=170.0, min_progress=0.55),
        )
        hit = detect_late_braking(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_LATE_BRAKING)
        self.assertGreater(hit.metrics_snapshot["brake_point_delta_m"], 5.0)

    def test_blocked_when_brake_delta_below_threshold(self) -> None:
        base = _record(lap_number=1, brake=_brake(init_dist_m=500.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=503.0),  # only 3m later
            apex=_phase(min_kph=95.0),
        )
        self.assertIsNone(
            detect_late_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_when_exit_speed_gained(self) -> None:
        base = _record(
            lap_number=1,
            brake=_brake(init_dist_m=500.0),
            exit_phase=_phase(exit_kph=170.0, entry_kph=140.0, min_kph=135.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=510.0),
            apex=_phase(min_kph=95.0),
            exit_phase=_phase(exit_kph=175.0, entry_kph=140.0, min_kph=140.0),
        )
        self.assertIsNone(
            detect_late_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_when_candidate_arrived_slower(self) -> None:
        base = _record(
            lap_number=1,
            brake=_brake(init_dist_m=500.0),
            entry=_phase(entry_kph=200.0, min_kph=160.0, exit_kph=140.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=510.0),
            entry=_phase(entry_kph=195.0, min_kph=155.0, exit_kph=135.0),
            apex=_phase(min_kph=95.0),
            exit_phase=_phase(exit_kph=170.0, entry_kph=130.0, min_kph=130.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_late_braking(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Over-slow mid-corner
# ---------------------------------------------------------------------------


class TestOverSlowMidCorner(unittest.TestCase):
    def test_fires_when_min_and_exit_both_slower(self) -> None:
        base = _record(
            lap_number=1,
            apex=_phase(min_kph=110.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            apex=_phase(min_kph=105.0),
            exit_phase=_phase(entry_kph=130.0, min_kph=130.0, exit_kph=175.0, min_progress=0.55),
        )
        hit = detect_over_slow_mid_corner(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_OVER_SLOW_MID_CORNER)

    def test_blocked_when_min_speed_delta_too_small(self) -> None:
        base = _record(lap_number=1, apex=_phase(min_kph=110.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            apex=_phase(min_kph=109.0),  # only -1 kph
        )
        self.assertIsNone(
            detect_over_slow_mid_corner(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_exit_speed_gained(self) -> None:
        base = _record(
            lap_number=1,
            apex=_phase(min_kph=110.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            apex=_phase(min_kph=105.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=185.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_over_slow_mid_corner(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Exit-phase loss
# ---------------------------------------------------------------------------


class TestExitPhaseLoss(unittest.TestCase):
    def test_fires_on_late_throttle_primary_gate(self) -> None:
        base = _record(lap_number=1, throttle=_throttle(pickup_dist_from_min=10.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(pickup_dist_from_min=22.0),
        )
        hit = detect_exit_phase_loss(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_EXIT_PHASE_LOSS)

    def test_fires_on_slow_exit_secondary_gate(self) -> None:
        base = _record(
            lap_number=1,
            throttle=_throttle(pickup_dist_from_min=10.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(pickup_dist_from_min=14.0),  # +4m delay
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=174.0, min_progress=0.55),
        )
        hit = detect_exit_phase_loss(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)

    def test_blocked_when_pickup_on_time_and_exit_ok(self) -> None:
        base = _record(lap_number=1, throttle=_throttle(pickup_dist_from_min=10.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(pickup_dist_from_min=11.0),
        )
        self.assertIsNone(
            detect_exit_phase_loss(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_suppressed_on_isolated_dip(self) -> None:
        base = _record(lap_number=1, throttle=_throttle(pickup_dist_from_min=10.0))
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(pickup_dist_from_min=12.0, dip=True),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_exit_phase_loss(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Weak exit
# ---------------------------------------------------------------------------


class TestWeakExit(unittest.TestCase):
    def test_fires_when_full_throttle_fraction_low(self) -> None:
        base = _record(
            lap_number=1,
            throttle=_throttle(exit_full_fraction=0.70, pickup_dist_from_min=10.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(exit_full_fraction=0.35, pickup_dist_from_min=12.0),
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=174.0, min_progress=0.55),
        )
        hit = detect_weak_exit(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_WEAK_EXIT)

    def test_blocked_when_fraction_delta_too_small(self) -> None:
        base = _record(
            lap_number=1,
            throttle=_throttle(exit_full_fraction=0.70, pickup_dist_from_min=10.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(exit_full_fraction=0.60, pickup_dist_from_min=10.0),
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=174.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_weak_exit(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_pickup_very_late(self) -> None:
        """If pickup is >= 8m late, exit_phase_loss is the root cause."""
        base = _record(
            lap_number=1,
            throttle=_throttle(exit_full_fraction=0.70, pickup_dist_from_min=10.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(exit_full_fraction=0.30, pickup_dist_from_min=20.0),
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=174.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_weak_exit(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_baseline_fraction_too_low(self) -> None:
        base = _record(
            lap_number=1,
            throttle=_throttle(exit_full_fraction=0.15, pickup_dist_from_min=10.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            throttle=_throttle(exit_full_fraction=0.0, pickup_dist_from_min=10.0),
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=174.0, min_progress=0.55),
        )
        self.assertIsNone(
            detect_weak_exit(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Steering instability
# ---------------------------------------------------------------------------


class TestSteeringInstability(unittest.TestCase):
    def test_fires_when_candidate_has_many_corrections(self) -> None:
        base = _record(
            lap_number=1,
            exit_steering_correction_count=1,
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            exit_steering_correction_count=6,
        )
        hit = detect_steering_instability(cand, _baseline_from(base), time_loss_s=0.3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.detector, DETECTOR_STEERING_INSTABILITY)

    def test_blocked_when_count_below_floor(self) -> None:
        base = _record(lap_number=1, exit_steering_correction_count=0)
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            exit_steering_correction_count=3,  # below floor of 4
        )
        self.assertIsNone(
            detect_steering_instability(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_delta_below_threshold(self) -> None:
        base = _record(lap_number=1, exit_steering_correction_count=3)
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            exit_steering_correction_count=5,  # delta=2, below threshold of 3
        )
        self.assertIsNone(
            detect_steering_instability(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_on_compound_corner(self) -> None:
        base = _record(
            lap_number=1,
            is_compound=True,
            exit_steering_correction_count=1,
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            is_compound=True,
            exit_steering_correction_count=8,
        )
        self.assertIsNone(
            detect_steering_instability(cand, _baseline_from(base), time_loss_s=0.3)
        )

    def test_blocked_when_baseline_too_noisy(self) -> None:
        base = _record(lap_number=1, exit_steering_correction_count=9)
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            exit_steering_correction_count=15,
        )
        self.assertIsNone(
            detect_steering_instability(cand, _baseline_from(base), time_loss_s=0.3)
        )


# ---------------------------------------------------------------------------
# Integration: run_all_detectors
# ---------------------------------------------------------------------------


class TestRunAllDetectors(unittest.TestCase):
    def test_multiple_detectors_can_fire_simultaneously(self) -> None:
        base = _record(
            lap_number=1,
            corner_time_s=6.0,
            brake=_brake(init_dist_m=500.0, trail_depth_m=-5.0),
            apex=_phase(min_kph=110.0),
            throttle=_throttle(pickup_dist_from_min=10.0),
            exit_phase=_phase(entry_kph=140.0, min_kph=140.0, exit_kph=180.0, min_progress=0.55),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.4,
            brake=_brake(
                init_dist_m=480.0,
                trail_depth_m=8.0,
                avg_decel=-6.5,
            ),
            apex=_phase(min_kph=100.0),
            throttle=_throttle(pickup_dist_from_min=25.0),
            exit_phase=_phase(entry_kph=130.0, min_kph=130.0, exit_kph=170.0, min_progress=0.55),
        )
        hits = run_all_detectors(cand, _baseline_from(base))
        detector_names = {hit.detector for hit in hits}
        self.assertIn(DETECTOR_EARLY_BRAKING, detector_names)
        self.assertIn(DETECTOR_TRAIL_BRAKE_PAST_APEX, detector_names)
        self.assertIn(DETECTOR_OVER_SLOW_MID_CORNER, detector_names)
        self.assertIn(DETECTOR_EXIT_PHASE_LOSS, detector_names)

    def test_every_hit_is_detector_hit(self) -> None:
        base = _record(
            lap_number=1,
            brake=_brake(init_dist_m=500.0, avg_decel=-7.0),
        )
        cand = _record(
            lap_number=2,
            corner_time_s=6.3,
            brake=_brake(init_dist_m=480.0, avg_decel=-6.5),
            exit_phase=_phase(entry_kph=135.0, min_kph=135.0, exit_kph=170.0, min_progress=0.55),
        )
        hits = run_all_detectors(cand, _baseline_from(base))
        for hit in hits:
            self.assertIsInstance(hit, DetectorHit)
            self.assertEqual(hit.corner_id, 1)
            self.assertEqual(hit.lap_number, 2)
            self.assertGreater(hit.time_loss_s, 0.0)
            self.assertGreaterEqual(hit.pattern_strength, 0.0)
            self.assertLessEqual(hit.pattern_strength, 1.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
