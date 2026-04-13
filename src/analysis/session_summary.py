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
from src.analysis.constants import CORNER_CARD_MIN_ACCUMULATED_LOSS_S, CORNER_CARDS_SESSION_CAP
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
    "abrupt_brake_release": "Abrupt brake release",
    "long_coasting_phase": "Long coasting phase",
}

_DETECTOR_CHARTS: dict[str, list[str]] = {
    "early_braking": ["speed", "brake", "racing_line"],
    "late_braking": ["speed", "brake", "racing_line"],
    "trail_brake_past_apex": ["speed", "brake", "steering"],
    "over_slow_mid_corner": ["speed", "brake", "throttle", "racing_line"],
    "exit_phase_loss": ["speed", "throttle"],
    "weak_exit": ["speed", "throttle"],
    "steering_instability": ["steering", "speed"],
    "abrupt_brake_release": ["brake", "speed"],
    "long_coasting_phase": ["throttle", "brake", "speed"],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CornerCard:
    """One coaching card per corner where time was left on the table.

    ``time_left_s`` is the average time loss per affected lap (not the
    worst-lap peak), so systematic corners score proportionally to how
    often they hurt rather than how bad their worst single lap was.

    ``laps_affected`` counts how many laps had a finding at this corner,
    giving context for how repeatable the issue is.
    """

    corner_id: int
    direction: str
    corner_start_m: float
    corner_end_m: float
    apex_m: float
    time_left_s: float          # mean time loss across affected laps
    laps_affected: int          # how many laps triggered a finding here
    primary_issue: str
    primary_detector: str
    causal_explanation: str
    best_example_lap: int
    compared_lap: int
    measurable_deltas: list[str]
    position_context: dict[str, float]
    charts_to_inspect: list[str]
    ai_context: str
    best_lap_corner_time_s: float | None = None
    best_lap_delta_s: float | None = None

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
    top_themes: list[dict[str, Any]]   # up to 3 dominant issues across session
    corner_cards: list[CornerCard]
    per_best_lap_corner_breakdown: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "theoretical_best_lap_s": self.theoretical_best_lap_s,
            "best_actual_lap_s": self.best_actual_lap_s,
            "best_actual_lap_number": self.best_actual_lap_number,
            "gap_to_theoretical_s": self.gap_to_theoretical_s,
            "biggest_time_left_corners": list(self.biggest_time_left_corners),
            "top_themes": list(self.top_themes),
            "corner_cards": [c.to_dict() for c in self.corner_cards],
            "per_best_lap_corner_breakdown": list(self.per_best_lap_corner_breakdown),
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
        per_corner_records=per_corner_records,
        best_actual_lap_number=best_actual_lap_number,
        corner_def_index=corner_def_index,
        reference_length_m=reference_length_m,
    )

    # -- biggest time-left corners (top 3, using accumulated loss) -----------
    biggest = [
        {
            "corner_id": c.corner_id,
            "time_left_s": c.time_left_s,
            "laps_affected": c.laps_affected,
            "direction": c.direction,
        }
        for c in cards[:3]
    ]

    # -- per best-lap corner breakdown --------------------------------------
    best_lap_breakdown = _build_best_lap_breakdown(
        per_corner_records=per_corner_records,
        per_corner_baselines=per_corner_baselines,
        best_actual_lap_number=best_actual_lap_number,
    )

    # -- top themes ----------------------------------------------------------
    top_themes = _compute_top_themes(findings_all)

    return SessionSummary(
        theoretical_best_lap_s=theoretical_best_s,
        best_actual_lap_s=best_actual_lap_s,
        best_actual_lap_number=best_actual_lap_number,
        gap_to_theoretical_s=gap,
        biggest_time_left_corners=biggest,
        top_themes=top_themes,
        corner_cards=cards,
        per_best_lap_corner_breakdown=best_lap_breakdown,
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


def _resolve_apex_m(corner_id: int, corner_def: CornerDefinition) -> float:
    """Return the correct apex distance for a corner or sub-corner.

    Sub-corner IDs encode their parent (corner_id // 100) and their
    1-based index within the parent (corner_id % 100).  We look that
    index up in ``sub_apex_distances_m``; if it's out of range we fall
    back to the parent corner's centre distance.
    """
    if corner_id <= 100:
        return corner_def.center_distance_m
    sub_idx = (corner_id % 100) - 1  # convert to 0-based
    distances = corner_def.sub_apex_distances_m
    if distances and 0 <= sub_idx < len(distances):
        return distances[sub_idx]
    return corner_def.center_distance_m


def _build_corner_cards(
    *,
    findings_all: list[Finding],
    per_corner_baselines: dict[int, CornerBaseline],
    per_corner_records: dict[int, list[CornerRecord]],
    best_actual_lap_number: int,
    corner_def_index: dict[int, CornerDefinition],
    reference_length_m: float,
) -> list[CornerCard]:
    """One card per corner, ordered by accumulated time loss descending.

    ``time_left_s`` is the *average* loss per affected lap so a corner
    that's 0.15 s slow on every lap scores its true average (0.15 s)
    rather than being buried by a one-off 0.25 s hit elsewhere.

    Cards are sorted by *accumulated* loss (average × laps_affected) so
    systematic corners rise to the top over single-lap outliers.
    """
    by_corner: dict[int, list[Finding]] = {}
    for f in findings_all:
        by_corner.setdefault(f.corner_id, []).append(f)

    cards: list[CornerCard] = []
    for corner_id, findings in by_corner.items():
        top_finding = max(findings, key=_ranking_key)

        # Systematic scoring: average loss per affected lap; sort by total.
        laps_affected = len(findings)
        avg_time_left = sum(f.time_loss_s for f in findings) / laps_affected

        # Min accumulated loss gate — suppress micro-loss single-lap noise.
        if avg_time_left * laps_affected < CORNER_CARD_MIN_ACCUMULATED_LOSS_S:
            continue

        # Resolve corner definition — sub-corners fall back to parent.
        corner_def = corner_def_index.get(corner_id)
        if corner_def is None and corner_id > 100:
            corner_def = corner_def_index.get(corner_id // 100)

        # Resolve baseline — sub-corner baselines use parent as proxy.
        baseline = per_corner_baselines.get(corner_id)
        if baseline is None and corner_id > 100:
            baseline = per_corner_baselines.get(corner_id // 100)

        # Position: sub-corners get their precise apex from sub_apex_distances_m.
        if corner_def is not None:
            direction = corner_def.direction
            start_m = corner_def.start_distance_m
            end_m = corner_def.end_distance_m
            apex_m = _resolve_apex_m(corner_id, corner_def)
        else:
            direction = "unknown"
            start_m = 0.0
            end_m = 0.0
            apex_m = 0.0

        best_example_lap = baseline.reference_lap_number if baseline else 0

        # Best-lap fields: how did the best actual lap do at this corner?
        best_lap_corner_time_s, best_lap_delta_s = _best_lap_corner_delta(
            corner_id=corner_id,
            per_corner_records=per_corner_records,
            per_corner_baselines=per_corner_baselines,
            best_actual_lap_number=best_actual_lap_number,
        )

        deltas = _measurable_deltas(top_finding)
        pos_ctx = _position_context(
            corner_def=corner_def,
            apex_m=apex_m,
            metrics=top_finding.metrics_snapshot,
        )
        charts = _DETECTOR_CHARTS.get(top_finding.detector, ["speed"])
        ai_ctx = _enrich_ai_context(
            base_context=top_finding.ai_context,
            corner_def=corner_def,
            apex_m=apex_m,
            metrics=top_finding.metrics_snapshot,
        )

        cards.append(CornerCard(
            corner_id=corner_id,
            direction=direction,
            corner_start_m=start_m,
            corner_end_m=end_m,
            apex_m=apex_m,
            time_left_s=avg_time_left,
            laps_affected=laps_affected,
            primary_issue=_DETECTOR_LABELS.get(top_finding.detector, top_finding.detector),
            primary_detector=top_finding.detector,
            causal_explanation=top_finding.templated_text,
            best_example_lap=best_example_lap,
            compared_lap=top_finding.lap_number,
            measurable_deltas=deltas,
            position_context=pos_ctx,
            charts_to_inspect=charts,
            ai_context=ai_ctx,
            best_lap_corner_time_s=best_lap_corner_time_s,
            best_lap_delta_s=best_lap_delta_s,
        ))

    # Sort by accumulated loss (average × laps) so systematic corners rank higher.
    cards.sort(
        key=lambda c: c.time_left_s * c.laps_affected,
        reverse=True,
    )
    return cards[:CORNER_CARDS_SESSION_CAP]


def _best_lap_corner_delta(
    *,
    corner_id: int,
    per_corner_records: dict[int, list[CornerRecord]],
    per_corner_baselines: dict[int, CornerBaseline],
    best_actual_lap_number: int,
) -> tuple[float | None, float | None]:
    """Return (corner_time_s, delta_s) for the best actual lap at this corner.

    Returns ``(None, None)`` if no record exists for that lap at that corner.
    """
    # Find the best lap's record at this corner.
    records = per_corner_records.get(corner_id, [])
    best_rec = next(
        (r for r in records if r.lap_number == best_actual_lap_number), None
    )
    if best_rec is None:
        return None, None

    # Resolve baseline (sub-corners fall back to parent).
    baseline = per_corner_baselines.get(corner_id)
    if baseline is None and corner_id > 100:
        baseline = per_corner_baselines.get(corner_id // 100)
    if baseline is None:
        return best_rec.corner_time_s, None

    delta = best_rec.corner_time_s - baseline.reference_record.corner_time_s
    return best_rec.corner_time_s, max(delta, 0.0)


def _build_best_lap_breakdown(
    *,
    per_corner_records: dict[int, list[CornerRecord]],
    per_corner_baselines: dict[int, CornerBaseline],
    best_actual_lap_number: int,
) -> list[dict[str, Any]]:
    """Per-corner breakdown of the best actual lap vs per-corner baselines.

    Only corners where the best lap was slower than the baseline are included.
    Sorted by ``delta_s`` descending.
    """
    breakdown: list[dict[str, Any]] = []
    for corner_id, records in per_corner_records.items():
        best_rec = next(
            (r for r in records if r.lap_number == best_actual_lap_number), None
        )
        if best_rec is None:
            continue
        baseline = per_corner_baselines.get(corner_id)
        if baseline is None:
            continue
        delta = best_rec.corner_time_s - baseline.reference_record.corner_time_s
        if delta > 0:
            breakdown.append({
                "corner_id": corner_id,
                "corner_time_s": best_rec.corner_time_s,
                "baseline_time_s": baseline.reference_record.corner_time_s,
                "delta_s": round(delta, 4),
                "baseline_lap_number": baseline.reference_lap_number,
            })
    breakdown.sort(key=lambda x: x["delta_s"], reverse=True)
    return breakdown


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
    if detector == "abrupt_brake_release":
        return [
            f"Release rate: {float(m.get('release_rate_per_s', 0)):.1f}/s "
            f"vs {float(m.get('baseline_release_rate_per_s', 0)):.1f}/s",
            f"Apex speed: {float(m.get('min_speed_delta_kph', 0)):+.1f} kph",
        ]
    if detector == "long_coasting_phase":
        return [
            f"Coasting: {float(m.get('coasting_delta_m', 0)):.0f} m more than best",
            f"Apex speed: {float(m.get('min_speed_delta_kph', 0)):+.1f} kph",
        ]
    return []


def _position_context(
    *,
    corner_def: CornerDefinition | None,
    apex_m: float,
    metrics: dict[str, Any],
) -> dict[str, float]:
    """Track-position context dict for the card."""
    ctx: dict[str, float] = {}
    if corner_def is not None:
        ctx["corner_start_m"] = corner_def.start_distance_m
        ctx["corner_end_m"] = corner_def.end_distance_m
        ctx["apex_m"] = apex_m  # already resolved for sub-corners

    if "candidate_brake_distance_m" in metrics:
        ctx["brake_point_m"] = float(metrics["candidate_brake_distance_m"])
    if "baseline_brake_distance_m" in metrics:
        ctx["baseline_brake_point_m"] = float(metrics["baseline_brake_distance_m"])

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
    apex_m: float,
    metrics: dict[str, Any],
) -> str:
    """Append position-anchored lines to the finding's existing ai_context."""
    lines: list[str] = []

    if corner_def is not None:
        lines.append(
            f"Track position: corner from {corner_def.start_distance_m:.0f} m "
            f"to {corner_def.end_distance_m:.0f} m | "
            f"apex at {apex_m:.0f} m | "
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


def _compute_top_themes(findings_all: list[Finding]) -> list[dict[str, Any]]:
    """Return up to 3 dominant session themes ordered by accumulated time loss.

    Each theme dict contains:
    - ``detector``:  raw detector constant
    - ``label``:     human-readable label
    - ``total_loss_s``: accumulated time loss across all findings of that type
    - ``corner_count``: number of distinct corners affected
    """
    if not findings_all:
        return []

    loss_by_detector: dict[str, float] = {}
    corners_by_detector: dict[str, set[int]] = {}
    for f in findings_all:
        loss_by_detector[f.detector] = (
            loss_by_detector.get(f.detector, 0.0) + f.time_loss_s
        )
        corners_by_detector.setdefault(f.detector, set()).add(f.corner_id)

    ranked = sorted(loss_by_detector, key=loss_by_detector.get, reverse=True)  # type: ignore[arg-type]
    return [
        {
            "detector": det,
            "label": _DETECTOR_LABELS.get(det, det),
            "total_loss_s": loss_by_detector[det],
            "corner_count": len(corners_by_detector[det]),
        }
        for det in ranked[:3]
    ]
