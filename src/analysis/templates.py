"""Deterministic templated text for each detector.

One function per detector, each taking the ``DetectorHit.metrics_snapshot``
dict plus the severity string. No LLM calls in v1 — every string is a
pure function of the metric values so snapshot tests stay stable.
"""

from __future__ import annotations

from typing import Any

from src.analysis.detectors import (
    DETECTOR_ABRUPT_BRAKE_RELEASE,
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
)


def render_finding_text(
    detector: str,
    corner_id: int,
    severity: str,
    metrics: dict[str, Any],
) -> str:
    """Dispatch to the per-detector template function."""
    if detector == DETECTOR_EARLY_BRAKING:
        return _early_braking_text(corner_id, severity, metrics)
    if detector == DETECTOR_TRAIL_BRAKE_PAST_APEX:
        return _trail_brake_past_apex_text(corner_id, severity, metrics)
    if detector == DETECTOR_ABRUPT_BRAKE_RELEASE:
        return _abrupt_brake_release_text(corner_id, severity, metrics)
    if detector == DETECTOR_OVER_SLOW_MID_CORNER:
        return _over_slow_mid_corner_text(corner_id, severity, metrics)
    if detector == DETECTOR_EXIT_PHASE_LOSS:
        return _exit_phase_loss_text(corner_id, severity, metrics)
    raise ValueError(f"Unknown detector: {detector}")


# ---------------------------------------------------------------------------
# Per-detector templates
# ---------------------------------------------------------------------------


def _early_braking_text(corner_id: int, severity: str, m: dict[str, Any]) -> str:
    delta = abs(float(m["brake_point_delta_m"]))
    time_loss = float(m["corner_time_delta_s"])
    exit_delta = float(m["exit_speed_delta_kph"])
    if severity == "minor":
        return (
            f"In T{corner_id}, braked {delta:.0f} m earlier than your best lap "
            f"through here, costing {time_loss:.2f} s. Try delaying turn-in "
            f"brake point."
        )
    return (
        f"T{corner_id}: Early brake point ({delta:.0f} m before your best), "
        f"{time_loss:.2f} s lost. Exit speed {exit_delta:+.1f} kph vs best — "
        f"early braking isn't buying exit, it's costing time."
    )


def _trail_brake_past_apex_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    trail_depth = float(m["trail_brake_depth_m"])
    min_delta = float(m["min_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, brake is held {trail_depth:.0f} m past the "
            f"slowest point. Try releasing a touch earlier to let the car "
            f"rotate. {time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Still trail braking {trail_depth:.0f} m past your "
        f"slowest point. Min speed {min_delta:+.1f} kph vs best — releasing "
        f"brake earlier should let the car rotate. {time_loss:.2f} s lost."
    )


def _abrupt_brake_release_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    release_value = float(m["release_brake_value"])
    release_rate = float(m["release_rate_per_s"])
    min_delta = float(m["min_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, brake release is a bit abrupt "
            f"({release_rate:.1f}/s from {release_value:.2f}). Smoothing "
            f"the transition may improve turn-in stability. {time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Abrupt brake release (dropped from {release_value:.2f} "
        f"at {release_rate:.1f}/s). Car pitches up, min speed {min_delta:+.1f} "
        f"kph vs best. {time_loss:.2f} s lost."
    )


def _over_slow_mid_corner_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    min_delta = float(m["min_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, mid-corner speed is {min_delta:+.1f} kph "
            f"below your best. Look for a bit more speed through the middle. "
            f"{time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Min speed {min_delta:+.1f} kph below best AND exit "
        f"speed {exit_delta:+.1f} kph below best — {time_loss:.2f} s lost. "
        f"You're leaving mid-corner speed on the table without gaining it back."
    )


def _exit_phase_loss_text(corner_id: int, severity: str, m: dict[str, Any]) -> str:
    pickup_delay = float(m["throttle_pickup_delay_m"])
    exit_delta = float(m["exit_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, throttle pickup is {pickup_delay:.0f} m later "
            f"than your best. A slightly earlier commit could help. "
            f"{time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Throttle pickup {pickup_delay:.0f} m later than best. "
        f"Exit speed {exit_delta:+.1f} kph, {time_loss:.2f} s lost. Commit "
        f"earlier on exit."
    )
