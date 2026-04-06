from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import (
    DeleteResponse,
    ProcessResponse,
    SessionDetail,
    SessionSummary,
    SessionUpdateRequest,
)
from src.api.services.capture_manager import CaptureManager
from src.api.services.session_scanner import (
    delete_session,
    get_session_detail,
    get_track_segmentation,
    list_sessions,
    update_session_metadata,
)
from src.core.config import RAW_DATA_ROOT
from src.processing.distance import process_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
def get_sessions():
    return list_sessions()


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str):
    detail = get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/{session_id}", response_model=SessionDetail)
def update_session(session_id: str, payload: SessionUpdateRequest):
    detail = update_session_metadata(
        session_id,
        display_name=payload.display_name,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.post("/{session_id}/process", response_model=ProcessResponse)
def process_session_endpoint(session_id: str):
    capture_status = CaptureManager.get().status
    if capture_status["is_active"] and capture_status["session_id"] == session_id:
        raise HTTPException(
            status_code=409,
            detail="Stop capture before processing this session",
        )

    raw_dir = RAW_DATA_ROOT / session_id
    if not raw_dir.exists():
        raise HTTPException(status_code=404, detail="Raw session not found")

    try:
        written = process_session(raw_dir)
        return ProcessResponse(
            session_id=session_id,
            processed_laps=len(written),
            message=f"Processed {len(written)} laps",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{session_id}/segmentation")
def get_segmentation(session_id: str):
    result = get_track_segmentation(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Segmentation not available")
    return result


@router.delete("/{session_id}", response_model=DeleteResponse)
def delete_session_endpoint(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return DeleteResponse(message=f"Deleted session {session_id}")
