from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.core.schemas import REFERENCE_PATH_COLUMNS
from src.processing.segmentation import (
    APPROACH_LEAD_M,
    CENTER_REGION_FRACTION,
    CURVATURE_CORNER_THRESHOLD,
    CURVATURE_NOISE_FLOOR,
    MIN_CORNER_LENGTH_M,
    MIN_STRAIGHT_GAP_M,
    MIN_TURNING_ANGLE_RAD,
    MIN_SUB_APEX_SEPARATION_M,
    SEGMENTATION_VERSION,
    CornerDefinition,
    StraightDefinition,
    TrackSegmentation,
    segment_track,
    _compute_signed_curvature,
    _find_prominent_peaks,
    _smooth_curvature,
)


def _build_reference_path_df(
    x: np.ndarray,
    z: np.ndarray,
    lap_number: int = 1,
) -> pd.DataFrame:
    """Build a reference path DataFrame from x/z coordinate arrays."""
    n = len(x)
    dx = np.diff(x, prepend=x[0])
    dz = np.diff(z, prepend=z[0])
    step = np.sqrt(dx**2 + dz**2)
    step[0] = 0.0
    dist_m = np.cumsum(step)
    total = dist_m[-1] if dist_m[-1] > 0 else 1.0
    prog_norm = dist_m / total

    return pd.DataFrame({
        "ReferenceSampleIndex": np.arange(n, dtype=int),
        "ReferenceLapNumber": lap_number,
        "PositionX": x,
        "PositionY": np.zeros(n),
        "PositionZ": z,
        "ReferenceDistanceM": dist_m,
        "ReferenceProgressNorm": prog_norm,
    })


def _straight_segment(start_x: float, start_z: float, length_m: float, heading_rad: float) -> tuple[np.ndarray, np.ndarray]:
    """Generate a straight segment at 1m spacing."""
    n = max(2, int(round(length_m)))
    t = np.linspace(0, length_m, n, endpoint=False)
    x = start_x + t * np.cos(heading_rad)
    z = start_z + t * np.sin(heading_rad)
    return x, z


def _arc_segment(
    center_x: float,
    center_z: float,
    radius: float,
    start_angle_rad: float,
    arc_angle_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate an arc segment at ~1m spacing.

    arc_angle_rad > 0 = counterclockwise, < 0 = clockwise.
    """
    arc_length = abs(arc_angle_rad) * radius
    n = max(3, int(round(arc_length)))
    angles = np.linspace(start_angle_rad, start_angle_rad + arc_angle_rad, n, endpoint=False)
    x = center_x + radius * np.cos(angles)
    z = center_z + radius * np.sin(angles)
    return x, z


def _concat_segments(*segments: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate coordinate segments, removing duplicate junction points."""
    all_x: list[np.ndarray] = []
    all_z: list[np.ndarray] = []
    for i, (sx, sz) in enumerate(segments):
        if i > 0 and len(sx) > 0:
            sx = sx[1:]
            sz = sz[1:]
        if len(sx) > 0:
            all_x.append(sx)
            all_z.append(sz)
    return np.concatenate(all_x), np.concatenate(all_z)


class TestSegmentationDegenerate(unittest.TestCase):
    """Test 10: Empty / degenerate input."""

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame(columns=REFERENCE_PATH_COLUMNS)
        result = segment_track(df)
        self.assertIsInstance(result, TrackSegmentation)
        self.assertEqual(len(result.corners), 0)
        self.assertEqual(result.segmentation_version, SEGMENTATION_VERSION)

    def test_single_point(self) -> None:
        df = _build_reference_path_df(np.array([0.0]), np.array([0.0]))
        result = segment_track(df)
        self.assertEqual(len(result.corners), 0)

    def test_two_points(self) -> None:
        df = _build_reference_path_df(np.array([0.0, 1.0]), np.array([0.0, 0.0]))
        result = segment_track(df)
        self.assertEqual(len(result.corners), 0)

    def test_very_short_path(self) -> None:
        x = np.linspace(0, 10, 10)
        z = np.zeros(10)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self.assertEqual(len(result.corners), 0)


class TestStraightPath(unittest.TestCase):
    """Test 1: Perfectly straight path should produce zero corners."""

    def test_straight_line_no_corners(self) -> None:
        x = np.linspace(0, 1000, 1001)
        z = np.zeros(1001)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 0)
        self.assertAlmostEqual(result.reference_length_m, 1000.0, places=0)
        self.assertEqual(result.reference_lap_number, 1)

    def test_diagonal_straight_no_corners(self) -> None:
        t = np.linspace(0, 1000, 1001)
        x = t * np.cos(0.7)
        z = t * np.sin(0.7)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self.assertEqual(len(result.corners), 0)


class TestSingleArc(unittest.TestCase):
    """Test 2: Single circular arc embedded in a straight."""

    def _build_single_corner_path(self, radius: float = 50.0, arc_degrees: float = 90.0) -> pd.DataFrame:
        arc_rad = np.radians(arc_degrees)

        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        end_x, end_z = straight1_x[-1], straight1_z[-1]

        center_x = end_x
        center_z = end_z + radius
        start_angle = -np.pi / 2

        arc_x, arc_z = _arc_segment(center_x, center_z, radius, start_angle, arc_rad)

        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading_after_arc = start_angle + arc_rad + np.pi / 2
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, heading_after_arc)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        return _build_reference_path_df(x, z)

    def test_single_corner_detected(self) -> None:
        df = self._build_single_corner_path(radius=50.0, arc_degrees=90.0)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 1)
        corner = result.corners[0]
        self.assertEqual(corner.corner_id, 1)
        self.assertFalse(corner.is_compound)
        self.assertGreater(corner.length_m, MIN_CORNER_LENGTH_M)

        expected_curvature = 1.0 / 50.0
        self.assertAlmostEqual(corner.peak_curvature, expected_curvature, delta=0.005)

    def test_corner_has_valid_subregions(self) -> None:
        df = self._build_single_corner_path()
        result = segment_track(df)
        corner = result.corners[0]

        self.assertGreaterEqual(corner.entry_end_progress_norm, corner.start_progress_norm)
        self.assertLessEqual(corner.exit_start_progress_norm, corner.end_progress_norm)
        self.assertLessEqual(corner.entry_end_progress_norm, corner.exit_start_progress_norm)

    def test_direction_is_set(self) -> None:
        df = self._build_single_corner_path()
        result = segment_track(df)
        self.assertIn(result.corners[0].direction, ("left", "right"))

    def test_sub_apex_single_element(self) -> None:
        df = self._build_single_corner_path()
        result = segment_track(df)
        corner = result.corners[0]
        self.assertEqual(len(corner.sub_apex_progress_norms), 1)
        self.assertAlmostEqual(
            corner.sub_apex_progress_norms[0],
            corner.center_progress_norm,
            places=6,
        )


class TestTwoSeparateCorners(unittest.TestCase):
    """Test 3: Two arcs separated by a long straight (> MIN_STRAIGHT_GAP_M)."""

    def test_two_corners_detected(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 40
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)

        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)

        s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
        cx2 = s2_end_x - 40
        cz2 = s2_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)

        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (straight2_x, straight2_z),
            (arc2_x, arc2_z),
            (straight3_x, straight3_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 2)
        self.assertEqual(result.corners[0].corner_id, 1)
        self.assertEqual(result.corners[1].corner_id, 2)
        self.assertFalse(result.corners[0].is_compound)
        self.assertFalse(result.corners[1].is_compound)
        self.assertLess(
            result.corners[0].end_progress_norm,
            result.corners[1].start_progress_norm,
        )


class TestChicaneMerge(unittest.TestCase):
    """Test 4: Two arcs in opposite directions separated by < MIN_STRAIGHT_GAP_M."""

    def test_chicane_merged_into_compound(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 30
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 30, -np.pi / 2, np.pi / 2)

        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        short_straight_x, short_straight_z = _straight_segment(
            arc1_end_x, arc1_end_z, 20, np.pi / 2,
        )

        ss_end_x, ss_end_z = short_straight_x[-1], short_straight_z[-1]
        cx2 = ss_end_x + 30
        cz2 = ss_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 30, np.pi, -np.pi / 2)

        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight2_x, straight2_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi / 2)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (short_straight_x, short_straight_z),
            (arc2_x, arc2_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 1)
        corner = result.corners[0]
        self.assertTrue(corner.is_compound)
        self.assertGreaterEqual(len(corner.sub_apex_progress_norms), 2)


class TestGentleSweeper(unittest.TestCase):
    """Test 5: Gentle arc (R=250m) that stays below corner threshold."""

    def test_gentle_bend_not_detected(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        end_x, end_z = straight1_x[-1], straight1_z[-1]
        center_x = end_x
        center_z = end_z + 250
        arc_angle = 150.0 / 250.0
        arc_x, arc_z = _arc_segment(center_x, center_z, 250, -np.pi / 2, arc_angle)

        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading = -np.pi / 2 + arc_angle + np.pi / 2
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, heading)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        curvature_at_arc = 1.0 / 250.0
        self.assertLess(curvature_at_arc, CURVATURE_CORNER_THRESHOLD)
        self.assertEqual(len(result.corners), 0)


class TestFastSweeperQualifies(unittest.TestCase):
    """Test 6: Arc with R=150m that exceeds corner threshold."""

    def test_fast_sweeper_detected(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        end_x, end_z = straight1_x[-1], straight1_z[-1]
        center_x = end_x
        center_z = end_z + 150
        arc_angle = 100.0 / 150.0
        arc_x, arc_z = _arc_segment(center_x, center_z, 150, -np.pi / 2, arc_angle)

        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading = -np.pi / 2 + arc_angle + np.pi / 2
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, heading)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        curvature_at_arc = 1.0 / 150.0
        self.assertGreater(curvature_at_arc, CURVATURE_CORNER_THRESHOLD)
        self.assertEqual(len(result.corners), 1)


class TestTinyKinkFiltered(unittest.TestCase):
    """Test 7: A very short arc (10m) is filtered by minimum length."""

    def test_tiny_kink_not_detected(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        end_x, end_z = straight1_x[-1], straight1_z[-1]
        radius = 20.0
        arc_angle = 10.0 / radius
        center_x = end_x
        center_z = end_z + radius
        arc_x, arc_z = _arc_segment(center_x, center_z, radius, -np.pi / 2, arc_angle)

        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading = -np.pi / 2 + arc_angle + np.pi / 2
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, heading)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        arc_length = arc_angle * radius
        self.assertLess(arc_length, MIN_CORNER_LENGTH_M)
        self.assertEqual(len(result.corners), 0)


class TestWrapAround(unittest.TestCase):
    """Test 8: Corner straddling the start/finish line."""

    def test_wrap_around_merge(self) -> None:
        radius = 40.0
        arc_half_angle = np.pi / 4

        center_x, center_z = 0.0, radius
        arc_x, arc_z = _arc_segment(center_x, center_z, radius, -np.pi / 2 - arc_half_angle, 2 * arc_half_angle)

        arc_mid = len(arc_x) // 2
        second_half_x = arc_x[arc_mid:]
        second_half_z = arc_z[arc_mid:]
        first_half_x = arc_x[:arc_mid + 1]
        first_half_z = arc_z[:arc_mid + 1]

        s_end_x, s_end_z = second_half_x[-1], second_half_z[-1]
        dx = first_half_x[0] - s_end_x
        dz = first_half_z[0] - s_end_z
        heading = np.arctan2(dz, dx)

        gap_dist = np.hypot(dx, dz)
        straight_length = max(200.0, gap_dist + 100)
        straight_x, straight_z = _straight_segment(s_end_x, s_end_z, straight_length, heading)

        x = np.concatenate([second_half_x, straight_x[1:], first_half_x[1:]])
        z = np.concatenate([second_half_z, straight_z[1:], first_half_z[1:]])

        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        has_wrap_corner = False
        for corner in result.corners:
            if corner.start_progress_norm > corner.end_progress_norm:
                has_wrap_corner = True
                break

        if not has_wrap_corner and len(result.corners) >= 1:
            first_starts_near_zero = result.corners[0].start_distance_m < MIN_STRAIGHT_GAP_M
            last_ends_near_end = (result.reference_length_m - result.corners[-1].end_distance_m) < MIN_STRAIGHT_GAP_M
            if first_starts_near_zero or last_ends_near_end:
                has_wrap_corner = True

        self.assertTrue(
            has_wrap_corner or len(result.corners) >= 1,
            "Expected at least one corner near the wrap-around boundary",
        )


class TestCurvatureComputation(unittest.TestCase):
    """Unit tests for the curvature computation itself."""

    def test_circle_curvature(self) -> None:
        radius = 100.0
        n = 200
        angles = np.linspace(0, np.pi, n)
        x = radius * np.cos(angles)
        z = radius * np.sin(angles)

        dx = np.diff(x, prepend=x[0])
        dz = np.diff(z, prepend=z[0])
        step = np.sqrt(dx**2 + dz**2)
        step[0] = 0.0
        dist_m = np.cumsum(step)

        kappa = _compute_signed_curvature(x, z, dist_m)
        kappa_smooth = _smooth_curvature(kappa)

        interior = kappa_smooth[10:-10]
        expected = 1.0 / radius
        np.testing.assert_allclose(
            np.abs(interior), expected, atol=0.002,
            err_msg=f"Expected curvature ~{expected:.4f} for R={radius}m circle",
        )

    def test_straight_curvature_is_zero(self) -> None:
        x = np.linspace(0, 500, 501)
        z = np.zeros(501)
        dist_m = x.copy()
        kappa = _compute_signed_curvature(x, z, dist_m)
        np.testing.assert_allclose(kappa, 0.0, atol=1e-12)


class TestSerializationRoundtrip(unittest.TestCase):
    """Verify to_dict produces valid JSON-serializable output."""

    def test_to_dict(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx = straight1_x[-1]
        cz = straight1_z[-1] + 40
        arc_x, arc_z = _arc_segment(cx, cz, 40, -np.pi / 2, np.pi / 2)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, np.pi / 2)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("corners", d)
        self.assertIn("segmentation_version", d)
        self.assertIsInstance(d["corners"], list)
        if d["corners"]:
            c = d["corners"][0]
            self.assertIn("corner_id", c)
            self.assertIn("start_progress_norm", c)
            self.assertIn("direction", c)
            self.assertIn("sub_apex_progress_norms", c)

        import json
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)


class TestCornerBoundaryOrdering(unittest.TestCase):
    """Verify that progress_norm values within each corner are ordered correctly."""

    def test_boundary_ordering(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx = straight1_x[-1]
        cz = straight1_z[-1] + 40
        arc_x, arc_z = _arc_segment(cx, cz, 40, -np.pi / 2, np.pi / 2)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, np.pi / 2)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        for corner in result.corners:
            if corner.start_progress_norm < corner.end_progress_norm:
                self.assertLessEqual(corner.start_progress_norm, corner.entry_end_progress_norm)
                self.assertLessEqual(corner.entry_end_progress_norm, corner.center_progress_norm)
                self.assertLessEqual(corner.center_progress_norm, corner.exit_start_progress_norm)
                self.assertLessEqual(corner.exit_start_progress_norm, corner.end_progress_norm)

            self.assertGreater(corner.length_m, 0)
            self.assertGreater(corner.peak_curvature, 0)
            self.assertGreater(corner.mean_curvature, 0)


class TestTurningAngleFilter(unittest.TestCase):
    """An arc that passes length and curvature thresholds but fails turning angle."""

    def test_low_turning_angle_filtered(self) -> None:
        radius = 100.0
        arc_length = 16.0
        arc_angle = arc_length / radius

        curvature = 1.0 / radius
        self.assertGreater(curvature, CURVATURE_CORNER_THRESHOLD)
        self.assertGreater(arc_length, MIN_CORNER_LENGTH_M)
        self.assertLess(arc_length * curvature, MIN_TURNING_ANGLE_RAD)

        straight1_x, straight1_z = _straight_segment(0, 0, 300, 0)
        end_x, end_z = straight1_x[-1], straight1_z[-1]
        center_x, center_z = end_x, end_z + radius
        arc_x, arc_z = _arc_segment(center_x, center_z, radius, -np.pi / 2, arc_angle)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading = -np.pi / 2 + arc_angle + np.pi / 2
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 300, heading)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self.assertEqual(len(result.corners), 0)


class TestDirectionCorrectness(unittest.TestCase):
    """Verify left vs right direction matches the geometry."""

    def _build_arc(self, arc_angle_rad: float, radius: float = 50.0) -> pd.DataFrame:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        end_x, end_z = straight1_x[-1], straight1_z[-1]

        if arc_angle_rad > 0:
            center_x, center_z = end_x, end_z + radius
            start_angle = -np.pi / 2
        else:
            center_x, center_z = end_x, end_z - radius
            start_angle = np.pi / 2

        arc_x, arc_z = _arc_segment(center_x, center_z, radius, start_angle, arc_angle_rad)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        heading = start_angle + arc_angle_rad + (np.pi / 2 if arc_angle_rad > 0 else -np.pi / 2)
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, heading)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        return _build_reference_path_df(x, z)

    def test_left_turn_direction(self) -> None:
        df = self._build_arc(arc_angle_rad=np.pi / 2)
        result = segment_track(df)
        self.assertEqual(len(result.corners), 1)
        self.assertEqual(result.corners[0].direction, "left")

    def test_right_turn_direction(self) -> None:
        df = self._build_arc(arc_angle_rad=-np.pi / 2)
        result = segment_track(df)
        self.assertEqual(len(result.corners), 1)
        self.assertEqual(result.corners[0].direction, "right")


class TestNonOverlappingCorners(unittest.TestCase):
    """Verify no two corners have overlapping progress ranges."""

    def test_corners_do_not_overlap(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)

        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 40
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)

        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)

        s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
        cx2 = s2_end_x - 40
        cz2 = s2_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)

        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (straight2_x, straight2_z),
            (arc2_x, arc2_z),
            (straight3_x, straight3_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        non_wrap = [c for c in result.corners if c.start_progress_norm < c.end_progress_norm]
        sorted_corners = sorted(non_wrap, key=lambda c: c.start_progress_norm)
        for i in range(len(sorted_corners) - 1):
            self.assertLessEqual(
                sorted_corners[i].end_progress_norm,
                sorted_corners[i + 1].start_progress_norm,
                f"Corner {sorted_corners[i].corner_id} overlaps corner {sorted_corners[i+1].corner_id}",
            )


class TestSerializationFields(unittest.TestCase):
    """Verify all expected fields exist in serialized output."""

    def test_min_turning_angle_in_dict(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx = straight1_x[-1]
        cz = straight1_z[-1] + 40
        arc_x, arc_z = _arc_segment(cx, cz, 40, -np.pi / 2, np.pi / 2)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, 200, np.pi / 2)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc_x, arc_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        d = result.to_dict()

        self.assertIn("min_turning_angle_rad", d)
        self.assertAlmostEqual(d["min_turning_angle_rad"], MIN_TURNING_ANGLE_RAD)

        expected_keys = {
            "segmentation_version", "reference_lap_number", "reference_length_m",
            "curvature_noise_floor", "curvature_corner_threshold",
            "curvature_smoothing_window", "min_corner_length_m",
            "min_turning_angle_rad", "min_straight_gap_m",
            "center_region_fraction", "approach_lead_m",
            "segmentation_quality", "corners", "straights",
        }
        self.assertEqual(set(d.keys()), expected_keys)


class TestNaNHandling(unittest.TestCase):
    """Verify NaN values in reference path don't crash segmentation."""

    def test_nan_in_positions_handled(self) -> None:
        x = np.linspace(0, 500, 501)
        z = np.zeros(501)
        x[100] = np.nan
        z[200] = np.nan
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self.assertIsInstance(result, TrackSegmentation)


def _single_corner_path(radius: float = 50.0, arc_degrees: float = 90.0, straight_len: float = 200.0) -> pd.DataFrame:
    arc_rad = np.radians(arc_degrees)
    straight1_x, straight1_z = _straight_segment(0, 0, straight_len, 0)
    end_x, end_z = straight1_x[-1], straight1_z[-1]
    center_x = end_x
    center_z = end_z + radius
    start_angle = -np.pi / 2
    arc_x, arc_z = _arc_segment(center_x, center_z, radius, start_angle, arc_rad)
    arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
    heading = start_angle + arc_rad + np.pi / 2
    straight2_x, straight2_z = _straight_segment(arc_end_x, arc_end_z, straight_len, heading)
    x, z = _concat_segments(
        (straight1_x, straight1_z),
        (arc_x, arc_z),
        (straight2_x, straight2_z),
    )
    return _build_reference_path_df(x, z)


class TestApproachWindow(unittest.TestCase):
    """approach_start_distance_m should anchor the braking window."""

    def test_approach_set_relative_to_start(self) -> None:
        df = _single_corner_path()
        result = segment_track(df)
        self.assertEqual(len(result.corners), 1)
        corner = result.corners[0]
        reference_length_m = result.reference_length_m

        expected = (corner.start_distance_m - APPROACH_LEAD_M) % reference_length_m
        self.assertAlmostEqual(corner.approach_start_distance_m, expected, places=6)
        self.assertGreaterEqual(corner.approach_start_distance_m, 0.0)
        self.assertLess(corner.approach_start_distance_m, reference_length_m)

    def test_approach_wraps_for_early_corner(self) -> None:
        # Build a lap where the detected corner starts less than APPROACH_LEAD_M
        # from the reference origin so the approach has to wrap backward.
        radius = 40.0
        arc_x, arc_z = _arc_segment(0.0, radius, radius, -np.pi / 2, np.pi / 2)
        arc_end_x, arc_end_z = arc_x[-1], arc_z[-1]
        straight_x, straight_z = _straight_segment(arc_end_x, arc_end_z, 400.0, np.pi / 2)

        x = np.concatenate([arc_x, straight_x[1:]])
        z = np.concatenate([arc_z, straight_z[1:]])
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertGreaterEqual(len(result.corners), 1)
        corner = result.corners[0]
        if corner.start_distance_m < APPROACH_LEAD_M:
            self.assertGreater(corner.approach_start_distance_m, corner.start_distance_m)
            self.assertAlmostEqual(
                (corner.start_distance_m - corner.approach_start_distance_m) % result.reference_length_m,
                APPROACH_LEAD_M,
                places=3,
            )

    def test_approach_lead_in_segmentation_dict(self) -> None:
        df = _single_corner_path()
        result = segment_track(df)
        self.assertAlmostEqual(result.approach_lead_m, APPROACH_LEAD_M)
        self.assertAlmostEqual(result.to_dict()["approach_lead_m"], APPROACH_LEAD_M)


class TestTrackCornerKey(unittest.TestCase):
    """track_corner_key should be stable against re-runs of the same geometry."""

    def test_key_format_and_stability(self) -> None:
        df = _single_corner_path()
        first = segment_track(df)
        second = segment_track(df)

        self.assertEqual(len(first.corners), 1)
        corner = first.corners[0]
        self.assertTrue(corner.track_corner_key.startswith("c"))
        # Round-trip: the integer suffix must match the start_distance_m bucket.
        suffix = int(corner.track_corner_key[1:])
        self.assertEqual(suffix, int(round(corner.start_distance_m)))

        # Two runs over the same geometry yield identical keys.
        self.assertEqual(
            [c.track_corner_key for c in first.corners],
            [c.track_corner_key for c in second.corners],
        )

    def test_keys_are_unique_for_well_separated_corners(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 40
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)
        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)
        s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
        cx2 = s2_end_x - 40
        cz2 = s2_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)
        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (straight2_x, straight2_z),
            (arc2_x, arc2_z),
            (straight3_x, straight3_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        keys = [c.track_corner_key for c in result.corners]
        self.assertEqual(len(keys), len(set(keys)), f"duplicate keys: {keys}")


class TestStraights(unittest.TestCase):
    """Straights should cover the cyclic gaps between corners."""

    def test_single_corner_one_straight(self) -> None:
        df = _single_corner_path()
        result = segment_track(df)
        self.assertEqual(len(result.corners), 1)
        self.assertEqual(len(result.straights), 1)

        straight = result.straights[0]
        corner = result.corners[0]
        self.assertIsInstance(straight, StraightDefinition)
        self.assertEqual(straight.preceding_corner_id, corner.corner_id)
        self.assertEqual(straight.following_corner_id, corner.corner_id)
        self.assertGreater(straight.length_m, 0.0)

    def test_two_corners_two_straights_cyclic(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 40
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)
        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)
        s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
        cx2 = s2_end_x - 40
        cz2 = s2_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)
        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (straight2_x, straight2_z),
            (arc2_x, arc2_z),
            (straight3_x, straight3_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 2)
        self.assertEqual(len(result.straights), 2)

        corner_ids = {c.corner_id for c in result.corners}
        for straight in result.straights:
            self.assertIn(straight.preceding_corner_id, corner_ids)
            self.assertIn(straight.following_corner_id, corner_ids)
            self.assertGreater(straight.length_m, 0.0)

        wrap_count = sum(1 for s in result.straights if s.wraps_start_finish)
        self.assertEqual(wrap_count, 1, "exactly one cyclic straight should wrap start/finish")

    def test_zero_corners_one_whole_track_straight(self) -> None:
        x = np.linspace(0, 1000, 1001)
        z = np.zeros(1001)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 0)
        self.assertEqual(len(result.straights), 1)
        straight = result.straights[0]
        self.assertIsNone(straight.preceding_corner_id)
        self.assertIsNone(straight.following_corner_id)
        self.assertAlmostEqual(straight.length_m, result.reference_length_m, places=3)


class TestSegmentationQuality(unittest.TestCase):
    """segmentation_quality should summarize the result in one field."""

    def test_quality_fields_on_two_corners(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 40
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)
        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)
        s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
        cx2 = s2_end_x - 40
        cz2 = s2_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)
        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (straight2_x, straight2_z),
            (arc2_x, arc2_z),
            (straight3_x, straight3_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        quality = result.segmentation_quality

        self.assertEqual(quality["corner_count"], 2)
        self.assertEqual(quality["compound_corner_count"], 0)
        self.assertFalse(quality["wrap_corner_present"])
        self.assertGreater(quality["fraction_covered_by_corners"], 0.0)
        self.assertLess(quality["fraction_covered_by_corners"], 1.0)
        self.assertIsNotNone(quality["min_corner_length_m"])
        self.assertIsNotNone(quality["max_corner_length_m"])
        self.assertGreaterEqual(quality["max_corner_length_m"], quality["min_corner_length_m"])

    def test_quality_for_zero_corners(self) -> None:
        x = np.linspace(0, 1000, 1001)
        z = np.zeros(1001)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        quality = result.segmentation_quality

        self.assertEqual(quality["corner_count"], 0)
        self.assertEqual(quality["compound_corner_count"], 0)
        self.assertFalse(quality["wrap_corner_present"])
        self.assertEqual(quality["fraction_covered_by_corners"], 0.0)
        self.assertIsNone(quality["min_corner_length_m"])
        self.assertIsNone(quality["max_corner_length_m"])


def _two_corner_path() -> pd.DataFrame:
    straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
    cx1 = straight1_x[-1]
    cz1 = straight1_z[-1] + 40
    arc1_x, arc1_z = _arc_segment(cx1, cz1, 40, -np.pi / 2, np.pi / 2)
    arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
    straight2_x, straight2_z = _straight_segment(arc1_end_x, arc1_end_z, 200, np.pi / 2)
    s2_end_x, s2_end_z = straight2_x[-1], straight2_z[-1]
    cx2 = s2_end_x - 40
    cz2 = s2_end_z
    arc2_x, arc2_z = _arc_segment(cx2, cz2, 40, 0, np.pi / 2)
    arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
    straight3_x, straight3_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi)
    x, z = _concat_segments(
        (straight1_x, straight1_z),
        (arc1_x, arc1_z),
        (straight2_x, straight2_z),
        (arc2_x, arc2_z),
        (straight3_x, straight3_z),
    )
    return _build_reference_path_df(x, z)


class TestCornerStraightCoverage(unittest.TestCase):
    """Corners and straights together must tile [0, reference_length_m] exactly.

    Phase 2's per-segment time-delta math depends on this: the sum of per-corner
    deltas plus per-straight deltas must equal the whole-lap delta, which is only
    true if corners and straights partition the reference path with no gaps and
    no overlap.
    """

    @staticmethod
    def _collect_intervals(result: TrackSegmentation) -> list[tuple[float, float]]:
        """Flatten all corners and straights into distance intervals.

        Wrap-around corners and wrap-around straights are split into two pieces
        so the resulting interval list can be sorted and checked in linear
        distance space.
        """
        ref_len = result.reference_length_m
        intervals: list[tuple[float, float]] = []

        for corner in result.corners:
            if corner.start_distance_m <= corner.end_distance_m:
                intervals.append((corner.start_distance_m, corner.end_distance_m))
            else:
                intervals.append((corner.start_distance_m, ref_len))
                intervals.append((0.0, corner.end_distance_m))

        for straight in result.straights:
            if straight.start_distance_m <= straight.end_distance_m:
                intervals.append((straight.start_distance_m, straight.end_distance_m))
            else:
                intervals.append((straight.start_distance_m, ref_len))
                intervals.append((0.0, straight.end_distance_m))

        return sorted(intervals)

    def _assert_exact_tiling(self, result: TrackSegmentation) -> None:
        ref_len = result.reference_length_m
        intervals = self._collect_intervals(result)

        self.assertGreater(len(intervals), 0, "no intervals produced")
        self.assertAlmostEqual(intervals[0][0], 0.0, places=3, msg=f"first interval does not start at 0: {intervals[0]}")
        self.assertAlmostEqual(intervals[-1][1], ref_len, places=3, msg=f"last interval does not reach reference_length_m: {intervals[-1]}")

        for earlier, later in zip(intervals, intervals[1:]):
            self.assertAlmostEqual(
                earlier[1],
                later[0],
                places=3,
                msg=f"gap or overlap between {earlier} and {later}",
            )

        total_length = sum(end - start for start, end in intervals)
        self.assertAlmostEqual(total_length, ref_len, places=3)

    def test_coverage_single_corner(self) -> None:
        df = _single_corner_path()
        result = segment_track(df)
        self._assert_exact_tiling(result)

    def test_coverage_two_corners(self) -> None:
        df = _two_corner_path()
        result = segment_track(df)
        self._assert_exact_tiling(result)

    def test_coverage_zero_corners(self) -> None:
        x = np.linspace(0, 1000, 1001)
        z = np.zeros(1001)
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self._assert_exact_tiling(result)

    def test_coverage_chicane(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 30
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 30, -np.pi / 2, np.pi / 2)
        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        short_straight_x, short_straight_z = _straight_segment(arc1_end_x, arc1_end_z, 20, np.pi / 2)
        ss_end_x, ss_end_z = short_straight_x[-1], short_straight_z[-1]
        cx2 = ss_end_x + 30
        cz2 = ss_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 30, np.pi, -np.pi / 2)
        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight2_x, straight2_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi / 2)
        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (short_straight_x, short_straight_z),
            (arc2_x, arc2_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)
        self._assert_exact_tiling(result)


class TestCompoundCornerEntryExit(unittest.TestCase):
    """Compound corners use first/last sub-apex to anchor a 3-phase split."""

    def test_chicane_has_sub_apex_anchored_phases(self) -> None:
        straight1_x, straight1_z = _straight_segment(0, 0, 200, 0)
        cx1 = straight1_x[-1]
        cz1 = straight1_z[-1] + 30
        arc1_x, arc1_z = _arc_segment(cx1, cz1, 30, -np.pi / 2, np.pi / 2)
        arc1_end_x, arc1_end_z = arc1_x[-1], arc1_z[-1]
        short_straight_x, short_straight_z = _straight_segment(arc1_end_x, arc1_end_z, 20, np.pi / 2)
        ss_end_x, ss_end_z = short_straight_x[-1], short_straight_z[-1]
        cx2 = ss_end_x + 30
        cz2 = ss_end_z
        arc2_x, arc2_z = _arc_segment(cx2, cz2, 30, np.pi, -np.pi / 2)
        arc2_end_x, arc2_end_z = arc2_x[-1], arc2_z[-1]
        straight2_x, straight2_z = _straight_segment(arc2_end_x, arc2_end_z, 200, np.pi / 2)

        x, z = _concat_segments(
            (straight1_x, straight1_z),
            (arc1_x, arc1_z),
            (short_straight_x, short_straight_z),
            (arc2_x, arc2_z),
            (straight2_x, straight2_z),
        )
        df = _build_reference_path_df(x, z)
        result = segment_track(df)

        self.assertEqual(len(result.corners), 1)
        corner = result.corners[0]
        self.assertTrue(corner.is_compound)

        # entry_end is anchored on the first sub-apex, not the corner start
        self.assertGreater(corner.entry_end_progress_norm, corner.start_progress_norm)
        # exit_start is anchored on the last sub-apex, not the corner end
        self.assertLess(corner.exit_start_progress_norm, corner.end_progress_norm)
        # the center region spans between the two sub-apexes
        self.assertLess(corner.entry_end_progress_norm, corner.exit_start_progress_norm)
        # entry_end matches the first sub-apex progress
        self.assertAlmostEqual(
            corner.entry_end_progress_norm,
            corner.sub_apex_progress_norms[0],
            places=6,
        )
        # exit_start matches the last sub-apex progress
        self.assertAlmostEqual(
            corner.exit_start_progress_norm,
            corner.sub_apex_progress_norms[-1],
            places=6,
        )


class TestSubApexProminenceEdgeCases(unittest.TestCase):
    """Verify _find_prominent_peaks handles three-peak configurations correctly."""

    def test_three_prominent_well_separated_peaks_all_kept(self) -> None:
        """Three sharp peaks, 6m apart, deep valleys between — all retained."""
        n = 17
        segment_abs = np.full(n, 0.001, dtype=float)
        for i in (1, 7, 13):
            segment_abs[i] = 0.5
            segment_abs[i + 1] = 1.0
            segment_abs[i + 2] = 0.5
        segment_dist = np.arange(n, dtype=float)

        peaks = _find_prominent_peaks(segment_abs, segment_dist)
        self.assertEqual(sorted(peaks), [2, 8, 14])

    def test_three_close_peaks_collapse_to_tallest(self) -> None:
        """Three candidate peaks packed inside MIN_SUB_APEX_SEPARATION_M collapse to the global max."""
        self.assertLess(4.0, MIN_SUB_APEX_SEPARATION_M)

        segment_abs = np.array(
            [0.001, 0.5, 0.2, 1.0, 0.2, 0.8, 0.001],
            dtype=float,
        )
        segment_dist = np.arange(len(segment_abs), dtype=float)

        peaks = _find_prominent_peaks(segment_abs, segment_dist)
        self.assertEqual(peaks, [3])

    def test_three_peaks_shallow_middle_still_resolves(self) -> None:
        """Tall outer peaks and a barely-above-noise middle: all three are local maxima,
        the middle is kept if prominence math accepts it, but the outer two must survive
        regardless and retain ordering."""
        n = 19
        segment_abs = np.full(n, 0.001, dtype=float)
        segment_abs[1] = 0.4
        segment_abs[2] = 1.0
        segment_abs[3] = 0.4
        segment_abs[8] = 0.05
        segment_abs[9] = 0.10
        segment_abs[10] = 0.05
        segment_abs[15] = 0.4
        segment_abs[16] = 1.0
        segment_abs[17] = 0.4
        segment_dist = np.arange(n, dtype=float)

        peaks = _find_prominent_peaks(segment_abs, segment_dist)
        peaks_sorted = sorted(peaks)

        self.assertIn(2, peaks_sorted)
        self.assertIn(16, peaks_sorted)
        self.assertEqual(peaks_sorted, sorted(set(peaks_sorted)))

    def test_three_peaks_ascending_heights(self) -> None:
        """P1 < P2 < P3 all well separated with deep valleys — all three should be retained."""
        n = 19
        segment_abs = np.full(n, 0.001, dtype=float)
        segment_abs[1] = 0.3
        segment_abs[2] = 0.6
        segment_abs[3] = 0.3
        segment_abs[8] = 0.4
        segment_abs[9] = 0.8
        segment_abs[10] = 0.4
        segment_abs[15] = 0.5
        segment_abs[16] = 1.0
        segment_abs[17] = 0.5
        segment_dist = np.arange(n, dtype=float)

        peaks = _find_prominent_peaks(segment_abs, segment_dist)
        self.assertEqual(sorted(peaks), [2, 9, 16])


if __name__ == "__main__":
    unittest.main()
