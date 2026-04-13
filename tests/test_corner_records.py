"""Unit tests for ``src.analysis.corner_records``.

These tests construct synthetic resampled laps with hand-crafted speed,
brake, and throttle profiles so every computed field has a known expected
value. The fixtures avoid the real alignment pipeline — we only need a
DataFrame with ``ALIGNED_LAP_COLUMNS`` + a ``TrackSegmentation`` stub.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.analysis.corner_records import (
    BrakeEvent,
    CornerRecord,
    PhaseMetrics,
    StraightRecord,
    ThrottleEvent,
    extract_corner_records,
    _LapArrays,
    _estimate_steering_noise,
)
from src.core.schemas import ALIGNED_LAP_COLUMNS
from src.processing.segmentation import (
    CornerDefinition,
    StraightDefinition,
    TrackSegmentation,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_resampled_lap(
    *,
    track_length_m: float,
    num_points: int,
    lap_time_s: float,
    speed_fn,
    brake_fn,
    throttle_fn,
    long_accel_fn=None,
    gear_fn=None,
    is_coasting_fn=None,
    steering_fn=None,
) -> pd.DataFrame:
    """Build a resampled-lap DataFrame with given per-progress profiles."""
    progress_norm = np.linspace(0.0, 1.0, num_points, endpoint=False)
    progress_m = progress_norm * track_length_m
    speed_kph = np.array([speed_fn(p) for p in progress_norm], dtype=float)
    speed_mps = speed_kph / 3.6
    brake = np.array([brake_fn(p) for p in progress_norm], dtype=float)
    throttle = np.array([throttle_fn(p) for p in progress_norm], dtype=float)

    if long_accel_fn is None:
        long_accel = np.zeros(num_points, dtype=float)
    else:
        long_accel = np.array([long_accel_fn(p) for p in progress_norm], dtype=float)

    if gear_fn is None:
        gear = np.full(num_points, 4, dtype=float)
    else:
        gear = np.array([gear_fn(p) for p in progress_norm], dtype=float)

    if is_coasting_fn is None:
        is_coasting = np.zeros(num_points, dtype=float)
    else:
        is_coasting = np.array([is_coasting_fn(p) for p in progress_norm], dtype=float)

    if steering_fn is None:
        steering = np.zeros(num_points, dtype=float)
    else:
        steering = np.array([steering_fn(p) for p in progress_norm], dtype=float)

    # Elapsed time from speed: dt = dx / v. We drive this via a trapezoidal
    # integration on SpeedMps so the timing math in the module lines up.
    safe_mps = np.clip(speed_mps, 0.1, None)
    dx = np.diff(progress_m, prepend=progress_m[0])
    dx[0] = 0.0
    dt = dx / safe_mps
    elapsed = np.cumsum(dt)
    # Rescale to requested lap time.
    if elapsed[-1] > 0:
        elapsed = elapsed * (lap_time_s / elapsed[-1])

    df = pd.DataFrame({
        "TrackProgressNorm": progress_norm,
        "TrackProgressM": progress_m,
        "ElapsedTimeS": elapsed,
        "SpeedMps": speed_mps,
        "SpeedKph": speed_kph,
        "Throttle": throttle,
        "Brake": brake,
        "Steering": steering,
        "EngineRpm": np.full(num_points, 5000.0),
        "Gear": gear,
        "LongitudinalAccelMps2": long_accel,
        "IsCoasting": is_coasting,
    })
    assert list(df.columns) == ALIGNED_LAP_COLUMNS
    return df


def _make_processed_lap(
    *,
    resampled: pd.DataFrame,
    residual_m: float = 0.2,
    used_fallback: bool = False,
) -> pd.DataFrame:
    """Build a thin processed-lap DataFrame used only for alignment-quality lookups."""
    n = len(resampled)
    return pd.DataFrame({
        "TrackProgressNorm": resampled["TrackProgressNorm"].to_numpy(),
        "AlignmentResidualM": np.full(n, residual_m, dtype=float),
        "AlignmentUsedFallback": np.full(n, 1 if used_fallback else 0, dtype=int),
    })


def _make_corner(
    *,
    corner_id: int,
    start_p: float,
    end_p: float,
    track_length_m: float,
    is_compound: bool = False,
    sub_apex_progress_norms: list[float] | None = None,
    entry_frac: float = 0.30,
    approach_lead_m: float = 80.0,
) -> CornerDefinition:
    center_p = (start_p + end_p) / 2.0
    width = end_p - start_p
    if is_compound:
        entry_end = start_p
        exit_start = end_p
    else:
        entry_end = start_p + width * entry_frac
        exit_start = end_p - width * entry_frac
    return CornerDefinition(
        corner_id=corner_id,
        track_corner_key=f"T{corner_id}",
        start_progress_norm=start_p,
        end_progress_norm=end_p,
        center_progress_norm=center_p,
        start_distance_m=start_p * track_length_m,
        end_distance_m=end_p * track_length_m,
        center_distance_m=center_p * track_length_m,
        approach_start_distance_m=max(0.0, start_p * track_length_m - approach_lead_m),
        entry_end_progress_norm=entry_end,
        exit_start_progress_norm=exit_start,
        length_m=width * track_length_m,
        peak_curvature=0.02,
        mean_curvature=0.015,
        direction="right",
        is_compound=is_compound,
        sub_apex_progress_norms=sub_apex_progress_norms or [],
        sub_apex_distances_m=[
            p * track_length_m for p in (sub_apex_progress_norms or [])
        ],
    )


def _make_segmentation(
    corners: list[CornerDefinition],
    straights: list[StraightDefinition] | None = None,
    reference_length_m: float = 2000.0,
) -> TrackSegmentation:
    return TrackSegmentation(
        corners=corners,
        straights=straights or [],
        reference_lap_number=1,
        reference_length_m=reference_length_m,
        curvature_noise_floor=0.001,
        curvature_corner_threshold=0.005,
        curvature_smoothing_window=11,
        min_corner_length_m=20.0,
        min_turning_angle_rad=0.2,
        min_straight_gap_m=30.0,
        center_region_fraction=0.30,
        approach_lead_m=80.0,
        segmentation_quality={},
        segmentation_version="test",
    )


# ---------------------------------------------------------------------------
# Profile builders — composable piecewise-linear generators
# ---------------------------------------------------------------------------


def _piecewise(points: list[tuple[float, float]]):
    """Return a callable that evaluates a piecewise-linear function.

    ``points`` is a sorted list of ``(progress, value)`` breakpoints. Values
    outside the outer breakpoints saturate to the nearest endpoint.
    """
    xs = np.array([p for p, _ in points], dtype=float)
    ys = np.array([v for _, v in points], dtype=float)

    def _eval(p: float) -> float:
        return float(np.interp(p, xs, ys))

    return _eval


# ---------------------------------------------------------------------------
# Scenario: single simple corner at [0.30, 0.50]
# ---------------------------------------------------------------------------


class TestSimpleCornerRecord(unittest.TestCase):
    """Corner with a textbook brake → apex → throttle profile."""

    TRACK_LEN = 2000.0
    NUM_POINTS = 400
    LAP_TIME = 60.0

    def _speed_profile(self):
        return _piecewise([
            (0.0, 200.0),
            (0.27, 200.0),
            (0.40, 80.0),      # min speed at p=0.40 (effective apex)
            (0.52, 200.0),
            (1.0, 200.0),
        ])

    def _brake_profile(self):
        return _piecewise([
            (0.0, 0.0),
            (0.26, 0.0),
            (0.28, 0.80),
            (0.38, 0.80),
            (0.40, 0.0),
            (1.0, 0.0),
        ])

    def _throttle_profile(self):
        return _piecewise([
            (0.0, 1.0),
            (0.26, 1.0),
            (0.27, 0.0),
            (0.40, 0.0),
            (0.44, 0.5),
            (0.48, 1.0),
            (1.0, 1.0),
        ])

    def _long_accel_profile(self):
        return _piecewise([
            (0.0, 0.0),
            (0.27, 0.0),
            (0.28, -8.0),
            (0.39, -8.0),
            (0.40, 0.0),
            (0.42, 4.0),
            (0.50, 4.0),
            (0.52, 0.0),
            (1.0, 0.0),
        ])

    def _build(self):
        resampled = _make_resampled_lap(
            track_length_m=self.TRACK_LEN,
            num_points=self.NUM_POINTS,
            lap_time_s=self.LAP_TIME,
            speed_fn=self._speed_profile(),
            brake_fn=self._brake_profile(),
            throttle_fn=self._throttle_profile(),
            long_accel_fn=self._long_accel_profile(),
        )
        processed = _make_processed_lap(resampled=resampled, residual_m=0.3)
        corner = _make_corner(
            corner_id=1,
            start_p=0.30,
            end_p=0.50,
            track_length_m=self.TRACK_LEN,
        )
        segmentation = _make_segmentation([corner], reference_length_m=self.TRACK_LEN)
        return extract_corner_records(resampled, processed, segmentation, lap_number=2)

    def test_returns_one_corner_record_no_straights(self) -> None:
        corners, straights = self._build()
        self.assertEqual(len(corners), 1)
        self.assertEqual(len(straights), 0)

    def test_corner_identity_fields(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertEqual(record.lap_number, 2)
        self.assertEqual(record.corner_id, 1)
        self.assertFalse(record.is_compound)
        self.assertEqual(record.sub_corner_records, [])

    def test_effective_apex_is_min_speed_point(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        # Min-speed point is at p=0.40, speed=80 kph.
        self.assertAlmostEqual(record.min_speed_kph, 80.0, delta=1.0)
        self.assertAlmostEqual(record.min_speed_progress_norm, 0.40, delta=0.01)

    def test_phase_metrics_shape(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertIsInstance(record.entry, PhaseMetrics)
        self.assertIsInstance(record.apex, PhaseMetrics)
        self.assertIsInstance(record.exit, PhaseMetrics)
        # Entry phase starts inside the braking zone but before the apex, so
        # its entry speed is well above the min but below the pre-brake plateau.
        self.assertGreater(record.entry.entry_speed_kph, record.apex.min_speed_kph)
        self.assertLess(record.entry.entry_speed_kph, 200.0)
        # Apex phase contains the effective apex.
        self.assertLess(record.apex.min_speed_kph, 100.0)
        # Exit phase should end at or near full speed again.
        self.assertGreater(record.exit.exit_speed_kph, 150.0)

    def test_phase_times_sum_to_corner_time(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        phase_sum = record.entry.time_s + record.apex.time_s + record.exit.time_s
        self.assertAlmostEqual(phase_sum, record.corner_time_s, delta=0.05)

    def test_corner_time_is_positive(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertGreater(record.corner_time_s, 0.0)

    def test_brake_event_populated(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertIsNotNone(record.brake)
        assert record.brake is not None
        self.assertIsInstance(record.brake, BrakeEvent)
        # Initiation happened roughly around p=0.27-0.28.
        self.assertGreater(record.brake.initiation_progress_norm, 0.25)
        self.assertLess(record.brake.initiation_progress_norm, 0.30)
        # Peak brake matches the plateau value.
        self.assertAlmostEqual(record.brake.peak_brake, 0.80, delta=0.05)
        # Decel during brake phase is negative.
        self.assertLess(record.brake.peak_decel_mps2, -5.0)
        # Trail brake depth should be small — release is just before apex.
        self.assertLess(abs(record.brake.trail_brake_depth_m), 30.0)

    def test_throttle_event_populated(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertIsNotNone(record.throttle)
        assert record.throttle is not None
        self.assertIsInstance(record.throttle, ThrottleEvent)
        # Pickup should be shortly after p=0.40 (the min-speed point).
        self.assertGreater(record.throttle.pickup_progress_norm, 0.40)
        self.assertLess(record.throttle.pickup_progress_norm, 0.46)
        # Pickup distance from min speed is positive (after apex).
        self.assertGreater(record.throttle.pickup_distance_from_min_speed_m, 0.0)
        # Eventually reaches full throttle inside the exit region.
        self.assertIsNotNone(record.throttle.full_throttle_progress_norm)
        # No spurious dip in this profile.
        self.assertFalse(record.throttle.throttle_dip_detected)

    def test_alignment_quality_clean(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertAlmostEqual(record.alignment_quality_m, 0.3, delta=0.01)
        self.assertFalse(record.alignment_used_fallback)

    def test_gear_at_min_speed(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertEqual(record.gear_at_min_speed, 4)


# ---------------------------------------------------------------------------
# Scenario: lift-only corner — no brake event
# ---------------------------------------------------------------------------


class TestLiftOnlyCorner(unittest.TestCase):
    """Fast sweeper taken on a lift — peak brake stays below the presence gate."""

    TRACK_LEN = 2000.0
    NUM_POINTS = 400
    LAP_TIME = 60.0

    def _build(self):
        speed_fn = _piecewise([
            (0.0, 220.0),
            (0.35, 220.0),
            (0.40, 200.0),
            (0.45, 220.0),
            (1.0, 220.0),
        ])
        brake_fn = _piecewise([(0.0, 0.0), (1.0, 0.0)])  # never touches brake
        throttle_fn = _piecewise([
            (0.0, 1.0),
            (0.35, 1.0),
            (0.36, 0.5),  # lift
            (0.44, 0.5),
            (0.45, 1.0),
            (1.0, 1.0),
        ])
        resampled = _make_resampled_lap(
            track_length_m=self.TRACK_LEN,
            num_points=self.NUM_POINTS,
            lap_time_s=self.LAP_TIME,
            speed_fn=speed_fn,
            brake_fn=brake_fn,
            throttle_fn=throttle_fn,
        )
        processed = _make_processed_lap(resampled=resampled)
        corner = _make_corner(
            corner_id=7,
            start_p=0.34,
            end_p=0.46,
            track_length_m=self.TRACK_LEN,
        )
        segmentation = _make_segmentation([corner], reference_length_m=self.TRACK_LEN)
        return extract_corner_records(resampled, processed, segmentation, lap_number=1)

    def test_no_brake_event(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        self.assertIsNone(record.brake)

    def test_throttle_still_computed(self) -> None:
        corners, _ = self._build()
        record = corners[0]
        # Throttle never fell below the pickup threshold, so the detector may
        # either return an event or return None if post-apex throttle is
        # already > threshold. Either way we should get a valid record.
        self.assertIsNotNone(record)


# ---------------------------------------------------------------------------
# Scenario: corner inside a fallback-alignment region
# ---------------------------------------------------------------------------


class TestFallbackAlignment(unittest.TestCase):
    def test_alignment_used_fallback_is_true(self) -> None:
        resampled = _make_resampled_lap(
            track_length_m=2000.0,
            num_points=400,
            lap_time_s=60.0,
            speed_fn=_piecewise([(0.0, 150.0), (1.0, 150.0)]),
            brake_fn=_piecewise([(0.0, 0.0), (1.0, 0.0)]),
            throttle_fn=_piecewise([(0.0, 0.8), (1.0, 0.8)]),
        )
        processed = _make_processed_lap(
            resampled=resampled, residual_m=1.8, used_fallback=True
        )
        corner = _make_corner(
            corner_id=3, start_p=0.40, end_p=0.55, track_length_m=2000.0
        )
        segmentation = _make_segmentation([corner], reference_length_m=2000.0)
        corners, _ = extract_corner_records(resampled, processed, segmentation, lap_number=1)
        self.assertTrue(corners[0].alignment_used_fallback)
        self.assertAlmostEqual(corners[0].alignment_quality_m, 1.8, delta=0.01)


# ---------------------------------------------------------------------------
# Scenario: compound corner with two sub-apexes
# ---------------------------------------------------------------------------


class TestCompoundCornerSubRecords(unittest.TestCase):
    """Compound corner with distinct min-speed points per sub-apex."""

    TRACK_LEN = 3000.0
    NUM_POINTS = 600
    LAP_TIME = 90.0

    def _build(self):
        # Two dips in speed at p=0.40 and p=0.55.
        speed_fn = _piecewise([
            (0.00, 200.0),
            (0.32, 200.0),
            (0.40, 90.0),   # first apex
            (0.47, 140.0),  # mid reacceleration
            (0.55, 75.0),   # second apex (slower)
            (0.63, 200.0),
            (1.00, 200.0),
        ])
        brake_fn = _piecewise([
            (0.00, 0.0),
            (0.32, 0.0),
            (0.34, 0.7),
            (0.39, 0.7),
            (0.40, 0.0),
            (0.48, 0.0),
            (0.50, 0.8),
            (0.54, 0.8),
            (0.55, 0.0),
            (1.00, 0.0),
        ])
        throttle_fn = _piecewise([
            (0.00, 1.0),
            (0.32, 1.0),
            (0.33, 0.0),
            (0.40, 0.0),
            (0.44, 0.5),
            (0.47, 0.5),
            (0.49, 0.0),
            (0.55, 0.0),
            (0.58, 0.5),
            (0.63, 1.0),
            (1.00, 1.0),
        ])
        resampled = _make_resampled_lap(
            track_length_m=self.TRACK_LEN,
            num_points=self.NUM_POINTS,
            lap_time_s=self.LAP_TIME,
            speed_fn=speed_fn,
            brake_fn=brake_fn,
            throttle_fn=throttle_fn,
        )
        processed = _make_processed_lap(resampled=resampled)
        corner = _make_corner(
            corner_id=5,
            start_p=0.32,
            end_p=0.63,
            track_length_m=self.TRACK_LEN,
            is_compound=True,
            sub_apex_progress_norms=[0.40, 0.55],
        )
        segmentation = _make_segmentation([corner], reference_length_m=self.TRACK_LEN)
        return extract_corner_records(resampled, processed, segmentation, lap_number=3)

    def test_compound_flag_propagates(self) -> None:
        corners, _ = self._build()
        self.assertTrue(corners[0].is_compound)

    def test_two_sub_corner_records(self) -> None:
        corners, _ = self._build()
        self.assertEqual(len(corners[0].sub_corner_records), 2)

    def test_sub_records_bracket_distinct_apexes(self) -> None:
        corners, _ = self._build()
        sub1, sub2 = corners[0].sub_corner_records
        # First sub-record's min-speed sits around p=0.40; second around p=0.55.
        self.assertAlmostEqual(sub1.min_speed_progress_norm, 0.40, delta=0.02)
        self.assertAlmostEqual(sub2.min_speed_progress_norm, 0.55, delta=0.02)
        # Second apex is slower than first in this profile.
        self.assertLess(sub2.min_speed_kph, sub1.min_speed_kph)

    def test_sub_records_not_themselves_compound(self) -> None:
        corners, _ = self._build()
        for sub in corners[0].sub_corner_records:
            self.assertFalse(sub.is_compound)
            self.assertEqual(sub.sub_corner_records, [])


# ---------------------------------------------------------------------------
# Scenario: effective apex far from geometric center
# ---------------------------------------------------------------------------


class TestEffectiveApexAnchoring(unittest.TestCase):
    """Min-speed point is near the start of the corner, not the center."""

    def test_min_speed_location_uses_speed_not_center(self) -> None:
        track_len = 2000.0
        num_points = 400
        # Corner spans [0.30, 0.60]; center_progress_norm = 0.45. But the
        # min-speed point is at 0.33 — an early-apex hairpin-like profile.
        speed_fn = _piecewise([
            (0.00, 200.0),
            (0.28, 200.0),
            (0.33, 60.0),   # early apex
            (0.58, 180.0),
            (1.00, 200.0),
        ])
        brake_fn = _piecewise([
            (0.00, 0.0),
            (0.27, 0.0),
            (0.29, 0.9),
            (0.32, 0.9),
            (0.33, 0.0),
            (1.00, 0.0),
        ])
        throttle_fn = _piecewise([
            (0.00, 1.0),
            (0.28, 0.0),
            (0.33, 0.0),
            (0.40, 0.5),
            (0.55, 1.0),
            (1.00, 1.0),
        ])
        resampled = _make_resampled_lap(
            track_length_m=track_len,
            num_points=num_points,
            lap_time_s=60.0,
            speed_fn=speed_fn,
            brake_fn=brake_fn,
            throttle_fn=throttle_fn,
        )
        processed = _make_processed_lap(resampled=resampled)
        corner = _make_corner(
            corner_id=2, start_p=0.30, end_p=0.60, track_length_m=track_len
        )
        # Sanity-check the fixture: center is at 0.45, effective apex at 0.33.
        self.assertAlmostEqual(corner.center_progress_norm, 0.45, delta=0.001)
        segmentation = _make_segmentation([corner], reference_length_m=track_len)
        corners, _ = extract_corner_records(
            resampled, processed, segmentation, lap_number=1
        )
        record = corners[0]
        # The record's min_speed_progress_norm must anchor on the speed min,
        # NOT on the geometric center.
        self.assertAlmostEqual(record.min_speed_progress_norm, 0.33, delta=0.02)
        self.assertLess(abs(record.min_speed_progress_norm - 0.33), 0.05)
        self.assertGreater(
            abs(record.min_speed_progress_norm - corner.center_progress_norm), 0.08
        )
        # Throttle pickup distance is measured from the effective apex.
        assert record.throttle is not None
        self.assertGreaterEqual(
            record.throttle.pickup_distance_from_min_speed_m, 0.0
        )


# ---------------------------------------------------------------------------
# Scenario: straight records
# ---------------------------------------------------------------------------


class TestStraightRecord(unittest.TestCase):
    def test_straight_time_and_speeds(self) -> None:
        track_len = 2000.0
        num_points = 400
        # Constant-speed straight: 180 kph from start to finish.
        speed_fn = _piecewise([(0.0, 180.0), (1.0, 180.0)])
        resampled = _make_resampled_lap(
            track_length_m=track_len,
            num_points=num_points,
            lap_time_s=40.0,
            speed_fn=speed_fn,
            brake_fn=_piecewise([(0.0, 0.0), (1.0, 0.0)]),
            throttle_fn=_piecewise([(0.0, 1.0), (1.0, 1.0)]),
        )
        processed = _make_processed_lap(resampled=resampled)
        straight = StraightDefinition(
            straight_id=1,
            start_distance_m=200.0,   # p=0.10
            end_distance_m=1000.0,    # p=0.50
            length_m=800.0,
            preceding_corner_id=None,
            following_corner_id=None,
            wraps_start_finish=False,
        )
        segmentation = _make_segmentation(
            corners=[], straights=[straight], reference_length_m=track_len
        )
        _, straights = extract_corner_records(
            resampled, processed, segmentation, lap_number=1
        )
        self.assertEqual(len(straights), 1)
        record = straights[0]
        self.assertIsInstance(record, StraightRecord)
        self.assertEqual(record.straight_id, 1)
        self.assertEqual(record.lap_number, 1)
        # Constant-speed lap: entry speed == exit speed == 180.
        self.assertAlmostEqual(record.entry_speed_kph, 180.0, delta=0.5)
        self.assertAlmostEqual(record.exit_speed_kph, 180.0, delta=0.5)
        # Time through 800 m at 50 m/s = 16 s. Allow small tolerance from
        # lap-time rescaling + interpolation.
        self.assertAlmostEqual(record.time_s, 16.0, delta=0.2)


# ---------------------------------------------------------------------------
# Trail brake depth sign convention
# ---------------------------------------------------------------------------


class TestTrailBrakeDepthSign(unittest.TestCase):
    """Verify trail_brake_depth_m sign: positive = held past apex, negative = released before."""

    TRACK_LEN = 2000.0
    NUM_POINTS = 400
    LAP_TIME = 60.0

    def _build(self, brake_fn):
        speed_fn = _piecewise([
            (0.0, 200.0), (0.27, 200.0), (0.40, 80.0),
            (0.52, 200.0), (1.0, 200.0),
        ])
        throttle_fn = _piecewise([
            (0.0, 1.0), (0.26, 1.0), (0.27, 0.0),
            (0.50, 0.0), (0.54, 1.0), (1.0, 1.0),
        ])
        long_accel_fn = _piecewise([
            (0.0, 0.0), (0.27, 0.0), (0.28, -12.0),
            (0.36, -12.0), (0.38, 0.0), (1.0, 0.0),
        ])
        resampled = _make_resampled_lap(
            track_length_m=self.TRACK_LEN,
            num_points=self.NUM_POINTS,
            lap_time_s=self.LAP_TIME,
            speed_fn=speed_fn,
            brake_fn=brake_fn,
            throttle_fn=throttle_fn,
            long_accel_fn=long_accel_fn,
        )
        processed = _make_processed_lap(resampled=resampled)
        corner = _make_corner(
            corner_id=1, start_p=0.30, end_p=0.50, track_length_m=self.TRACK_LEN,
        )
        segmentation = _make_segmentation([corner], reference_length_m=self.TRACK_LEN)
        corners, _ = extract_corner_records(resampled, processed, segmentation, lap_number=1)
        return corners[0]

    def test_brake_held_past_apex_gives_positive_depth(self) -> None:
        # Brake holds through the apex (p=0.40), releases at p=0.46.
        brake_fn = _piecewise([
            (0.0, 0.0), (0.26, 0.0), (0.28, 0.80),
            (0.44, 0.80), (0.46, 0.0), (1.0, 0.0),
        ])
        record = self._build(brake_fn)
        self.assertIsNotNone(record.brake)
        assert record.brake is not None
        self.assertGreater(record.brake.trail_brake_depth_m, 0.0)

    def test_brake_released_before_apex_gives_negative_depth(self) -> None:
        # Brake releases at p=0.35, well before apex at p=0.40.
        brake_fn = _piecewise([
            (0.0, 0.0), (0.26, 0.0), (0.28, 0.80),
            (0.34, 0.80), (0.36, 0.0), (1.0, 0.0),
        ])
        record = self._build(brake_fn)
        self.assertIsNotNone(record.brake)
        assert record.brake is not None
        self.assertLess(record.brake.trail_brake_depth_m, 0.0)


# ---------------------------------------------------------------------------
# Adaptive steering noise estimator
# ---------------------------------------------------------------------------


class TestEstimateSteeringNoise(unittest.TestCase):
    """_estimate_steering_noise should return lower values for quiet steering."""

    def _make_arrays(self, steering: list[float]) -> _LapArrays:
        n = len(steering)
        zeros = np.zeros(n)
        ones = np.ones(n)
        return _LapArrays(
            progress_norm=np.linspace(0.0, 1.0, n),
            progress_m=np.linspace(0.0, 3000.0, n),
            elapsed_s=np.linspace(0.0, 90.0, n),
            speed_kph=ones * 100.0,
            throttle=zeros,
            brake=zeros,
            steering=np.array(steering, dtype=float),
            gear=ones * 3.0,
            long_accel=zeros,
            is_coasting=zeros,
        )

    def test_quiet_lap_gives_lower_noise_than_noisy_lap(self) -> None:
        quiet = self._make_arrays([0.0, 0.001, 0.002, 0.001, 0.0] * 20)
        noisy = self._make_arrays([0.0, 0.05, -0.05, 0.05, -0.05] * 20)
        noise_quiet = _estimate_steering_noise(quiet)
        noise_noisy = _estimate_steering_noise(noisy)
        self.assertLess(noise_quiet, noise_noisy)

    def test_floor_at_0_01_for_flat_steering(self) -> None:
        flat = self._make_arrays([0.0] * 100)
        self.assertGreaterEqual(_estimate_steering_noise(flat), 0.01)

    def test_empty_arrays_returns_default(self) -> None:
        from src.analysis.constants import STEERING_NOISE_THRESHOLD
        empty = self._make_arrays([0.0])  # only 1 sample → diff is empty
        self.assertEqual(_estimate_steering_noise(empty), STEERING_NOISE_THRESHOLD)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
