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
