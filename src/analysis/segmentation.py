from __future__ import annotations

from typing import Any

import pandas as pd


def _append_segment(
    segments: list[dict[str, Any]],
    processed_lap: pd.DataFrame,
    region_type: str,
    start_idx: int,
    end_idx: int,
) -> None:
    if end_idx < start_idx:
        return

    segment_df = processed_lap.iloc[start_idx : end_idx + 1]
    if segment_df.empty:
        return

    segments.append(
        {
            "RegionType": region_type,
            "StartIndex": int(start_idx),
            "EndIndex": int(end_idx),
            "StartNormDistance": float(segment_df["NormalizedDistance"].iloc[0]),
            "EndNormDistance": float(segment_df["NormalizedDistance"].iloc[-1]),
            "StartTimeS": float(segment_df["ElapsedTimeS"].iloc[0]),
            "EndTimeS": float(segment_df["ElapsedTimeS"].iloc[-1]),
            "MinSpeedKph": float(segment_df["SpeedKph"].min()),
            "MaxBrake": float(segment_df["Brake"].max()),
            "MaxSteering": float(segment_df["Steering"].abs().max()),
        }
    )


def _corner_groups(processed_lap: pd.DataFrame, steering_threshold: float, brake_threshold: float) -> list[tuple[int, int]]:
    corner_mask = (processed_lap["Steering"].abs() >= steering_threshold) | (
        processed_lap["Brake"] >= brake_threshold
    )

    groups: list[tuple[int, int]] = []
    start_idx: int | None = None
    for idx, is_corner in enumerate(corner_mask.tolist()):
        if is_corner and start_idx is None:
            start_idx = idx
        elif not is_corner and start_idx is not None:
            if idx - start_idx >= 3:
                groups.append((start_idx, idx - 1))
            start_idx = None

    if start_idx is not None and len(processed_lap) - start_idx >= 3:
        groups.append((start_idx, len(processed_lap) - 1))

    return groups


def segment_lap(
    processed_lap: pd.DataFrame,
    steering_threshold: float = 0.15,
    brake_threshold: float = 0.1,
) -> pd.DataFrame:
    """Partition a processed lap into straights and corner subregions."""

    ordered_lap = processed_lap.sort_values("NormalizedDistance").reset_index(drop=True)
    segments: list[dict[str, Any]] = []
    corner_groups = _corner_groups(ordered_lap, steering_threshold=steering_threshold, brake_threshold=brake_threshold)

    previous_end = 0
    for group_start, group_end in corner_groups:
        if group_start > previous_end:
            _append_segment(segments, ordered_lap, "straight", previous_end, group_start - 1)

        corner_df = ordered_lap.iloc[group_start : group_end + 1]
        apex_local_idx = int(corner_df["SpeedKph"].idxmin())
        brake_before_apex = ordered_lap.loc[group_start:apex_local_idx, "Brake"] >= brake_threshold
        brake_indices = brake_before_apex[brake_before_apex].index.tolist()

        apex_window_start = max(group_start, apex_local_idx - 1)
        apex_window_end = min(group_end, apex_local_idx + 1)

        if brake_indices:
            braking_end = int(brake_indices[-1])
            _append_segment(segments, ordered_lap, "braking_zone", group_start, braking_end)
            entry_start = braking_end + 1
        else:
            entry_start = group_start

        entry_end = apex_window_start - 1
        _append_segment(segments, ordered_lap, "corner_entry", entry_start, entry_end)
        _append_segment(segments, ordered_lap, "apex", apex_window_start, apex_window_end)
        _append_segment(segments, ordered_lap, "corner_exit", apex_window_end + 1, group_end)

        previous_end = group_end + 1

    if previous_end < len(ordered_lap):
        _append_segment(segments, ordered_lap, "straight", previous_end, len(ordered_lap) - 1)

    return pd.DataFrame(segments)
