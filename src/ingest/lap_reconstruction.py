from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.core.telemetry import CanonicalTelemetrySample


@dataclass(frozen=True)
class ReconstructedLap:
    lap_number: int
    start_index: int
    end_index: int
    started_native_ns: int
    ended_native_ns: int
    duration_s: float
    sample_count: int


@dataclass(frozen=True)
class LapReconstructionResult:
    method: str
    lap_numbers: List[Optional[int]]
    projected_progress: List[Optional[float]]
    laps: List[ReconstructedLap]
    quality_report: Dict[str, Any]


def _finite(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value)


def _heading_radians(value: Optional[float]) -> Optional[float]:
    if not _finite(value):
        return None
    heading = float(value)
    return math.radians(heading) if abs(heading) > 2.0 * math.pi else heading


def _progress_boundaries(
    samples: Sequence[CanonicalTelemetrySample],
    min_lap_duration_s: float,
) -> List[int]:
    values = [sample.lap_progress for sample in samples]
    finite = [float(value) for value in values if _finite(value)]
    if not finite or max(finite) - min(finite) < 0.5:
        return []
    boundaries = [0]
    last_boundary_time = samples[0].native_timestamp_ns
    for index in range(1, len(samples)):
        previous = values[index - 1]
        current = values[index]
        if not (_finite(previous) and _finite(current)):
            continue
        elapsed = (samples[index].native_timestamp_ns - last_boundary_time) / 1e9
        if float(previous) >= 0.8 and float(current) <= 0.2 and elapsed >= min_lap_duration_s:
            boundaries.append(index)
            last_boundary_time = samples[index].native_timestamp_ns
    return boundaries


def _geometry_boundaries(
    samples: Sequence[CanonicalTelemetrySample],
    min_lap_duration_s: float,
    crossing_half_width_m: float,
    minimum_heading_dot: float,
) -> Tuple[List[int], Dict[str, Any]]:
    positions = np.asarray(
        [
            [sample.position_x_m if _finite(sample.position_x_m) else np.nan,
             sample.position_z_m if _finite(sample.position_z_m) else np.nan]
            for sample in samples
        ],
        dtype=float,
    )
    finite_indices = np.flatnonzero(np.isfinite(positions).all(axis=1))
    if len(finite_indices) < 3:
        return [], {"reason": "insufficient_finite_positions"}

    origin_index = int(finite_indices[0])
    lookahead_candidates = finite_indices[finite_indices > origin_index]
    tangent = None
    for candidate_index in lookahead_candidates[:100]:
        delta = positions[int(candidate_index)] - positions[origin_index]
        norm = float(np.linalg.norm(delta))
        if norm >= 1.0:
            tangent = delta / norm
            break
    if tangent is None:
        return [], {"reason": "stationary_start"}

    normal = np.asarray([-tangent[1], tangent[0]])
    origin_heading = _heading_radians(samples[origin_index].heading_rad)
    relative = positions - positions[origin_index]
    signed_distance = np.sum(relative * tangent, axis=1)
    lateral_distance = np.abs(np.sum(relative * normal, axis=1))

    boundaries = [origin_index]
    last_crossing_ns = samples[origin_index].native_timestamp_ns
    rejected_direction = 0
    rejected_duration = 0
    for index in range(origin_index + 2, len(samples)):
        if not (
            np.isfinite(signed_distance[index - 1])
            and np.isfinite(signed_distance[index])
            and np.isfinite(lateral_distance[index])
        ):
            continue
        crossed_forward = signed_distance[index - 1] <= 0.0 < signed_distance[index]
        near_line = lateral_distance[index] <= crossing_half_width_m
        if not crossed_forward or not near_line:
            continue

        local_delta = positions[index] - positions[index - 1]
        norm = float(np.linalg.norm(local_delta))
        heading_dot = float(np.sum((local_delta / norm) * tangent)) if norm > 1e-6 else -1.0
        reported_heading = _heading_radians(samples[index].heading_rad)
        if origin_heading is not None and reported_heading is not None:
            reported_heading_dot = math.cos(reported_heading - origin_heading)
            heading_dot = min(heading_dot, reported_heading_dot)
        if heading_dot < minimum_heading_dot:
            rejected_direction += 1
            continue

        elapsed_s = (samples[index].native_timestamp_ns - last_crossing_ns) / 1e9
        if elapsed_s < min_lap_duration_s:
            rejected_duration += 1
            continue
        boundaries.append(index)
        last_crossing_ns = samples[index].native_timestamp_ns

    diagnostics = {
        "origin_index": origin_index,
        "origin_x_m": float(positions[origin_index, 0]),
        "origin_z_m": float(positions[origin_index, 1]),
        "tangent_x": float(tangent[0]),
        "tangent_z": float(tangent[1]),
        "reported_heading_available": origin_heading is not None,
        "crossing_half_width_m": crossing_half_width_m,
        "rejected_wrong_direction_crossings": rejected_direction,
        "rejected_short_crossings": rejected_duration,
    }
    return boundaries, diagnostics


def _laps_from_boundaries(
    samples: Sequence[CanonicalTelemetrySample],
    boundaries: Sequence[int],
    min_lap_duration_s: float,
    max_lap_duration_s: float,
    minimum_samples: int,
) -> Tuple[List[ReconstructedLap], List[Dict[str, Any]]]:
    laps = []
    rejected = []
    for start_index, end_index in zip(boundaries, boundaries[1:]):
        duration_s = (
            samples[end_index].native_timestamp_ns - samples[start_index].native_timestamp_ns
        ) / 1e9
        # Crossing samples belong to the following lap, so intervals are
        # half-open and every native sample has at most one lap assignment.
        sample_count = end_index - start_index
        reasons = []
        if duration_s < min_lap_duration_s:
            reasons.append("below_minimum_duration")
        if duration_s > max_lap_duration_s:
            reasons.append("above_maximum_duration")
        if sample_count < minimum_samples:
            reasons.append("too_few_samples")
        if reasons:
            rejected.append(
                {
                    "start_index": start_index,
                    "end_index": end_index,
                    "duration_s": duration_s,
                    "reasons": reasons,
                }
            )
            continue
        lap_number = len(laps) + 1
        laps.append(
            ReconstructedLap(
                lap_number=lap_number,
                start_index=start_index,
                end_index=end_index,
                started_native_ns=samples[start_index].native_timestamp_ns,
                ended_native_ns=samples[end_index].native_timestamp_ns,
                duration_s=duration_s,
                sample_count=sample_count,
            )
        )
    return laps, rejected


def _project_onto_reference(
    samples: Sequence[CanonicalTelemetrySample],
    laps: Sequence[ReconstructedLap],
    max_reference_points: int = 1200,
) -> List[Optional[float]]:
    projected: List[Optional[float]] = [None] * len(samples)
    if not laps:
        return projected

    reference_lap = max(laps, key=lambda lap: lap.sample_count)
    reference_indices = np.arange(reference_lap.start_index, reference_lap.end_index)
    if len(reference_indices) > max_reference_points:
        reference_indices = reference_indices[
            np.linspace(0, len(reference_indices) - 1, max_reference_points).astype(int)
        ]
    reference = np.asarray(
        [[samples[index].position_x_m, samples[index].position_z_m] for index in reference_indices],
        dtype=float,
    )
    finite_reference = np.isfinite(reference).all(axis=1)
    reference = reference[finite_reference]
    if len(reference) < 2:
        return projected

    step_distance = np.linalg.norm(np.diff(reference, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(step_distance)))
    if cumulative[-1] <= 0:
        return projected
    reference_progress = cumulative / cumulative[-1]

    for lap in laps:
        indices = np.arange(lap.start_index, lap.end_index)
        positions = np.asarray(
            [[samples[index].position_x_m, samples[index].position_z_m] for index in indices],
            dtype=float,
        )
        finite = np.isfinite(positions).all(axis=1)
        nearest_progress = np.full(len(indices), np.nan)
        finite_offsets = np.flatnonzero(finite)
        for block_start in range(0, len(finite_offsets), 2000):
            offsets = finite_offsets[block_start : block_start + 2000]
            delta = positions[offsets, None, :] - reference[None, :, :]
            nearest = np.argmin(np.sum(delta * delta, axis=2), axis=1)
            nearest_progress[offsets] = reference_progress[nearest]
        if finite.any():
            valid_values = nearest_progress[finite]
            nearest_progress[finite] = np.maximum.accumulate(valid_values)
            maximum = float(np.nanmax(nearest_progress))
            minimum = float(np.nanmin(nearest_progress))
            if maximum > minimum:
                nearest_progress = (nearest_progress - minimum) / (maximum - minimum)
        for index, value in zip(indices, nearest_progress):
            if np.isfinite(value):
                projected[int(index)] = min(max(float(value), 0.0), 1.0)
    return projected


def reconstruct_laps(
    samples: Sequence[CanonicalTelemetrySample],
    min_lap_duration_s: float = 30.0,
    max_lap_duration_s: float = 900.0,
    minimum_samples: int = 100,
    crossing_half_width_m: float = 12.0,
    minimum_heading_dot: float = 0.35,
) -> LapReconstructionResult:
    if len(samples) < 2:
        return LapReconstructionResult(
            method="none",
            lap_numbers=[None] * len(samples),
            projected_progress=[None] * len(samples),
            laps=[],
            quality_report={"status": "rejected", "reason": "insufficient_samples", "rows": len(samples)},
        )

    progress_values = [sample.lap_progress for sample in samples if _finite(sample.lap_progress)]
    completed_values = [sample.completed_laps for sample in samples if sample.completed_laps is not None]
    progress_constant = not progress_values or max(progress_values) - min(progress_values) < 0.5
    completed_constant = not completed_values or max(completed_values) == min(completed_values)

    boundaries = _progress_boundaries(samples, min_lap_duration_s)
    method = "reported_progress"
    diagnostics: Dict[str, Any] = {}
    if len(boundaries) < 2:
        method = "directed_position_crossing"
        boundaries, diagnostics = _geometry_boundaries(
            samples,
            min_lap_duration_s=min_lap_duration_s,
            crossing_half_width_m=crossing_half_width_m,
            minimum_heading_dot=minimum_heading_dot,
        )

    laps, rejected = _laps_from_boundaries(
        samples,
        boundaries,
        min_lap_duration_s=min_lap_duration_s,
        max_lap_duration_s=max_lap_duration_s,
        minimum_samples=minimum_samples,
    )
    lap_numbers: List[Optional[int]] = [None] * len(samples)
    for lap in laps:
        for index in range(lap.start_index, lap.end_index):
            lap_numbers[index] = lap.lap_number
    projected = _project_onto_reference(samples, laps)
    unlabeled = sum(lap_number is None for lap_number in lap_numbers)
    report = {
        "status": "accepted" if laps else "rejected",
        "method": method,
        "rows": len(samples),
        "lap_progress_constant_or_missing": progress_constant,
        "completed_laps_constant_or_missing": completed_constant,
        "candidate_boundaries": list(boundaries),
        "accepted_laps": len(laps),
        "rejected_laps": rejected,
        "unlabeled_partial_rows": unlabeled,
        "diagnostics": diagnostics,
    }
    if not laps:
        report["reason"] = "no_unambiguous_complete_laps"
    return LapReconstructionResult(
        method=method,
        lap_numbers=lap_numbers,
        projected_progress=projected,
        laps=laps,
        quality_report=report,
    )
