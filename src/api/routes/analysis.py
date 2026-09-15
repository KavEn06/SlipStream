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
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, HTTPException

from src.api.models import (
    AnalyzeSessionRequest,
    AnalyzeSessionResponse,
    ManualConditionResponse,
    ManualConditionUpdateRequest,
    RecommendationRatingRequest,
    RecommendationRatingResponse,
    SessionAnalysisResponse,
)
from src.api.services import session_scanner
from src.analysis.session_analysis import (
    ANALYSIS_ARTIFACT_FILENAME,
    ReconciliationError,
    run,
)
from src.core.config import PROCESSED_DATA_ROOT
from src.ml.feedback import RATING_SCHEMA_VERSION
from src.services.telemetry_store import get_default_telemetry_store


router = APIRouter(prefix="/api/sessions", tags=["analysis"])
RATINGS_ARTIFACT_FILENAME = "recommendation_ratings.json"


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
                finding_ml_context = finding.get("ml_context")
                if isinstance(finding_ml_context, dict):
                    expected_profile = finding_ml_context.get(
                        "expected_input_profile"
                    )
                    if (
                        isinstance(expected_profile, dict)
                        and "lap_number" in expected_profile
                    ):
                        expected_profile["lap_number"] = _map_display_lap_number(
                            expected_profile["lap_number"],
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
            expected_profile = baseline.get("champion_expected_input_profile")
            if (
                isinstance(expected_profile, dict)
                and "lap_number" in expected_profile
            ):
                expected_profile["lap_number"] = _map_display_lap_number(
                    expected_profile["lap_number"],
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

    ml_context = normalized.get("ml_context")
    if isinstance(ml_context, dict):
        for key in ("expected_profiles", "section_pace"):
            values = ml_context.get(key)
            if not isinstance(values, dict):
                continue
            normalized_values: dict[str, object] = {}
            for lap_number, value in values.items():
                display_lap_number = _map_display_lap_number(
                    lap_number, stored_to_display
                )
                if isinstance(value, dict) and "lap_number" in value:
                    value["lap_number"] = display_lap_number
                normalized_values[str(display_lap_number)] = value
            ml_context[key] = normalized_values

    return normalized


@router.post("/{session_id}/analyze", response_model=AnalyzeSessionResponse)
def analyze_session(
    session_id: str,
    request: Optional[AnalyzeSessionRequest] = None,
):
    """Run the analysis pipeline and persist ``session_analysis.json``."""
    session_dir = PROCESSED_DATA_ROOT / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Processed session not found")

    datastore = get_default_telemetry_store()
    try:
        database_usable = datastore is not None
        if datastore is not None:
            datastore.get_session_detail(session_id)
    except Exception:
        database_usable = False
    try:
        result = run(
            session_id,
            write=True,
            strict_reconciliation=True,
            datastore=datastore if database_usable else None,
            experimental_detectors=(
                request.experimental_detectors if request is not None else None
            ),
        )
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
        "detector_configuration": dict(result.detector_configuration),
        "ml_status": str(result.ml_context.get("status", "unavailable")),
    }


@router.get("/{session_id}/analysis", response_model=SessionAnalysisResponse)
def get_session_analysis(session_id: str):
    """Return the persisted analysis payload with display lap numbers."""
    datastore = get_default_telemetry_store()
    try:
        database_payload = datastore.get_latest_analysis(session_id) if datastore is not None else None
    except Exception:
        database_payload = None
    if database_payload is not None:
        normalized_payload = _normalize_analysis_payload_for_output(session_id, database_payload)
        _attach_recommendation_ratings(session_id, normalized_payload, datastore)
        normalized_payload["track_outline"] = session_scanner.get_track_outline(session_id)
        return normalized_payload

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
    normalized_payload = _normalize_analysis_payload_for_output(session_id, payload)
    _attach_recommendation_ratings(session_id, normalized_payload, datastore)
    normalized_payload["track_outline"] = session_scanner.get_track_outline(session_id)
    return normalized_payload


@router.get(
    "/{session_id}/conditions",
    response_model=ManualConditionResponse,
)
def get_session_conditions(session_id: str):
    datastore = get_default_telemetry_store()
    if datastore is not None:
        try:
            if datastore.get_session_detail(session_id) is not None:
                return {
                    "session_id": session_id,
                    "conditions": datastore.get_session_conditions(session_id),
                    "origin": "manual",
                }
        except Exception:
            pass
    metadata_path = PROCESSED_DATA_ROOT / session_id / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Processed session not found")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Session metadata is unreadable") from exc
    conditions = (
        dict(metadata.get("conditions") or {})
        if isinstance(metadata, dict)
        else {}
    )
    return {
        "session_id": session_id,
        "conditions": conditions,
        "origin": "manual",
    }


@router.patch(
    "/{session_id}/conditions",
    response_model=ManualConditionResponse,
)
def update_session_conditions(
    session_id: str,
    request: ManualConditionUpdateRequest,
):
    supplied = request.supplied()
    if not supplied:
        raise HTTPException(
            status_code=422,
            detail="At least one condition override is required",
        )
    datastore = get_default_telemetry_store()
    if datastore is not None:
        try:
            updated = datastore.update_session_conditions(session_id, supplied)
        except Exception:
            updated = None
        if updated is not None:
            return {
                "session_id": session_id,
                "conditions": updated,
                "origin": "manual",
            }

    metadata_path = PROCESSED_DATA_ROOT / session_id / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Processed session not found")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("unexpected metadata shape")
        conditions = (
            dict(metadata.get("conditions") or {})
            if isinstance(metadata.get("conditions"), dict)
            else {}
        )
        conditions.update(supplied)
        metadata["conditions"] = conditions
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist manual conditions",
        ) from exc
    return {
        "session_id": session_id,
        "conditions": conditions,
        "origin": "manual",
    }


@router.get(
    "/{session_id}/recommendations/{recommendation_id}/rating",
    response_model=RecommendationRatingResponse,
)
def get_recommendation_rating(session_id: str, recommendation_id: str):
    if not _session_has_recommendation(session_id, recommendation_id):
        raise HTTPException(status_code=404, detail="Recommendation not found")
    datastore = get_default_telemetry_store()
    if datastore is not None:
        try:
            stored = datastore.get_recommendation_rating(session_id, recommendation_id)
        except Exception:
            stored = None
        if stored is not None:
            return stored
    stored = _load_filesystem_ratings(session_id).get(recommendation_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Rating not found")
    return stored


@router.post(
    "/{session_id}/recommendations/{recommendation_id}/rating",
    response_model=RecommendationRatingResponse,
)
def rate_recommendation(
    session_id: str,
    recommendation_id: str,
    request: RecommendationRatingRequest,
):
    if not _session_has_recommendation(session_id, recommendation_id):
        raise HTTPException(status_code=404, detail="Recommendation not found")
    datastore = get_default_telemetry_store()
    if datastore is not None:
        try:
            stored = datastore.rate_recommendation(
                session_id,
                recommendation_id,
                helpful=bool(request.helpful),
                reason=request.normalized_reason(),
            )
        except Exception:
            stored = None
        if stored is not None:
            return stored
    return _write_filesystem_rating(
        session_id,
        recommendation_id,
        helpful=bool(request.helpful),
        reason=request.normalized_reason(),
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iter_recommendation_dicts(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    ml_context = payload.get("ml_context")
    if isinstance(ml_context, dict):
        recommendations = ml_context.get("recommendations")
        if isinstance(recommendations, list):
            collected.extend(
                item for item in recommendations if isinstance(item, dict)
            )
    for findings_key in ("findings_top", "findings_all"):
        findings = payload.get(findings_key)
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            recommendation = finding.get("scenario_recommendation")
            if isinstance(recommendation, dict):
                collected.append(recommendation)
    return collected


def _recommendation_ids(payload: Mapping[str, Any]) -> List[str]:
    ids: List[str] = []
    seen = set()
    for recommendation in _iter_recommendation_dicts(payload):
        recommendation_id = recommendation.get("recommendation_id")
        if not recommendation_id or recommendation_id in seen:
            continue
        seen.add(str(recommendation_id))
        ids.append(str(recommendation_id))
    return ids


def _load_analysis_payload(session_id: str) -> Optional[Dict[str, Any]]:
    datastore = get_default_telemetry_store()
    if datastore is not None:
        try:
            payload = datastore.get_latest_analysis(session_id)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload
    artifact = PROCESSED_DATA_ROOT / session_id / ANALYSIS_ARTIFACT_FILENAME
    if not artifact.is_file():
        return None
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _session_has_recommendation(session_id: str, recommendation_id: str) -> bool:
    payload = _load_analysis_payload(session_id)
    if payload is None:
        return False
    return recommendation_id in _recommendation_ids(payload)


def _load_filesystem_ratings(session_id: str) -> Dict[str, Dict[str, Any]]:
    path = PROCESSED_DATA_ROOT / session_id / RATINGS_ARTIFACT_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    ratings: Dict[str, Dict[str, Any]] = {}
    for recommendation_id, rating in payload.items():
        if isinstance(rating, dict):
            ratings[str(recommendation_id)] = dict(rating)
    return ratings


def _write_filesystem_rating(
    session_id: str,
    recommendation_id: str,
    helpful: bool,
    reason: Optional[str],
) -> Dict[str, Any]:
    session_dir = PROCESSED_DATA_ROOT / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Processed session not found")
    ratings = _load_filesystem_ratings(session_id)
    stored = {
        "recommendation_id": recommendation_id,
        "helpful": helpful,
        "reason": reason,
        "schema_version": RATING_SCHEMA_VERSION,
        "training_eligible": False,
        "origin": "manual",
        "recorded_at_utc": _utc_now(),
    }
    ratings[recommendation_id] = stored
    try:
        (session_dir / RATINGS_ARTIFACT_FILENAME).write_text(
            json.dumps(ratings, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist recommendation rating",
        ) from exc
    return stored


def _attach_recommendation_ratings(
    session_id: str,
    payload: Dict[str, Any],
    datastore: Any,
) -> None:
    recommendation_ids = _recommendation_ids(payload)
    ratings: Dict[str, Dict[str, Any]] = {}
    filesystem = _load_filesystem_ratings(session_id)
    ratings.update(filesystem)
    if datastore is not None and recommendation_ids:
        try:
            ratings.update(
                datastore.ratings_for_session(session_id, recommendation_ids)
            )
        except Exception:
            pass
    for recommendation in _iter_recommendation_dicts(payload):
        recommendation_id = recommendation.get("recommendation_id")
        if not recommendation_id:
            continue
        rating = ratings.get(str(recommendation_id))
        if rating is not None:
            recommendation["rating"] = dict(rating)
            recommendation["rating"]["training_eligible"] = False
