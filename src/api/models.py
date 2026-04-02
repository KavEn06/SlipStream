from __future__ import annotations

from pydantic import BaseModel


class SessionSummary(BaseModel):
    session_id: str
    display_name: str | None = None
    created_at_utc: str | None = None
    track_circuit: str | None = None
    track_layout: str | None = None
    track_location: str | None = None
    car_ordinal: int | None = None
    total_laps: int = 0
    has_processed: bool = False


class LapSummary(BaseModel):
    lap_number: int
    has_raw: bool = False
    has_processed: bool = False
    lap_time_s: float | None = None
    is_valid: bool | None = None


class SessionDetail(BaseModel):
    session_id: str
    display_name: str | None = None
    created_at_utc: str | None = None
    sim: str | None = None
    track_circuit: str | None = None
    track_layout: str | None = None
    track_location: str | None = None
    track_length_m: float | None = None
    car_ordinal: int | None = None
    total_laps: int = 0
    has_processed: bool = False
    schema_version: str | None = None
    processed_schema_version: str | None = None
    notes: str = ""
    laps: list[LapSummary] = []


class LapData(BaseModel):
    session_id: str
    lap_number: int
    data_type: str
    columns: list[str]
    records: list[dict]


class CaptureStatus(BaseModel):
    is_active: bool = False
    session_id: str | None = None
    ip: str | None = None
    port: int | None = None
    laps_detected: int = 0


class CaptureStartRequest(BaseModel):
    ip: str = "127.0.0.1"
    port: int = 5300
    session_id: str | None = None


class ProcessResponse(BaseModel):
    session_id: str
    processed_laps: int
    message: str


class DeleteResponse(BaseModel):
    message: str


class SessionUpdateRequest(BaseModel):
    display_name: str | None = None
