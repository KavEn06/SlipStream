"""Seven detectors for the corner analysis layer.

Each detector is a pure function that takes a candidate ``CornerRecord``
and its per-corner ``CornerBaseline`` and returns a ``DetectorHit | None``.
``DetectorHit`` is a thin intermediate: it carries the raw metrics,
telemetry strength, and evidence pointers that ``findings.py`` later turns
into a :class:`src.analysis.findings.Finding` (with confidence scoring,
severity binning, and templated text).

Detectors do **not** compute confidence or mutual-suppression rules. Those
happen in the ranking pass so we can reason about the full candidate set
at once.

A universal gate is applied before any detector runs via
:func:`run_all_detectors`. See the module docstring of
``src.analysis.baselines`` for the corresponding baseline strategy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import (
    ALIGNMENT_QUALITY_POOR_M,
    EARLY_BRAKE_DELTA_M,
    EXIT_PHASE_LOSS_THROTTLE_DELAY_M,
    LATE_BRAKE_DELTA_M,
    OVER_SLOW_EXIT_SPEED_DELTA_KPH,
    OVER_SLOW_MIN_SPEED_DELTA_KPH,
    STEERING_INSTABILITY_BASELINE_CEILING,
    STEERING_INSTABILITY_CORRECTION_DELTA,
    STEERING_INSTABILITY_CORRECTION_FLOOR,
    TIME_LOSS_GATE_S,
    TRAIL_BRAKE_PAST_APEX_M,
    WEAK_EXIT_EXIT_SPEED_DELTA_KPH,
    WEAK_EXIT_FRACTION_DELTA,
)
from src.analysis.corner_records import CornerRecord


DETECTOR_EARLY_BRAKING = "early_braking"
DETECTOR_LATE_BRAKING = "late_braking"
DETECTOR_TRAIL_BRAKE_PAST_APEX = "trail_brake_past_apex"
DETECTOR_OVER_SLOW_MID_CORNER = "over_slow_mid_corner"
DETECTOR_EXIT_PHASE_LOSS = "exit_phase_loss"
DETECTOR_WEAK_EXIT = "weak_exit"
DETECTOR_STEERING_INSTABILITY = "steering_instability"


@dataclass(frozen=True)
class DetectorHit:
    """Raw detector output before confidence scoring / templated text.

    Attributes
    ----------
    detector:
        Stable identifier for the detector (one of the ``DETECTOR_*``
        constants in this module).
    corner_id, lap_number:
        Identify the candidate record the hit came from.
    time_loss_s:
        ``candidate.corner_time_s - baseline.reference_record.corner_time_s``
        — always positive for emitted hits (universal gate enforces this).
    pattern_strength:
        Value in ``[0, 1]`` quantifying how hard the telemetry gate was
        exceeded. Used by ``findings.py`` as one of the three confidence
        sub-scores.
    metrics_snapshot:
        The raw numbers the detector considered. Written verbatim into the
        finding JSON so downstream consumers (LLM coach, frontend) can see
        the evidence.
    evidence_refs:
        Pointers to telemetry windows the frontend can draw as traces.
        Each ref is ``{"column": str, "progress_start": float,
        "progress_end": float}``.
    """

    detector: str
    corner_id: int
    lap_number: int
    time_loss_s: float
    pattern_strength: float
    metrics_snapshot: dict[str, Any]
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Universal gate + top-level runner
# ---------------------------------------------------------------------------


def universal_gate(record: CornerRecord, baseline: CornerBaseline) -> float | None:
    """Return the corner time delta if the record passes the universal gate.

    The universal gate enforces, in order:
      1. The candidate is not the baseline lap.
      2. The candidate's alignment did not use fallback inside the corner.
      3. The candidate's median alignment residual is below the poor-threshold.
      4. The corner time delta exceeds :data:`TIME_LOSS_GATE_S`.

    If any check fails we return ``None`` and the detectors are skipped. If
    all pass we return the (positive) time delta for detector reuse.
    """
    if record.lap_number == baseline.reference_lap_number:
        return None
    if record.alignment_used_fallback:
        return None
    if record.alignment_quality_m >= ALIGNMENT_QUALITY_POOR_M:
        return None
    delta = record.corner_time_s - baseline.reference_record.corner_time_s
    if delta <= TIME_LOSS_GATE_S:
        return None
    return float(delta)


def run_all_detectors(
    record: CornerRecord, baseline: CornerBaseline
) -> list[DetectorHit]:
    """Run every detector against one (record, baseline) pair.

    Mutual-suppression rules are NOT applied here — they operate over the
    full candidate pool in ``findings.py``. This function only enforces the
    universal gate and collects raw hits.
    """
    time_loss_s = universal_gate(record, baseline)
    if time_loss_s is None:
        return []

    hits: list[DetectorHit] = []
    for detector_fn in (
        detect_early_braking,
        detect_late_braking,
        detect_trail_brake_past_apex,
        detect_over_slow_mid_corner,
        detect_exit_phase_loss,
        detect_weak_exit,
        detect_steering_instability,
    ):
        hit = detector_fn(record, baseline, time_loss_s)
        if hit is not None:
            hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# H.1 — Early braking
# ---------------------------------------------------------------------------


def detect_early_braking(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record
    if record.brake is None or base.brake is None:
        return None

    brake_point_delta_m = (
        record.brake.initiation_distance_m - base.brake.initiation_distance_m
    )
    # Candidate braked >= EARLY_BRAKE_DELTA_M earlier than baseline.
    if brake_point_delta_m > -EARLY_BRAKE_DELTA_M:
        return None

    exit_speed_delta_kph = record.exit.exit_speed_kph - base.exit.exit_speed_kph
    # The early brake must not have bought a better exit — otherwise it's a
    # valid alternative line, not a mistake.
    if exit_speed_delta_kph > 0.0:
        return None

    # False-positive: candidate arrived meaningfully hotter → early brake is
    # prudent, not wasteful.
    entry_speed_delta = record.entry.entry_speed_kph - base.entry.entry_speed_kph
    if entry_speed_delta > 5.0:
        return None

    # False-positive: baseline was coasting, not braking — comparison is
    # degenerate. Guard against zero baseline decel.
    baseline_decel = abs(base.brake.avg_decel_mps2)
    candidate_decel = abs(record.brake.avg_decel_mps2)
    if baseline_decel < 1e-3 or candidate_decel < 1e-3:
        return None
    if baseline_decel * 1.5 < candidate_decel:
        return None

    pattern_strength = _saturate(
        (abs(brake_point_delta_m) - EARLY_BRAKE_DELTA_M) / EARLY_BRAKE_DELTA_M
    )

    metrics = {
        "brake_point_delta_m": brake_point_delta_m,
        "candidate_brake_distance_m": record.brake.initiation_distance_m,
        "baseline_brake_distance_m": base.brake.initiation_distance_m,
        "exit_speed_delta_kph": exit_speed_delta_kph,
        "entry_speed_delta_kph": entry_speed_delta,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "Brake",
            "progress_start": float(record.brake.initiation_progress_norm),
            "progress_end": float(record.brake.release_progress_norm),
        },
        {
            "column": "SpeedKph",
            "progress_start": float(record.brake.initiation_progress_norm),
            "progress_end": float(record.apex.min_speed_progress_norm),
        },
    ]
    return DetectorHit(
        detector=DETECTOR_EARLY_BRAKING,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.2 — Trail brake past apex
# ---------------------------------------------------------------------------


def detect_trail_brake_past_apex(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record
    if record.brake is None or base.brake is None:
        return None

    # Compound corners run detectors on sub-records separately.
    if record.is_compound:
        return None

    trail_depth = record.brake.trail_brake_depth_m
    if trail_depth <= TRAIL_BRAKE_PAST_APEX_M:
        return None

    min_speed_delta = record.apex.min_speed_kph - base.apex.min_speed_kph
    if min_speed_delta >= -1.0:
        return None

    # False-positive: this corner naturally needs late trail braking (the
    # baseline lap trailed too). Allow a 2 m margin.
    if base.brake.trail_brake_depth_m >= trail_depth - 2.0:
        return None

    pattern_strength = _saturate(
        (trail_depth - TRAIL_BRAKE_PAST_APEX_M) / TRAIL_BRAKE_PAST_APEX_M
    )

    metrics = {
        "trail_brake_depth_m": trail_depth,
        "baseline_trail_brake_depth_m": base.brake.trail_brake_depth_m,
        "min_speed_delta_kph": min_speed_delta,
        "corner_time_delta_s": time_loss_s,
    }
    release_p = float(record.brake.release_progress_norm)
    apex_p = float(record.apex.min_speed_progress_norm)
    evidence = [
        {
            "column": "Brake",
            "progress_start": min(release_p, apex_p),
            "progress_end": max(release_p, apex_p),
        },
        {
            "column": "SpeedKph",
            "progress_start": min(release_p, apex_p),
            "progress_end": max(release_p, apex_p),
        },
    ]
    return DetectorHit(
        detector=DETECTOR_TRAIL_BRAKE_PAST_APEX,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.3 — Late braking / overshoot
# ---------------------------------------------------------------------------


def detect_late_braking(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record
    if record.brake is None or base.brake is None:
        return None

    brake_point_delta_m = (
        record.brake.initiation_distance_m - base.brake.initiation_distance_m
    )
    # Candidate braked >= LATE_BRAKE_DELTA_M later than baseline.
    if brake_point_delta_m < LATE_BRAKE_DELTA_M:
        return None

    min_speed_delta = record.apex.min_speed_kph - base.apex.min_speed_kph
    exit_speed_delta = record.exit.exit_speed_kph - base.exit.exit_speed_kph

    # Overshoot confirmation: the late brake must have hurt.
    if min_speed_delta >= -2.0 and exit_speed_delta >= -3.0:
        return None

    # False-positive: exit speed gained means the late brake was a
    # legitimate aggressive line.
    if exit_speed_delta > 0.0:
        return None

    # False-positive: candidate arrived meaningfully slower — the later
    # brake is due to lower approach speed, not overshooting.
    entry_speed_delta = record.entry.entry_speed_kph - base.entry.entry_speed_kph
    if entry_speed_delta < -3.0:
        return None

    # Baseline decel guard (same as early_braking).
    baseline_decel = abs(base.brake.avg_decel_mps2)
    candidate_decel = abs(record.brake.avg_decel_mps2)
    if baseline_decel < 1e-3 or candidate_decel < 1e-3:
        return None

    pattern_strength = _saturate(
        (brake_point_delta_m - LATE_BRAKE_DELTA_M) / LATE_BRAKE_DELTA_M
    )

    metrics = {
        "brake_point_delta_m": brake_point_delta_m,
        "candidate_brake_distance_m": record.brake.initiation_distance_m,
        "baseline_brake_distance_m": base.brake.initiation_distance_m,
        "min_speed_delta_kph": min_speed_delta,
        "exit_speed_delta_kph": exit_speed_delta,
        "entry_speed_delta_kph": entry_speed_delta,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "Brake",
            "progress_start": float(record.brake.initiation_progress_norm),
            "progress_end": float(record.brake.release_progress_norm),
        },
        {
            "column": "SpeedKph",
            "progress_start": float(record.brake.initiation_progress_norm),
            "progress_end": float(record.apex.min_speed_progress_norm),
        },
    ]
    return DetectorHit(
        detector=DETECTOR_LATE_BRAKING,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.4 — Over-slowing mid-corner
# ---------------------------------------------------------------------------


def detect_over_slow_mid_corner(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record

    min_speed_delta = record.apex.min_speed_kph - base.apex.min_speed_kph
    if min_speed_delta > OVER_SLOW_MIN_SPEED_DELTA_KPH:
        return None

    exit_speed_delta = record.exit.exit_speed_kph - base.exit.exit_speed_kph
    if exit_speed_delta > OVER_SLOW_EXIT_SPEED_DELTA_KPH:
        return None

    pattern_strength = _saturate(
        (abs(min_speed_delta) - abs(OVER_SLOW_MIN_SPEED_DELTA_KPH))
        / max(abs(OVER_SLOW_MIN_SPEED_DELTA_KPH), 1.0)
    )

    metrics = {
        "min_speed_delta_kph": min_speed_delta,
        "exit_speed_delta_kph": exit_speed_delta,
        "candidate_min_speed_kph": record.apex.min_speed_kph,
        "baseline_min_speed_kph": base.apex.min_speed_kph,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "SpeedKph",
            "progress_start": float(record.apex.min_speed_progress_norm) - 0.02,
            "progress_end": float(record.exit.min_speed_progress_norm) + 0.02,
        },
    ]
    return DetectorHit(
        detector=DETECTOR_OVER_SLOW_MID_CORNER,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.5 — Exit-phase loss (merged late throttle + weak exit)
# ---------------------------------------------------------------------------


def detect_exit_phase_loss(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record
    if record.throttle is None or base.throttle is None:
        return None

    candidate_pickup = record.throttle.pickup_distance_from_min_speed_m
    baseline_pickup = base.throttle.pickup_distance_from_min_speed_m
    pickup_delay_m = candidate_pickup - baseline_pickup
    exit_speed_delta = record.exit.exit_speed_kph - base.exit.exit_speed_kph

    primary_gate = pickup_delay_m >= EXIT_PHASE_LOSS_THROTTLE_DELAY_M
    secondary_gate = exit_speed_delta < -3.0 and pickup_delay_m >= 3.0
    if not (primary_gate or secondary_gate):
        return None

    # False-positive: isolated throttle dip with nothing else wrong → v2.
    if (
        record.throttle.throttle_dip_detected
        and pickup_delay_m < EXIT_PHASE_LOSS_THROTTLE_DELAY_M
        and exit_speed_delta >= -1.0
    ):
        return None

    pattern_strength = _saturate(
        max(
            (pickup_delay_m - EXIT_PHASE_LOSS_THROTTLE_DELAY_M)
            / EXIT_PHASE_LOSS_THROTTLE_DELAY_M,
            abs(min(exit_speed_delta, 0.0)) / 10.0,
        )
    )

    metrics = {
        "throttle_pickup_delay_m": pickup_delay_m,
        "candidate_pickup_distance_from_min_speed_m": candidate_pickup,
        "baseline_pickup_distance_from_min_speed_m": baseline_pickup,
        "exit_speed_delta_kph": exit_speed_delta,
        "exit_full_throttle_fraction": record.throttle.exit_full_throttle_fraction,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "Throttle",
            "progress_start": float(record.apex.min_speed_progress_norm),
            "progress_end": float(record.throttle.pickup_progress_norm) + 0.03,
        },
        {
            "column": "SpeedKph",
            "progress_start": float(record.apex.min_speed_progress_norm),
            "progress_end": float(record.apex.min_speed_progress_norm) + 0.05,
        },
    ]
    return DetectorHit(
        detector=DETECTOR_EXIT_PHASE_LOSS,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.6 — Weak exit (tentative throttle application)
# ---------------------------------------------------------------------------


def detect_weak_exit(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record
    if record.throttle is None or base.throttle is None:
        return None

    # Both must have a meaningful full-throttle reference.
    if base.throttle.exit_full_throttle_fraction < 0.20:
        return None

    cand_fraction = record.throttle.exit_full_throttle_fraction
    base_fraction = base.throttle.exit_full_throttle_fraction
    fraction_delta = base_fraction - cand_fraction
    if fraction_delta < WEAK_EXIT_FRACTION_DELTA:
        return None

    exit_speed_delta = record.exit.exit_speed_kph - base.exit.exit_speed_kph
    if exit_speed_delta > WEAK_EXIT_EXIT_SPEED_DELTA_KPH:
        return None

    # Guard: if throttle pickup is very late, this is an exit_phase_loss
    # problem, not a weak_exit problem.
    pickup_delay_m = (
        record.throttle.pickup_distance_from_min_speed_m
        - base.throttle.pickup_distance_from_min_speed_m
    )
    if pickup_delay_m >= EXIT_PHASE_LOSS_THROTTLE_DELAY_M:
        return None

    pattern_strength = _saturate(
        (fraction_delta - WEAK_EXIT_FRACTION_DELTA) / 0.30
    )

    metrics = {
        "exit_full_throttle_fraction": cand_fraction,
        "baseline_exit_full_throttle_fraction": base_fraction,
        "exit_full_throttle_fraction_delta": fraction_delta,
        "exit_speed_delta_kph": exit_speed_delta,
        "throttle_pickup_delay_m": pickup_delay_m,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "Throttle",
            "progress_start": float(record.throttle.pickup_progress_norm),
            "progress_end": float(record.apex.min_speed_progress_norm) + 0.08,
        },
        {
            "column": "SpeedKph",
            "progress_start": float(record.apex.min_speed_progress_norm),
            "progress_end": float(record.apex.min_speed_progress_norm) + 0.08,
        },
    ]
    return DetectorHit(
        detector=DETECTOR_WEAK_EXIT,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# H.7 — Steering instability on exit
# ---------------------------------------------------------------------------


def detect_steering_instability(
    record: CornerRecord, baseline: CornerBaseline, time_loss_s: float
) -> DetectorHit | None:
    base = baseline.reference_record

    # Compound corners naturally have multiple direction changes.
    if record.is_compound:
        return None

    cand_count = record.exit_steering_correction_count
    base_count = base.exit_steering_correction_count

    # Absolute floor — need at least this many corrections to be meaningful.
    if cand_count < STEERING_INSTABILITY_CORRECTION_FLOOR:
        return None

    # Skip corners where even the baseline is noisy.
    if base_count >= STEERING_INSTABILITY_BASELINE_CEILING:
        return None

    delta = cand_count - base_count
    if delta < STEERING_INSTABILITY_CORRECTION_DELTA:
        return None

    pattern_strength = _saturate((delta - STEERING_INSTABILITY_CORRECTION_DELTA) / 5.0)

    metrics = {
        "exit_steering_correction_count": cand_count,
        "baseline_exit_steering_correction_count": base_count,
        "correction_count_delta": delta,
        "corner_time_delta_s": time_loss_s,
    }
    evidence = [
        {
            "column": "Steering",
            "progress_start": float(record.exit.min_speed_progress_norm),
            "progress_end": float(record.exit.min_speed_progress_norm) + 0.08,
        },
    ]
    return DetectorHit(
        detector=DETECTOR_STEERING_INSTABILITY,
        corner_id=record.corner_id,
        lap_number=record.lap_number,
        time_loss_s=time_loss_s,
        pattern_strength=pattern_strength,
        metrics_snapshot=metrics,
        evidence_refs=evidence,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _saturate(value: float) -> float:
    """Clamp to ``[0.0, 1.0]``."""
    if value != value:  # NaN guard
        return 0.0
    return float(max(0.0, min(1.0, value)))
