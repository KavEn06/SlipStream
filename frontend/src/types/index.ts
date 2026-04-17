export interface SessionSummary {
  session_id: string;
  display_name: string | null;
  created_at_utc: string | null;
  track_circuit: string | null;
  track_layout: string | null;
  track_location: string | null;
  car_ordinal: number | null;
  total_laps: number;
  has_processed: boolean;
}

export interface LapSummary {
  lap_number: number;
  has_raw: boolean;
  has_processed: boolean;
  lap_time_s: number | null;
  is_valid: boolean | null;
}

export interface SessionDetail extends SessionSummary {
  sim: string | null;
  track_length_m: number | null;
  schema_version: string | null;
  processed_schema_version: string | null;
  notes: string;
  laps: LapSummary[];
}

export interface LapData {
  session_id: string;
  lap_number: number;
  data_type: string;
  columns: string[];
  records: Record<string, number | string>[];
  summary: {
    lap_time_s: number | null;
    lap_is_valid: boolean | null;
  };
  sampling: {
    view: string;
    source_rows: number;
    returned_rows: number;
    max_points: number | null;
    x_key: string;
  };
}

export interface CompareCandidateLap {
  lap_number: number;
  lap_time_s: number | null;
}

export interface CompareCandidateSession {
  session_id: string;
  display_name: string | null;
  created_at_utc: string | null;
  track_circuit: string | null;
  track_layout: string | null;
  track_location: string | null;
  laps: CompareCandidateLap[];
}

export interface CompareCandidatesResponse {
  seed_session_id: string;
  track_circuit: string;
  track_layout: string;
  track_location: string | null;
  sessions: CompareCandidateSession[];
}

export interface LapOverlaySelection {
  session_id: string;
  lap_number: number;
}

export interface LapOverlaySeries {
  session_id: string;
  display_name: string | null;
  lap_number: number;
  lap_time_s: number | null;
  records: Record<string, number | string>[];
}

export interface TrackOutlinePoint {
  progress_norm: number;
  distance_m: number;
  center_x: number;
  center_z: number;
  left_x: number;
  left_z: number;
  right_x: number;
  right_z: number;
  width_m: number;
}

export interface TrackOutline {
  outline_version: string;
  session_id: string;
  source_kind: "session_aggregate" | "synthetic_reference_path" | string;
  reference_lap_number: number;
  reference_length_m: number;
  sample_spacing_m: number;
  source_lap_numbers: number[];
  contributing_lap_count: number;
  points: TrackOutlinePoint[];
}

export interface LapOverlayResponse {
  track_circuit: string;
  track_layout: string;
  track_location: string | null;
  reference_lap: LapOverlaySelection;
  segmentation: TrackSegmentation | null;
  track_outline: TrackOutline | null;
  series: LapOverlaySeries[];
}

export interface CaptureStatus {
  is_active: boolean;
  session_id: string | null;
  ip: string | null;
  port: number | null;
  laps_detected: number;
}

export interface CaptureStartRequest {
  ip?: string;
  port?: number;
  session_id?: string | null;
}

export interface ProcessResponse {
  session_id: string;
  processed_laps: number;
  message: string;
}

export interface DeleteResponse {
  message: string;
}

export interface SessionUpdateRequest {
  display_name: string | null;
}

export interface CornerDefinition {
  corner_id: number;
  start_progress_norm: number;
  end_progress_norm: number;
  center_progress_norm: number;
  approach_start_distance_m: number;
  start_distance_m: number;
  end_distance_m: number;
  center_distance_m: number;
  entry_end_progress_norm: number;
  exit_start_progress_norm: number;
  length_m: number;
  peak_curvature: number;
  mean_curvature: number;
  direction: string;
  is_compound: boolean;
  sub_apex_progress_norms: number[];
  sub_apex_distances_m: number[];
}

export interface TrackSegmentation {
  segmentation_version: string;
  reference_lap_number: number;
  reference_length_m: number;
  corners: CornerDefinition[];
}

export interface AnalysisFinding {
  finding_id: string;
  corner_id: number;
  lap_number: number;
  detector: string;
  severity: "minor" | "moderate" | "major";
  confidence: number;
  time_loss_s: number;
  templated_text: string;
  evidence_refs: Array<{
    column?: string;
    progress_start?: number;
    progress_end?: number;
    [key: string]: unknown;
  }>;
  metrics_snapshot: Record<string, unknown>;
}

export interface SessionAnalysis {
  analysis_version: string;
  session_id: string;
  reference_lap_number: number;
  analyzed_at_utc: string;
  reference_length_m: number;
  corner_definitions: CornerDefinition[];
  per_corner_records: Record<string, unknown[]>;
  per_corner_baselines: Record<string, unknown>;
  straight_records: unknown[];
  findings_top: AnalysisFinding[];
  findings_all: AnalysisFinding[];
  lap_time_delta_reconciliation: Record<string, Record<string, number>>;
  quality_report: Record<string, unknown>;
  track_outline: TrackOutline | null;
}

export interface AnalyzeSessionResponse {
  session_id: string;
  analysis_version: string;
  analyzed_at_utc: string;
  corner_record_count: number;
  findings_top_count: number;
  findings_all_count: number;
  artifact_path: string;
}
