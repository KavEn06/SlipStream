"""Session summary: theoretical best lap, corner cards, and session theme.

This is a pure synthesis layer that sits on top of the existing analysis
pipeline output.  It does not touch raw telemetry or re-run detectors —
it simply assembles a coaching-oriented view from ``per_corner_records``,
``per_corner_baselines``, ``straight_records``, ``findings_all``, and
``corner_definitions``.

The output is designed so an external AI (or the frontend) can present
one story per corner, a session-level priority list, and the driver's
theoretical best lap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import CORNER_CARDS_SESSION_CAP
from src.analysis.corner_records import CornerRecord, StraightRecord
from src.analysis.findings import Finding
from src.processing.segmentation import CornerDefinition


# ---------------------------------------------------------------------------
# Detector label / chart / delta mappings
# ---------------------------------------------------------------------------

_DETECTOR_LABELS: dict[str, str] = {
    "early_braking": "Braking too early",
    "late_braking": "Braking too late / overshoot",
    "trail_brake_past_apex": "Trail braking past apex",
    "over_slow_mid_corner": "Too slow through the apex",
    "exit_phase_loss": "Late throttle pickup on exit",
    "weak_exit": "Tentative throttle on exit",
    "steering_instability": "Steering corrections on exit",
}

_DETECTOR_CHARTS: dict[str, list[str]] = {
    "early_braking": ["speed", "brake", "racing_line"],
    "late_braking": ["speed", "brake", "racing_line"],
    "trail_brake_past_apex": ["speed", "brake", "steering"],
    "over_slow_mid_corner": ["speed", "brake", "throttle", "racing_line"],
    "exit_phase_loss": ["speed", "throttle"],
    "weak_exit": ["speed", "throttle"],
    "steering_instability": ["steering", "speed"],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CornerCard:
    """One coaching card per corner where time was left on the table."""

    corner_id: int
    direction: str
    corner_start_m: float
    corner_end_m: float
    apex_m: float
    time_left_s: float
    primary_issue: str
    primary_detector: str
    causal_explanation: str
    best_example_lap: int
    compared_lap: int
    measurable_deltas: list[str]
    position_context: dict[str, float]
    charts_to_inspect: list[str]
    ai_context: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSummary:
    """Top-level session coaching summary."""

    theoretical_best_lap_s: float
    best_actual_lap_s: float
    best_actual_lap_number: int
    gap_to_theoretical_s: float
    biggest_time_left_corners: list[dict[str, Any]]
    main_repeated_theme: str
    main_repeated_theme_total_loss_s: float
    corner_cards: list[CornerCard]

    def to_dict(self) -> dict[str, Any]:
        return {
            "theoretical_best_lap_s": self.theoretical_best_lap_s,
            "best_actual_lap_s": self.best_actual_lap_s,
            "best_actual_lap_number": self.best_actual_lap_number,
            "gap_to_theoretical_s": self.gap_to_theoretical_s,
            "biggest_time_left_corners": list(self.biggest_time_left_corners),
            "main_repeated_theme": self.main_repeated_theme,
            "main_repeated_theme_total_loss_s": self.main_repeated_theme_total_loss_s,
            "corner_cards": [c.to_dict() for c in self.corner_cards],
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_session_summary(
    *,
    per_corner_records: dict[int, list[CornerRecord]],
    per_corner_baselines: dict[int, CornerBaseline],
    straight_records: list[StraightRecord],
    findings_all: list[Finding],
    corner_definitions: list[CornerDefinition],
    per_lap_lap_times: dict[int, float],
    reference_length_m: float,
) -> SessionSummary:
    """Build the session coaching summary from existing analysis artifacts."""

    # -- theoretical best lap ------------------------------------------------
    corner_best_sum = sum(
        bl.reference_record.corner_time_s
        for bl in per_corner_baselines.values()
    )
    straight_best_sum = _best_straight_sum(straight_records)
    theoretical_best_s = corner_best_sum + straight_best_sum

    # -- best actual lap -----------------------------------------------------
    best_actual_lap_number = min(per_lap_lap_times, key=per_lap_lap_times.get)  # type: ignore[arg-type]
    best_actual_lap_s = per_lap_lap_times[best_actual_lap_number]
    gap = best_actual_lap_s - theoretical_best_s

    # -- corner cards --------------------------------------------------------
    corner_def_index = {cd.corner_id: cd for cd in corner_definitions}
    cards = _build_corner_cards(
        findings_all=findings_all,
        per_corner_baselines=per_corner_baselines,
        corner_def_index=corner_def_index,
        reference_length_m=reference_length_m,
    )

    # -- biggest time-left corners (top 3) -----------------------------------
    biggest = [
        {
            "corner_id": c.corner_id,
            "time_left_s": c.time_left_s,
            "direction": c.direction,
        }
        for c in cards[:3]
    ]

    # -- main repeated theme -------------------------------------------------
    theme, theme_loss = _compute_theme(findings_all)

    return SessionSummary(
        theoretical_best_lap_s=theoretical_best_s,
        best_actual_lap_s=best_actual_lap_s,
        best_actual_lap_number=best_actual_lap_number,
        gap_to_theoretical_s=gap,
        biggest_time_left_corners=biggest,
        main_repeated_theme=theme,
        main_repeated_theme_total_loss_s=theme_loss,
        corner_cards=cards,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _best_straight_sum(straight_records: list[StraightRecord]) -> float:
    """Sum of the fastest time through each straight across all laps."""
    best: dict[int, float] = {}
    for sr in straight_records:
        if sr.straight_id not in best or sr.time_s < best[sr.straight_id]:
            best[sr.straight_id] = sr.time_s
    return sum(best.values())


def _ranking_key(finding: Finding) -> float:
    return abs(finding.time_loss_s) * finding.confidence


def _build_corner_cards(
    *,
    findings_all: list[Finding],
    per_corner_baselines: dict[int, CornerBaseline],
    corner_def_index: dict[int, CornerDefinition],
    reference_length_m: float,
) -> list[CornerCard]:
    """One card per corner, ordered by time_left_s descending."""
    # Group findings by corner, pick highest-ranking per corner.
    by_corner: dict[int, list[Finding]] = {}
    for f in findings_all:
        by_corner.setdefault(f.corner_id, []).append(f)

    cards: list[CornerCard] = []
    for corner_id, findings in by_corner.items():
        top_finding = max(findings, key=_ranking_key)
        corner_def = corner_def_index.get(corner_id)
        # Sub-corner IDs (e.g. 802) map to parent corner (8) for position data.
        if corner_def is None and corner_id > 100:
            corner_def = corner_def_index.get(corner_id // 100)
        baseline = per_corner_baselines.get(corner_id)
        # Sub-corner baselines aren't stored on SessionAnalysis; use parent.
        if baseline is None and corner_id > 100:
            baseline = per_corner_baselines.get(corner_id // 100)

        # Position data — fall back to zeros for sub-corners without a definition.
        if corner_def is not None:
            direction = corner_def.direction
            start_m = corner_def.start_distance_m
            end_m = corner_def.end_distance_m
            apex_m = corner_def.center_distance_m
        else:
            direction = "unknown"
            start_m = 0.0
            end_m = 0.0
            apex_m = 0.0

        best_example_lap = baseline.reference_lap_number if baseline else 0

        deltas = _measurable_deltas(top_finding)
        pos_ctx = _position_context(
            corner_def=corner_def,
            metrics=top_finding.metrics_snapshot,
            reference_length_m=reference_length_m,
        )
        charts = _DETECTOR_CHARTS.get(top_finding.detector, ["speed"])
        ai_ctx = _enrich_ai_context(
            base_context=top_finding.ai_context,
            corner_def=corner_def,
            metrics=top_finding.metrics_snapshot,
        )

        cards.append(CornerCard(
            corner_id=corner_id,
            direction=direction,
            corner_start_m=start_m,
            corner_end_m=end_m,
            apex_m=apex_m,
            time_left_s=top_finding.time_loss_s,
            primary_issue=_DETECTOR_LABELS.get(top_finding.detector, top_finding.detector),
            primary_detector=top_finding.detector,
            causal_explanation=top_finding.templated_text,
            best_example_lap=best_example_lap,
            compared_lap=top_finding.lap_number,
            measurable_deltas=deltas,
            position_context=pos_ctx,
            charts_to_inspect=charts,
            ai_context=ai_ctx,
        ))

    cards.sort(key=lambda c: c.time_left_s, reverse=True)
    return cards[:CORNER_CARDS_SESSION_CAP]


def _measurable_deltas(finding: Finding) -> list[str]:
    """Pick the 2–3 most relevant deltas for the finding's detector type."""
    m = finding.metrics_snapshot
    detector = finding.detector

    if detector == "early_braking":
        return [
            f"Brake point: {abs(float(m.get('brake_point_delta_m', 0))):.0f} m earlier",
            f"Entry speed: {float(m.get('entry_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "late_braking":
        return [
            f"Brake point: {abs(float(m.get('brake_point_delta_m', 0))):.0f} m later",
            f"Apex speed: {float(m.get('min_speed_delta_kph', 0)):+.1f} kph",
            f"Exit speed: {float(m.get('exit_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "trail_brake_past_apex":
        return [
            f"Trail brake depth: {float(m.get('trail_brake_depth_m', 0)):.0f} m past apex",
            f"Apex speed: {float(m.get('min_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "over_slow_mid_corner":
        return [
            f"Apex speed: {float(m.get('min_speed_delta_kph', 0)):+.1f} kph",
            f"Exit speed: {float(m.get('exit_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "exit_phase_loss":
        return [
            f"Throttle pickup: {float(m.get('throttle_pickup_delay_m', 0)):.0f} m later",
            f"Exit speed: {float(m.get('exit_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "weak_exit":
        cand = float(m.get("exit_full_throttle_fraction", 0)) * 100
        base = float(m.get("baseline_exit_full_throttle_fraction", 0)) * 100
        return [
            f"Full throttle: {cand:.0f}% vs {base:.0f}%",
            f"Exit speed: {float(m.get('exit_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "steering_instability":
        return [
            f"Corrections: {int(m.get('exit_steering_correction_count', 0))} "
            f"vs {int(m.get('baseline_exit_steering_correction_count', 0))}",
        ]
    return []


def _position_context(
    *,
    corner_def: CornerDefinition | None,
    metrics: dict[str, Any],
    reference_length_m: float,
) -> dict[str, float]:
    """Track-position context dict for the card."""
    ctx: dict[str, float] = {}
    if corner_def is not None:
        ctx["corner_start_m"] = corner_def.start_distance_m
        ctx["corner_end_m"] = corner_def.end_distance_m
        ctx["apex_m"] = corner_def.center_distance_m

    # Braking detectors include brake point distance.
    if "candidate_brake_distance_m" in metrics:
        ctx["brake_point_m"] = float(metrics["candidate_brake_distance_m"])
    if "baseline_brake_distance_m" in metrics:
        ctx["baseline_brake_point_m"] = float(metrics["baseline_brake_distance_m"])

    # Throttle detectors: convert progress to meters if available.
    if "candidate_pickup_distance_from_min_speed_m" in metrics:
        ctx["throttle_pickup_from_apex_m"] = float(
            metrics["candidate_pickup_distance_from_min_speed_m"]
        )
    if "baseline_pickup_distance_from_min_speed_m" in metrics:
        ctx["baseline_throttle_pickup_from_apex_m"] = float(
            metrics["baseline_pickup_distance_from_min_speed_m"]
        )

    return ctx


def _enrich_ai_context(
    *,
    base_context: str,
    corner_def: CornerDefinition | None,
    metrics: dict[str, Any],
) -> str:
    """Append position-anchored lines to the finding's existing ai_context."""
    lines: list[str] = []

    if corner_def is not None:
        lines.append(
            f"Track position: corner from {corner_def.start_distance_m:.0f} m "
            f"to {corner_def.end_distance_m:.0f} m | "
            f"apex at {corner_def.center_distance_m:.0f} m | "
            f"direction: {corner_def.direction}"
        )

    if "candidate_brake_distance_m" in metrics:
        lines.append(
            f"Brake point on track: this lap at "
            f"{float(metrics['candidate_brake_distance_m']):.0f} m | "
            f"best lap at {float(metrics['baseline_brake_distance_m']):.0f} m"
        )

    if not lines:
        return base_context
    return base_context + "\n".join(lines) + "\n"


def _compute_theme(findings_all: list[Finding]) -> tuple[str, float]:
    """Return the dominant detector label and its accumulated time loss."""
    if not findings_all:
        return ("No issues detected", 0.0)

    loss_by_detector: dict[str, float] = {}
    for f in findings_all:
        loss_by_detector[f.detector] = loss_by_detector.get(f.detector, 0.0) + f.time_loss_s

    dominant = max(loss_by_detector, key=loss_by_detector.get)  # type: ignore[arg-type]
    label = _DETECTOR_LABELS.get(dominant, dominant)
    return (label, loss_by_detector[dominant])
