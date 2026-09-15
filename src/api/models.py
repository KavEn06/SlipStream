from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionSummary(BaseModel):
    session_id: str
    display_name: Optional[str] = None
    created_at_utc: Optional[str] = None
    track_circuit: Optional[str] = None
    track_layout: Optional[str] = None
    track_location: Optional[str] = None
    car_ordinal: Optional[int] = None
    total_laps: int = 0
    has_processed: bool = False


class LapSummary(BaseModel):
    lap_number: int
    has_raw: bool = False
    has_processed: bool = False
    lap_time_s: Optional[float] = None
    is_valid: Optional[bool] = None


class SessionDetail(BaseModel):
    session_id: str
    display_name: Optional[str] = None
    created_at_utc: Optional[str] = None
    sim: Optional[str] = None
    track_circuit: Optional[str] = None
    track_layout: Optional[str] = None
    track_location: Optional[str] = None
    track_length_m: Optional[float] = None
    car_ordinal: Optional[int] = None
    total_laps: int = 0
    has_processed: bool = False
    schema_version: Optional[str] = None
    processed_schema_version: Optional[str] = None
    notes: str = ""
    laps: list[LapSummary] = []


class LapDataSummary(BaseModel):
    lap_time_s: Optional[float] = None
    lap_is_valid: Optional[bool] = None


class LapDataSampling(BaseModel):
    view: str
    source_rows: int
    returned_rows: int
    max_points: Optional[int] = None
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
    lap_time_s: Optional[float] = None


class CompareCandidateSession(BaseModel):
    session_id: str
    display_name: Optional[str] = None
    created_at_utc: Optional[str] = None
    track_circuit: Optional[str] = None
    track_layout: Optional[str] = None
    track_location: Optional[str] = None
    laps: list[CompareCandidateLap] = []


class CompareCandidatesResponse(BaseModel):
    seed_session_id: str
    track_circuit: str
    track_layout: str
    track_location: Optional[str] = None
    sessions: list[CompareCandidateSession] = []


class LapOverlaySelection(BaseModel):
    session_id: str
    lap_number: int


class LapOverlayRequest(BaseModel):
    selections: list[LapOverlaySelection]
    reference_lap: LapOverlaySelection


class LapOverlaySeries(BaseModel):
    session_id: str
    display_name: Optional[str] = None
    lap_number: int
    lap_time_s: Optional[float] = None
    records: list[dict]


class TrackOutlinePoint(BaseModel):
    progress_norm: float
    distance_m: float
    center_x: float
    center_z: float
    left_x: float
    left_z: float
    right_x: float
    right_z: float
    width_m: float


class TrackOutline(BaseModel):
    outline_version: str
    session_id: str
    source_kind: str
    reference_lap_number: int
    reference_length_m: float
    sample_spacing_m: float
    source_lap_numbers: list[int] = []
    contributing_lap_count: int = 0
    points: list[TrackOutlinePoint] = []


class LapOverlayResponse(BaseModel):
    track_circuit: str
    track_layout: str
    track_location: Optional[str] = None
    reference_lap: LapOverlaySelection
    segmentation: Optional[dict] = None
    track_outline: Optional[TrackOutline] = None
    series: list[LapOverlaySeries]


class CaptureStatus(BaseModel):
    is_active: bool = False
    session_id: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    laps_detected: int = 0


class CaptureStartRequest(BaseModel):
    ip: str = "127.0.0.1"
    port: int = 5300
    session_id: Optional[str] = None


class ProcessResponse(BaseModel):
    session_id: str
    processed_laps: int
    message: str


class DeleteResponse(BaseModel):
    message: str


class SessionUpdateRequest(BaseModel):
    display_name: Optional[str] = None


class AnalyzeSessionRequest(BaseModel):
    experimental_detectors: Optional[bool] = None


class AnalyzeSessionResponse(BaseModel):
    session_id: str
    analysis_version: str
    analyzed_at_utc: str
    corner_record_count: int
    findings_top_count: int
    findings_all_count: int
    artifact_path: str
    detector_configuration: Dict[str, Any] = {}
    ml_status: str = "unavailable"


class ExpectedBand(BaseModel):
    expected: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None


class ExpectedTracePoint(BaseModel):
    progress_norm: float
    throttle: ExpectedBand
    brake: ExpectedBand
    steering: ExpectedBand
    speed: ExpectedBand


class ExpectedInputProfile(BaseModel):
    lap_number: int
    support: Optional[float] = None
    points: List[ExpectedTracePoint] = []


class MLModelContext(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    version: Optional[str] = None
    family: Optional[str] = None
    status: Optional[str] = None
    provenance: Optional[str] = None

    class Config:
        extra = "allow"


class MLAnalysisContext(BaseModel):
    status: str = "unavailable"
    optional: bool = True
    model: Optional[MLModelContext] = None
    dataset: Dict[str, Any] = {}
    expected_profiles: Dict[str, ExpectedInputProfile] = {}
    section_pace: Dict[str, List[Dict[str, Any]]] = {}
    recommendations: List[Dict[str, Any]] = []
    support: Dict[str, Any] = {}
    abstained: bool = True
    abstention_reasons: List[str] = []
    scenario: Dict[str, Any] = {}
    conditions: Dict[str, Any] = {}
    authority: Dict[str, Any] = {}

    class Config:
        extra = "allow"


class FindingMLContext(BaseModel):
    learned: bool = True
    model: Optional[MLModelContext] = None
    section_key: Optional[str] = None
    section_priority: Optional[float] = None
    deviation_strength: Optional[float] = None
    support: Optional[float] = None
    supported: bool = False
    abstained: bool = True
    abstention_reason: Optional[str] = None
    provenance: str = "registry_champion"
    expected_input_profile: Optional[ExpectedInputProfile] = None

    class Config:
        extra = "allow"


class ScenarioRecommendationResponse(BaseModel):
    recommendation_id: str
    section_key: str
    feature: str
    hypothesis: str
    cue: str
    learned: bool
    confidence: float
    model_version: Optional[str] = None
    abstention_reason: Optional[str] = None
    non_quantified_idea: bool = True
    seconds_saved_claimed: bool = False

    class Config:
        extra = "allow"


class AnalysisFindingResponse(BaseModel):
    finding_id: str
    corner_id: int
    lap_number: int
    detector: str
    severity: str
    confidence: float
    measured_confidence: Optional[float] = None
    section_priority: Optional[float] = None
    time_loss_s: float
    templated_text: str
    ai_context: Optional[str] = None
    evidence_refs: List[Dict[str, Any]] = []
    metrics_snapshot: Dict[str, Any] = {}
    ml_context: Optional[FindingMLContext] = None
    scenario_recommendation: Optional[ScenarioRecommendationResponse] = None


class SessionAnalysisResponse(BaseModel):
    analysis_version: str
    session_id: str
    reference_lap_number: int
    analyzed_at_utc: str
    reference_length_m: float = 0.0
    corner_definitions: List[Dict[str, Any]] = []
    per_corner_records: Dict[str, List[Dict[str, Any]]] = {}
    per_corner_baselines: Dict[str, Dict[str, Any]] = {}
    straight_records: List[Dict[str, Any]] = []
    findings_top: List[AnalysisFindingResponse] = []
    findings_all: List[AnalysisFindingResponse] = []
    lap_time_delta_reconciliation: Dict[str, Dict[str, Any]] = {}
    quality_report: Dict[str, Any] = {}
    detector_configuration: Dict[str, Any] = {}
    ml_context: MLAnalysisContext = MLAnalysisContext()
    track_outline: Optional[TrackOutline] = None

    class Config:
        extra = "allow"


class ManualConditionUpdateRequest(BaseModel):
    wetness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    air_temp_c: Optional[float] = Field(default=None, ge=-80.0, le=80.0)
    track_temp_c: Optional[float] = Field(default=None, ge=-80.0, le=100.0)
    tyre_wear: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    def supplied(self) -> Dict[str, float]:
        return {
            key: float(value)
            for key, value in {
                "wetness": self.wetness,
                "air_temp_c": self.air_temp_c,
                "track_temp_c": self.track_temp_c,
                "tyre_wear": self.tyre_wear,
            }.items()
            if value is not None
        }


class ManualConditionResponse(BaseModel):
    session_id: str
    conditions: Dict[str, Any] = {}
    origin: str = "manual"


class ModelMetricHealth(BaseModel):
    split: str
    name: str
    value: float


class ModelVersionHealth(BaseModel):
    id: int
    name: str
    version: str
    family: str
    status: str
    metrics: List[ModelMetricHealth] = []
    compatibility: Dict[str, Any] = {}
    source_revisions: Dict[str, Any] = {}


class ModelHealthResponse(BaseModel):
    status: str
    champion: Optional[ModelVersionHealth] = None
    challengers: List[ModelVersionHealth] = []
    fallback_reasons: List[str] = []


class DataHealthResponse(BaseModel):
    row_count: Dict[str, int] = {}
    effective_laps: Optional[int] = None
    source_imports: List[Dict[str, Any]] = []
    fallback_reasons: List[str] = []
