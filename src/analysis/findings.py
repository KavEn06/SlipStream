"""Convert ``DetectorHit`` instances into ranked, text-ready ``Finding``s.

This module is the bridge between raw detector output and the serialized
output JSON. It applies, in order:

1. **Confidence scoring.** Each hit's ``pattern_strength`` is combined with
   a cost-significance sub-score and an alignment-quality sub-score into a
   scalar in ``[0, 1]``.
2. **Confidence gate.** Hits below :data:`CONFIDENCE_MIN` are dropped.
3. **Severity classification.** Binned from ``time_loss_s``.
4. **Templated text.** Deterministic per detector, via :mod:`templates`.
5. **Mutual suppression.** Per-corner suppression rules from plan §H:
   - over-slow-mid is suppressed if trail-brake-past-apex fires on the
     same (corner, lap).
   - exit-phase-loss is suppressed if over-slow-mid fires with a larger
     time loss on the same (corner, lap).
6. **Per-corner cap.** Top ``FINDINGS_PER_CORNER_CAP`` per corner by the
   ranking key.
7. **Session cap.** Top ``FINDINGS_SESSION_TOP_CAP`` surfaced as
   ``findings_top``; everything else goes to ``findings_all``.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from src.analysis.baselines import CornerBaseline
from src.analysis.constants import (
    ALIGNMENT_QUALITY_GOOD_M,
    ALIGNMENT_QUALITY_POOR_M,
    CONFIDENCE_MIN,
    COST_SIGNIFICANCE_CEIL_S,
    COST_SIGNIFICANCE_FLOOR_S,
    FINDINGS_PER_CORNER_CAP,
    FINDINGS_SESSION_TOP_CAP,
    SEVERITY_MAJOR_S,
    SEVERITY_MINOR_S,
    SEVERITY_MODERATE_S,
)
from src.analysis.corner_records import CornerRecord
from src.analysis.detectors import (
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_LATE_BRAKING,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
    DETECTOR_WEAK_EXIT,
    DetectorHit,
)
from src.analysis.templates import render_ai_context, render_finding_text


SEVERITY_MINOR = "minor"
SEVERITY_MODERATE = "moderate"
SEVERITY_MAJOR = "major"


@dataclass(frozen=True)
class Finding:
    finding_id: str
    corner_id: int
    lap_number: int
    detector: str
    severity: str
    confidence: float
    time_loss_s: float
    templated_text: str
    ai_context: str
    evidence_refs: list[dict[str, Any]]
    metrics_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FindingSet:
    findings_top: list[Finding]
    findings_all: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings_top": [f.to_dict() for f in self.findings_top],
            "findings_all": [f.to_dict() for f in self.findings_all],
        }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def compute_confidence(
    *,
    pattern_strength: float,
    time_loss_s: float,
    alignment_quality_m: float,
) -> float:
    """Combine three sub-scores into a scalar confidence.

    - ``pattern_strength`` — detector-provided, already in ``[0, 1]``.
    - ``cost_significance`` — linear ramp from ``COST_SIGNIFICANCE_FLOOR_S``
      to ``COST_SIGNIFICANCE_CEIL_S``.
    - ``alignment_quality_score`` — ``1.0`` below ``ALIGNMENT_QUALITY_GOOD_M``,
      linear decay to ``0.0`` at ``ALIGNMENT_QUALITY_POOR_M``.
    """
    pattern = _clamp01(pattern_strength)
    cost = _cost_significance_score(time_loss_s)
    alignment = _alignment_quality_score(alignment_quality_m)
    return float(pattern * cost * alignment)


def _cost_significance_score(time_loss_s: float) -> float:
    if time_loss_s <= COST_SIGNIFICANCE_FLOOR_S:
        return 0.0
    if time_loss_s >= COST_SIGNIFICANCE_CEIL_S:
        return 1.0
    span = COST_SIGNIFICANCE_CEIL_S - COST_SIGNIFICANCE_FLOOR_S
    return float((time_loss_s - COST_SIGNIFICANCE_FLOOR_S) / span)


def _alignment_quality_score(alignment_quality_m: float) -> float:
    if alignment_quality_m <= ALIGNMENT_QUALITY_GOOD_M:
        return 1.0
    if alignment_quality_m >= ALIGNMENT_QUALITY_POOR_M:
        return 0.0
    span = ALIGNMENT_QUALITY_POOR_M - ALIGNMENT_QUALITY_GOOD_M
    return float(1.0 - (alignment_quality_m - ALIGNMENT_QUALITY_GOOD_M) / span)


def classify_severity(time_loss_s: float) -> str:
    if time_loss_s >= SEVERITY_MAJOR_S:
        return SEVERITY_MAJOR
    if time_loss_s >= SEVERITY_MODERATE_S:
        return SEVERITY_MODERATE
    if time_loss_s >= SEVERITY_MINOR_S:
        return SEVERITY_MINOR
    return SEVERITY_MINOR


def _clamp01(value: float) -> float:
    if value != value:  # NaN
        return 0.0
    return max(0.0, min(1.0, float(value)))


# ---------------------------------------------------------------------------
# Building Findings
# ---------------------------------------------------------------------------


def build_findings(
    hits: Iterable[DetectorHit],
    records_by_corner: dict[int, list[CornerRecord]],
) -> FindingSet:
    """Turn a flat list of detector hits into a ranked ``FindingSet``.

    Parameters
    ----------
    hits:
        All raw detector hits across every (corner, lap) pair.
    records_by_corner:
        Used to look up the candidate record's alignment quality (needed for
        the confidence sub-score). Keyed by ``corner_id``.
    """
    record_index = _index_records(records_by_corner)

    candidates: list[Finding] = []
    for hit in hits:
        record = record_index.get((hit.corner_id, hit.lap_number))
        if record is None:
            continue
        confidence = compute_confidence(
            pattern_strength=hit.pattern_strength,
            time_loss_s=hit.time_loss_s,
            alignment_quality_m=record.alignment_quality_m,
        )
        if confidence < CONFIDENCE_MIN:
            continue
        severity = classify_severity(hit.time_loss_s)
        text = render_finding_text(
            detector=hit.detector,
            corner_id=hit.corner_id,
            severity=severity,
            metrics=hit.metrics_snapshot,
        )
        ai_ctx = render_ai_context(
            detector=hit.detector,
            corner_id=hit.corner_id,
            lap_number=hit.lap_number,
            severity=severity,
            confidence=confidence,
            metrics=hit.metrics_snapshot,
        )
        candidates.append(
            Finding(
                finding_id=_finding_id(hit),
                corner_id=hit.corner_id,
                lap_number=hit.lap_number,
                detector=hit.detector,
                severity=severity,
                confidence=confidence,
                time_loss_s=hit.time_loss_s,
                templated_text=text,
                ai_context=ai_ctx,
                evidence_refs=list(hit.evidence_refs),
                metrics_snapshot=dict(hit.metrics_snapshot),
            )
        )

    # Mutual suppression applies per (corner, lap) pair.
    candidates = _apply_mutual_suppression(candidates)

    findings_all = _cap_per_corner(candidates, FINDINGS_PER_CORNER_CAP)
    findings_top = _session_top(findings_all, FINDINGS_SESSION_TOP_CAP)
    return FindingSet(findings_top=findings_top, findings_all=findings_all)


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _ranking_key(finding: Finding) -> float:
    return abs(finding.time_loss_s) * finding.confidence


def _cap_per_corner(findings: list[Finding], cap: int) -> list[Finding]:
    by_corner: dict[int, list[Finding]] = {}
    for finding in findings:
        by_corner.setdefault(finding.corner_id, []).append(finding)
    capped: list[Finding] = []
    for corner_id, group in by_corner.items():
        group_sorted = sorted(group, key=_ranking_key, reverse=True)
        capped.extend(group_sorted[:cap])
    # Keep global ordering stable for downstream consumers.
    return sorted(capped, key=_ranking_key, reverse=True)


def _session_top(findings: list[Finding], cap: int) -> list[Finding]:
    return sorted(findings, key=_ranking_key, reverse=True)[:cap]


def _apply_mutual_suppression(findings: list[Finding]) -> list[Finding]:
    """Drop redundant findings per (corner, lap).

    Suppression follows a root-cause hierarchy: upstream causes suppress their
    downstream symptoms so the driver sees the actionable root cause, not a pile
    of consequences that all trace back to the same mistake.

    Entry causes  →  Apex symptom  →  Exit consequence
    ─────────────────────────────────────────────────
    early_braking         ↓                  ↓
    late_braking          ↓                  ↓
                       over_slow       exit_phase_loss → weak_exit
    trail_brake    →   over_slow
                                   steering_instability (independent)

    NOTE: all detectors receive the same ``time_loss_s`` (the full corner
    delta from the universal gate), so magnitude-based "which lost more"
    comparisons are meaningless — do not use them here.
    """
    by_pair: dict[tuple[int, int], list[Finding]] = {}
    for finding in findings:
        by_pair.setdefault((finding.corner_id, finding.lap_number), []).append(finding)

    kept: list[Finding] = []
    for group in by_pair.values():
        detectors_in_group = {f.detector: f for f in group}
        early_brake = detectors_in_group.get(DETECTOR_EARLY_BRAKING)
        late_brake = detectors_in_group.get(DETECTOR_LATE_BRAKING)
        trail_brake = detectors_in_group.get(DETECTOR_TRAIL_BRAKE_PAST_APEX)
        over_slow = detectors_in_group.get(DETECTOR_OVER_SLOW_MID_CORNER)
        exit_loss = detectors_in_group.get(DETECTOR_EXIT_PHASE_LOSS)
        weak_exit = detectors_in_group.get(DETECTOR_WEAK_EXIT)

        dropped_ids: set[str] = set()

        # Early braking and late braking are mutually exclusive (you can't brake
        # both too early AND too late on the same lap). Keep the higher-ranking
        # one so the driver sees the dominant root cause.
        if early_brake is not None and late_brake is not None:
            if _ranking_key(early_brake) >= _ranking_key(late_brake):
                dropped_ids.add(late_brake.finding_id)
            else:
                dropped_ids.add(early_brake.finding_id)

        # Entry causes dominate apex symptom + exit consequence.
        for entry_cause in (early_brake, late_brake):
            if entry_cause is not None:
                if over_slow is not None:
                    dropped_ids.add(over_slow.finding_id)
                if exit_loss is not None:
                    dropped_ids.add(exit_loss.finding_id)

        # Trail-brake-past-apex dominates over-slow-mid: the held brake caused
        # the slow apex, over_slow is a downstream symptom.
        if trail_brake is not None and over_slow is not None:
            dropped_ids.add(over_slow.finding_id)

        # exit_phase_loss dominates weak_exit: late pickup is the root cause
        # of not reaching full throttle.
        if exit_loss is not None and weak_exit is not None:
            dropped_ids.add(weak_exit.finding_id)

        # over_slow and exit_phase_loss are INDEPENDENT phases (apex vs exit).
        # steering_instability is fully independent of all other detectors.

        for finding in group:
            if finding.finding_id not in dropped_ids:
                kept.append(finding)
    return kept


def _index_records(
    records_by_corner: dict[int, list[CornerRecord]],
) -> dict[tuple[int, int], CornerRecord]:
    index: dict[tuple[int, int], CornerRecord] = {}
    for corner_id, records in records_by_corner.items():
        for record in records:
            index[(corner_id, record.lap_number)] = record
    return index


def _finding_id(hit: DetectorHit) -> str:
    """Stable short hash identifying a (detector, corner, lap) triple."""
    payload = f"{hit.detector}|{hit.corner_id}|{hit.lap_number}".encode()
    return hashlib.sha1(payload).hexdigest()[:12]
