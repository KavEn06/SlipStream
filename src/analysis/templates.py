"""Deterministic templated text for each detector.

One function per detector, each taking the ``DetectorHit.metrics_snapshot``
dict plus the severity string. No LLM calls in v1 — every string is a
pure function of the metric values so snapshot tests stay stable.

``render_ai_context`` produces a second, richer string per finding that
contains every metric with labelled candidate and baseline values.  Callers
can pass this directly as part of an LLM prompt to generate bespoke coaching
advice beyond the canned ``templated_text``.
"""

from __future__ import annotations

from typing import Any

from src.analysis.detectors import (
    DETECTOR_ABRUPT_BRAKE_RELEASE,
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_LATE_BRAKING,
    DETECTOR_LONG_COASTING_PHASE,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_STEERING_INSTABILITY,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
    DETECTOR_WEAK_EXIT,
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
    if detector == DETECTOR_LATE_BRAKING:
        return _late_braking_text(corner_id, severity, metrics)
    if detector == DETECTOR_TRAIL_BRAKE_PAST_APEX:
        return _trail_brake_past_apex_text(corner_id, severity, metrics)
    if detector == DETECTOR_OVER_SLOW_MID_CORNER:
        return _over_slow_mid_corner_text(corner_id, severity, metrics)
    if detector == DETECTOR_EXIT_PHASE_LOSS:
        return _exit_phase_loss_text(corner_id, severity, metrics)
    if detector == DETECTOR_WEAK_EXIT:
        return _weak_exit_text(corner_id, severity, metrics)
    if detector == DETECTOR_STEERING_INSTABILITY:
        return _steering_instability_text(corner_id, severity, metrics)
    if detector == DETECTOR_ABRUPT_BRAKE_RELEASE:
        return _abrupt_brake_release_text(corner_id, severity, metrics)
    if detector == DETECTOR_LONG_COASTING_PHASE:
        return _long_coasting_phase_text(corner_id, severity, metrics)
    raise ValueError(f"Unknown detector: {detector}")


def render_ai_context(
    detector: str,
    corner_id: int,
    lap_number: int,
    severity: str,
    confidence: float,
    metrics: dict[str, Any],
) -> str:
    """Return a rich, fully-labelled context string for every detector.

    Every numeric metric is included with its candidate value, baseline value
    (where applicable), and the delta.  The string is self-contained so it
    can be prepended to an LLM prompt without any additional formatting.
    """
    if detector == DETECTOR_EARLY_BRAKING:
        return _early_braking_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_LATE_BRAKING:
        return _late_braking_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_TRAIL_BRAKE_PAST_APEX:
        return _trail_brake_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_OVER_SLOW_MID_CORNER:
        return _over_slow_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_EXIT_PHASE_LOSS:
        return _exit_phase_loss_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_WEAK_EXIT:
        return _weak_exit_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_STEERING_INSTABILITY:
        return _steering_instability_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_ABRUPT_BRAKE_RELEASE:
        return _abrupt_brake_release_ai(corner_id, lap_number, severity, confidence, metrics)
    if detector == DETECTOR_LONG_COASTING_PHASE:
        return _long_coasting_phase_ai(corner_id, lap_number, severity, confidence, metrics)
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


def _late_braking_text(corner_id: int, severity: str, m: dict[str, Any]) -> str:
    delta = abs(float(m["brake_point_delta_m"]))
    min_delta = float(m["min_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, braked {delta:.0f} m later than your best lap. "
            f"Try braking a touch earlier to carry more mid-corner speed. "
            f"{time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Late brake point ({delta:.0f} m past your best). "
        f"Overshooting cost {min_delta:+.1f} kph at the apex — "
        f"{time_loss:.2f} s lost. Brake earlier to avoid scrubbing speed."
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


def _weak_exit_text(corner_id: int, severity: str, m: dict[str, Any]) -> str:
    fraction = float(m["exit_full_throttle_fraction"])
    base_fraction = float(m["baseline_exit_full_throttle_fraction"])
    exit_delta = float(m["exit_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    pct = fraction * 100
    base_pct = base_fraction * 100
    if severity == "minor":
        return (
            f"In T{corner_id}, only {pct:.0f}% of the exit is at full throttle "
            f"(vs {base_pct:.0f}% on your best). Try committing to throttle "
            f"more decisively. {time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Tentative throttle on exit — {pct:.0f}% at full "
        f"throttle vs {base_pct:.0f}% on best lap. Exit speed "
        f"{exit_delta:+.1f} kph, {time_loss:.2f} s lost. Commit to full "
        f"throttle earlier once the car is pointed."
    )


def _steering_instability_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    count = int(m["exit_steering_correction_count"])
    base_count = int(m["baseline_exit_steering_correction_count"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, {count} steering corrections on exit "
            f"(vs {base_count} on your best). Try unwinding the wheel "
            f"more smoothly. {time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: {count} steering corrections on exit vs "
        f"{base_count} on best lap — the car isn't settled. "
        f"{time_loss:.2f} s lost. Focus on a smoother line through "
        f"the exit to build confidence on throttle."
    )


def _abrupt_brake_release_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    cand_rate = float(m["release_rate_per_s"])
    base_rate = float(m["baseline_release_rate_per_s"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, brake release is abrupt ({cand_rate:.1f}/s vs "
            f"{base_rate:.1f}/s on best). Try trailing off the pedal more "
            f"progressively. {time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Abrupt brake release ({cand_rate:.1f}/s vs "
        f"{base_rate:.1f}/s on best lap) — dropping the pedal suddenly "
        f"unsettles the car at turn-in. {time_loss:.2f} s lost. Trail off "
        f"the brake progressively to keep weight on the front axle."
    )


def _long_coasting_phase_text(
    corner_id: int, severity: str, m: dict[str, Any]
) -> str:
    coast_delta = float(m["coasting_delta_m"])
    min_delta = float(m["min_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    if severity == "minor":
        return (
            f"In T{corner_id}, coasting {coast_delta:.0f} m more than your "
            f"best. Try staying on either brake or throttle through the corner. "
            f"{time_loss:.2f} s lost."
        )
    return (
        f"T{corner_id}: Long coasting phase — {coast_delta:.0f} m more than "
        f"best lap with neither brake nor throttle applied. Apex speed "
        f"{min_delta:+.1f} kph vs best, {time_loss:.2f} s lost. Reduce the "
        f"neutral phase by trailing the brake deeper or picking up throttle earlier."
    )


# ---------------------------------------------------------------------------
# AI context — rich, fully-labelled metric strings
# ---------------------------------------------------------------------------


def _header(detector_label: str, corner_id: int, lap_number: int, severity: str, confidence: float, time_loss: float) -> str:
    return (
        f"[Finding] {detector_label} | T{corner_id} | Lap {lap_number}\n"
        f"Severity: {severity} | Confidence: {confidence:.2f} | Time lost: +{time_loss:.3f}s\n"
    )


def _early_braking_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_bp = float(m["candidate_brake_distance_m"])
    base_bp = float(m["baseline_brake_distance_m"])
    delta_bp = float(m["brake_point_delta_m"])
    entry_delta = float(m["entry_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    overlap_cand = float(m["brake_steering_overlap_m"])
    overlap_base = float(m["baseline_brake_steering_overlap_m"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Early braking", corner_id, lap_number, severity, confidence, time_loss)
        + f"Brake point: this lap {cand_bp:.1f} m | best lap {base_bp:.1f} m | delta {delta_bp:+.1f} m\n"
        f"Entry speed delta: {entry_delta:+.1f} kph (this lap vs best lap)\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
        f"Brake-steering overlap: this lap {overlap_cand:.1f} m | best lap {overlap_base:.1f} m | delta {overlap_cand - overlap_base:+.1f} m\n"
    )


def _late_braking_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_bp = float(m["candidate_brake_distance_m"])
    base_bp = float(m["baseline_brake_distance_m"])
    delta_bp = float(m["brake_point_delta_m"])
    min_delta = float(m["min_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    entry_delta = float(m["entry_speed_delta_kph"])
    overlap_cand = float(m["brake_steering_overlap_m"])
    overlap_base = float(m["baseline_brake_steering_overlap_m"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Late braking / overshoot", corner_id, lap_number, severity, confidence, time_loss)
        + f"Brake point: this lap {cand_bp:.1f} m | best lap {base_bp:.1f} m | delta {delta_bp:+.1f} m\n"
        f"Apex speed delta: {min_delta:+.1f} kph (this lap vs best lap)\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
        f"Entry speed delta: {entry_delta:+.1f} kph (this lap vs best lap)\n"
        f"Brake-steering overlap: this lap {overlap_cand:.1f} m | best lap {overlap_base:.1f} m | delta {overlap_cand - overlap_base:+.1f} m\n"
    )


def _trail_brake_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    trail = float(m["trail_brake_depth_m"])
    base_trail = float(m["baseline_trail_brake_depth_m"])
    min_delta = float(m["min_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Trail brake past apex", corner_id, lap_number, severity, confidence, time_loss)
        + f"Trail brake depth past apex: this lap {trail:.1f} m | best lap {base_trail:.1f} m | delta {trail - base_trail:+.1f} m\n"
        f"Apex speed delta: {min_delta:+.1f} kph (this lap vs best lap)\n"
    )


def _over_slow_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_min = float(m["candidate_min_speed_kph"])
    base_min = float(m["baseline_min_speed_kph"])
    min_delta = float(m["min_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    coasting_delta = float(m["coasting_delta_m"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Over-slow mid-corner", corner_id, lap_number, severity, confidence, time_loss)
        + f"Apex speed: this lap {cand_min:.1f} kph | best lap {base_min:.1f} kph | delta {min_delta:+.1f} kph\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
        f"Coasting distance delta: {coasting_delta:+.1f} m (this lap vs best lap)\n"
    )


def _exit_phase_loss_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_pu = float(m["candidate_pickup_distance_from_min_speed_m"])
    base_pu = float(m["baseline_pickup_distance_from_min_speed_m"])
    delay = float(m["throttle_pickup_delay_m"])
    exit_delta = float(m["exit_speed_delta_kph"])
    full_throttle_frac = float(m["exit_full_throttle_fraction"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Exit-phase loss (late throttle pickup)", corner_id, lap_number, severity, confidence, time_loss)
        + f"Throttle pickup from apex: this lap {cand_pu:.1f} m | best lap {base_pu:.1f} m | delay {delay:+.1f} m\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
        f"Exit full-throttle fraction: {full_throttle_frac:.2f} (this lap)\n"
    )


def _weak_exit_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_frac = float(m["exit_full_throttle_fraction"])
    base_frac = float(m["baseline_exit_full_throttle_fraction"])
    frac_delta = float(m["exit_full_throttle_fraction_delta"])
    exit_delta = float(m["exit_speed_delta_kph"])
    pickup_delay = float(m["throttle_pickup_delay_m"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Weak exit (tentative throttle)", corner_id, lap_number, severity, confidence, time_loss)
        + f"Exit full-throttle fraction: this lap {cand_frac:.2f} ({cand_frac*100:.0f}%) | best lap {base_frac:.2f} ({base_frac*100:.0f}%) | delta {-frac_delta:+.2f}\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
        f"Throttle pickup delay vs best: {pickup_delay:+.1f} m\n"
    )


def _steering_instability_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    count = int(m["exit_steering_correction_count"])
    base_count = int(m["baseline_exit_steering_correction_count"])
    delta = int(m["correction_count_delta"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Steering instability on exit", corner_id, lap_number, severity, confidence, time_loss)
        + f"Exit steering corrections: this lap {count} | best lap {base_count} | delta +{delta}\n"
    )


def _abrupt_brake_release_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_rate = float(m["release_rate_per_s"])
    base_rate = float(m["baseline_release_rate_per_s"])
    ratio = float(m["release_rate_ratio"])
    min_delta = float(m["min_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Abrupt brake release", corner_id, lap_number, severity, confidence, time_loss)
        + f"Release rate: this lap {cand_rate:.1f}/s | best lap {base_rate:.1f}/s | ratio {ratio:.1f}×\n"
        f"Apex speed delta: {min_delta:+.1f} kph (this lap vs best lap)\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
    )


def _long_coasting_phase_ai(
    corner_id: int, lap_number: int, severity: str, confidence: float, m: dict[str, Any]
) -> str:
    cand_coast = float(m["coasting_distance_m"])
    base_coast = float(m["baseline_coasting_distance_m"])
    coast_delta = float(m["coasting_delta_m"])
    min_delta = float(m["min_speed_delta_kph"])
    exit_delta = float(m["exit_speed_delta_kph"])
    time_loss = float(m["corner_time_delta_s"])
    return (
        _header("Long coasting phase", corner_id, lap_number, severity, confidence, time_loss)
        + f"Coasting distance: this lap {cand_coast:.1f} m | best lap {base_coast:.1f} m | delta {coast_delta:+.1f} m\n"
        f"Apex speed delta: {min_delta:+.1f} kph (this lap vs best lap)\n"
        f"Exit speed delta: {exit_delta:+.1f} kph (this lap vs best lap)\n"
    )
