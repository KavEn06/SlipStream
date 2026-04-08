from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.api.models import (
    CompareCandidatesResponse,
    LapOverlayRequest,
    LapOverlayResponse,
)
from src.api.services.session_scanner import build_lap_overlay, get_compare_candidates

router = APIRouter(prefix="/api/compare", tags=["compare"])


@router.get("/laps/candidates", response_model=CompareCandidatesResponse)
def get_compare_lap_candidates(session_id: str = Query(..., min_length=1)):
    try:
        return get_compare_candidates(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/laps", response_model=LapOverlayResponse)
def build_compare_lap_overlay(payload: LapOverlayRequest):
    try:
        return build_lap_overlay(
            [selection.model_dump() for selection in payload.selections],
            payload.reference_lap.model_dump(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
