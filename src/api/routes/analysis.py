"""HTTP surface for the corner analysis layer.

Two endpoints:

- ``POST /api/sessions/{session_id}/analyze`` runs the analysis pipeline
  against the processed session on disk, writes
  ``session_analysis.json``, and returns a thin summary.
- ``GET /api/sessions/{session_id}/analysis`` reads the previously written
  artifact and normalizes stored lap numbers into user-facing display lap
  numbers before returning it.

Neither endpoint rebuilds processed artifacts — analysis is layered on
top of phase-1 output and is idempotent.
"""

from __future__ import annotations

import json
from copy import deepcopy

from fastapi import APIRouter, HTTPException

from src.api.services import session_scanner
from src.analysis.session_analysis import (
    ANALYSIS_ARTIFACT_FILENAME,
    ReconciliationError,
    run,
)
from src.core.config import PROCESSED_DATA_ROOT


router = APIRouter(prefix="/api/sessions", tags=["analysis"])


def _map_display_lap_number(value: object, stored_to_display: dict[int, int]) -> object:
    try:
        stored_lap_number = int(value)
    except (TypeError, ValueError):
        return value
    return stored_to_display.get(stored_lap_number, stored_lap_number)


def _normalize_corner_record_lap_numbers(
    record: dict[str, object],
    stored_to_display: dict[int, int],
) -> dict[str, object]:
    normalized = dict(record)
    if "lap_number" in normalized:
        normalized["lap_number"] = _map_display_lap_number(
            normalized["lap_number"],
            stored_to_display,
        )

    sub_corner_records = normalized.get("sub_corner_records")
    if isinstance(sub_corner_records, list):
        normalized["sub_corner_records"] = [
            _normalize_corner_record_lap_numbers(sub_record, stored_to_display)
            if isinstance(sub_record, dict)
            else sub_record
            for sub_record in sub_corner_records
        ]
    return normalized


def _normalize_analysis_payload_for_output(
    session_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    stored_to_display = session_scanner.get_session_lap_number_mapping(session_id)[
        "stored_to_display"
    ]
    if not stored_to_display:
        return payload

    normalized = deepcopy(payload)

    if "reference_lap_number" in normalized:
        normalized["reference_lap_number"] = _map_display_lap_number(
            normalized["reference_lap_number"],
            stored_to_display,
        )

    for findings_key in ("findings_top", "findings_all"):
        findings = normalized.get(findings_key)
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if isinstance(finding, dict) and "lap_number" in finding:
                finding["lap_number"] = _map_display_lap_number(
                    finding["lap_number"],
                    stored_to_display,
                )

    straight_records = normalized.get("straight_records")
    if isinstance(straight_records, list):
        for record in straight_records:
            if isinstance(record, dict) and "lap_number" in record:
                record["lap_number"] = _map_display_lap_number(
                    record["lap_number"],
                    stored_to_display,
                )

    per_corner_records = normalized.get("per_corner_records")
    if isinstance(per_corner_records, dict):
        for corner_id, records in list(per_corner_records.items()):
            if not isinstance(records, list):
                continue
            per_corner_records[corner_id] = [
                _normalize_corner_record_lap_numbers(record, stored_to_display)
                if isinstance(record, dict)
                else record
                for record in records
            ]

    per_corner_baselines = normalized.get("per_corner_baselines")
    if isinstance(per_corner_baselines, dict):
        for baseline in per_corner_baselines.values():
            if not isinstance(baseline, dict):
                continue
            if "reference_lap_number" in baseline:
                baseline["reference_lap_number"] = _map_display_lap_number(
                    baseline["reference_lap_number"],
                    stored_to_display,
                )
            candidate_lap_numbers = baseline.get("candidate_lap_numbers")
            if isinstance(candidate_lap_numbers, list):
                baseline["candidate_lap_numbers"] = [
                    _map_display_lap_number(lap_number, stored_to_display)
                    for lap_number in candidate_lap_numbers
                ]
            reference_record = baseline.get("reference_record")
            if isinstance(reference_record, dict):
                baseline["reference_record"] = _normalize_corner_record_lap_numbers(
                    reference_record,
                    stored_to_display,
                )

    reconciliation = normalized.get("lap_time_delta_reconciliation")
    if isinstance(reconciliation, dict):
        normalized_reconciliation: dict[str, object] = {}
        for lap_number, entry in reconciliation.items():
            display_lap_number = str(
                _map_display_lap_number(lap_number, stored_to_display)
            )
            if isinstance(entry, dict) and "reference_lap_number" in entry:
                normalized_entry = dict(entry)
                normalized_entry["reference_lap_number"] = _map_display_lap_number(
                    normalized_entry["reference_lap_number"],
                    stored_to_display,
                )
                normalized_reconciliation[display_lap_number] = normalized_entry
            else:
                normalized_reconciliation[display_lap_number] = entry
        normalized["lap_time_delta_reconciliation"] = normalized_reconciliation

    quality_report = normalized.get("quality_report")
    if isinstance(quality_report, dict):
        usable_lap_numbers = quality_report.get("usable_lap_numbers")
        if isinstance(usable_lap_numbers, list):
            quality_report["usable_lap_numbers"] = [
                _map_display_lap_number(lap_number, stored_to_display)
                for lap_number in usable_lap_numbers
            ]

        per_lap = quality_report.get("per_lap")
        if isinstance(per_lap, dict):
            normalized_per_lap: dict[str, object] = {}
            for lap_number, entry in per_lap.items():
                display_lap_number = _map_display_lap_number(
                    lap_number,
                    stored_to_display,
                )
                normalized_per_lap[str(display_lap_number)] = entry
            quality_report["per_lap"] = normalized_per_lap

    return normalized


@router.post("/{session_id}/analyze")
def analyze_session(session_id: str):
    """Run the analysis pipeline and persist ``session_analysis.json``."""
    session_dir = PROCESSED_DATA_ROOT / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Processed session not found")

    try:
        result = run(session_id, write=True, strict_reconciliation=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ReconciliationError as exc:
        # Reconciliation failure is a hard invariant. Surface it as 500 so
        # the UI can't silently consume bad data.
        raise HTTPException(
            status_code=500,
            detail=f"Time-delta reconciliation failed: {exc}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "session_id": session_id,
        "analysis_version": result.analysis_version,
        "analyzed_at_utc": result.analyzed_at_utc,
        "corner_record_count": sum(
            len(records) for records in result.per_corner_records.values()
        ),
        "findings_top_count": len(result.findings_top),
        "findings_all_count": len(result.findings_all),
        "artifact_path": str(session_dir / ANALYSIS_ARTIFACT_FILENAME),
    }


@router.get("/{session_id}/analysis")
def get_session_analysis(session_id: str):
    """Return the persisted analysis payload with display lap numbers."""
    artifact = PROCESSED_DATA_ROOT / session_id / ANALYSIS_ARTIFACT_FILENAME
    if not artifact.is_file():
        raise HTTPException(
            status_code=404,
            detail="Analysis not available — POST /analyze first",
        )
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis artifact is corrupt: {exc}",
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail="Analysis artifact has an unexpected top-level shape",
        )
    return _normalize_analysis_payload_for_output(session_id, payload)
