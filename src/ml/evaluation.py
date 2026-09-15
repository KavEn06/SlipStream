"""Whole-lap evaluation metrics shared by offline model candidates."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np
import pandas as pd

from src.ml.dataset import PROFILE_TARGETS, LapDataset


def evaluate_sklearn_model(model: Any, dataset: LapDataset) -> Dict[str, float]:
    profiles = model.predict_profiles(dataset.sample_frame)
    sections = model.predict_section_pace(dataset.section_frame)
    laps = model.predict_lap_pace(dataset.lap_frame)
    return evaluate_predictions(
        dataset,
        profile_expected=profiles.expected,
        profile_lower=profiles.lower,
        profile_upper=profiles.upper,
        section_expected=sections.expected,
        lap_expected=laps.expected,
    )


def evaluate_torch_model(model: Any, dataset: LapDataset) -> Dict[str, float]:
    prediction = model.predict_dataset(dataset)
    return evaluate_predictions(
        dataset,
        profile_expected=prediction.profiles.expected,
        profile_lower=prediction.profiles.lower,
        profile_upper=prediction.profiles.upper,
        section_expected=prediction.section_pace.expected,
        lap_expected=prediction.lap_pace.expected,
    )


def evaluate_predictions(
    dataset: LapDataset,
    profile_expected: np.ndarray,
    profile_lower: np.ndarray,
    profile_upper: np.ndarray,
    section_expected: np.ndarray,
    lap_expected: np.ndarray,
) -> Dict[str, float]:
    samples = _ordered_samples(dataset)
    sections = _ordered_sections(dataset)
    laps = dataset.lap_frame.reset_index(drop=True)
    actual_profiles = samples[list(PROFILE_TARGETS)].to_numpy(dtype=float)
    profile_expected = np.asarray(profile_expected, dtype=float).reshape(actual_profiles.shape)
    profile_lower = np.asarray(profile_lower, dtype=float).reshape(actual_profiles.shape)
    profile_upper = np.asarray(profile_upper, dtype=float).reshape(actual_profiles.shape)
    actual_sections = sections["section_time_s"].to_numpy(dtype=float)
    section_expected = np.asarray(section_expected, dtype=float).reshape(-1)
    actual_laps = laps["lap_time_s"].to_numpy(dtype=float)
    lap_expected = np.asarray(lap_expected, dtype=float).reshape(-1)

    metrics: Dict[str, float] = {}
    absolute_error = np.abs(profile_expected - actual_profiles)
    for column, target in enumerate(PROFILE_TARGETS):
        metrics["{0}_mae".format(target)] = float(np.mean(absolute_error[:, column]))
        covered = (
            (actual_profiles[:, column] >= profile_lower[:, column])
            & (actual_profiles[:, column] <= profile_upper[:, column])
        )
        metrics["{0}_interval_coverage".format(target)] = float(np.mean(covered))

    speed_scale = max(float(np.nanpercentile(actual_profiles[:, 3], 95)), 1.0)
    normalized_profile_mae = np.column_stack(
        [
            absolute_error[:, 0],
            absolute_error[:, 1],
            absolute_error[:, 2],
            absolute_error[:, 3] / speed_scale,
        ]
    )
    metrics["profile_mae_normalized"] = float(np.mean(normalized_profile_mae))
    coverage = (actual_profiles >= profile_lower) & (actual_profiles <= profile_upper)
    metrics["interval_coverage"] = float(np.mean(coverage))
    metrics["section_pace_mae_s"] = float(np.mean(np.abs(section_expected - actual_sections)))
    metrics["lap_pace_mae_s"] = float(np.mean(np.abs(lap_expected - actual_laps)))
    metrics["pairwise_faster_lap_accuracy"] = pairwise_faster_lap_accuracy(
        laps, lap_expected
    )
    event_metrics = event_timing_errors(samples, profile_expected)
    metrics.update(event_metrics)
    metrics["composite_score"] = composite_score(metrics, dataset)
    return metrics


def pairwise_faster_lap_accuracy(
    lap_frame: pd.DataFrame,
    predicted_lap_times: Sequence[float],
) -> float:
    predictions = np.asarray(predicted_lap_times, dtype=float)
    correct = 0
    total = 0
    frame = lap_frame.reset_index(drop=True)
    for _, comparable in frame.groupby(["track_key", "car_key"], dropna=False):
        indices = comparable.index.to_numpy(dtype=int)
        for left_offset in range(len(indices)):
            for right_offset in range(left_offset + 1, len(indices)):
                left = indices[left_offset]
                right = indices[right_offset]
                actual_difference = float(frame.loc[left, "lap_time_s"]) - float(
                    frame.loc[right, "lap_time_s"]
                )
                if abs(actual_difference) <= 1e-9:
                    continue
                predicted_difference = predictions[left] - predictions[right]
                correct += int(np.sign(actual_difference) == np.sign(predicted_difference))
                total += 1
    return float(correct / total) if total else 0.5


def event_timing_errors(
    ordered_samples: pd.DataFrame,
    predicted_profiles: np.ndarray,
) -> Dict[str, float]:
    brake_errors: List[float] = []
    throttle_errors: List[float] = []
    offset = 0
    for _, lap_samples in ordered_samples.groupby("lap_key", sort=False):
        count = len(lap_samples)
        prediction = predicted_profiles[offset : offset + count]
        progress = lap_samples["progress"].to_numpy(dtype=float)
        actual_brake = lap_samples["brake"].to_numpy(dtype=float)
        actual_throttle = lap_samples["throttle"].to_numpy(dtype=float)
        brake_error = _event_error(progress, actual_brake, prediction[:, 1], threshold=0.10)
        throttle_error = _event_error(
            progress, actual_throttle, prediction[:, 0], threshold=0.20
        )
        if brake_error is not None:
            brake_errors.append(brake_error)
        if throttle_error is not None:
            throttle_errors.append(throttle_error)
        offset += count
    return {
        "brake_event_progress_mae": float(np.mean(brake_errors)) if brake_errors else 0.0,
        "throttle_event_progress_mae": (
            float(np.mean(throttle_errors)) if throttle_errors else 0.0
        ),
    }


def composite_score(metrics: Mapping[str, float], dataset: LapDataset) -> float:
    """Declared lower-is-better candidate selection objective."""

    section_scale = max(
        float(np.median(dataset.section_frame["section_time_s"].to_numpy(dtype=float))),
        1e-3,
    )
    lap_scale = max(
        float(np.median(dataset.lap_frame["lap_time_s"].to_numpy(dtype=float))),
        1e-3,
    )
    ranking_error = 1.0 - float(metrics["pairwise_faster_lap_accuracy"])
    coverage_error = abs(float(metrics["interval_coverage"]) - 0.80)
    event_error = 0.5 * (
        float(metrics["brake_event_progress_mae"])
        + float(metrics["throttle_event_progress_mae"])
    )
    return float(
        0.35 * float(metrics["profile_mae_normalized"])
        + 0.20 * float(metrics["section_pace_mae_s"]) / section_scale
        + 0.20 * float(metrics["lap_pace_mae_s"]) / lap_scale
        + 0.15 * ranking_error
        + 0.05 * coverage_error
        + 0.05 * event_error
    )


def average_metrics(fold_metrics: Iterable[Mapping[str, float]]) -> Dict[str, float]:
    rows = list(fold_metrics)
    if not rows:
        return {}
    names = sorted(set.intersection(*(set(row) for row in rows)))
    return {
        name: float(np.mean([float(row[name]) for row in rows]))
        for name in names
    }


def _event_error(
    progress: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    threshold: float,
) -> Any:
    actual_indices = np.flatnonzero(actual >= threshold)
    predicted_indices = np.flatnonzero(predicted >= threshold)
    if not len(actual_indices) or not len(predicted_indices):
        return None
    return abs(float(progress[actual_indices[0]]) - float(progress[predicted_indices[0]]))


def _ordered_samples(dataset: LapDataset) -> pd.DataFrame:
    order = {lap_key: index for index, lap_key in enumerate(dataset.lap_keys)}
    frame = dataset.sample_frame.copy()
    frame["_lap_order"] = frame["lap_key"].map(order)
    return frame.sort_values(["_lap_order", "progress"]).drop(columns=["_lap_order"]).reset_index(drop=True)


def _ordered_sections(dataset: LapDataset) -> pd.DataFrame:
    order = {lap_key: index for index, lap_key in enumerate(dataset.lap_keys)}
    frame = dataset.section_frame.copy()
    frame["_lap_order"] = frame["lap_key"].map(order)
    return (
        frame.sort_values(["_lap_order", "section_index"])
        .drop(columns=["_lap_order"])
        .reset_index(drop=True)
    )
