import type {
  AnalyzeSessionResponse,
  CaptureStartRequest,
  CaptureStatus,
  CompareCandidatesResponse,
  DeleteResponse,
  LapData,
  LapOverlayResponse,
  LapOverlaySelection,
  ProcessResponse,
  SessionAnalysis,
  SessionDetail,
  SessionSummary,
  SessionUpdateRequest,
  TrackSegmentation,
} from "../types";

const API_BASE = "/api";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  getSessions: () => fetchJson<SessionSummary[]>("/sessions"),

  getSession: (id: string) => fetchJson<SessionDetail>(`/sessions/${id}`),

  getLap: (
    sessionId: string,
    lapNumber: number,
    type: "raw" | "processed" = "processed",
    options?: {
      view?: "full" | "review";
      maxPoints?: number;
    },
  ) =>
    fetchJson<LapData>(`/sessions/${sessionId}/laps/${lapNumber}?${new URLSearchParams({
      data_type: type,
      ...(options?.view ? { view: options.view } : {}),
      ...(options?.maxPoints !== undefined ? { max_points: String(options.maxPoints) } : {}),
    }).toString()}`),

  getCompareLapCandidates: (sessionId: string) =>
    fetchJson<CompareCandidatesResponse>(
      `/compare/laps/candidates?${new URLSearchParams({ session_id: sessionId }).toString()}`,
    ),

  buildLapCompare: (body: {
    selections: LapOverlaySelection[];
    reference_lap: LapOverlaySelection;
  }) =>
    fetchJson<LapOverlayResponse>("/compare/laps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  processSession: (id: string) =>
    fetchJson<ProcessResponse>(`/sessions/${id}/process`, { method: "POST" }),

  updateSession: (id: string, body: SessionUpdateRequest) =>
    fetchJson<SessionDetail>(`/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  getSegmentation: (sessionId: string) =>
    fetchJson<TrackSegmentation>(`/sessions/${sessionId}/segmentation`),

  deleteSession: (id: string) =>
    fetchJson<DeleteResponse>(`/sessions/${id}`, { method: "DELETE" }),

  deleteLap: (sessionId: string, lapNumber: number) =>
    fetchJson<DeleteResponse>(`/sessions/${sessionId}/laps/${lapNumber}`, {
      method: "DELETE",
    }),

  getCaptureStatus: () => fetchJson<CaptureStatus>("/capture/status"),

  startCapture: (body: CaptureStartRequest) =>
    fetchJson<CaptureStatus>("/capture/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  stopCapture: () =>
    fetchJson<CaptureStatus>("/capture/stop", { method: "POST" }),

  analyzeSession: (id: string) =>
    fetchJson<AnalyzeSessionResponse>(`/sessions/${id}/analyze`, {
      method: "POST",
    }),

  getSessionAnalysis: (id: string) =>
    fetchJson<SessionAnalysis>(`/sessions/${id}/analysis`),
};
