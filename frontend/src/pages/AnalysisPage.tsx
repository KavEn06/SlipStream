import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { CornerAnalysisPanel } from "../components/CornerAnalysisPanel";
import { SurfaceMessage, SurfaceSkeleton } from "../components/PageState";
import type { SessionSummary } from "../types";
import {
  applySessionDisplayNameOverrides,
  formatSessionDateLabel,
  getSessionTitle,
  getSessionVehicleTrackLabel,
  sortSessionsForLibrary,
} from "../utils/sessions";

function AnalysisStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="density-analysis-stat min-w-[130px] rounded-xl border border-border/70 bg-surface-2/80">
      <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">{label}</p>
      <p className="mt-1.5 text-sm font-medium text-text-primary">{value}</p>
    </div>
  );
}

function buildAnalysisSearchParams(sessionId: string): URLSearchParams {
  const params = new URLSearchParams();
  params.set("sessionId", sessionId);
  return params;
}

export function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const seededSessionId = searchParams.get("sessionId")?.trim() ?? "";
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionListOpen, setSessionListOpen] = useState(true);

  const loadSessions = async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
    }

    try {
      const result = await api.getSessions();
      setSessions(applySessionDisplayNameOverrides(result));
      setLoadError(null);
    } catch (error) {
      setLoadError(
        error instanceof Error ? error.message : "Failed to load processed sessions",
      );
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    void loadSessions(true);
  }, []);

  const processedSessions = useMemo(
    () => sortSessionsForLibrary(sessions.filter((session) => session.has_processed), "newest"),
    [sessions],
  );

  const selectedSession = useMemo(
    () =>
      processedSessions.find((session) => session.session_id === seededSessionId) ??
      processedSessions[0] ??
      null,
    [processedSessions, seededSessionId],
  );

  useEffect(() => {
    if (!processedSessions.length || !selectedSession) {
      return;
    }

    if (selectedSession.session_id !== seededSessionId) {
      setSearchParams(buildAnalysisSearchParams(selectedSession.session_id), {
        replace: true,
      });
    }
  }, [processedSessions, seededSessionId, selectedSession, setSearchParams]);

  const handleSelectSession = (sessionId: string) => {
    setSearchParams(buildAnalysisSearchParams(sessionId), { replace: true });
  };

  const uniqueTracks = useMemo(
    () =>
      new Set(
        processedSessions.map((session) =>
          `${session.track_circuit?.trim() || "Unknown"}::${session.track_layout?.trim() || "--"}`,
        ),
      ).size,
    [processedSessions],
  );

  if (loading) {
    return (
      <div className="density-analysis-stack max-w-7xl">
        <SurfaceSkeleton rows={4} />
        <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
          <SurfaceSkeleton rows={6} />
          <SurfaceSkeleton rows={6} />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <SurfaceMessage
        title="Could not load processed sessions"
        message={loadError}
        tone="danger"
        actionLabel="Retry"
        onAction={() => void loadSessions(true)}
      />
    );
  }

  if (processedSessions.length === 0) {
    return (
      <SurfaceMessage
        title="No processed sessions yet"
        message="Process a session first, then SlipStream can run corner analysis for it here."
      />
    );
  }

  return (
    <div className="density-analysis-stack max-w-7xl">
      <section className="relative overflow-hidden rounded-[28px] border border-border/70 bg-surface-1/92 backdrop-blur-xl">
        <div className="hero-overlay pointer-events-none absolute inset-0" />
        <div className="hero-band pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg]" />
        <div className="density-analysis-panel relative">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="min-w-0 truncate text-3xl font-semibold tracking-tight text-text-primary">
                  Session Analysis
                </h2>
                <span className="inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-accent">
                  Deterministic coaching layer
                </span>
              </div>
              <p className="mt-2 text-sm text-text-secondary">
                Run and review corner-level findings for processed sessions without leaving the analysis workspace.
              </p>
            </div>

            {selectedSession && (
              <div className="flex flex-wrap items-center gap-3">
                <Link
                  to={`/sessions/${selectedSession.session_id}`}
                  className="motion-safe-color inline-flex h-10 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-sm font-medium text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                >
                  Open Session
                </Link>
              </div>
            )}
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <AnalysisStat label="Processed Sessions" value={String(processedSessions.length)} />
            <AnalysisStat
              label="Unique Track Layouts"
              value={String(uniqueTracks)}
            />
            <AnalysisStat
              label="Selected Session"
              value={selectedSession ? getSessionTitle(selectedSession) : "--"}
            />
          </div>
        </div>
      </section>

      <div
        className={`grid gap-5 ${
          sessionListOpen ? "lg:grid-cols-[minmax(0,340px)_1fr]" : "grid-cols-1"
        }`}
      >
        {sessionListOpen && (
          <section className="density-analysis-panel rounded-[28px] border border-border/70 bg-surface-1/85">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                Processed Sessions
              </p>
              <p className="mt-1 text-sm text-text-secondary">
                Click a session. Run analysis from the right panel.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSessionListOpen(false)}
              aria-label="Hide session list"
              title="Hide session list"
              className="motion-safe-color shrink-0 rounded-full border border-border/70 bg-surface-2/84 px-2.5 py-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
            >
              Hide
            </button>
          </div>

          <div className="mt-5 space-y-3">
            {processedSessions.map((session) => {
              const selected = selectedSession?.session_id === session.session_id;

              return (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => handleSelectSession(session.session_id)}
                  className={`motion-safe-color w-full rounded-2xl border p-4 text-left transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 ${
                    selected
                      ? "border-accent/24 bg-accent/10"
                      : "border-border/70 bg-surface-2/78 hover:border-border-strong hover:bg-surface-2/92"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <p className="truncate text-sm font-medium text-text-primary">
                        {getSessionTitle(session)}
                      </p>
                      {selected && (
                        <span className="shrink-0 rounded-full border border-accent/24 bg-accent/12 px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.14em] text-accent">
                          Selected
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-text-secondary">
                      {getSessionVehicleTrackLabel(session)}
                    </p>
                    <p className="mt-1 text-[11px] text-text-muted">
                      {formatSessionDateLabel(session)} · {session.total_laps} laps
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
          </section>
        )}

        <section className="density-analysis-panel rounded-[28px] border border-border/70 bg-surface-1/85">
          {!sessionListOpen && (
            <div className="mb-4">
              <button
                type="button"
                onClick={() => setSessionListOpen(true)}
                aria-label="Show session list"
                className="motion-safe-color inline-flex h-8 items-center rounded-full border border-accent/24 bg-accent/12 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-accent hover:bg-accent/18 cursor-pointer"
              >
                Sessions
              </button>
            </div>
          )}
          {selectedSession ? (
            <CornerAnalysisPanel
              key={selectedSession.session_id}
              sessionId={selectedSession.session_id}
              enabled
            />
          ) : (
            <SurfaceMessage
              title="No processed session selected"
              message="Open the session list and pick a session to view or run analysis."
            />
          )}
        </section>
      </div>
    </div>
  );
}
