import type {
  CaptureStartRequest,
  CaptureStatus,
  DeleteResponse,
  LapData,
  ProcessResponse,
  SessionDetail,
  SessionSummary,
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
  ) =>
    fetchJson<LapData>(
      `/sessions/${sessionId}/laps/${lapNumber}?data_type=${type}`,
    ),

  processSession: (id: string) =>
    fetchJson<ProcessResponse>(`/sessions/${id}/process`, { method: "POST" }),

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
};
