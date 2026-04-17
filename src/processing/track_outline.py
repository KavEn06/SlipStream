from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


TRACK_OUTLINE_FILENAME = "track_outline.json"
TRACK_OUTLINE_VERSION = "2026.04-v1"
TRACK_OUTLINE_SOURCE_SESSION_AGGREGATE = "session_aggregate"
TRACK_OUTLINE_SOURCE_SYNTHETIC_REFERENCE_PATH = "synthetic_reference_path"
MIN_TRACK_OUTLINE_SAMPLES = 20
TRACK_OUTLINE_MARGIN_M = 0.75
TRACK_OUTLINE_MIN_WIDTH_M = 9.0
TRACK_OUTLINE_LEFT_PERCENTILE = 5.0
TRACK_OUTLINE_RIGHT_PERCENTILE = 95.0


@dataclass(frozen=True)
class TrackOutlinePoint:
    progress_norm: float
    distance_m: float
    center_x: float
    center_z: float
    left_x: float
    left_z: float
    right_x: float
    right_z: float
    width_m: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class TrackOutlineArtifact:
    outline_version: str
    session_id: str
    source_kind: str
    reference_lap_number: int
    reference_length_m: float
    sample_spacing_m: float
    source_lap_numbers: list[int] = field(default_factory=list)
    contributing_lap_count: int = 0
    points: list[TrackOutlinePoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outline_version": self.outline_version,
            "session_id": self.session_id,
            "source_kind": self.source_kind,
            "reference_lap_number": self.reference_lap_number,
            "reference_length_m": self.reference_length_m,
            "sample_spacing_m": self.sample_spacing_m,
            "source_lap_numbers": self.source_lap_numbers,
            "contributing_lap_count": self.contributing_lap_count,
            "points": [point.to_dict() for point in self.points],
        }

    def metadata_summary(self) -> dict[str, Any]:
        return {
            "status": "complete",
            "artifact_file": TRACK_OUTLINE_FILENAME,
            "source_kind": self.source_kind,
            "contributing_lap_count": self.contributing_lap_count,
            "source_lap_numbers": self.source_lap_numbers,
        }


def build_session_track_outline(
    session_id: str,
    aligned_laps: dict[int, pd.DataFrame],
    reference_path_df: pd.DataFrame | None,
) -> TrackOutlineArtifact | None:
    if reference_path_df is None or reference_path_df.empty:
        return None

    reference_inputs = _extract_reference_inputs(reference_path_df)
    if reference_inputs is None:
        return None

    (
        reference_lap_number,
        center_x,
        center_z,
        distance_m,
        progress_norm,
        normals,
        sample_spacing_m,
    ) = reference_inputs

    lap_offsets: list[np.ndarray] = []
    source_lap_numbers: list[int] = []
    for lap_number in sorted(aligned_laps):
        lap_df = aligned_laps[lap_number]
        offsets = _build_lap_offset_series(lap_df, progress_norm, center_x, center_z, normals)
        if offsets is None:
            continue
        lap_offsets.append(offsets)
        source_lap_numbers.append(lap_number)

    if not lap_offsets:
        return _build_synthetic_track_outline(
            session_id=session_id,
            reference_lap_number=reference_lap_number,
            center_x=center_x,
            center_z=center_z,
            distance_m=distance_m,
            progress_norm=progress_norm,
            normals=normals,
            sample_spacing_m=sample_spacing_m,
        )

    aggregated_offsets = _aggregate_outline_offsets(lap_offsets)
    if aggregated_offsets is None:
        return _build_synthetic_track_outline(
            session_id=session_id,
            reference_lap_number=reference_lap_number,
            center_x=center_x,
            center_z=center_z,
            distance_m=distance_m,
            progress_norm=progress_norm,
            normals=normals,
            sample_spacing_m=sample_spacing_m,
        )

    left_offsets, right_offsets = aggregated_offsets
    return _build_outline_artifact(
        session_id=session_id,
        source_kind=TRACK_OUTLINE_SOURCE_SESSION_AGGREGATE,
        reference_lap_number=reference_lap_number,
        center_x=center_x,
        center_z=center_z,
        distance_m=distance_m,
        progress_norm=progress_norm,
        normals=normals,
        left_offsets=left_offsets,
        right_offsets=right_offsets,
        sample_spacing_m=sample_spacing_m,
        source_lap_numbers=source_lap_numbers,
    )


def _extract_reference_inputs(
    reference_path_df: pd.DataFrame,
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float] | None:
    x = pd.to_numeric(reference_path_df["PositionX"], errors="coerce").to_numpy(dtype=float)
    z = pd.to_numeric(reference_path_df["PositionZ"], errors="coerce").to_numpy(dtype=float)
    distance_m = pd.to_numeric(reference_path_df["ReferenceDistanceM"], errors="coerce").to_numpy(dtype=float)
    progress_norm = pd.to_numeric(reference_path_df["ReferenceProgressNorm"], errors="coerce").to_numpy(dtype=float)

    finite_mask = np.isfinite(x) & np.isfinite(z) & np.isfinite(distance_m) & np.isfinite(progress_norm)
    if int(finite_mask.sum()) < 2:
        return None

    x = x[finite_mask]
    z = z[finite_mask]
    distance_m = distance_m[finite_mask]
    progress_norm = progress_norm[finite_mask]
    if distance_m[-1] <= 0:
        return None

    reference_lap_number = int(
        pd.to_numeric(reference_path_df["ReferenceLapNumber"], errors="coerce").dropna().iloc[0]
    )
    normals = _compute_reference_normals(x, z, distance_m)
    sample_spacing_m = (
        float(np.median(np.diff(distance_m))) if len(distance_m) >= 2 else 1.0
    )
    return reference_lap_number, x, z, distance_m, progress_norm, normals, sample_spacing_m


def _compute_reference_normals(
    center_x: np.ndarray,
    center_z: np.ndarray,
    distance_m: np.ndarray,
) -> np.ndarray:
    tangent_x = np.gradient(center_x, distance_m)
    tangent_z = np.gradient(center_z, distance_m)
    tangent_norm = np.hypot(tangent_x, tangent_z)
    tangent_norm = np.where(tangent_norm > 1e-9, tangent_norm, 1.0)
    tangent_x = tangent_x / tangent_norm
    tangent_z = tangent_z / tangent_norm
    return np.column_stack((tangent_z, -tangent_x))


def _build_lap_offset_series(
    lap_df: pd.DataFrame,
    reference_progress_norm: np.ndarray,
    center_x: np.ndarray,
    center_z: np.ndarray,
    normals: np.ndarray,
) -> np.ndarray | None:
    if not _lap_is_outline_eligible(lap_df):
        return None

    lap_positions = lap_df[["PositionX", "PositionZ", "TrackProgressNorm"]].apply(pd.to_numeric, errors="coerce")
    lap_positions = lap_positions.dropna(subset=["PositionX", "PositionZ", "TrackProgressNorm"])
    if len(lap_positions) < MIN_TRACK_OUTLINE_SAMPLES:
        return None

    lap_positions = (
        lap_positions.sort_values("TrackProgressNorm")
        .drop_duplicates(subset="TrackProgressNorm")
        .reset_index(drop=True)
    )
    if len(lap_positions) < 2:
        return None

    lap_progress = lap_positions["TrackProgressNorm"].to_numpy(dtype=float)
    lap_x = lap_positions["PositionX"].to_numpy(dtype=float)
    lap_z = lap_positions["PositionZ"].to_numpy(dtype=float)

    valid_mask = (reference_progress_norm >= lap_progress[0]) & (reference_progress_norm <= lap_progress[-1])
    if int(valid_mask.sum()) < MIN_TRACK_OUTLINE_SAMPLES:
        return None

    sampled_x = np.full(len(reference_progress_norm), np.nan)
    sampled_z = np.full(len(reference_progress_norm), np.nan)
    sampled_x[valid_mask] = np.interp(reference_progress_norm[valid_mask], lap_progress, lap_x)
    sampled_z[valid_mask] = np.interp(reference_progress_norm[valid_mask], lap_progress, lap_z)

    delta_x = sampled_x - center_x
    delta_z = sampled_z - center_z
    offsets = (delta_x * normals[:, 0]) + (delta_z * normals[:, 1])
    return offsets


def _lap_is_outline_eligible(lap_df: pd.DataFrame) -> bool:
    lap_is_valid = pd.to_numeric(lap_df.get("LapIsValid"), errors="coerce").fillna(0)
    if lap_is_valid.empty or int(lap_is_valid.iloc[-1]) != 1:
        return False

    eligible_rows = lap_df[["PositionX", "PositionZ", "TrackProgressNorm"]].apply(pd.to_numeric, errors="coerce")
    finite_rows = eligible_rows.notna().all(axis=1)
    return int(finite_rows.sum()) >= MIN_TRACK_OUTLINE_SAMPLES


def _aggregate_outline_offsets(
    lap_offsets: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray] | None:
    if not lap_offsets:
        return None

    sample_count = len(lap_offsets[0])
    left_offsets = np.full(sample_count, np.nan)
    right_offsets = np.full(sample_count, np.nan)

    for index in range(sample_count):
        values = np.array(
            [offsets[index] for offsets in lap_offsets if np.isfinite(offsets[index])],
            dtype=float,
        )
        if values.size == 0:
            continue
        left_offsets[index] = float(np.percentile(values, TRACK_OUTLINE_LEFT_PERCENTILE))
        right_offsets[index] = float(np.percentile(values, TRACK_OUTLINE_RIGHT_PERCENTILE))

    if not np.isfinite(left_offsets).any() or not np.isfinite(right_offsets).any():
        return None

    left_offsets = pd.Series(left_offsets).interpolate(limit_direction="both").to_numpy(dtype=float)
    right_offsets = pd.Series(right_offsets).interpolate(limit_direction="both").to_numpy(dtype=float)
    if not np.isfinite(left_offsets).all() or not np.isfinite(right_offsets).all():
        return None

    left_offsets -= TRACK_OUTLINE_MARGIN_M
    right_offsets += TRACK_OUTLINE_MARGIN_M

    widths = right_offsets - left_offsets
    narrow_mask = widths < TRACK_OUTLINE_MIN_WIDTH_M
    if np.any(narrow_mask):
        centers = (left_offsets + right_offsets) / 2.0
        half_width = TRACK_OUTLINE_MIN_WIDTH_M / 2.0
        left_offsets = np.where(narrow_mask, centers - half_width, left_offsets)
        right_offsets = np.where(narrow_mask, centers + half_width, right_offsets)

    return left_offsets, right_offsets


def _build_outline_artifact(
    session_id: str,
    source_kind: str,
    reference_lap_number: int,
    center_x: np.ndarray,
    center_z: np.ndarray,
    distance_m: np.ndarray,
    progress_norm: np.ndarray,
    normals: np.ndarray,
    left_offsets: np.ndarray,
    right_offsets: np.ndarray,
    sample_spacing_m: float,
    source_lap_numbers: list[int],
) -> TrackOutlineArtifact:
    points: list[TrackOutlinePoint] = []
    for index in range(len(distance_m)):
        left_x = float(center_x[index] + (left_offsets[index] * normals[index, 0]))
        left_z = float(center_z[index] + (left_offsets[index] * normals[index, 1]))
        right_x = float(center_x[index] + (right_offsets[index] * normals[index, 0]))
        right_z = float(center_z[index] + (right_offsets[index] * normals[index, 1]))
        points.append(
            TrackOutlinePoint(
                progress_norm=float(progress_norm[index]),
                distance_m=float(distance_m[index]),
                center_x=float(center_x[index]),
                center_z=float(center_z[index]),
                left_x=left_x,
                left_z=left_z,
                right_x=right_x,
                right_z=right_z,
                width_m=float(max(TRACK_OUTLINE_MIN_WIDTH_M, right_offsets[index] - left_offsets[index])),
            )
        )

    return TrackOutlineArtifact(
        outline_version=TRACK_OUTLINE_VERSION,
        session_id=session_id,
        source_kind=source_kind,
        reference_lap_number=reference_lap_number,
        reference_length_m=float(distance_m[-1]),
        sample_spacing_m=float(sample_spacing_m),
        source_lap_numbers=source_lap_numbers,
        contributing_lap_count=len(source_lap_numbers),
        points=points,
    )


def _build_synthetic_track_outline(
    session_id: str,
    reference_lap_number: int,
    center_x: np.ndarray,
    center_z: np.ndarray,
    distance_m: np.ndarray,
    progress_norm: np.ndarray,
    normals: np.ndarray,
    sample_spacing_m: float,
) -> TrackOutlineArtifact:
    half_width = TRACK_OUTLINE_MIN_WIDTH_M / 2.0
    left_offsets = np.full(len(distance_m), -half_width, dtype=float)
    right_offsets = np.full(len(distance_m), half_width, dtype=float)
    return _build_outline_artifact(
        session_id=session_id,
        source_kind=TRACK_OUTLINE_SOURCE_SYNTHETIC_REFERENCE_PATH,
        reference_lap_number=reference_lap_number,
        center_x=center_x,
        center_z=center_z,
        distance_m=distance_m,
        progress_norm=progress_norm,
        normals=normals,
        left_offsets=left_offsets,
        right_offsets=right_offsets,
        sample_spacing_m=sample_spacing_m,
        source_lap_numbers=[],
    )
