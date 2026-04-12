"""HTTP surface for the corner analysis layer.

Two endpoints:

- ``POST /api/sessions/{session_id}/analyze`` runs the analysis pipeline
  against the processed session on disk, writes
  ``session_analysis.json``, and returns a thin summary.
- ``GET /api/sessions/{session_id}/analysis`` reads the previously written
  artifact and returns it verbatim.

Neither endpoint rebuilds processed artifacts — analysis is layered on
top of phase-1 output and is idempotent.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from src.analysis.session_analysis import (
    ANALYSIS_ARTIFACT_FILENAME,
    ReconciliationError,
    run,
)
from src.core.config import PROCESSED_DATA_ROOT


router = APIRouter(prefix="/api/sessions", tags=["analysis"])


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
    """Return the persisted ``session_analysis.json`` payload."""
    artifact = PROCESSED_DATA_ROOT / session_id / ANALYSIS_ARTIFACT_FILENAME
    if not artifact.is_file():
        raise HTTPException(
            status_code=404,
            detail="Analysis not available — POST /analyze first",
        )
    try:
        return json.loads(artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis artifact is corrupt: {exc}",
        )
