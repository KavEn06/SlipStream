from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from src.analysis.segmentation import segment_lap
from src.config import DEFAULT_RESAMPLE_POINTS, DEFAULT_SECTOR_BOUNDARIES
from src.processing.distance import resample_processed_lap
from src.schemas import Finding, REFERENCE_LAP_COLUMNS


def lap_time_s(processed_lap: pd.DataFrame) -> float:
    return float(processed_lap["LapTimeS"].iloc[-1])


def align_lap(processed_lap: pd.DataFrame, num_points: int = DEFAULT_RESAMPLE_POINTS) -> pd.DataFrame:
    aligned = resample_processed_lap(processed_lap, num_points=num_points, columns=REFERENCE_LAP_COLUMNS)
    aligned["ElapsedTimeS"] = np.maximum.accumulate(aligned["ElapsedTimeS"])
    return aligned


def _average_reference(aligned_laps: list[pd.DataFrame]) -> pd.DataFrame:
    reference = aligned_laps[0][["NormalizedDistance"]].copy()
    for column in REFERENCE_LAP_COLUMNS:
        if column == "NormalizedDistance":
            continue
        reference[column] = np.mean([lap[column].to_numpy() for lap in aligned_laps], axis=0)
    return reference


def _sector_time(aligned_lap: pd.DataFrame, start: float, end: float) -> float:
    start_time = float(np.interp(start, aligned_lap["NormalizedDistance"], aligned_lap["ElapsedTimeS"]))
    end_time = float(np.interp(end, aligned_lap["NormalizedDistance"], aligned_lap["ElapsedTimeS"]))
    return end_time - start_time


def _best_sector_reference(
    aligned_laps: list[pd.DataFrame],
    sector_boundaries: Iterable[float],
) -> pd.DataFrame:
    boundaries = list(sector_boundaries)
    reference_parts: list[pd.DataFrame] = []

    for sector_start, sector_end in zip(boundaries[:-1], boundaries[1:]):
        best_lap = min(aligned_laps, key=lambda lap: _sector_time(lap, sector_start, sector_end))
        mask = (best_lap["NormalizedDistance"] >= sector_start) & (best_lap["NormalizedDistance"] <= sector_end)
        reference_parts.append(best_lap.loc[mask, REFERENCE_LAP_COLUMNS])

    return pd.concat(reference_parts, ignore_index=True).drop_duplicates(subset="NormalizedDistance")


def build_reference_lap(
    processed_laps: list[pd.DataFrame],
    mode: str = "personal_best",
    num_points: int = DEFAULT_RESAMPLE_POINTS,
    sector_boundaries: Iterable[float] = DEFAULT_SECTOR_BOUNDARIES,
) -> pd.DataFrame:
    if not processed_laps:
        raise ValueError("At least one processed lap is required")

    aligned_laps = [align_lap(lap, num_points=num_points) for lap in processed_laps]

    if mode == "personal_best":
        best_index = int(np.argmin([lap_time_s(lap) for lap in processed_laps]))
        reference = aligned_laps[best_index].copy()
    elif mode == "session_average":
        reference = _average_reference(aligned_laps)
    elif mode == "best_sector":
        reference = _best_sector_reference(aligned_laps, sector_boundaries=sector_boundaries)
    else:
        raise ValueError(f"Unsupported reference mode: {mode}")

    reference["ReferenceMode"] = mode
    return reference


def _time_in_region(region_df: pd.DataFrame) -> float:
    if len(region_df) < 2:
        return 0.0
    distance_delta = region_df["CumulativeDistanceM"].diff().fillna(0.0)
    speed = region_df["SpeedMps"].replace(0.0, np.nan).bfill().fillna(0.1)
    return float((distance_delta / speed).sum())


def _first_threshold_crossing(region_df: pd.DataFrame, column: str, threshold: float) -> float | None:
    active = region_df[column] >= threshold
    if not active.any():
        return None
    first_idx = active[active].index[0]
    return float(region_df.loc[first_idx, "NormalizedDistance"])


def compare_lap_to_reference(
    target_lap: pd.DataFrame,
    reference_lap: pd.DataFrame,
    segments: pd.DataFrame | None = None,
    num_points: int = DEFAULT_RESAMPLE_POINTS,
) -> pd.DataFrame:
    aligned_target = align_lap(target_lap, num_points=num_points)
    aligned_reference = reference_lap.copy()
    if len(aligned_reference) != len(aligned_target) or not aligned_reference["NormalizedDistance"].equals(
        aligned_target["NormalizedDistance"]
    ):
        aligned_reference = align_lap(reference_lap, num_points=num_points)

    segment_table = segments if segments is not None else segment_lap(target_lap)
    findings: list[dict[str, object]] = []

    for _, segment in segment_table.iterrows():
        start = float(segment["StartNormDistance"])
        end = float(segment["EndNormDistance"])
        if end <= start:
            continue

        target_region = aligned_target[
            (aligned_target["NormalizedDistance"] >= start) & (aligned_target["NormalizedDistance"] <= end)
        ]
        reference_region = aligned_reference[
            (aligned_reference["NormalizedDistance"] >= start) & (aligned_reference["NormalizedDistance"] <= end)
        ]

        if target_region.empty or reference_region.empty:
            continue

        observed_time = _time_in_region(target_region)
        reference_time = _time_in_region(reference_region)
        time_loss = observed_time - reference_time
        min_speed_delta = float(target_region["SpeedKph"].min() - reference_region["SpeedKph"].min())
        observed_coast = float((target_region["IsCoasting"] * target_region["ElapsedTimeS"].diff().fillna(0.0)).sum())
        reference_coast = float(
            (reference_region["IsCoasting"] * reference_region["ElapsedTimeS"].diff().fillna(0.0)).sum()
        )
        brake_point_target = _first_threshold_crossing(target_region, "Brake", 0.1)
        brake_point_reference = _first_threshold_crossing(reference_region, "Brake", 0.1)
        throttle_pickup_target = _first_threshold_crossing(target_region, "Throttle", 0.2)
        throttle_pickup_reference = _first_threshold_crossing(reference_region, "Throttle", 0.2)

        time_finding = Finding(
            finding_type="time_loss",
            region_type=str(segment["RegionType"]),
            start_norm_distance=start,
            end_norm_distance=end,
            metric="time_loss_s",
            observed=observed_time,
            reference=reference_time,
            delta=time_loss,
            summary=(
                f"{segment['RegionType']} loses {time_loss:.3f}s versus the reference"
                if time_loss > 0
                else f"{segment['RegionType']} is {abs(time_loss):.3f}s quicker than the reference"
            ),
        )
        findings.append(time_finding.to_dict())

        findings.append(
            Finding(
                finding_type="minimum_speed",
                region_type=str(segment["RegionType"]),
                start_norm_distance=start,
                end_norm_distance=end,
                metric="min_speed_delta_kph",
                observed=float(target_region["SpeedKph"].min()),
                reference=float(reference_region["SpeedKph"].min()),
                delta=min_speed_delta,
                summary=f"{segment['RegionType']} minimum speed delta is {min_speed_delta:.2f} kph",
            ).to_dict()
        )

        findings.append(
            Finding(
                finding_type="coasting",
                region_type=str(segment["RegionType"]),
                start_norm_distance=start,
                end_norm_distance=end,
                metric="coasting_delta_s",
                observed=observed_coast,
                reference=reference_coast,
                delta=observed_coast - reference_coast,
                summary=f"{segment['RegionType']} coasting delta is {observed_coast - reference_coast:.3f}s",
            ).to_dict()
        )

        if brake_point_target is not None and brake_point_reference is not None:
            findings.append(
                Finding(
                    finding_type="brake_point",
                    region_type=str(segment["RegionType"]),
                    start_norm_distance=start,
                    end_norm_distance=end,
                    metric="brake_point_delta_norm",
                    observed=brake_point_target,
                    reference=brake_point_reference,
                    delta=brake_point_target - brake_point_reference,
                    summary=(
                        f"{segment['RegionType']} brake point delta is "
                        f"{brake_point_target - brake_point_reference:.4f} normalized distance"
                    ),
                ).to_dict()
            )

        if throttle_pickup_target is not None and throttle_pickup_reference is not None:
            findings.append(
                Finding(
                    finding_type="throttle_pickup",
                    region_type=str(segment["RegionType"]),
                    start_norm_distance=start,
                    end_norm_distance=end,
                    metric="throttle_pickup_delta_norm",
                    observed=throttle_pickup_target,
                    reference=throttle_pickup_reference,
                    delta=throttle_pickup_target - throttle_pickup_reference,
                    summary=(
                        f"{segment['RegionType']} throttle pickup delta is "
                        f"{throttle_pickup_target - throttle_pickup_reference:.4f} normalized distance"
                    ),
                ).to_dict()
            )

        if (
            time_loss > 0.02
            and min_speed_delta < -3.0
            and brake_point_target is not None
            and brake_point_reference is not None
        ):
            indicator_type = "underdriving_indicator"
            indicator_summary = f"{segment['RegionType']} shows underdriving: earlier braking and lower minimum speed"

            if brake_point_target > brake_point_reference:
                indicator_type = "overdriving_indicator"
                indicator_summary = f"{segment['RegionType']} shows overdriving: later braking but lower minimum speed"

            findings.append(
                Finding(
                    finding_type=indicator_type,
                    region_type=str(segment["RegionType"]),
                    start_norm_distance=start,
                    end_norm_distance=end,
                    metric="driving_indicator_score",
                    observed=float(abs(min_speed_delta)),
                    reference=0.0,
                    delta=float(abs(min_speed_delta)),
                    summary=indicator_summary,
                ).to_dict()
            )

    findings_df = pd.DataFrame(findings)
    if findings_df.empty:
        return findings_df

    return findings_df.sort_values(["finding_type", "delta"], ascending=[True, False]).reset_index(drop=True)


def session_consistency_metrics(processed_laps: list[pd.DataFrame]) -> dict[str, float]:
    lap_times = [lap_time_s(lap) for lap in processed_laps]
    if not lap_times:
        return {"lap_time_mean_s": 0.0, "lap_time_std_s": 0.0, "lap_count": 0.0}

    return {
        "lap_time_mean_s": float(np.mean(lap_times)),
        "lap_time_std_s": float(np.std(lap_times)),
        "lap_count": float(len(lap_times)),
    }
