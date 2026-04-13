"""Per-lap, per-corner record extraction.

This module is the foundation of the corner analysis layer. It takes a
resampled aligned lap (400 points on ``TrackProgressNorm``) plus the
session's ``TrackSegmentation`` and produces structured records describing
what happened inside each corner and each straight.

Nothing in this module compares laps. Comparison lives in ``detectors.py``.
The records produced here are the stable numerical input to every downstream
layer of the analysis pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.analysis.constants import (
    BRAKE_ACTIVE_THRESHOLD,
    BRAKE_INIT_THRESHOLD,
    BRAKE_PRESENCE_THRESHOLD,
    BRAKE_RELEASE_THRESHOLD,
    FULL_THROTTLE_THRESHOLD,
    STEERING_ACTIVE_THRESHOLD,
    THROTTLE_DIP_LOWER,
    THROTTLE_DIP_UPPER,
    THROTTLE_PICKUP_THRESHOLD,
    STEERING_NOISE_THRESHOLD,
    TRAIL_BRAKE_CLEAR_THRESHOLD,
)
from src.processing.segmentation import CornerDefinition, StraightDefinition, TrackSegmentation


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseMetrics:
    """Summary of one phase (entry, apex, or exit) inside a corner."""

    time_s: float
    entry_speed_kph: float
    exit_speed_kph: float
    min_speed_kph: float
    min_speed_progress_norm: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrakeEvent:
    """One braking action inside a corner window.

    ``trail_brake_depth_m`` is the distance from the brake release point to
    the min-speed (apex) point.  Positive means the brake was held past the
    apex; negative means it was released before the apex.
    """

    initiation_progress_norm: float
    initiation_distance_m: float
    initiation_speed_kph: float
    release_progress_norm: float
    release_distance_m: float
    release_brake_value: float
    release_rate_per_s: float
    peak_brake: float
    peak_decel_mps2: float
    avg_decel_mps2: float
    trail_brake_end_progress_norm: float
    trail_brake_depth_m: float
    brake_steering_overlap_m: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThrottleEvent:
    """Throttle re-application on corner exit."""

    pickup_progress_norm: float
    pickup_speed_kph: float
    pickup_distance_from_min_speed_m: float
    full_throttle_progress_norm: float | None
    exit_full_throttle_fraction: float
    throttle_dip_detected: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CornerRecord:
    """Everything the analysis layer knows about a single (lap, corner)."""

    lap_number: int
    corner_id: int
    is_compound: bool
    alignment_quality_m: float
    alignment_used_fallback: bool
    corner_time_s: float
    entry: PhaseMetrics
    apex: PhaseMetrics
    exit: PhaseMetrics
    brake: BrakeEvent | None
    throttle: ThrottleEvent | None
    coasting_distance_m: float
    gear_at_min_speed: int | None
    min_speed_kph: float
    min_speed_progress_norm: float
    corner_end_progress_norm: float
    exit_steering_correction_count: int
    sub_corner_records: list["CornerRecord"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "corner_id": self.corner_id,
            "is_compound": self.is_compound,
            "alignment_quality_m": self.alignment_quality_m,
            "alignment_used_fallback": self.alignment_used_fallback,
            "corner_time_s": self.corner_time_s,
            "entry": self.entry.to_dict(),
            "apex": self.apex.to_dict(),
            "exit": self.exit.to_dict(),
            "brake": self.brake.to_dict() if self.brake is not None else None,
            "throttle": self.throttle.to_dict() if self.throttle is not None else None,
            "coasting_distance_m": self.coasting_distance_m,
            "gear_at_min_speed": self.gear_at_min_speed,
            "min_speed_kph": self.min_speed_kph,
            "min_speed_progress_norm": self.min_speed_progress_norm,
            "corner_end_progress_norm": self.corner_end_progress_norm,
            "exit_steering_correction_count": self.exit_steering_correction_count,
            "sub_corner_records": [record.to_dict() for record in self.sub_corner_records],
        }


@dataclass(frozen=True)
class StraightRecord:
    """Thin record for the straight connecting two corners."""

    straight_id: int
    lap_number: int
    time_s: float
    entry_speed_kph: float
    exit_speed_kph: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_corner_records(
    resampled_lap: pd.DataFrame,
    processed_lap: pd.DataFrame,
    segmentation: TrackSegmentation,
    lap_number: int,
) -> tuple[list[CornerRecord], list[StraightRecord]]:
    """Build corner and straight records for a single lap.

    Parameters
    ----------
    resampled_lap:
        400-point resampled lap produced by ``resample_aligned_lap``.
    processed_lap:
        The pre-resample processed lap (with ``AlignmentResidualM`` and
        ``AlignmentUsedFallback`` columns). Used only for per-corner
        alignment-quality lookups.
    segmentation:
        The session's ``TrackSegmentation``.
    lap_number:
        Lap number recorded on the resulting records.

    Returns
    -------
    ``(corner_records, straight_records)`` — one entry per corner and one per
    straight. The straight list may be shorter than the corner list if the
    segmentation has fewer straights (e.g. edge cases around wrap-around).
    """
    arrays = _LapArrays.from_resampled(resampled_lap)
    processed_arrays = _ProcessedArrays.from_processed(processed_lap)
    reference_length_m = float(segmentation.reference_length_m)

    corner_records: list[CornerRecord] = []
    for corner in segmentation.corners:
        corner_records.append(
            _build_corner_record(
                corner=corner,
                arrays=arrays,
                processed_arrays=processed_arrays,
                lap_number=lap_number,
                reference_length_m=reference_length_m,
            )
        )

    straight_records: list[StraightRecord] = []
    for straight in segmentation.straights:
        straight_records.append(
            _build_straight_record(
                straight=straight,
                arrays=arrays,
                lap_number=lap_number,
                reference_length_m=reference_length_m,
            )
        )

    return corner_records, straight_records


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LapArrays:
    """Numpy arrays extracted from a resampled lap, pre-sorted on progress."""

    progress_norm: np.ndarray
    progress_m: np.ndarray
    elapsed_s: np.ndarray
    speed_kph: np.ndarray
    throttle: np.ndarray
    brake: np.ndarray
    steering: np.ndarray
    gear: np.ndarray
    long_accel: np.ndarray
    is_coasting: np.ndarray

    @classmethod
    def from_resampled(cls, df: pd.DataFrame) -> "_LapArrays":
        if df.empty:
            raise ValueError("Resampled lap must contain samples")

        ordered = df.sort_values("TrackProgressNorm").reset_index(drop=True)
        return cls(
            progress_norm=pd.to_numeric(ordered["TrackProgressNorm"], errors="coerce").to_numpy(dtype=float),
            progress_m=pd.to_numeric(ordered["TrackProgressM"], errors="coerce").to_numpy(dtype=float),
            elapsed_s=pd.to_numeric(ordered["ElapsedTimeS"], errors="coerce").to_numpy(dtype=float),
            speed_kph=pd.to_numeric(ordered["SpeedKph"], errors="coerce").to_numpy(dtype=float),
            throttle=pd.to_numeric(ordered["Throttle"], errors="coerce").to_numpy(dtype=float),
            brake=pd.to_numeric(ordered["Brake"], errors="coerce").to_numpy(dtype=float),
            steering=pd.to_numeric(ordered["Steering"], errors="coerce").to_numpy(dtype=float),
            gear=pd.to_numeric(ordered["Gear"], errors="coerce").to_numpy(dtype=float),
            long_accel=pd.to_numeric(ordered["LongitudinalAccelMps2"], errors="coerce").to_numpy(dtype=float),
            is_coasting=pd.to_numeric(ordered["IsCoasting"], errors="coerce").to_numpy(dtype=float),
        )


@dataclass(frozen=True)
class _ProcessedArrays:
    """Minimal slice of the pre-resample lap for alignment quality lookups."""

    progress_norm: np.ndarray
    residual_m: np.ndarray
    used_fallback: np.ndarray

    @classmethod
    def from_processed(cls, df: pd.DataFrame) -> "_ProcessedArrays":
        if df.empty:
            return cls(
                progress_norm=np.zeros(0, dtype=float),
                residual_m=np.zeros(0, dtype=float),
                used_fallback=np.zeros(0, dtype=int),
            )
        return cls(
            progress_norm=pd.to_numeric(df["TrackProgressNorm"], errors="coerce").to_numpy(dtype=float),
            residual_m=pd.to_numeric(df["AlignmentResidualM"], errors="coerce").to_numpy(dtype=float),
            used_fallback=pd.to_numeric(df["AlignmentUsedFallback"], errors="coerce").fillna(0).to_numpy(dtype=int),
        )


# ---------------------------------------------------------------------------
# Straight records
# ---------------------------------------------------------------------------


def _build_straight_record(
    straight: StraightDefinition,
    arrays: _LapArrays,
    lap_number: int,
    reference_length_m: float,
) -> StraightRecord:
    start_norm = _distance_to_progress(straight.start_distance_m, reference_length_m)
    end_norm = _distance_to_progress(straight.end_distance_m, reference_length_m)

    time_s = _time_through_window(arrays, start_norm, end_norm)
    entry_speed = _speed_at_progress(arrays, start_norm)
    exit_speed = _speed_at_progress(arrays, end_norm)

    return StraightRecord(
        straight_id=straight.straight_id,
        lap_number=lap_number,
        time_s=float(time_s),
        entry_speed_kph=float(entry_speed),
        exit_speed_kph=float(exit_speed),
    )


# ---------------------------------------------------------------------------
# Corner records
# ---------------------------------------------------------------------------


def _build_corner_record(
    corner: CornerDefinition,
    arrays: _LapArrays,
    processed_arrays: _ProcessedArrays,
    lap_number: int,
    reference_length_m: float,
) -> CornerRecord:
    start_p = corner.start_progress_norm
    end_p = corner.end_progress_norm

    corner_mask = _progress_window_mask(arrays.progress_norm, start_p, end_p)
    brake_search_end_m = corner.center_distance_m if corner.center_distance_m > 0 else corner.start_distance_m
    brake_search_start_p = _distance_to_progress(corner.approach_start_distance_m, reference_length_m)
    brake_search_end_p = _distance_to_progress(brake_search_end_m, reference_length_m)
    brake_search_mask = _progress_window_mask(arrays.progress_norm, brake_search_start_p, brake_search_end_p)

    corner_time_s = _time_through_window(arrays, start_p, end_p)

    # Effective apex: min-speed point inside the corner slice. For wrap-around
    # corners the slice is made contiguous by _contiguous_slice.
    corner_slice_idx = np.where(corner_mask)[0]
    if corner_slice_idx.size == 0:
        # Degenerate — corner boundary missed the grid. Fall back to interp.
        return _degenerate_corner_record(corner, arrays, processed_arrays, lap_number, reference_length_m)

    min_speed_local = int(np.argmin(arrays.speed_kph[corner_slice_idx]))
    min_speed_idx = int(corner_slice_idx[min_speed_local])
    min_speed_kph = float(arrays.speed_kph[min_speed_idx])
    min_speed_progress_norm = float(arrays.progress_norm[min_speed_idx])

    # Gear at min speed (rounded from the interpolated numeric gear value).
    gear_value = arrays.gear[min_speed_idx]
    gear_at_min_speed: int | None = None if np.isnan(gear_value) else int(round(float(gear_value)))

    # Phase boundaries. For compound corners segmentation collapses entry and
    # exit to zero-width, so we synthesize phase slices around the effective
    # apex using the corner's overall width as a sensible default.
    entry_end_p, exit_start_p = _resolve_phase_boundaries(corner, min_speed_progress_norm)

    entry_metrics = _phase_metrics(arrays, start_p, entry_end_p)
    apex_metrics = _phase_metrics(arrays, entry_end_p, exit_start_p)
    exit_metrics = _phase_metrics(arrays, exit_start_p, end_p)

    brake_event = _detect_brake_event(
        arrays=arrays,
        corner_mask=corner_mask,
        brake_search_mask=brake_search_mask,
        min_speed_idx=min_speed_idx,
        reference_length_m=reference_length_m,
    )
    throttle_event = _detect_throttle_event(
        arrays=arrays,
        corner_mask=corner_mask,
        min_speed_idx=min_speed_idx,
        exit_start_p=exit_start_p,
        end_p=end_p,
    )
    coasting_distance_m = _coasting_distance(arrays, corner_mask)
    steering_noise = _estimate_steering_noise(arrays)
    exit_steering_corrections = _exit_steering_corrections(
        arrays, exit_start_p, end_p, noise_threshold=steering_noise
    )

    alignment_quality_m, alignment_used_fallback = _alignment_quality(
        processed_arrays, start_p, end_p
    )

    sub_corner_records: list[CornerRecord] = []
    if corner.is_compound and len(corner.sub_apex_progress_norms) > 1:
        sub_corner_records = _build_sub_corner_records(
            corner=corner,
            arrays=arrays,
            processed_arrays=processed_arrays,
            lap_number=lap_number,
            reference_length_m=reference_length_m,
        )

    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner.corner_id,
        is_compound=corner.is_compound,
        alignment_quality_m=alignment_quality_m,
        alignment_used_fallback=alignment_used_fallback,
        corner_time_s=float(corner_time_s),
        entry=entry_metrics,
        apex=apex_metrics,
        exit=exit_metrics,
        brake=brake_event,
        throttle=throttle_event,
        coasting_distance_m=float(coasting_distance_m),
        gear_at_min_speed=gear_at_min_speed,
        min_speed_kph=min_speed_kph,
        min_speed_progress_norm=min_speed_progress_norm,
        corner_end_progress_norm=float(end_p),
        exit_steering_correction_count=exit_steering_corrections,
        sub_corner_records=sub_corner_records,
    )


def _degenerate_corner_record(
    corner: CornerDefinition,
    arrays: _LapArrays,
    processed_arrays: _ProcessedArrays,
    lap_number: int,
    reference_length_m: float,
) -> CornerRecord:
    """Emit a zeroed record when the corner window produced no samples.

    This is unusual on the default 400-point grid (~15m spacing), but we still
    need to return *something* rather than crashing. Everything is filled with
    safe defaults; detectors will skip the record via the alignment-quality
    gate.
    """
    start_p = corner.start_progress_norm
    end_p = corner.end_progress_norm
    alignment_quality_m, alignment_used_fallback = _alignment_quality(
        processed_arrays, start_p, end_p
    )
    entry_speed = _speed_at_progress(arrays, start_p)
    exit_speed = _speed_at_progress(arrays, end_p)
    phase = PhaseMetrics(
        time_s=0.0,
        entry_speed_kph=float(entry_speed),
        exit_speed_kph=float(exit_speed),
        min_speed_kph=float(min(entry_speed, exit_speed)),
        min_speed_progress_norm=float(start_p),
    )
    return CornerRecord(
        lap_number=lap_number,
        corner_id=corner.corner_id,
        is_compound=corner.is_compound,
        alignment_quality_m=alignment_quality_m,
        alignment_used_fallback=alignment_used_fallback,
        corner_time_s=float(_time_through_window(arrays, start_p, end_p)),
        entry=phase,
        apex=phase,
        exit=phase,
        brake=None,
        throttle=None,
        coasting_distance_m=0.0,
        gear_at_min_speed=None,
        min_speed_kph=phase.min_speed_kph,
        min_speed_progress_norm=phase.min_speed_progress_norm,
        corner_end_progress_norm=float(end_p),
        exit_steering_correction_count=0,
        sub_corner_records=[],
    )


def _build_sub_corner_records(
    corner: CornerDefinition,
    arrays: _LapArrays,
    processed_arrays: _ProcessedArrays,
    lap_number: int,
    reference_length_m: float,
) -> list[CornerRecord]:
    """Split a compound corner into one synthetic sub-corner per sub-apex."""
    sub_progs = sorted(corner.sub_apex_progress_norms)
    start_p = corner.start_progress_norm
    end_p = corner.end_progress_norm

    # Sub-corner boundaries are the midpoints between consecutive sub-apexes,
    # with the corner's own start/end as the outer edges. This keeps every
    # sub-record anchored on exactly one sub-apex.
    boundaries: list[float] = [start_p]
    for i in range(len(sub_progs) - 1):
        boundaries.append((sub_progs[i] + sub_progs[i + 1]) / 2.0)
    boundaries.append(end_p)

    sub_records: list[CornerRecord] = []
    for sub_index, sub_apex_progress in enumerate(sub_progs):
        sub_start = boundaries[sub_index]
        sub_end = boundaries[sub_index + 1]
        synthetic = CornerDefinition(
            corner_id=corner.corner_id * 100 + sub_index + 1,
            track_corner_key=f"{corner.track_corner_key}.s{sub_index + 1}",
            start_progress_norm=sub_start,
            end_progress_norm=sub_end,
            center_progress_norm=sub_apex_progress,
            start_distance_m=_progress_to_distance(sub_start, reference_length_m),
            end_distance_m=_progress_to_distance(sub_end, reference_length_m),
            center_distance_m=_progress_to_distance(sub_apex_progress, reference_length_m),
            approach_start_distance_m=max(
                0.0,
                _progress_to_distance(sub_start, reference_length_m) - 20.0,
            ),
            entry_end_progress_norm=(sub_start + sub_apex_progress) / 2.0,
            exit_start_progress_norm=(sub_apex_progress + sub_end) / 2.0,
            length_m=max(
                0.0,
                _progress_to_distance(sub_end, reference_length_m)
                - _progress_to_distance(sub_start, reference_length_m),
            ),
            peak_curvature=corner.peak_curvature,
            mean_curvature=corner.mean_curvature,
            direction=corner.direction,
            is_compound=False,
            sub_apex_progress_norms=[],
            sub_apex_distances_m=[],
        )
        sub_records.append(
            _build_corner_record(
                corner=synthetic,
                arrays=arrays,
                processed_arrays=processed_arrays,
                lap_number=lap_number,
                reference_length_m=reference_length_m,
            )
        )
    return sub_records


# ---------------------------------------------------------------------------
# Phase metrics
# ---------------------------------------------------------------------------


def _resolve_phase_boundaries(
    corner: CornerDefinition, min_speed_progress_norm: float
) -> tuple[float, float]:
    """Return ``(entry_end, exit_start)`` for computing phase metrics.

    Segmentation collapses ``entry_end_progress_norm`` and ``exit_start_progress_norm``
    to the corner boundaries for compound corners (so "the whole corner is
    apex"). That is correct for segmentation but useless for a three-phase
    decomposition. In that case we synthesize a phase split around the
    effective apex (the min-speed point), using ~30% of the corner width as a
    half-apex window — mirroring CENTER_REGION_FRACTION in segmentation.
    """
    start_p = corner.start_progress_norm
    end_p = corner.end_progress_norm
    corner_width = _cyclic_span(start_p, end_p)
    if corner_width <= 0:
        return start_p, end_p

    if corner.is_compound:
        half_apex = 0.15 * corner_width
        entry_end = _cyclic_subtract(min_speed_progress_norm, half_apex)
        exit_start = _cyclic_add(min_speed_progress_norm, half_apex)
        return _clamp_to_window(entry_end, start_p, end_p), _clamp_to_window(exit_start, start_p, end_p)

    return corner.entry_end_progress_norm, corner.exit_start_progress_norm


def _phase_metrics(arrays: _LapArrays, start_p: float, end_p: float) -> PhaseMetrics:
    mask = _progress_window_mask(arrays.progress_norm, start_p, end_p)
    slice_idx = np.where(mask)[0]
    entry_speed = _speed_at_progress(arrays, start_p)
    exit_speed = _speed_at_progress(arrays, end_p)
    if slice_idx.size == 0:
        # Zero-width or empty phase — use boundary speeds for min-speed.
        local_min = float(min(entry_speed, exit_speed))
        return PhaseMetrics(
            time_s=float(_time_through_window(arrays, start_p, end_p)),
            entry_speed_kph=float(entry_speed),
            exit_speed_kph=float(exit_speed),
            min_speed_kph=local_min,
            min_speed_progress_norm=float(start_p),
        )

    speed_window = arrays.speed_kph[slice_idx]
    local_argmin = int(np.argmin(speed_window))
    abs_min_idx = int(slice_idx[local_argmin])
    return PhaseMetrics(
        time_s=float(_time_through_window(arrays, start_p, end_p)),
        entry_speed_kph=float(entry_speed),
        exit_speed_kph=float(exit_speed),
        min_speed_kph=float(speed_window[local_argmin]),
        min_speed_progress_norm=float(arrays.progress_norm[abs_min_idx]),
    )


# ---------------------------------------------------------------------------
# Brake event
# ---------------------------------------------------------------------------


def _detect_brake_event(
    arrays: _LapArrays,
    corner_mask: np.ndarray,
    brake_search_mask: np.ndarray,
    min_speed_idx: int,
    reference_length_m: float,
) -> BrakeEvent | None:
    search_mask = corner_mask | brake_search_mask
    search_idx = np.where(search_mask)[0]
    if search_idx.size == 0:
        return None

    brake_in_window = arrays.brake[search_idx]
    if float(brake_in_window.max(initial=0.0)) < BRAKE_PRESENCE_THRESHOLD:
        return None

    # Corner end index — used to bound the forward release scan and the
    # trail-brake-end scan so they stay within the corner window.
    corner_idx = np.where(corner_mask)[0]
    corner_end_idx = int(corner_idx[-1]) if corner_idx.size else len(arrays.brake) - 1

    # --- Anchor to the main brake zone. Pick the peak sample inside the
    # search window, then scan backward from peak to locate the true
    # initiation (contiguous crossing of BRAKE_INIT_THRESHOLD leading into
    # the peak, not an earlier light dab). Scan forward from peak for the
    # release. This prevents a pre-corner feathering dab from being scored
    # as the brake event when the real braking happens later.
    peak_local = int(np.argmax(brake_in_window))
    peak_idx = int(search_idx[peak_local])

    # Backward scan: find the latest sample at-or-before peak where brake
    # is below the init threshold — initiation is the next sample after it.
    # Bounded by the start of the search window to avoid escaping into a
    # previous corner.
    search_floor = int(search_idx[0])
    init_idx = peak_idx
    for i in range(peak_idx, search_floor - 1, -1):
        if float(arrays.brake[i]) <= BRAKE_INIT_THRESHOLD:
            init_idx = min(peak_idx, i + 1)
            break
        init_idx = i

    # Forward scan: from peak to corner end, find the first drop below the
    # release threshold. Extends past the min-speed point so we can detect
    # trail braking past the apex (brake held after the min-speed point).
    forward_end = min(len(arrays.brake), corner_end_idx + 1)
    if forward_end <= peak_idx:
        forward_end = min(len(arrays.brake), peak_idx + 2)
    forward_idx = np.arange(peak_idx, forward_end, dtype=int)
    if forward_idx.size == 0:
        return None
    forward_brake = arrays.brake[forward_idx]
    below_release = forward_brake < BRAKE_RELEASE_THRESHOLD
    if below_release.any():
        release_local = int(np.argmax(below_release))
        release_idx = int(forward_idx[max(release_local - 1, 0)])
    else:
        release_idx = int(forward_idx[-1])
    release_idx = max(release_idx, init_idx)

    peak_slice = slice(init_idx, release_idx + 1)
    peak_brake = float(arrays.brake[peak_slice].max(initial=0.0))
    long_accel_window = arrays.long_accel[peak_slice]
    peak_decel = float(long_accel_window.min(initial=0.0)) if long_accel_window.size else 0.0
    avg_decel = float(long_accel_window.mean()) if long_accel_window.size else 0.0

    release_rate_per_s = _release_rate_per_second(arrays, release_idx)
    release_brake_value = float(arrays.brake[release_idx])
    init_speed = _speed_at_progress(arrays, float(arrays.progress_norm[init_idx]))

    # --- Trail brake end: first sample after init where brake drops below
    # the near-zero clear threshold, bounded to the corner window.
    trail_end_idx = _trail_brake_end_index(arrays, init_idx, corner_end_idx)
    trail_end_progress = float(arrays.progress_norm[trail_end_idx])
    # Positive = brake held past the apex (problematic).
    # Negative = brake released before the apex (normal).
    trail_depth_m = float(
        arrays.progress_m[release_idx] - arrays.progress_m[min_speed_idx]
    )

    brake_steering_overlap_m = _brake_steering_overlap(arrays, corner_mask)

    return BrakeEvent(
        initiation_progress_norm=float(arrays.progress_norm[init_idx]),
        initiation_distance_m=float(arrays.progress_m[init_idx]),
        initiation_speed_kph=float(init_speed),
        release_progress_norm=float(arrays.progress_norm[release_idx]),
        release_distance_m=float(arrays.progress_m[release_idx]),
        release_brake_value=release_brake_value,
        release_rate_per_s=release_rate_per_s,
        peak_brake=peak_brake,
        peak_decel_mps2=peak_decel,
        avg_decel_mps2=avg_decel,
        trail_brake_end_progress_norm=trail_end_progress,
        trail_brake_depth_m=trail_depth_m,
        brake_steering_overlap_m=brake_steering_overlap_m,
    )


def _release_rate_per_second(arrays: _LapArrays, release_idx: int) -> float:
    """Brake-value-per-second at the release point.

    Uses a two-sided difference when possible so we pick up the shape of the
    release curve rather than noise at a single sample.
    """
    n = len(arrays.brake)
    lo = max(0, release_idx - 1)
    hi = min(n - 1, release_idx + 1)
    if hi <= lo:
        return 0.0
    dt = float(arrays.elapsed_s[hi] - arrays.elapsed_s[lo])
    if dt <= 0:
        return 0.0
    dbrake = float(arrays.brake[lo] - arrays.brake[hi])  # positive on release
    return max(0.0, dbrake / dt)


def _trail_brake_end_index(arrays: _LapArrays, init_idx: int, max_idx: int) -> int:
    post = np.arange(init_idx, max_idx + 1, dtype=int)
    if post.size == 0:
        return init_idx
    clear = arrays.brake[post] < TRAIL_BRAKE_CLEAR_THRESHOLD
    if not clear.any():
        return int(post[-1])
    return int(post[int(np.argmax(clear))])


# ---------------------------------------------------------------------------
# Throttle event
# ---------------------------------------------------------------------------


def _detect_throttle_event(
    arrays: _LapArrays,
    corner_mask: np.ndarray,
    min_speed_idx: int,
    exit_start_p: float,
    end_p: float,
) -> ThrottleEvent | None:
    n = len(arrays.throttle)
    search_start = int(min_speed_idx)
    search_end = int(_last_index_in_window(arrays.progress_norm, end_p))
    if search_end <= search_start:
        search_end = min(n - 1, search_start + 1)

    search_idx = np.arange(search_start, search_end + 1, dtype=int)
    if search_idx.size == 0:
        return None

    throttle_window = arrays.throttle[search_idx]
    above_pickup = throttle_window > THROTTLE_PICKUP_THRESHOLD
    if not above_pickup.any():
        return None

    pickup_local = int(np.argmax(above_pickup))
    pickup_idx = int(search_idx[pickup_local])

    full_throttle_progress: float | None = None
    post_pickup = throttle_window[pickup_local:]
    above_full = post_pickup > FULL_THROTTLE_THRESHOLD
    if above_full.any():
        full_local = pickup_local + int(np.argmax(above_full))
        full_throttle_progress = float(arrays.progress_norm[int(search_idx[full_local])])

    pickup_distance_from_min = float(
        arrays.progress_m[pickup_idx] - arrays.progress_m[min_speed_idx]
    )

    exit_mask = _progress_window_mask(arrays.progress_norm, exit_start_p, end_p)
    exit_throttle = arrays.throttle[exit_mask]
    exit_full_fraction = (
        float((exit_throttle > FULL_THROTTLE_THRESHOLD).mean()) if exit_throttle.size else 0.0
    )

    throttle_dip_detected = _detect_throttle_dip(exit_throttle)

    return ThrottleEvent(
        pickup_progress_norm=float(arrays.progress_norm[pickup_idx]),
        pickup_speed_kph=float(arrays.speed_kph[pickup_idx]),
        pickup_distance_from_min_speed_m=pickup_distance_from_min,
        full_throttle_progress_norm=full_throttle_progress,
        exit_full_throttle_fraction=exit_full_fraction,
        throttle_dip_detected=throttle_dip_detected,
    )


def _detect_throttle_dip(exit_throttle: np.ndarray) -> bool:
    """Return True if throttle rose above DIP_UPPER then dropped below DIP_LOWER."""
    if exit_throttle.size < 2:
        return False
    reached_upper = False
    for value in exit_throttle:
        if not reached_upper and value >= THROTTLE_DIP_UPPER:
            reached_upper = True
            continue
        if reached_upper and value < THROTTLE_DIP_LOWER:
            return True
    return False


# ---------------------------------------------------------------------------
# Coasting / overlap metrics
# ---------------------------------------------------------------------------


def _coasting_distance(arrays: _LapArrays, corner_mask: np.ndarray) -> float:
    idx = np.where(corner_mask)[0]
    if idx.size < 2:
        return 0.0
    coasting = arrays.is_coasting[idx] >= 0.5
    if not coasting.any():
        return 0.0
    distances = arrays.progress_m[idx]
    segment_lengths = np.diff(distances, prepend=distances[0])
    segment_lengths[0] = 0.0
    return float(np.sum(segment_lengths[coasting]))


def _brake_steering_overlap(arrays: _LapArrays, corner_mask: np.ndarray) -> float:
    idx = np.where(corner_mask)[0]
    if idx.size < 2:
        return 0.0
    brake = arrays.brake[idx]
    steering_abs = np.abs(arrays.steering[idx])
    overlap = (brake > BRAKE_ACTIVE_THRESHOLD) & (steering_abs > STEERING_ACTIVE_THRESHOLD)
    if not overlap.any():
        return 0.0
    distances = arrays.progress_m[idx]
    segment_lengths = np.diff(distances, prepend=distances[0])
    segment_lengths[0] = 0.0
    return float(np.sum(segment_lengths[overlap]))


# ---------------------------------------------------------------------------
# Alignment quality
# ---------------------------------------------------------------------------


def _alignment_quality(
    processed_arrays: _ProcessedArrays, start_p: float, end_p: float
) -> tuple[float, bool]:
    if processed_arrays.progress_norm.size == 0:
        return 0.0, False
    mask = _progress_window_mask(processed_arrays.progress_norm, start_p, end_p)
    if not mask.any():
        return 0.0, False
    residuals = processed_arrays.residual_m[mask]
    finite = residuals[np.isfinite(residuals)]
    median_residual = float(np.median(finite)) if finite.size else 0.0
    used_fallback = bool(processed_arrays.used_fallback[mask].any())
    return median_residual, used_fallback


# ---------------------------------------------------------------------------
# Steering stability helpers
# ---------------------------------------------------------------------------


def _estimate_steering_noise(arrays: _LapArrays) -> float:
    """Adaptive steering noise floor derived from the lap's own data.

    Uses the 25th percentile of ``|diff(steering)|`` across the whole lap as
    a proxy for sensor noise and small tracking movements.  This naturally
    adapts to hardware noise levels and track conditions without requiring
    per-track configuration.  Floored at 0.01 to handle perfectly smooth
    sim data where the percentile would otherwise collapse to zero.
    """
    dsteering = np.abs(np.diff(arrays.steering))
    if dsteering.size == 0:
        return STEERING_NOISE_THRESHOLD
    return max(float(np.percentile(dsteering, 25)), 0.01)


def _exit_steering_corrections(
    arrays: _LapArrays, exit_start_p: float, end_p: float,
    noise_threshold: float = STEERING_NOISE_THRESHOLD,
) -> int:
    """Count steering direction changes in the exit phase (noise-filtered)."""
    mask = _progress_window_mask(arrays.progress_norm, exit_start_p, end_p)
    idx = np.where(mask)[0]
    if idx.size < 3:
        return 0
    steering_exit = arrays.steering[idx]
    dsteering = np.diff(steering_exit)
    dsteering[np.abs(dsteering) < noise_threshold] = 0.0
    nonzero = dsteering[dsteering != 0.0]
    if nonzero.size < 2:
        return 0
    signs = np.sign(nonzero)
    return int(np.sum(signs[1:] != signs[:-1]))


# ---------------------------------------------------------------------------
# Window / interpolation helpers
# ---------------------------------------------------------------------------


def _progress_window_mask(
    progress_norm: np.ndarray, start_p: float, end_p: float
) -> np.ndarray:
    """Boolean mask for samples inside a (possibly wrap-around) progress window."""
    if start_p <= end_p:
        return (progress_norm >= start_p) & (progress_norm <= end_p)
    return (progress_norm >= start_p) | (progress_norm <= end_p)


def _last_index_in_window(progress_norm: np.ndarray, end_p: float) -> int:
    candidates = np.where(progress_norm <= end_p)[0]
    if candidates.size == 0:
        return 0
    return int(candidates[-1])


def _time_through_window(arrays: _LapArrays, start_p: float, end_p: float) -> float:
    progress = arrays.progress_norm
    elapsed = arrays.elapsed_s
    if progress.size == 0:
        return 0.0

    if start_p <= end_p:
        t_start = float(np.interp(start_p, progress, elapsed))
        t_end = float(np.interp(end_p, progress, elapsed))
        return max(0.0, t_end - t_start)

    # Wrap-around: split into [start, 1.0) + [0.0, end] and compute in terms
    # of elapsed differences. At the 1.0 boundary we take the last sample's
    # elapsed time; at the 0.0 boundary we take the first.
    t_start = float(np.interp(start_p, progress, elapsed))
    t_lap_end = float(elapsed[-1])
    t_lap_start = float(elapsed[0])
    t_end = float(np.interp(end_p, progress, elapsed))
    return max(0.0, (t_lap_end - t_start) + (t_end - t_lap_start))


def _speed_at_progress(arrays: _LapArrays, progress: float) -> float:
    if arrays.progress_norm.size == 0:
        return 0.0
    return float(np.interp(progress, arrays.progress_norm, arrays.speed_kph))


def _distance_to_progress(distance_m: float, reference_length_m: float) -> float:
    if reference_length_m <= 0:
        return 0.0
    return float(np.clip(distance_m / reference_length_m, 0.0, 1.0))


def _progress_to_distance(progress: float, reference_length_m: float) -> float:
    if reference_length_m <= 0:
        return 0.0
    return float(np.clip(progress, 0.0, 1.0) * reference_length_m)


def _cyclic_span(start_p: float, end_p: float) -> float:
    if start_p <= end_p:
        return end_p - start_p
    return (1.0 - start_p) + end_p


def _cyclic_add(progress: float, delta: float) -> float:
    return (progress + delta) % 1.0


def _cyclic_subtract(progress: float, delta: float) -> float:
    return (progress - delta) % 1.0


def _clamp_to_window(progress: float, start_p: float, end_p: float) -> float:
    """Clamp a progress value into a corner window, handling wrap-around."""
    if start_p <= end_p:
        return float(min(max(progress, start_p), end_p))
    # Wrap-around corner — the valid region is [start_p, 1.0] ∪ [0.0, end_p].
    if progress >= start_p or progress <= end_p:
        return float(progress)
    # Outside — snap to the nearest boundary.
    dist_to_start = min(abs(progress - start_p), 1.0 - abs(progress - start_p))
    dist_to_end = min(abs(progress - end_p), 1.0 - abs(progress - end_p))
    return float(start_p if dist_to_start <= dist_to_end else end_p)
