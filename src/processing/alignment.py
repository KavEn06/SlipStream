from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.core.config import DEFAULT_RESAMPLE_POINTS
from src.core.schemas import ALIGNED_LAP_COLUMNS, REFERENCE_PATH_COLUMNS


REFERENCE_POINT_SPACING_M = 1.0
REFERENCE_DEDUPE_DISTANCE_M = 0.25
REFERENCE_SMOOTHING_WINDOW = 5
MIN_REFERENCE_FINITE_XYZ_SAMPLES = 20
MIN_REFERENCE_FINITE_XYZ_RATIO = 0.80
MAX_REFERENCE_GAP_SPAN_RATIO = 0.08
FIRST_SAMPLE_SEARCH_WINDOW_M = 100.0
PROJECTION_BACKWARD_TOLERANCE_M = 5.0
PROJECTION_FORWARD_WINDOW_M = 60.0
MAX_PROJECTION_RESIDUAL_M = 20.0
MIN_ALIGNMENT_COVERAGE_SPAN_RATIO = 0.95
MAX_ALIGNMENT_FALLBACK_RATIO = 0.10
MAX_ALIGNMENT_LONGEST_FALLBACK_RUN_RATIO = 0.05

ALIGNMENT_METHOD_PROJECTION_ONLY = "projection_only"
ALIGNMENT_METHOD_HYBRID_FALLBACK = "hybrid_fallback"
ALIGNMENT_METHOD_UNALIGNED = "unaligned"
ALIGNMENT_STATUS_COMPLETE = "complete"
ALIGNMENT_STATUS_SKIPPED_NO_VALID_LAPS = "skipped_no_valid_laps"
ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY = "skipped_no_reference_geometry"


@dataclass(frozen=True)
class LapAlignmentDiagnostics:
    alignment_method: str
    is_usable: bool
    coverage_span_ratio: float | None
    bin_coverage_ratio: float | None
    fallback_ratio: float
    fallback_run_count: int
    longest_fallback_run_m: float
    longest_fallback_run_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "alignment_method": self.alignment_method,
            "is_usable": self.is_usable,
            "coverage_span_ratio": self.coverage_span_ratio,
            "bin_coverage_ratio": self.bin_coverage_ratio,
            "fallback_ratio": self.fallback_ratio,
            "fallback_run_count": self.fallback_run_count,
            "longest_fallback_run_m": self.longest_fallback_run_m,
            "longest_fallback_run_ratio": self.longest_fallback_run_ratio,
        }


@dataclass(frozen=True)
class SessionAlignmentArtifacts:
    aligned_laps: dict[int, pd.DataFrame]
    reference_path: pd.DataFrame | None
    metadata: dict[str, Any]


def select_reference_lap(processed_laps: dict[int, pd.DataFrame]) -> int | None:
    candidates: list[tuple[float, int]] = []
    for lap_number, processed_df in processed_laps.items():
        if _lap_is_valid(processed_df):
            lap_time_s = float(pd.to_numeric(processed_df["LapTimeS"], errors="coerce").iloc[0])
            if _can_build_reference_path(processed_df):
                candidates.append((lap_time_s, lap_number))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def build_reference_path(reference_lap_df: pd.DataFrame) -> pd.DataFrame:
    if reference_lap_df.empty:
        raise ValueError("Reference lap must contain samples")

    reference_lap_number, smoothed_points, cumulative_distance_m = _prepare_reference_path_inputs(reference_lap_df)
    reference_length_m = float(cumulative_distance_m[-1])

    reference_grid_m = _build_reference_grid(reference_length_m)
    reference_path_df = pd.DataFrame(
        {
            "ReferenceSampleIndex": np.arange(len(reference_grid_m), dtype=int),
            "ReferenceLapNumber": reference_lap_number,
            "PositionX": np.interp(reference_grid_m, cumulative_distance_m, smoothed_points[:, 0]),
            "PositionY": np.interp(reference_grid_m, cumulative_distance_m, smoothed_points[:, 1]),
            "PositionZ": np.interp(reference_grid_m, cumulative_distance_m, smoothed_points[:, 2]),
            "ReferenceDistanceM": reference_grid_m,
            "ReferenceProgressNorm": reference_grid_m / reference_length_m,
        }
    )
    return reference_path_df[REFERENCE_PATH_COLUMNS]


def align_processed_lap(
    processed_df: pd.DataFrame,
    reference_path_df: pd.DataFrame,
) -> tuple[pd.DataFrame, LapAlignmentDiagnostics]:
    if processed_df.empty or not _lap_is_valid(processed_df):
        return _build_unaligned_processed_lap(processed_df), _unaligned_diagnostics()

    reference_points = reference_path_df[["PositionX", "PositionY", "PositionZ"]].to_numpy(dtype=float)
    reference_distances = reference_path_df["ReferenceDistanceM"].to_numpy(dtype=float)
    reference_length_m = float(reference_distances[-1]) if len(reference_distances) else 0.0

    sample_points = processed_df[["PositionX", "PositionY", "PositionZ"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    normalized_distance = pd.to_numeric(processed_df["NormalizedDistance"], errors="coerce").fillna(0.0).to_numpy(dtype=float)

    track_progress_m = np.full(len(processed_df), np.nan)
    track_progress_norm = np.full(len(processed_df), np.nan)
    alignment_residual_m = np.full(len(processed_df), np.nan)
    alignment_used_fallback = np.zeros(len(processed_df), dtype=int)

    previous_progress_m: float | None = None
    for index, point in enumerate(sample_points):
        progress_m, residual_m, used_fallback = _align_sample(
            point=point,
            normalized_distance=float(normalized_distance[index]),
            reference_points=reference_points,
            reference_distances=reference_distances,
            reference_length_m=reference_length_m,
            previous_progress_m=previous_progress_m,
        )
        track_progress_m[index] = progress_m
        track_progress_norm[index] = 0.0 if reference_length_m <= 0 else progress_m / reference_length_m
        alignment_residual_m[index] = residual_m
        alignment_used_fallback[index] = int(used_fallback)
        previous_progress_m = progress_m

    aligned_df = processed_df.copy()
    aligned_df["TrackProgressM"] = track_progress_m
    aligned_df["TrackProgressNorm"] = track_progress_norm
    aligned_df["AlignmentResidualM"] = alignment_residual_m
    aligned_df["AlignmentUsedFallback"] = alignment_used_fallback

    diagnostics = _build_alignment_diagnostics(
        track_progress_m=track_progress_m,
        alignment_used_fallback=alignment_used_fallback,
        reference_length_m=reference_length_m,
    )
    aligned_df["AlignmentIsUsable"] = int(diagnostics.is_usable)
    return aligned_df, diagnostics


def align_session_laps(processed_laps: dict[int, pd.DataFrame]) -> SessionAlignmentArtifacts:
    normalized_laps = {lap_number: _build_unaligned_processed_lap(processed_df) for lap_number, processed_df in processed_laps.items()}
    if not any(_lap_is_valid(processed_df) for processed_df in processed_laps.values()):
        lap_metadata = {
            str(lap_number): _unaligned_diagnostics().to_dict()
            for lap_number in sorted(normalized_laps)
        }
        return SessionAlignmentArtifacts(
            aligned_laps=normalized_laps,
            reference_path=None,
            metadata={
                "status": ALIGNMENT_STATUS_SKIPPED_NO_VALID_LAPS,
                "reference_lap_number": None,
                "reference_length_m": None,
                "reference_spacing_m": None,
                "reference_path_file": None,
                "aligned_lap_count": 0,
                "excluded_lap_count": len(normalized_laps),
                "laps": lap_metadata,
            },
        )

    reference_lap_number = select_reference_lap(processed_laps)
    if reference_lap_number is None:
        lap_metadata = {
            str(lap_number): _unaligned_diagnostics().to_dict()
            for lap_number in sorted(normalized_laps)
        }
        return SessionAlignmentArtifacts(
            aligned_laps=normalized_laps,
            reference_path=None,
            metadata={
                "status": ALIGNMENT_STATUS_SKIPPED_NO_REFERENCE_GEOMETRY,
                "reference_lap_number": None,
                "reference_length_m": None,
                "reference_spacing_m": None,
                "reference_path_file": None,
                "aligned_lap_count": 0,
                "excluded_lap_count": len(normalized_laps),
                "laps": lap_metadata,
            },
        )

    reference_path_df = build_reference_path(processed_laps[reference_lap_number])
    lap_metadata: dict[str, dict[str, Any]] = {}
    aligned_laps: dict[int, pd.DataFrame] = {}
    aligned_lap_count = 0

    for lap_number in sorted(processed_laps):
        processed_df = processed_laps[lap_number]
        if _lap_is_valid(processed_df):
            aligned_df, diagnostics = align_processed_lap(processed_df, reference_path_df)
        else:
            aligned_df = _build_unaligned_processed_lap(processed_df)
            diagnostics = _unaligned_diagnostics()

        aligned_laps[lap_number] = aligned_df
        lap_metadata[str(lap_number)] = diagnostics.to_dict()
        if diagnostics.is_usable:
            aligned_lap_count += 1

    return SessionAlignmentArtifacts(
        aligned_laps=aligned_laps,
        reference_path=reference_path_df,
        metadata={
            "status": ALIGNMENT_STATUS_COMPLETE,
            "reference_lap_number": reference_lap_number,
            "reference_length_m": float(reference_path_df["ReferenceDistanceM"].iloc[-1]),
            "reference_spacing_m": REFERENCE_POINT_SPACING_M,
            "reference_path_file": "reference_path.csv",
            "aligned_lap_count": aligned_lap_count,
            "excluded_lap_count": len(aligned_laps) - aligned_lap_count,
            "laps": lap_metadata,
        },
    )


def resample_aligned_lap(
    processed_df: pd.DataFrame,
    num_points: int = DEFAULT_RESAMPLE_POINTS,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    if num_points < 2:
        raise ValueError("num_points must be at least 2")
    if processed_df.empty or int(pd.to_numeric(processed_df["AlignmentIsUsable"], errors="coerce").fillna(0).iloc[0]) != 1:
        raise ValueError("Processed lap must have AlignmentIsUsable=1")

    return _resample_dataframe_on_axis(
        processed_df=processed_df,
        axis_column="TrackProgressNorm",
        num_points=num_points,
        columns=columns or ALIGNED_LAP_COLUMNS,
    )


def _align_sample(
    point: np.ndarray,
    normalized_distance: float,
    reference_points: np.ndarray,
    reference_distances: np.ndarray,
    reference_length_m: float,
    previous_progress_m: float | None,
) -> tuple[float, float | None, bool]:
    fallback_progress_m = float(np.clip(normalized_distance, 0.0, 1.0)) * reference_length_m
    if previous_progress_m is not None:
        fallback_progress_m = max(fallback_progress_m, previous_progress_m)
    fallback_progress_m = float(np.clip(fallback_progress_m, 0.0, reference_length_m))

    if np.isnan(point).any():
        return fallback_progress_m, None, True

    if previous_progress_m is None:
        search_start_m = 0.0
        search_end_m = min(reference_length_m, FIRST_SAMPLE_SEARCH_WINDOW_M)
    else:
        search_start_m = max(0.0, previous_progress_m - PROJECTION_BACKWARD_TOLERANCE_M)
        search_end_m = min(reference_length_m, previous_progress_m + PROJECTION_FORWARD_WINDOW_M)

    projection_progress_m, projection_residual_m = _project_point_within_window(
        point=point,
        reference_points=reference_points,
        reference_distances=reference_distances,
        search_start_m=search_start_m,
        search_end_m=search_end_m,
    )

    used_fallback = projection_progress_m is None or projection_residual_m is None
    if used_fallback or projection_residual_m > MAX_PROJECTION_RESIDUAL_M:
        assigned_progress_m = fallback_progress_m
        used_fallback = True
    else:
        assigned_progress_m = float(projection_progress_m)
        if previous_progress_m is not None:
            assigned_progress_m = max(assigned_progress_m, previous_progress_m)
        assigned_progress_m = float(np.clip(assigned_progress_m, 0.0, reference_length_m))

    assigned_reference_point = _interpolate_reference_point(reference_points, reference_distances, assigned_progress_m)
    assigned_residual_m = float(np.linalg.norm(point - assigned_reference_point))
    return assigned_progress_m, assigned_residual_m, used_fallback


def _project_point_within_window(
    point: np.ndarray,
    reference_points: np.ndarray,
    reference_distances: np.ndarray,
    search_start_m: float,
    search_end_m: float,
) -> tuple[float | None, float | None]:
    if len(reference_points) < 2:
        return None, None

    max_segment_index = len(reference_points) - 2
    start_index = max(0, min(max_segment_index, int(np.floor(search_start_m))))
    end_index = max(0, min(max_segment_index, int(np.ceil(search_end_m))))
    if end_index < start_index:
        return None, None

    best_progress_m: float | None = None
    best_residual_m: float | None = None

    for segment_index in range(start_index, end_index + 1):
        segment_start_m = float(reference_distances[segment_index])
        segment_end_m = float(reference_distances[segment_index + 1])
        if segment_end_m < search_start_m or segment_start_m > search_end_m:
            continue

        candidate_progress_m = _project_point_onto_segment_progress(
            point=point,
            segment_start=reference_points[segment_index],
            segment_end=reference_points[segment_index + 1],
            segment_start_m=segment_start_m,
            segment_end_m=segment_end_m,
        )
        candidate_progress_m = float(np.clip(candidate_progress_m, search_start_m, search_end_m))
        candidate_point = _interpolate_reference_point(reference_points, reference_distances, candidate_progress_m)
        candidate_residual_m = float(np.linalg.norm(point - candidate_point))

        if best_residual_m is None or candidate_residual_m < best_residual_m:
            best_progress_m = candidate_progress_m
            best_residual_m = candidate_residual_m

    return best_progress_m, best_residual_m


def _project_point_onto_segment_progress(
    point: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    segment_start_m: float,
    segment_end_m: float,
) -> float:
    segment_vector = segment_end - segment_start
    segment_norm_sq = float(np.dot(segment_vector, segment_vector))
    if segment_norm_sq <= 0:
        return segment_start_m

    offset_vector = point - segment_start
    projection_ratio = float(np.dot(offset_vector, segment_vector) / segment_norm_sq)
    projection_ratio = float(np.clip(projection_ratio, 0.0, 1.0))
    return segment_start_m + (projection_ratio * (segment_end_m - segment_start_m))


def _build_alignment_diagnostics(
    track_progress_m: np.ndarray,
    alignment_used_fallback: np.ndarray,
    reference_length_m: float,
) -> LapAlignmentDiagnostics:
    coverage_span_ratio = _calculate_coverage_span_ratio(track_progress_m, reference_length_m)
    bin_coverage_ratio = _calculate_bin_coverage_ratio(track_progress_m, reference_length_m)
    fallback_ratio = float(alignment_used_fallback.mean()) if len(alignment_used_fallback) else 0.0
    fallback_run_count, longest_fallback_run_m = _calculate_fallback_runs(track_progress_m, alignment_used_fallback)
    longest_fallback_run_ratio = 0.0 if reference_length_m <= 0 else longest_fallback_run_m / reference_length_m
    alignment_method = (
        ALIGNMENT_METHOD_HYBRID_FALLBACK
        if bool(alignment_used_fallback.any())
        else ALIGNMENT_METHOD_PROJECTION_ONLY
    )
    is_usable = (
        coverage_span_ratio is not None
        and coverage_span_ratio >= MIN_ALIGNMENT_COVERAGE_SPAN_RATIO
        and fallback_ratio <= MAX_ALIGNMENT_FALLBACK_RATIO
        and longest_fallback_run_ratio <= MAX_ALIGNMENT_LONGEST_FALLBACK_RUN_RATIO
    )

    return LapAlignmentDiagnostics(
        alignment_method=alignment_method,
        is_usable=is_usable,
        coverage_span_ratio=coverage_span_ratio,
        bin_coverage_ratio=bin_coverage_ratio,
        fallback_ratio=fallback_ratio,
        fallback_run_count=fallback_run_count,
        longest_fallback_run_m=longest_fallback_run_m,
        longest_fallback_run_ratio=longest_fallback_run_ratio,
    )


def _calculate_coverage_span_ratio(track_progress_m: np.ndarray, reference_length_m: float) -> float | None:
    valid_progress = track_progress_m[~np.isnan(track_progress_m)]
    if reference_length_m <= 0 or len(valid_progress) == 0:
        return None
    return float((valid_progress.max() - valid_progress.min()) / reference_length_m)


def _calculate_bin_coverage_ratio(track_progress_m: np.ndarray, reference_length_m: float) -> float | None:
    valid_progress = track_progress_m[~np.isnan(track_progress_m)]
    if reference_length_m <= 0 or len(valid_progress) == 0:
        return None

    total_bins = max(1, int(np.floor(reference_length_m)) + 1)
    hit_bins = np.floor(np.clip(valid_progress, 0.0, reference_length_m)).astype(int)
    return float(len(np.unique(hit_bins)) / total_bins)


def _calculate_fallback_runs(track_progress_m: np.ndarray, alignment_used_fallback: np.ndarray) -> tuple[int, float]:
    fallback_run_count = 0
    longest_fallback_run_m = 0.0
    run_start_index: int | None = None

    for index, is_fallback in enumerate(alignment_used_fallback):
        if is_fallback and run_start_index is None:
            run_start_index = index
            fallback_run_count += 1
        elif not is_fallback and run_start_index is not None:
            longest_fallback_run_m = max(
                longest_fallback_run_m,
                _calculate_run_span_m(track_progress_m, run_start_index, index - 1),
            )
            run_start_index = None

    if run_start_index is not None:
        longest_fallback_run_m = max(
            longest_fallback_run_m,
            _calculate_run_span_m(track_progress_m, run_start_index, len(alignment_used_fallback) - 1),
        )

    return fallback_run_count, longest_fallback_run_m


def _calculate_run_span_m(track_progress_m: np.ndarray, start_index: int, end_index: int) -> float:
    start_progress_m = track_progress_m[start_index]
    end_progress_m = track_progress_m[end_index]
    if np.isnan(start_progress_m) or np.isnan(end_progress_m):
        return 0.0
    return float(max(0.0, end_progress_m - start_progress_m))


def _build_reference_keep_indices(points: np.ndarray) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))

    keep_indices = [0]
    for index in range(1, len(points) - 1):
        distance_from_last_kept = float(np.linalg.norm(points[index] - points[keep_indices[-1]]))
        if distance_from_last_kept >= REFERENCE_DEDUPE_DISTANCE_M:
            keep_indices.append(index)

    if keep_indices[-1] != len(points) - 1:
        keep_indices.append(len(points) - 1)
    return keep_indices


def _prepare_reference_path_inputs(reference_lap_df: pd.DataFrame) -> tuple[int, np.ndarray, np.ndarray]:
    ordered_df = reference_lap_df.sort_values("CumulativeDistanceM").reset_index(drop=True)
    reference_lap_number = int(pd.to_numeric(ordered_df["LapNumber"], errors="coerce").iloc[0])

    xyz_df = ordered_df[["PositionX", "PositionY", "PositionZ"]].apply(pd.to_numeric, errors="coerce")
    cumulative_distance_series = pd.to_numeric(ordered_df["CumulativeDistanceM"], errors="coerce").ffill()
    total_sample_count = len(ordered_df)
    finite_xyz_mask = xyz_df.notna().all(axis=1)
    xyz_df = xyz_df.loc[finite_xyz_mask].reset_index(drop=True)
    valid_progress = cumulative_distance_series.loc[finite_xyz_mask].reset_index(drop=True)
    finite_xyz_count = len(xyz_df)
    finite_xyz_ratio = 0.0 if total_sample_count == 0 else finite_xyz_count / total_sample_count
    if finite_xyz_count < MIN_REFERENCE_FINITE_XYZ_SAMPLES or finite_xyz_ratio < MIN_REFERENCE_FINITE_XYZ_RATIO:
        raise ValueError("Reference lap does not contain enough usable XYZ coverage")
    if _largest_reference_gap_ratio(valid_progress) > MAX_REFERENCE_GAP_SPAN_RATIO:
        raise ValueError("Reference lap contains a geometry gap that is too large to trust")

    keep_indices = _build_reference_keep_indices(xyz_df.to_numpy(dtype=float))
    cleaned_xyz_df = xyz_df.iloc[keep_indices].reset_index(drop=True)
    if len(cleaned_xyz_df) < 2:
        raise ValueError("Reference lap must retain at least two points after cleanup")

    smoothed_xyz_df = cleaned_xyz_df.rolling(
        window=REFERENCE_SMOOTHING_WINDOW,
        min_periods=1,
        center=True,
    ).mean()
    smoothed_points = smoothed_xyz_df.to_numpy(dtype=float)
    cumulative_distance_m = _cumulative_distance_from_points(smoothed_points)
    if len(cumulative_distance_m) == 0 or float(cumulative_distance_m[-1]) <= 0:
        raise ValueError("Reference lap must span positive distance")

    return reference_lap_number, smoothed_points, cumulative_distance_m


def _can_build_reference_path(processed_df: pd.DataFrame) -> bool:
    try:
        _prepare_reference_path_inputs(processed_df)
    except ValueError:
        return False
    return True


def _largest_reference_gap_ratio(valid_progress: pd.Series) -> float:
    numeric_progress = pd.to_numeric(valid_progress, errors="coerce").dropna().reset_index(drop=True)
    if len(numeric_progress) < 2:
        return 1.0

    total_span_m = float(numeric_progress.iloc[-1] - numeric_progress.iloc[0])
    if total_span_m <= 0:
        return 1.0

    max_gap_m = float(numeric_progress.diff().fillna(0.0).max())
    return max_gap_m / total_span_m


def _cumulative_distance_from_points(points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return np.array([], dtype=float)

    point_deltas = np.diff(points, axis=0, prepend=points[[0]])
    step_distance_m = np.sqrt((point_deltas**2).sum(axis=1))
    step_distance_m[0] = 0.0
    return np.cumsum(step_distance_m)


def _build_reference_grid(reference_length_m: float) -> np.ndarray:
    reference_grid_m = np.arange(0.0, reference_length_m, REFERENCE_POINT_SPACING_M, dtype=float)
    if len(reference_grid_m) == 0 or not np.isclose(reference_grid_m[-1], reference_length_m):
        reference_grid_m = np.append(reference_grid_m, reference_length_m)
    return reference_grid_m


def _interpolate_reference_point(
    reference_points: np.ndarray,
    reference_distances: np.ndarray,
    progress_m: float,
) -> np.ndarray:
    clamped_progress_m = float(np.clip(progress_m, 0.0, reference_distances[-1]))
    return np.array(
        [
            np.interp(clamped_progress_m, reference_distances, reference_points[:, 0]),
            np.interp(clamped_progress_m, reference_distances, reference_points[:, 1]),
            np.interp(clamped_progress_m, reference_distances, reference_points[:, 2]),
        ],
        dtype=float,
    )


def _lap_is_valid(processed_df: pd.DataFrame) -> bool:
    if processed_df.empty:
        return False
    lap_is_valid = pd.to_numeric(processed_df["LapIsValid"], errors="coerce").fillna(0).astype(int)
    return int(lap_is_valid.iloc[0]) == 1


def _build_unaligned_processed_lap(processed_df: pd.DataFrame) -> pd.DataFrame:
    unaligned_df = processed_df.copy()
    unaligned_df["TrackProgressM"] = np.nan
    unaligned_df["TrackProgressNorm"] = np.nan
    unaligned_df["AlignmentResidualM"] = np.nan
    unaligned_df["AlignmentUsedFallback"] = 0
    unaligned_df["AlignmentIsUsable"] = 0
    return unaligned_df


def _unaligned_diagnostics() -> LapAlignmentDiagnostics:
    return LapAlignmentDiagnostics(
        alignment_method=ALIGNMENT_METHOD_UNALIGNED,
        is_usable=False,
        coverage_span_ratio=None,
        bin_coverage_ratio=None,
        fallback_ratio=0.0,
        fallback_run_count=0,
        longest_fallback_run_m=0.0,
        longest_fallback_run_ratio=0.0,
    )


def _resample_dataframe_on_axis(
    processed_df: pd.DataFrame,
    axis_column: str,
    num_points: int,
    columns: list[str],
) -> pd.DataFrame:
    ordered_df = processed_df.sort_values(axis_column).drop_duplicates(subset=axis_column)
    grid = np.linspace(0.0, 1.0, num_points)
    resampled_df = pd.DataFrame({axis_column: grid})

    for column in columns:
        if column == axis_column:
            continue

        series = ordered_df[column]
        numeric_series = pd.to_numeric(series, errors="coerce")
        if series.dtype == bool or series.dropna().isin([0, 1]).all():
            interpolated = np.interp(grid, ordered_df[axis_column], numeric_series.astype(float))
            resampled_df[column] = np.rint(interpolated).astype(int)
        else:
            resampled_df[column] = np.interp(grid, ordered_df[axis_column], numeric_series.astype(float))

    return resampled_df
