"""Session-level orchestrator for the corner analysis layer.

Reads the existing processed artifacts for a session, runs every analysis
layer step in order, and writes ``session_analysis.json`` under the
session's processed directory. Safe to re-run without reprocessing the
session: this module never touches raw telemetry or reference paths.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.analysis.baselines import (
    CornerBaseline,
    build_per_corner_baselines,
    group_records_by_corner,
)
from src.analysis.constants import (
    ANALYSIS_VERSION,
    LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S,
)
from src.analysis.corner_records import (
    CornerRecord,
    StraightRecord,
    extract_corner_records,
)
from src.analysis.detectors import (
    DEFAULT_DETECTORS,
    EXPERIMENTAL_DETECTORS,
    DetectorHit,
    run_all_detectors,
)
from src.analysis.findings import Finding, FindingSet, build_findings
from src.analysis.session_summary import SessionSummary, build_session_summary
from src.core.config import PROCESSED_DATA_ROOT, get_settings
from src.processing.alignment import resample_aligned_lap
from src.processing.segmentation import (
    CornerDefinition,
    StraightDefinition,
    TrackSegmentation,
)
from src.ml.inference import MLInferenceResult, MLProductInferenceService
from src.services.telemetry_store import TelemetryDatastore


ANALYSIS_ARTIFACT_FILENAME = "session_analysis.json"


# ---------------------------------------------------------------------------
# Top-level dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionAnalysis:
    analysis_version: str
    session_id: str
    reference_lap_number: int
    analyzed_at_utc: str
    per_corner_records: dict[int, list[CornerRecord]]
    per_corner_baselines: dict[int, CornerBaseline]
    straight_records: list[StraightRecord]
    findings_top: list[Finding]
    findings_all: list[Finding]
    lap_time_delta_reconciliation: dict[int, dict[str, float]]
    corner_definitions: list[CornerDefinition] = field(default_factory=list)
    reference_length_m: float = 0.0
    session_summary: SessionSummary | None = None
    quality_report: dict[str, Any] = field(default_factory=dict)
    detector_configuration: dict[str, Any] = field(default_factory=dict)
    ml_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_version": self.analysis_version,
            "session_id": self.session_id,
            "reference_lap_number": self.reference_lap_number,
            "analyzed_at_utc": self.analyzed_at_utc,
            "reference_length_m": self.reference_length_m,
            "corner_definitions": [asdict(c) for c in self.corner_definitions],
            "per_corner_records": {
                str(corner_id): [r.to_dict() for r in records]
                for corner_id, records in self.per_corner_records.items()
            },
            "per_corner_baselines": {
                str(corner_id): baseline.to_dict()
                for corner_id, baseline in self.per_corner_baselines.items()
            },
            "straight_records": [r.to_dict() for r in self.straight_records],
            "findings_top": [f.to_dict() for f in self.findings_top],
            "findings_all": [f.to_dict() for f in self.findings_all],
            "lap_time_delta_reconciliation": {
                str(lap): dict(entry)
                for lap, entry in self.lap_time_delta_reconciliation.items()
            },
            "session_summary": (
                self.session_summary.to_dict() if self.session_summary else None
            ),
            "quality_report": dict(self.quality_report),
            "detector_configuration": dict(self.detector_configuration),
            "ml_context": dict(self.ml_context),
        }


class ReconciliationError(RuntimeError):
    """Raised when per-corner + per-straight time deltas fail to reconcile."""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run(
    session_id: str,
    *,
    processed_root: Path | None = None,
    write: bool = True,
    strict_reconciliation: bool = True,
    datastore: TelemetryDatastore | None = None,
    experimental_detectors: Optional[bool] = None,
    enable_ml: bool = True,
) -> SessionAnalysis:
    """Run the full analysis pipeline for a session.

    Parameters
    ----------
    session_id:
        The session directory name under ``processed_root``.
    processed_root:
        Override for the processed-data root. Defaults to
        :data:`PROCESSED_DATA_ROOT`. Used by the integration test.
    write:
        If ``True`` (default), persist ``session_analysis.json`` to disk.
    strict_reconciliation:
        If ``True``, raise :class:`ReconciliationError` when the per-corner
        + per-straight time deltas for any non-baseline lap drift more than
        :data:`LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S` from the actual
        lap-time delta. Tests with synthetic fixtures may want to disable.
    """
    root = processed_root or PROCESSED_DATA_ROOT
    session_dir = root / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Processed session directory not found: {session_dir}")

    metadata = _load_metadata(session_dir)
    segmentation = _load_segmentation(session_dir)
    include_experimental = (
        experimental_detectors
        if experimental_detectors is not None
        else get_settings().experimental_detectors_enabled
    )
    usable_lap_numbers = _usable_lap_numbers(metadata)
    if not usable_lap_numbers:
        raise ValueError(f"No usable laps for session {session_id!r}")

    # Per-lap extraction.
    per_lap_records: dict[int, list[CornerRecord]] = {}
    per_lap_straights: dict[int, list[StraightRecord]] = {}
    per_lap_lap_time: dict[int, float] = {}
    processed_laps: dict[int, pd.DataFrame] = {}
    for lap_number in usable_lap_numbers:
        processed_lap = _load_processed_lap(
            session_dir,
            lap_number,
            datastore=datastore,
            session_id=session_id,
        )
        if processed_lap.empty:
            continue
        processed_laps[lap_number] = processed_lap
        resampled = resample_aligned_lap(processed_lap)
        corners, straights = extract_corner_records(
            resampled_lap=resampled,
            processed_lap=processed_lap,
            segmentation=segmentation,
            lap_number=lap_number,
        )
        per_lap_records[lap_number] = corners
        per_lap_straights[lap_number] = straights
        per_lap_lap_time[lap_number] = _lap_time_s(processed_lap)

    ml_result = _run_optional_ml_inference(
        session_id=session_id,
        processed_laps=processed_laps,
        metadata=metadata,
        datastore=datastore,
        enabled=enable_ml,
    )

    # Group by corner and compute baselines.
    flat_records = [r for recs in per_lap_records.values() for r in recs]
    records_by_corner = group_records_by_corner(flat_records)
    baselines = build_per_corner_baselines(records_by_corner)
    baselines = _enrich_baselines_with_ml(
        baselines,
        segmentation,
        ml_result,
    )

    # Run detectors + build findings.
    hits: list[DetectorHit] = []
    for corner_id, records in records_by_corner.items():
        baseline = baselines.get(corner_id)
        if baseline is None:
            continue
        for record in records:
            hits.extend(
                run_all_detectors(
                    record,
                    baseline,
                    include_experimental=include_experimental,
                )
            )

    # Also run detectors on compound corner sub-records (e.g. chicane apexes).
    # Sub-records carry unique IDs (corner 3 → sub-corners 301, 302) so they
    # get their own per-sub-corner baselines and findings.
    flat_sub_records: list[CornerRecord] = [
        sub_rec
        for records in records_by_corner.values()
        for record in records
        for sub_rec in record.sub_corner_records
    ]
    if flat_sub_records:
        sub_records_by_corner = group_records_by_corner(flat_sub_records)
        sub_baselines = build_per_corner_baselines(sub_records_by_corner)
        for sub_corner_id, sub_records_list in sub_records_by_corner.items():
            sub_baseline = sub_baselines.get(sub_corner_id)
            if sub_baseline is None:
                continue
            for sub_record in sub_records_list:
                hits.extend(
                    run_all_detectors(
                        sub_record,
                        sub_baseline,
                        include_experimental=include_experimental,
                    )
                )
        # Merge so build_findings can resolve alignment quality for sub-corner hits.
        all_records_by_corner: dict[int, list[CornerRecord]] = {
            **records_by_corner,
            **sub_records_by_corner,
        }
    else:
        all_records_by_corner = records_by_corner

    finding_set = _enrich_findings_with_ml(
        build_findings(hits, all_records_by_corner),
        segmentation,
        ml_result,
    )

    # Reconciliation: |sum(corner_delta) + sum(straight_delta) - actual_delta|.
    reconciliation = _compute_reconciliation(
        per_lap_records=per_lap_records,
        per_lap_straights=per_lap_straights,
        per_lap_lap_time=per_lap_lap_time,
        baselines=baselines,
    )
    if strict_reconciliation:
        _assert_reconciliation(reconciliation)

    # Flatten straight records for the output (one list across laps).
    all_straights = [
        record
        for records in per_lap_straights.values()
        for record in records
    ]

    # Session coaching summary.
    session_summary = build_session_summary(
        per_corner_records=records_by_corner,
        per_corner_baselines=baselines,
        straight_records=all_straights,
        findings_all=finding_set.findings_all,
        corner_definitions=segmentation.corners,
        per_lap_lap_times=per_lap_lap_time,
        reference_length_m=segmentation.reference_length_m,
    )

    session_analysis = SessionAnalysis(
        analysis_version=ANALYSIS_VERSION,
        session_id=session_id,
        reference_lap_number=int(segmentation.reference_lap_number),
        analyzed_at_utc=datetime.now(timezone.utc).isoformat(),
        corner_definitions=segmentation.corners,
        reference_length_m=segmentation.reference_length_m,
        per_corner_records=records_by_corner,
        per_corner_baselines=baselines,
        straight_records=all_straights,
        findings_top=finding_set.findings_top,
        findings_all=finding_set.findings_all,
        lap_time_delta_reconciliation=reconciliation,
        session_summary=session_summary,
        quality_report=_quality_report(
            usable_lap_numbers=usable_lap_numbers,
            per_lap_records=per_lap_records,
        ),
        detector_configuration={
            "default_detectors": list(DEFAULT_DETECTORS),
            "experimental_detectors": list(EXPERIMENTAL_DETECTORS),
            "experimental_enabled": bool(include_experimental),
            "active_detector_count": len(DEFAULT_DETECTORS)
            + (len(EXPERIMENTAL_DETECTORS) if include_experimental else 0),
        },
        ml_context=ml_result.to_dict(),
    )

    if write:
        payload = session_analysis.to_dict()
        (session_dir / ANALYSIS_ARTIFACT_FILENAME).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        if datastore is not None and datastore.get_session_detail(session_id) is not None:
            datastore.persist_analysis(
                session_id=session_id,
                analysis_version=session_analysis.analysis_version,
                payload=payload,
                findings=[finding.to_dict() for finding in session_analysis.findings_all],
            )

    return session_analysis


def _run_optional_ml_inference(
    *,
    session_id: str,
    processed_laps: dict[int, pd.DataFrame],
    metadata: dict[str, Any],
    datastore: TelemetryDatastore | None,
    enabled: bool,
) -> MLInferenceResult:
    if not enabled:
        return MLInferenceResult.unavailable("ml_inference_disabled")
    conditions: dict[str, Any] = {}
    condition_reader = getattr(datastore, "get_session_conditions", None)
    if condition_reader is not None:
        try:
            stored_conditions = condition_reader(session_id)
            if isinstance(stored_conditions, dict):
                conditions = stored_conditions
        except Exception:
            conditions = {}
    return MLProductInferenceService(
        database_factory=getattr(datastore, "factory", None),
        model_root=get_settings().model_root,
    ).infer(
        session_id,
        processed_laps,
        session_metadata=metadata,
        conditions=conditions,
    )


def _enrich_baselines_with_ml(
    baselines: dict[int, CornerBaseline],
    segmentation: TrackSegmentation,
    ml_result: MLInferenceResult,
) -> dict[int, CornerBaseline]:
    if ml_result.model is None:
        return baselines
    enriched: dict[int, CornerBaseline] = {}
    for corner_id, baseline in baselines.items():
        corner = _corner_definition(corner_id, segmentation)
        if corner is None:
            enriched[corner_id] = baseline
            continue
        center = _corner_center_progress(corner_id, corner)
        profile = ml_result.profile_slice(
            baseline.reference_lap_number,
            max(
                0.0,
                corner.approach_start_distance_m
                / max(segmentation.reference_length_m, 1.0),
            ),
            corner.end_progress_norm,
        )
        section_context = ml_result.context_for(
            baseline.reference_lap_number,
            center,
        )
        enriched[corner_id] = replace(
            baseline,
            champion_expected_input_profile=profile,
            section_pace=section_context,
            model_context=(
                {
                    "model": dict(ml_result.model),
                    "abstained": ml_result.abstained,
                    "abstention_reasons": list(ml_result.abstention_reasons),
                }
            ),
            scenario_recommendation=ml_result.recommendation_for(center),
        )
    return enriched


def _enrich_findings_with_ml(
    finding_set: FindingSet,
    segmentation: TrackSegmentation,
    ml_result: MLInferenceResult,
) -> FindingSet:
    if ml_result.model is None:
        return finding_set
    enriched_by_id: dict[str, Finding] = {}
    for finding in finding_set.findings_all:
        corner = _corner_definition(finding.corner_id, segmentation)
        if corner is None:
            enriched_by_id[finding.finding_id] = finding
            continue
        center = _corner_center_progress(finding.corner_id, corner)
        context = ml_result.context_for(finding.lap_number, center)
        if context is None:
            context = {
                "learned": True,
                "model": dict(ml_result.model),
                "supported": False,
                "abstained": True,
                "abstention_reason": ", ".join(ml_result.abstention_reasons)
                or "expected_profile_unavailable",
                "provenance": "registry_champion",
            }
        profile = ml_result.profile_slice(
            finding.lap_number,
            max(
                0.0,
                corner.approach_start_distance_m
                / max(segmentation.reference_length_m, 1.0),
            ),
            corner.end_progress_norm,
        )
        context["expected_input_profile"] = profile
        support = context.get("support")
        measured_confidence = finding.confidence
        adjusted_confidence = measured_confidence
        if bool(context.get("supported")) and isinstance(support, (int, float)):
            # Learned support can tune confidence modestly; measured loss and
            # reconciliation remain unchanged and authoritative.
            adjusted_confidence = max(
                0.0,
                min(1.0, measured_confidence * (0.90 + 0.10 * float(support))),
            )
        evidence = list(finding.evidence_refs)
        if profile is not None:
            evidence.append(
                {
                    "kind": "champion_expected_band",
                    "progress_start": corner.start_progress_norm,
                    "progress_end": corner.end_progress_norm,
                    "model_version": ml_result.model.get("version"),
                }
            )
        enriched_by_id[finding.finding_id] = replace(
            finding,
            confidence=adjusted_confidence,
            measured_confidence=measured_confidence,
            section_priority=context.get("section_priority"),
            ml_context=context,
            scenario_recommendation=ml_result.recommendation_for(center),
            evidence_refs=evidence,
        )
    return FindingSet(
        findings_top=[
            enriched_by_id.get(finding.finding_id, finding)
            for finding in finding_set.findings_top
        ],
        findings_all=[
            enriched_by_id.get(finding.finding_id, finding)
            for finding in finding_set.findings_all
        ],
    )


def _corner_definition(
    corner_id: int,
    segmentation: TrackSegmentation,
) -> Optional[CornerDefinition]:
    parent_id = corner_id // 100 if corner_id >= 100 else corner_id
    return next(
        (
            corner
            for corner in segmentation.corners
            if corner.corner_id == parent_id
        ),
        None,
    )


def _corner_center_progress(
    corner_id: int,
    corner: CornerDefinition,
) -> float:
    if corner_id >= 100:
        sub_index = corner_id % 100 - 1
        if 0 <= sub_index < len(corner.sub_apex_progress_norms):
            return float(corner.sub_apex_progress_norms[sub_index])
    return float(corner.center_progress_norm)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_metadata(session_dir: Path) -> dict[str, Any]:
    path = session_dir / "metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"metadata.json not found in {session_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_segmentation(session_dir: Path) -> TrackSegmentation:
    path = session_dir / "track_segmentation.json"
    if not path.is_file():
        raise FileNotFoundError(f"track_segmentation.json not found in {session_dir}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return deserialize_segmentation(payload)


def _load_processed_lap(
    session_dir: Path,
    lap_number: int,
    datastore: TelemetryDatastore | None = None,
    session_id: str | None = None,
) -> pd.DataFrame:
    if datastore is not None and session_id is not None:
        try:
            database_frame = datastore.load_processed_lap(session_id, lap_number)
        except Exception:
            database_frame = None
        if database_frame is not None:
            return database_frame
    path = session_dir / f"lap_{lap_number:03d}.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def deserialize_segmentation(payload: dict[str, Any]) -> TrackSegmentation:
    """Turn a ``track_segmentation.json`` dict back into a ``TrackSegmentation``.

    The segmentation module serializes via ``asdict`` so this is the inverse —
    we just route each corner/straight dict into its dataclass constructor.
    """
    corners = [
        CornerDefinition(
            corner_id=int(c["corner_id"]),
            track_corner_key=str(c["track_corner_key"]),
            start_progress_norm=float(c["start_progress_norm"]),
            end_progress_norm=float(c["end_progress_norm"]),
            center_progress_norm=float(c["center_progress_norm"]),
            start_distance_m=float(c["start_distance_m"]),
            end_distance_m=float(c["end_distance_m"]),
            center_distance_m=float(c["center_distance_m"]),
            approach_start_distance_m=float(c["approach_start_distance_m"]),
            entry_end_progress_norm=float(c["entry_end_progress_norm"]),
            exit_start_progress_norm=float(c["exit_start_progress_norm"]),
            length_m=float(c["length_m"]),
            peak_curvature=float(c["peak_curvature"]),
            mean_curvature=float(c["mean_curvature"]),
            direction=str(c["direction"]),
            is_compound=bool(c["is_compound"]),
            sub_apex_progress_norms=[float(x) for x in c.get("sub_apex_progress_norms", [])],
            sub_apex_distances_m=[float(x) for x in c.get("sub_apex_distances_m", [])],
        )
        for c in payload.get("corners", [])
    ]
    straights = [
        StraightDefinition(
            straight_id=int(s["straight_id"]),
            start_distance_m=float(s["start_distance_m"]),
            end_distance_m=float(s["end_distance_m"]),
            length_m=float(s["length_m"]),
            preceding_corner_id=(
                int(s["preceding_corner_id"])
                if s.get("preceding_corner_id") is not None
                else None
            ),
            following_corner_id=(
                int(s["following_corner_id"])
                if s.get("following_corner_id") is not None
                else None
            ),
            wraps_start_finish=bool(s["wraps_start_finish"]),
        )
        for s in payload.get("straights", [])
    ]
    return TrackSegmentation(
        corners=corners,
        straights=straights,
        reference_lap_number=int(payload["reference_lap_number"]),
        reference_length_m=float(payload["reference_length_m"]),
        curvature_noise_floor=float(payload["curvature_noise_floor"]),
        curvature_corner_threshold=float(payload["curvature_corner_threshold"]),
        curvature_smoothing_window=int(payload["curvature_smoothing_window"]),
        min_corner_length_m=float(payload["min_corner_length_m"]),
        min_turning_angle_rad=float(payload["min_turning_angle_rad"]),
        min_straight_gap_m=float(payload["min_straight_gap_m"]),
        center_region_fraction=float(payload["center_region_fraction"]),
        approach_lead_m=float(payload["approach_lead_m"]),
        segmentation_quality=dict(payload.get("segmentation_quality", {})),
        segmentation_version=str(payload["segmentation_version"]),
    )


def _usable_lap_numbers(metadata: dict[str, Any]) -> list[int]:
    alignment = metadata.get("alignment", {})
    laps = alignment.get("laps", {}) or {}
    usable: list[int] = []
    for key, info in laps.items():
        if not info.get("is_usable", False):
            continue
        try:
            usable.append(int(key))
        except (TypeError, ValueError):
            continue
    return sorted(usable)


def _lap_time_s(processed_lap: pd.DataFrame) -> float:
    if processed_lap.empty:
        return 0.0
    if "LapTimeS" in processed_lap.columns:
        value = pd.to_numeric(processed_lap["LapTimeS"], errors="coerce").dropna()
        if not value.empty:
            return float(value.iloc[0])
    # Fallback: elapsed-time span of the lap.
    elapsed = pd.to_numeric(processed_lap["ElapsedTimeS"], errors="coerce").dropna()
    if elapsed.empty:
        return 0.0
    return float(elapsed.iloc[-1] - elapsed.iloc[0])


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _compute_reconciliation(
    *,
    per_lap_records: dict[int, list[CornerRecord]],
    per_lap_straights: dict[int, list[StraightRecord]],
    per_lap_lap_time: dict[int, float],
    baselines: dict[int, CornerBaseline],
) -> dict[int, dict[str, float]]:
    """Per-lap reconciliation of segment-level deltas vs actual lap delta.

    The reconciliation invariant compares ``candidate_lap`` to a single
    ``reference_lap`` (the session-fastest usable lap). Both corner and
    straight deltas are taken against *that same reference lap's* version
    of each segment — **not** against per-corner fastest baselines. Only
    then does the sum-of-deltas telescope cleanly into the actual lap-time
    delta.

    The per-corner baselines parameter is accepted for symmetry but not
    used here; it lives in ``baselines.py`` to serve detector input and is
    intentionally decoupled from reconciliation.
    """
    del baselines  # intentionally unused — see docstring
    if not per_lap_lap_time:
        return {}

    reference_lap_number = min(per_lap_lap_time, key=lambda k: per_lap_lap_time[k])
    reference_lap_time = per_lap_lap_time[reference_lap_number]

    reference_corner_time = _index_corner_times(
        per_lap_records.get(reference_lap_number, [])
    )
    reference_straight_time = _index_straight_times(
        per_lap_straights.get(reference_lap_number, [])
    )

    reconciliation: dict[int, dict[str, float]] = {}
    for lap_number, records in per_lap_records.items():
        if lap_number == reference_lap_number:
            continue
        corner_delta_sum = 0.0
        for record in records:
            base_time = reference_corner_time.get(record.corner_id)
            if base_time is None:
                continue
            corner_delta_sum += record.corner_time_s - base_time

        straight_delta_sum = 0.0
        for straight in per_lap_straights.get(lap_number, []):
            base_time = reference_straight_time.get(straight.straight_id)
            if base_time is None:
                continue
            straight_delta_sum += straight.time_s - base_time

        actual_delta = per_lap_lap_time[lap_number] - reference_lap_time
        residual = (corner_delta_sum + straight_delta_sum) - actual_delta
        reconciliation[lap_number] = {
            "sum_corner_delta_s": corner_delta_sum,
            "sum_straight_delta_s": straight_delta_sum,
            "actual_lap_delta_s": actual_delta,
            "residual_s": residual,
            "reference_lap_number": reference_lap_number,
        }
    return reconciliation


def _index_corner_times(records: list[CornerRecord]) -> dict[int, float]:
    return {r.corner_id: r.corner_time_s for r in records}


def _index_straight_times(records: list[StraightRecord]) -> dict[int, float]:
    return {r.straight_id: r.time_s for r in records}


def _assert_reconciliation(reconciliation: dict[int, dict[str, float]]) -> None:
    for lap_number, entry in reconciliation.items():
        if abs(entry["residual_s"]) > LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S:
            raise ReconciliationError(
                f"Lap {lap_number}: reconciliation residual "
                f"{entry['residual_s']:.3f}s exceeds tolerance "
                f"{LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S:.3f}s. "
                f"Sum corner: {entry['sum_corner_delta_s']:.3f}s, "
                f"sum straight: {entry['sum_straight_delta_s']:.3f}s, "
                f"actual: {entry['actual_lap_delta_s']:.3f}s."
            )


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------


def _quality_report(
    *,
    usable_lap_numbers: list[int],
    per_lap_records: dict[int, list[CornerRecord]],
) -> dict[str, Any]:
    lap_summary: dict[str, Any] = {}
    for lap_number in usable_lap_numbers:
        records = per_lap_records.get(lap_number, [])
        fallback_corners = sum(1 for r in records if r.alignment_used_fallback)
        lap_summary[str(lap_number)] = {
            "corner_count": len(records),
            "fallback_corner_count": fallback_corners,
        }
    return {
        "usable_lap_numbers": list(usable_lap_numbers),
        "per_lap": lap_summary,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic session analysis and optional champion inference."
    )
    parser.add_argument("session_id")
    parser.add_argument("--processed-root", type=Path, default=PROCESSED_DATA_ROOT)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-strict-reconciliation", action="store_true")
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument(
        "--experimental-detectors",
        action="store_true",
        default=None,
        help="Enable the two research detectors for this run.",
    )
    args = parser.parse_args(argv)
    result = run(
        args.session_id,
        processed_root=args.processed_root,
        write=not args.no_write,
        strict_reconciliation=not args.no_strict_reconciliation,
        experimental_detectors=args.experimental_detectors,
        enable_ml=not args.no_ml,
    )
    print(
        json.dumps(
            {
                "session_id": result.session_id,
                "analysis_version": result.analysis_version,
                "reference_lap_number": result.reference_lap_number,
                "findings_top_count": len(result.findings_top),
                "findings_all_count": len(result.findings_all),
                "detector_configuration": result.detector_configuration,
                "ml_status": result.ml_context.get("status", "unavailable"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
