"""Operational health surfaces for optional product inference."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.models import DataHealthResponse, ModelHealthResponse
from src.services.telemetry_store import get_default_telemetry_store


router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/model-health", response_model=ModelHealthResponse)
def get_model_health():
    datastore = get_default_telemetry_store()
    if datastore is None:
        return {
            "status": "fallback",
            "champion": None,
            "challengers": [],
            "fallback_reasons": ["database_unavailable"],
        }
    try:
        return datastore.get_model_health()
    except Exception as exc:
        return {
            "status": "fallback",
            "champion": None,
            "challengers": [],
            "fallback_reasons": [
                "model_health_unavailable:{0}".format(type(exc).__name__)
            ],
        }


@router.get("/data-health", response_model=DataHealthResponse)
def get_data_health():
    datastore = get_default_telemetry_store()
    if datastore is None:
        return {
            "row_count": {"raw": 0, "processed": 0, "total": 0},
            "effective_laps": 0,
            "source_imports": [],
            "fallback_reasons": ["database_unavailable"],
        }
    try:
        return datastore.get_data_health()
    except Exception as exc:
        return {
            "row_count": {"raw": 0, "processed": 0, "total": 0},
            "effective_laps": 0,
            "source_imports": [],
            "fallback_reasons": [
                "data_health_unavailable:{0}".format(type(exc).__name__)
            ],
        }
