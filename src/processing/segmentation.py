from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


SEGMENTATION_VERSION = "2026.04-v3"

CURVATURE_SMOOTHING_WINDOW = 7
CURVATURE_NOISE_FLOOR = 0.002
CURVATURE_CORNER_THRESHOLD = 0.005
MIN_CORNER_LENGTH_M = 15.0
MIN_STRAIGHT_GAP_M = 40.0
CENTER_REGION_FRACTION = 0.30
MIN_REFERENCE_POINTS = 20
MIN_TURNING_ANGLE_RAD = 0.26
MIN_SUB_APEX_SEPARATION_M = 30.0
SUB_APEX_PROMINENCE_RATIO = 0.50
APPROACH_LEAD_M = 80.0


@dataclass(frozen=True)
class CornerDefinition:
    corner_id: int
    track_corner_key: str
    start_progress_norm: float
    end_progress_norm: float
    center_progress_norm: float
    start_distance_m: float
    end_distance_m: float
    center_distance_m: float
    approach_start_distance_m: float
    entry_end_progress_norm: float
    exit_start_progress_norm: float
    length_m: float
    peak_curvature: float
    mean_curvature: float
    direction: str
    is_compound: bool
    sub_apex_progress_norms: list[float] = field(default_factory=list)
    sub_apex_distances_m: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StraightDefinition:
    straight_id: int
    start_distance_m: float
    end_distance_m: float
    length_m: float
    preceding_corner_id: int | None
    following_corner_id: int | None
    wraps_start_finish: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrackSegmentation:
    corners: list[CornerDefinition]
    straights: list[StraightDefinition]
    reference_lap_number: int
    reference_length_m: float
    curvature_noise_floor: float
    curvature_corner_threshold: float
    curvature_smoothing_window: int
    min_corner_length_m: float
    min_turning_angle_rad: float
    min_straight_gap_m: float
    center_region_fraction: float
    approach_lead_m: float
    segmentation_quality: dict[str, Any]
    segmentation_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "segmentation_version": self.segmentation_version,
            "reference_lap_number": self.reference_lap_number,
            "reference_length_m": self.reference_length_m,
            "curvature_noise_floor": self.curvature_noise_floor,
            "curvature_corner_threshold": self.curvature_corner_threshold,
            "curvature_smoothing_window": self.curvature_smoothing_window,
            "min_corner_length_m": self.min_corner_length_m,
            "min_turning_angle_rad": self.min_turning_angle_rad,
            "min_straight_gap_m": self.min_straight_gap_m,
            "center_region_fraction": self.center_region_fraction,
            "approach_lead_m": self.approach_lead_m,
            "segmentation_quality": self.segmentation_quality,
            "corners": [corner.to_dict() for corner in self.corners],
            "straights": [straight.to_dict() for straight in self.straights],
        }


def segment_track(reference_path_df: pd.DataFrame) -> TrackSegmentation:
    empty = _empty_segmentation(reference_path_df)

    if reference_path_df.empty or len(reference_path_df) < MIN_REFERENCE_POINTS:
        return empty

    x, z, dist_m, prog_norm, ref_lap_number = _extract_arrays(reference_path_df)
    if len(x) < MIN_REFERENCE_POINTS:
        return empty

    reference_length_m = float(dist_m[-1])
    if reference_length_m <= 0:
        return empty

    kappa_signed = _compute_signed_curvature(x, z, dist_m)
    kappa_smoothed = _smooth_curvature(kappa_signed)
    abs_kappa = np.abs(kappa_smoothed)

    regions = _find_above_floor_regions(abs_kappa)
    regions = _qualify_regions(regions, abs_kappa)
    regions = _filter_by_min_length(regions, dist_m)
    regions = _filter_by_turning_angle(regions, abs_kappa, dist_m)
    regions = _merge_nearby_regions(regions, dist_m)
    regions = _merge_wrap_around(regions, dist_m, reference_length_m)

    corners = _build_corner_definitions(
        regions, kappa_smoothed, abs_kappa, dist_m, prog_norm, reference_length_m,
    )
    straights = _build_straight_definitions(corners, reference_length_m)
    segmentation_quality = _build_segmentation_quality(corners, reference_length_m)

    return TrackSegmentation(
        corners=corners,
        straights=straights,
        reference_lap_number=ref_lap_number,
        reference_length_m=reference_length_m,
        curvature_noise_floor=CURVATURE_NOISE_FLOOR,
        curvature_corner_threshold=CURVATURE_CORNER_THRESHOLD,
        curvature_smoothing_window=CURVATURE_SMOOTHING_WINDOW,
        min_corner_length_m=MIN_CORNER_LENGTH_M,
        min_turning_angle_rad=MIN_TURNING_ANGLE_RAD,
        min_straight_gap_m=MIN_STRAIGHT_GAP_M,
        center_region_fraction=CENTER_REGION_FRACTION,
        approach_lead_m=APPROACH_LEAD_M,
        segmentation_quality=segmentation_quality,
        segmentation_version=SEGMENTATION_VERSION,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_arrays(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    x = pd.to_numeric(df["PositionX"], errors="coerce").to_numpy(dtype=float)
    z = pd.to_numeric(df["PositionZ"], errors="coerce").to_numpy(dtype=float)
    dist_m = pd.to_numeric(df["ReferenceDistanceM"], errors="coerce").to_numpy(dtype=float)
    prog_norm = pd.to_numeric(df["ReferenceProgressNorm"], errors="coerce").to_numpy(dtype=float)
    ref_lap = int(pd.to_numeric(df["ReferenceLapNumber"], errors="coerce").iloc[0])

    finite = np.isfinite(x) & np.isfinite(z) & np.isfinite(dist_m) & np.isfinite(prog_norm)
    if not finite.all():
        x = x[finite]
        z = z[finite]
        dist_m = dist_m[finite]
        prog_norm = prog_norm[finite]

    return x, z, dist_m, prog_norm, ref_lap


def _compute_signed_curvature(
    x: np.ndarray, z: np.ndarray, dist_m: np.ndarray,
) -> np.ndarray:
    n = len(x)
    kappa = np.zeros(n, dtype=float)
    if n < 3:
        return kappa

    dx = np.diff(x)
    dz = np.diff(z)

    vp_x = dx[:-1]
    vp_z = dz[:-1]
    vn_x = dx[1:]
    vn_z = dz[1:]

    cross = vp_x * vn_z - vp_z * vn_x
    len_p = np.hypot(vp_x, vp_z)
    len_n = np.hypot(vn_x, vn_z)
    ds = (len_p + len_n) / 2.0
    denom = len_p * len_n * ds

    valid = (len_p > 1e-9) & (len_n > 1e-9)
    safe_denom = np.where(valid, denom, 1.0)
    kappa[1:-1] = np.where(valid, cross / safe_denom, 0.0)

    return kappa


def _smooth_curvature(kappa: np.ndarray) -> np.ndarray:
    return (
        pd.Series(kappa)
        .rolling(window=CURVATURE_SMOOTHING_WINDOW, min_periods=1, center=True)
        .mean()
        .to_numpy()
    )


def _find_above_floor_regions(abs_kappa: np.ndarray) -> list[tuple[int, int]]:
    """Return (start_idx, end_idx) pairs for contiguous runs above the noise floor.

    end_idx is inclusive (the last index that is above the floor).
    """
    above = abs_kappa > CURVATURE_NOISE_FLOOR
    padded = np.concatenate(([False], above, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0] - 1
    return list(zip(starts.tolist(), ends.tolist()))


def _qualify_regions(
    regions: list[tuple[int, int]], abs_kappa: np.ndarray,
) -> list[tuple[int, int]]:
    """Keep only regions whose peak curvature exceeds the corner threshold."""
    return [
        (s, e)
        for s, e in regions
        if float(abs_kappa[s : e + 1].max()) > CURVATURE_CORNER_THRESHOLD
    ]


def _filter_by_min_length(
    regions: list[tuple[int, int]], dist_m: np.ndarray,
) -> list[tuple[int, int]]:
    return [
        (s, e)
        for s, e in regions
        if (dist_m[e] - dist_m[s]) >= MIN_CORNER_LENGTH_M
    ]


def _filter_by_turning_angle(
    regions: list[tuple[int, int]],
    abs_kappa: np.ndarray,
    dist_m: np.ndarray,
) -> list[tuple[int, int]]:
    """Keep regions whose total turning angle (∫|κ| ds) exceeds the threshold.

    Uses trapezoidal integration over the actual distance spacing rather than
    assuming a uniform grid, so the filter remains correct even if the
    reference path spacing is ever changed away from 1 m.
    """
    kept: list[tuple[int, int]] = []
    for s, e in regions:
        if e <= s:
            continue
        turning_angle = float(np.trapezoid(abs_kappa[s : e + 1], dist_m[s : e + 1]))
        if turning_angle >= MIN_TURNING_ANGLE_RAD:
            kept.append((s, e))
    return kept


def _merge_nearby_regions(
    regions: list[tuple[int, int]], dist_m: np.ndarray,
) -> list[tuple[int, int]]:
    if not regions:
        return []

    sorted_regions = sorted(regions, key=lambda r: r[0])
    merged: list[list[int]] = [list(sorted_regions[0])]

    for s, e in sorted_regions[1:]:
        gap = dist_m[s] - dist_m[merged[-1][1]]
        if gap < MIN_STRAIGHT_GAP_M:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    return [(m[0], m[1]) for m in merged]


def _merge_wrap_around(
    regions: list[tuple[int, int]],
    dist_m: np.ndarray,
    reference_length_m: float,
) -> list[tuple[int, int]]:
    if len(regions) < 2:
        return regions

    first_s, first_e = regions[0]
    last_s, last_e = regions[-1]

    gap_across = dist_m[first_s] + (reference_length_m - dist_m[last_e])
    if gap_across < MIN_STRAIGHT_GAP_M:
        merged_region = (last_s, first_e)
        return [merged_region] + regions[1:-1]

    return regions


def _find_sub_apexes(
    abs_kappa: np.ndarray, start_idx: int, end_idx: int, dist_m: np.ndarray,
) -> list[int]:
    """Find prominent local maxima of absolute curvature within a region.

    A local maximum must be separated from its neighbors by at least
    MIN_SUB_APEX_SEPARATION_M and have a meaningful valley between them
    (prominence filtering).
    """
    segment = abs_kappa[start_idx : end_idx + 1]
    segment_dist = dist_m[start_idx : end_idx + 1]
    result = _find_prominent_peaks(segment, segment_dist)
    return [start_idx + i for i in result]


def _build_corner_definitions(
    regions: list[tuple[int, int]],
    kappa_smoothed: np.ndarray,
    abs_kappa: np.ndarray,
    dist_m: np.ndarray,
    prog_norm: np.ndarray,
    reference_length_m: float,
) -> list[CornerDefinition]:
    corners: list[CornerDefinition] = []

    for corner_index, (start_idx, end_idx) in enumerate(regions):
        is_wrap = start_idx > end_idx

        if is_wrap:
            segment_abs = np.concatenate([abs_kappa[start_idx:], abs_kappa[: end_idx + 1]])
            segment_dist = np.concatenate([
                dist_m[start_idx:],
                dist_m[: end_idx + 1] + reference_length_m,
            ])
            n_tail = len(abs_kappa) - start_idx

            center_local = int(np.argmax(segment_abs))
            if center_local < n_tail:
                center_idx = start_idx + center_local
            else:
                center_idx = center_local - n_tail

            sub_apex_global: list[int] = []
            local_maxima = _find_sub_apexes_from_segment(segment_abs, segment_dist)
            for lm in local_maxima:
                if lm < n_tail:
                    sub_apex_global.append(start_idx + lm)
                else:
                    sub_apex_global.append(lm - n_tail)

            start_d = float(dist_m[start_idx])
            end_d = float(dist_m[end_idx])
            length = (reference_length_m - start_d) + end_d
        else:
            segment_abs = abs_kappa[start_idx : end_idx + 1]

            center_local = int(np.argmax(segment_abs))
            center_idx = start_idx + center_local

            sub_apex_indices = _find_sub_apexes(abs_kappa, start_idx, end_idx, dist_m)
            sub_apex_global = sub_apex_indices

            start_d = float(dist_m[start_idx])
            end_d = float(dist_m[end_idx])
            length = end_d - start_d

        peak_curv = float(abs_kappa[center_idx])
        mean_curv = float(np.mean(segment_abs)) if len(segment_abs) > 0 else 0.0
        direction = "left" if kappa_smoothed[center_idx] > 0 else "right"

        start_p = float(prog_norm[start_idx])
        end_p = float(prog_norm[end_idx])
        center_p = float(prog_norm[center_idx])
        center_d = float(dist_m[center_idx])

        is_compound = len(sub_apex_global) > 1

        if is_compound:
            # Anchor entry/exit on the first and last sub-apex so every corner
            # has a meaningful three-phase split:
            #   entry  = start → first sub-apex (approach + turn-in)
            #   center = first sub-apex → last sub-apex (multi-peak zone)
            #   exit   = last sub-apex → end (application of power out)
            entry_end_p = float(prog_norm[sub_apex_global[0]])
            exit_start_p = float(prog_norm[sub_apex_global[-1]])
        else:
            corner_width_p = (1.0 - start_p) + end_p if is_wrap else end_p - start_p
            center_half_width_p = (CENTER_REGION_FRACTION / 2.0) * corner_width_p

            if is_wrap:
                entry_end_p = center_p - center_half_width_p
                exit_start_p = center_p + center_half_width_p
                if entry_end_p < 0:
                    entry_end_p += 1.0
                if exit_start_p > 1.0:
                    exit_start_p -= 1.0
            else:
                entry_end_p = max(start_p, center_p - center_half_width_p)
                exit_start_p = min(end_p, center_p + center_half_width_p)

        sub_progs = [float(prog_norm[i]) for i in sub_apex_global]
        sub_dists = [float(dist_m[i]) for i in sub_apex_global]

        track_corner_key = f"c{int(round(start_d))}"
        approach_start_d = _approach_start_distance_m(start_d, reference_length_m)

        corners.append(CornerDefinition(
            corner_id=corner_index + 1,
            track_corner_key=track_corner_key,
            start_progress_norm=start_p,
            end_progress_norm=end_p,
            center_progress_norm=center_p,
            start_distance_m=start_d,
            end_distance_m=end_d,
            center_distance_m=center_d,
            approach_start_distance_m=approach_start_d,
            entry_end_progress_norm=entry_end_p,
            exit_start_progress_norm=exit_start_p,
            length_m=length,
            peak_curvature=peak_curv,
            mean_curvature=mean_curv,
            direction=direction,
            is_compound=is_compound,
            sub_apex_progress_norms=sub_progs,
            sub_apex_distances_m=sub_dists,
        ))

    return corners


def _approach_start_distance_m(start_distance_m: float, reference_length_m: float) -> float:
    """Where the braking approach to a corner begins, in reference-meters.

    Wraps around the start-finish line so a corner near the beginning of the
    lap still has a meaningful brake window pointing backward through the
    previous lap section.
    """
    if reference_length_m <= 0:
        return max(0.0, start_distance_m - APPROACH_LEAD_M)
    return float((start_distance_m - APPROACH_LEAD_M) % reference_length_m)


def _build_straight_definitions(
    corners: list[CornerDefinition],
    reference_length_m: float,
) -> list[StraightDefinition]:
    """Materialize straights as the cyclic gaps between consecutive corners.

    For a closed track with N corners we emit N straights; each straight
    follows a corner and precedes the next one. If no corners were detected,
    the entire reference path is a single straight. This keeps the invariant
    "corners + straights cover the whole track" intact.
    """
    if reference_length_m <= 0:
        return []

    if not corners:
        return [
            StraightDefinition(
                straight_id=1,
                start_distance_m=0.0,
                end_distance_m=reference_length_m,
                length_m=reference_length_m,
                preceding_corner_id=None,
                following_corner_id=None,
                wraps_start_finish=False,
            )
        ]

    straights: list[StraightDefinition] = []
    n = len(corners)
    for i, corner in enumerate(corners):
        next_corner = corners[(i + 1) % n]
        start_d = corner.end_distance_m
        end_d = next_corner.start_distance_m

        if end_d >= start_d:
            length = end_d - start_d
            wraps = False
        else:
            length = (reference_length_m - start_d) + end_d
            wraps = True

        if length <= 0:
            continue

        straights.append(
            StraightDefinition(
                straight_id=len(straights) + 1,
                start_distance_m=start_d,
                end_distance_m=end_d,
                length_m=length,
                preceding_corner_id=corner.corner_id,
                following_corner_id=next_corner.corner_id,
                wraps_start_finish=wraps,
            )
        )

    return straights


def _build_segmentation_quality(
    corners: list[CornerDefinition],
    reference_length_m: float,
) -> dict[str, Any]:
    """One-shot trust signal so downstream code can decide whether to act."""
    if reference_length_m <= 0:
        return {
            "corner_count": 0,
            "compound_corner_count": 0,
            "wrap_corner_present": False,
            "fraction_covered_by_corners": 0.0,
            "min_corner_length_m": None,
            "max_corner_length_m": None,
        }

    lengths = [float(corner.length_m) for corner in corners]
    total_corner_length = sum(lengths)
    fraction_covered = total_corner_length / reference_length_m if reference_length_m > 0 else 0.0
    wrap_present = any(
        corner.start_progress_norm > corner.end_progress_norm for corner in corners
    )
    compound_count = sum(1 for corner in corners if corner.is_compound)

    return {
        "corner_count": len(corners),
        "compound_corner_count": compound_count,
        "wrap_corner_present": wrap_present,
        "fraction_covered_by_corners": float(fraction_covered),
        "min_corner_length_m": float(min(lengths)) if lengths else None,
        "max_corner_length_m": float(max(lengths)) if lengths else None,
    }


def _find_sub_apexes_from_segment(
    segment_abs: np.ndarray, segment_dist: np.ndarray,
) -> list[int]:
    """Find prominent local maxima within an already-extracted segment array."""
    return _find_prominent_peaks(segment_abs, segment_dist)


def _find_prominent_peaks(
    segment_abs: np.ndarray, segment_dist: np.ndarray,
) -> list[int]:
    """Find local maxima with sufficient prominence and separation.

    Two peaks are considered distinct only if the minimum curvature between
    them drops by at least SUB_APEX_PROMINENCE_RATIO relative to the lower
    peak.
    """
    if len(segment_abs) < 3:
        return [int(np.argmax(segment_abs))]

    candidates: list[int] = []
    for i in range(1, len(segment_abs) - 1):
        if segment_abs[i] >= segment_abs[i - 1] and segment_abs[i] >= segment_abs[i + 1]:
            if segment_abs[i] > CURVATURE_NOISE_FLOOR:
                candidates.append(i)

    if not candidates:
        return [int(np.argmax(segment_abs))]

    spaced: list[int] = [candidates[0]]
    for idx in candidates[1:]:
        if (segment_dist[idx] - segment_dist[spaced[-1]]) >= MIN_SUB_APEX_SEPARATION_M:
            spaced.append(idx)
        elif segment_abs[idx] > segment_abs[spaced[-1]]:
            spaced[-1] = idx

    if len(spaced) < 2:
        return spaced

    prominent: list[int] = [spaced[0]]
    for idx in spaced[1:]:
        prev_idx = prominent[-1]
        lo = min(prev_idx, idx)
        hi = max(prev_idx, idx)
        valley = float(segment_abs[lo:hi + 1].min())
        lower_peak = min(segment_abs[prev_idx], segment_abs[idx])
        drop = 1.0 - (valley / lower_peak) if lower_peak > 0 else 0.0

        if drop >= SUB_APEX_PROMINENCE_RATIO:
            prominent.append(idx)
        elif segment_abs[idx] > segment_abs[prev_idx]:
            prominent[-1] = idx

    return prominent


def _empty_segmentation(reference_path_df: pd.DataFrame) -> TrackSegmentation:
    ref_lap = 0
    ref_length = 0.0
    if not reference_path_df.empty:
        ref_lap_series = pd.to_numeric(
            reference_path_df["ReferenceLapNumber"], errors="coerce"
        )
        if not ref_lap_series.dropna().empty:
            ref_lap = int(ref_lap_series.iloc[0])
        dist_series = pd.to_numeric(
            reference_path_df["ReferenceDistanceM"], errors="coerce"
        )
        if not dist_series.dropna().empty:
            ref_length = float(dist_series.iloc[-1])

    return TrackSegmentation(
        corners=[],
        straights=_build_straight_definitions([], ref_length),
        reference_lap_number=ref_lap,
        reference_length_m=ref_length,
        curvature_noise_floor=CURVATURE_NOISE_FLOOR,
        curvature_corner_threshold=CURVATURE_CORNER_THRESHOLD,
        curvature_smoothing_window=CURVATURE_SMOOTHING_WINDOW,
        min_corner_length_m=MIN_CORNER_LENGTH_M,
        min_turning_angle_rad=MIN_TURNING_ANGLE_RAD,
        min_straight_gap_m=MIN_STRAIGHT_GAP_M,
        center_region_fraction=CENTER_REGION_FRACTION,
        approach_lead_m=APPROACH_LEAD_M,
        segmentation_quality=_build_segmentation_quality([], ref_length),
        segmentation_version=SEGMENTATION_VERSION,
    )
