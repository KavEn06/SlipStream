from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import CaptureStartRequest, CaptureStatus
from src.api.services.capture_manager import CaptureManager

router = APIRouter(prefix="/api/capture", tags=["capture"])


@router.get("/status", response_model=CaptureStatus)
def capture_status():
    return CaptureManager.get().status


@router.post("/start", response_model=CaptureStatus)
def capture_start(request: CaptureStartRequest):
    try:
        return CaptureManager.get().start(
            ip=request.ip,
            port=request.port,
            session_id=request.session_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/stop", response_model=CaptureStatus)
def capture_stop():
    try:
        return CaptureManager.get().stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
