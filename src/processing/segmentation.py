from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


SEGMENTATION_VERSION = "2026.04-v1"

CURVATURE_SMOOTHING_WINDOW = 7
CURVATURE_NOISE_FLOOR = 0.002
CURVATURE_CORNER_THRESHOLD = 0.005
MIN_CORNER_LENGTH_M = 15.0
MIN_STRAIGHT_GAP_M = 40.0
CENTER_REGION_FRACTION = 0.30
MIN_REFERENCE_POINTS = 20
MIN_SUB_APEX_SEPARATION_M = 5.0
SUB_APEX_PROMINENCE_RATIO = 0.30


@dataclass(frozen=True)
class CornerDefinition:
    corner_id: int
    start_progress_norm: float
    end_progress_norm: float
    center_progress_norm: float
    start_distance_m: float
    end_distance_m: float
    center_distance_m: float
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
class TrackSegmentation:
    corners: list[CornerDefinition]
    reference_lap_number: int
    reference_length_m: float
    curvature_noise_floor: float
    curvature_corner_threshold: float
    curvature_smoothing_window: int
    min_corner_length_m: float
    min_straight_gap_m: float
    center_region_fraction: float
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
            "min_straight_gap_m": self.min_straight_gap_m,
            "center_region_fraction": self.center_region_fraction,
            "corners": [corner.to_dict() for corner in self.corners],
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
    regions = _merge_nearby_regions(regions, dist_m)
    regions = _merge_wrap_around(regions, dist_m, reference_length_m)

    corners = _build_corner_definitions(
        regions, kappa_smoothed, abs_kappa, dist_m, prog_norm,
    )

    return TrackSegmentation(
        corners=corners,
        reference_lap_number=ref_lap_number,
        reference_length_m=reference_length_m,
        curvature_noise_floor=CURVATURE_NOISE_FLOOR,
        curvature_corner_threshold=CURVATURE_CORNER_THRESHOLD,
        curvature_smoothing_window=CURVATURE_SMOOTHING_WINDOW,
        min_corner_length_m=MIN_CORNER_LENGTH_M,
        min_straight_gap_m=MIN_STRAIGHT_GAP_M,
        center_region_fraction=CENTER_REGION_FRACTION,
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
    return x, z, dist_m, prog_norm, ref_lap


def _compute_signed_curvature(
    x: np.ndarray, z: np.ndarray, dist_m: np.ndarray,
) -> np.ndarray:
    n = len(x)
    kappa = np.zeros(n, dtype=float)

    for i in range(1, n - 1):
        vp_x = x[i] - x[i - 1]
        vp_z = z[i] - z[i - 1]
        vn_x = x[i + 1] - x[i]
        vn_z = z[i + 1] - z[i]

        cross = vp_x * vn_z - vp_z * vn_x
        len_p = np.hypot(vp_x, vp_z)
        len_n = np.hypot(vn_x, vn_z)

        if len_p < 1e-9 or len_n < 1e-9:
            continue

        ds = (len_p + len_n) / 2.0
        kappa[i] = cross / (len_p * len_n * ds)

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
    regions: list[tuple[int, int]] = []
    start: int | None = None

    for i, val in enumerate(above):
        if val and start is None:
            start = i
        elif not val and start is not None:
            regions.append((start, i - 1))
            start = None

    if start is not None:
        regions.append((start, len(above) - 1))

    return regions


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
) -> list[CornerDefinition]:
    corners: list[CornerDefinition] = []

    for corner_index, (start_idx, end_idx) in enumerate(regions):
        is_wrap = start_idx > end_idx

        if is_wrap:
            segment_abs = np.concatenate([abs_kappa[start_idx:], abs_kappa[: end_idx + 1]])
            segment_signed = np.concatenate([kappa_smoothed[start_idx:], kappa_smoothed[: end_idx + 1]])
            segment_dist = np.concatenate([dist_m[start_idx:], dist_m[: end_idx + 1]])
            segment_prog = np.concatenate([prog_norm[start_idx:], prog_norm[: end_idx + 1]])
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
            reference_length = float(dist_m[-1])
            length = (reference_length - start_d) + end_d
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

        center_half_width_p = (CENTER_REGION_FRACTION / 2.0) * abs(end_p - start_p if not is_wrap else (1.0 - start_p) + end_p)
        entry_end_p = max(start_p, center_p - center_half_width_p) if not is_wrap else center_p - center_half_width_p
        exit_start_p = min(end_p, center_p + center_half_width_p) if not is_wrap else center_p + center_half_width_p

        if is_wrap:
            if entry_end_p < 0:
                entry_end_p += 1.0
            if exit_start_p > 1.0:
                exit_start_p -= 1.0

        is_compound = len(sub_apex_global) > 1
        sub_progs = [float(prog_norm[i]) for i in sub_apex_global]
        sub_dists = [float(dist_m[i]) for i in sub_apex_global]

        corners.append(CornerDefinition(
            corner_id=corner_index + 1,
            start_progress_norm=start_p,
            end_progress_norm=end_p,
            center_progress_norm=center_p,
            start_distance_m=start_d,
            end_distance_m=end_d,
            center_distance_m=center_d,
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
        reference_lap_number=ref_lap,
        reference_length_m=ref_length,
        curvature_noise_floor=CURVATURE_NOISE_FLOOR,
        curvature_corner_threshold=CURVATURE_CORNER_THRESHOLD,
        curvature_smoothing_window=CURVATURE_SMOOTHING_WINDOW,
        min_corner_length_m=MIN_CORNER_LENGTH_M,
        min_straight_gap_m=MIN_STRAIGHT_GAP_M,
        center_region_fraction=CENTER_REGION_FRACTION,
        segmentation_version=SEGMENTATION_VERSION,
    )
