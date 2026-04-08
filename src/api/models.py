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


class LapDataSummary(BaseModel):
    lap_time_s: float | None = None
    lap_is_valid: bool | None = None


class LapDataSampling(BaseModel):
    view: str
    source_rows: int
    returned_rows: int
    max_points: int | None = None
    x_key: str


class LapData(BaseModel):
    session_id: str
    lap_number: int
    data_type: str
    columns: list[str]
    records: list[dict]
    summary: LapDataSummary
    sampling: LapDataSampling


class CompareCandidateLap(BaseModel):
    lap_number: int
    lap_time_s: float | None = None


class CompareCandidateSession(BaseModel):
    session_id: str
    display_name: str | None = None
    created_at_utc: str | None = None
    track_circuit: str | None = None
    track_layout: str | None = None
    track_location: str | None = None
    laps: list[CompareCandidateLap] = []


class CompareCandidatesResponse(BaseModel):
    seed_session_id: str
    track_circuit: str
    track_layout: str
    track_location: str | None = None
    sessions: list[CompareCandidateSession] = []


class LapOverlaySelection(BaseModel):
    session_id: str
    lap_number: int


class LapOverlayRequest(BaseModel):
    selections: list[LapOverlaySelection]
    reference_lap: LapOverlaySelection


class LapOverlaySeries(BaseModel):
    session_id: str
    display_name: str | None = None
    lap_number: int
    lap_time_s: float | None = None
    records: list[dict]


class LapOverlayResponse(BaseModel):
    track_circuit: str
    track_layout: str
    track_location: str | None = None
    reference_lap: LapOverlaySelection
    segmentation: dict | None = None
    series: list[LapOverlaySeries]


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
