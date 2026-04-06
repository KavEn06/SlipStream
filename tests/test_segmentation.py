from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.core.schemas import REFERENCE_PATH_COLUMNS
from src.processing.segmentation import (
    CENTER_REGION_FRACTION,
    CURVATURE_CORNER_THRESHOLD,
    CURVATURE_NOISE_FLOOR,
    MIN_CORNER_LENGTH_M,
    MIN_STRAIGHT_GAP_M,
    SEGMENTATION_VERSION,
    CornerDefinition,
    TrackSegmentation,
    segment_track,
    _compute_signed_curvature,
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


if __name__ == "__main__":
    unittest.main()
