from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.api.models import DeleteResponse, LapData
from src.api.services.session_scanner import delete_lap, get_lap_data

router = APIRouter(prefix="/api/sessions", tags=["laps"])


@router.get("/{session_id}/laps/{lap_number}", response_model=LapData)
def get_lap(
    session_id: str,
    lap_number: int,
    data_type: str = Query("processed", pattern="^(raw|processed)$"),
    view: str = Query("full", pattern="^(full|review)$"),
    max_points: int = Query(1000, ge=100, le=5000),
):
    result = get_lap_data(session_id, lap_number, data_type, view=view, max_points=max_points)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Lap data not found ({data_type})")
    return result


@router.delete("/{session_id}/laps/{lap_number}", response_model=DeleteResponse)
def delete_lap_endpoint(session_id: str, lap_number: int):
    if not delete_lap(session_id, lap_number):
        raise HTTPException(status_code=404, detail="Lap not found")
    return DeleteResponse(message=f"Deleted lap {lap_number} from {session_id}")
