import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useCaptureController } from "../hooks/useCaptureController";
import type { SessionDetail, SessionSummary } from "../types";
import {
  deriveDashboardKpis,
  deriveTrackBreakdown,
  formatSessionDateLabel,
  formatSessionTimestamp,
  getRecentSessions,
} from "../utils/sessions";

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-3xl border border-white/5 bg-white/[0.02] p-5">
      <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
        {label}
      </p>
      <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-2 text-sm text-text-secondary">{hint}</p>
    </div>
  );
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/5 py-3 last:border-b-0">
      <span className="text-xs uppercase tracking-[0.14em] text-text-muted">
        {label}
      </span>
      <span className="text-right text-sm text-text-secondary">{value}</span>
    </div>
  );
}

function HeroMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="border-l-2 border-accent/70 pl-4">
      <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
        {value}
      </p>
      <p className="mt-1 text-xs uppercase tracking-[0.16em] text-text-secondary">
        {detail}
      </p>
    </div>
  );
}

function getCarNameLabel(carOrdinal: number | null | undefined): string {
  if (carOrdinal === null || carOrdinal === undefined) {
    return "No Active Car";
  }
  return `Car #${carOrdinal}`;
}

function getCarClassLabel(carOrdinal: number | null | undefined): string {
  if (carOrdinal === null || carOrdinal === undefined) {
    return "Waiting For Capture";
  }
  return "Class Unavailable";
}

export function HomePage() {
  const capture = useCaptureController();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);

  const loadSessions = async (showLoading = false) => {
    if (showLoading) {
      setSessionsLoading(true);
    }

    try {
      const result = await api.getSessions();
      setSessions(result);
      setSessionsError(null);
    } catch (err) {
      setSessionsError(
        err instanceof Error ? err.message : "Failed to load dashboard data",
      );
    } finally {
      if (showLoading) {
        setSessionsLoading(false);
      }
    }
  };

  useEffect(() => {
    let cancelled = false;

    const pollSessions = async (showLoading = false) => {
      if (cancelled) return;
      await loadSessions(showLoading);
    };

    void pollSessions(true);
    const id = window.setInterval(() => {
      void pollSessions(false);
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    const activeSessionId = capture.status?.is_active
      ? capture.status.session_id
      : null;

    if (!activeSessionId) {
      setActiveSession(null);
      return;
    }

    let cancelled = false;

    const loadActiveSession = async () => {
      try {
        const result = await api.getSession(activeSessionId);
        if (!cancelled) {
          setActiveSession(result);
        }
      } catch {
        if (!cancelled) {
          setActiveSession(null);
        }
      }
    };

    void loadActiveSession();
    const id = window.setInterval(() => {
      void loadActiveSession();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [capture.status?.is_active, capture.status?.session_id]);

  const kpis = useMemo(() => deriveDashboardKpis(sessions), [sessions]);
  const trackBreakdown = useMemo(() => deriveTrackBreakdown(sessions), [sessions]);
  const recentSessions = useMemo(() => getRecentSessions(sessions, 5), [sessions]);
  const activeSessionSummary = useMemo(
    () =>
      capture.status?.session_id
        ? sessions.find((session) => session.session_id === capture.status?.session_id) ??
          null
        : null,
    [sessions, capture.status?.session_id],
  );

  const isActive = capture.status?.is_active ?? false;
  const activeTrack =
    activeSession?.track_circuit ??
    activeSessionSummary?.track_circuit ??
    "Awaiting session metadata";
  const activeLayout =
    activeSession?.track_layout ?? activeSessionSummary?.track_layout ?? "--";
  const activeLocation =
    activeSession?.track_location ?? activeSessionSummary?.track_location ?? "--";
  const activeCarOrdinal =
    activeSession?.car_ordinal ?? activeSessionSummary?.car_ordinal;
  const carNameLabel = getCarNameLabel(activeCarOrdinal);
  const carClassLabel = getCarClassLabel(activeCarOrdinal);

  const handleCaptureAction = async () => {
    const result = isActive
      ? await capture.stopCapture()
      : await capture.startCapture();

    if (!result) return;

    await loadSessions(false);
    if (!result.is_active) {
      setActiveSession(null);
    }
  };

  return (
    <div className="max-w-6xl space-y-8">
      <section className="overflow-hidden rounded-[30px] border border-white/6 bg-white/[0.02]">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1.7fr)_360px]">
          <div className="relative overflow-hidden px-6 py-6 lg:px-8 lg:py-8">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(209,75,75,0.24),transparent_30%),linear-gradient(118deg,rgba(255,255,255,0.03),transparent_44%),repeating-linear-gradient(135deg,rgba(255,255,255,0.035)_0px,rgba(255,255,255,0.035)_1px,transparent_1px,transparent_18px)]" />
            <div className="pointer-events-none absolute -left-18 top-8 h-28 w-64 rotate-[-18deg] border-y border-white/8 bg-white/[0.02]" />
            <div className="pointer-events-none absolute bottom-12 right-6 h-24 w-52 rotate-[11deg] border border-white/8 bg-black/10" />

            <div className="relative">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center border border-white/8 bg-black/25 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-text-secondary [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]">
                    SlipStream // Race Control
                  </span>
                  <div className="flex items-center gap-2">
                    <div
                      className={`h-2.5 w-2.5 rounded-full ${
                        isActive ? "bg-success animate-pulse" : "bg-text-muted"
                      }`}
                    />
                    <span className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                      {isActive ? "Capture Live" : "Standby"}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] uppercase tracking-[0.24em] text-text-muted">
                  {activeLayout !== "--" ? `${activeTrack} // ${activeLayout}` : activeTrack}
                </span>
              </div>

              <div className="mt-10">
                <p className="text-sm uppercase tracking-[0.22em] text-text-muted">
                  {activeTrack}
                </p>
                <h2 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight text-white lg:text-[3.6rem] lg:leading-[1.02]">
                  {isActive
                    ? "Telemetry is flowing."
                    : "SlipStream is ready for the next run."}
                </h2>
                <p className="mt-4 max-w-2xl text-sm leading-6 text-text-secondary">
                  Keep capture controls, live session state, and your session library in one
                  place with a layout that stays focused on the car you are driving right now.
                </p>
              </div>

              <div className="mt-10 grid gap-5 border-t border-white/6 pt-6 md:grid-cols-3">
                <HeroMetric
                  label="Session"
                  value={capture.status?.session_id ?? "No active session"}
                  detail={isActive ? "Live session id" : "Waiting to start"}
                />
                <HeroMetric
                  label="Laps Detected"
                  value={String(capture.status?.laps_detected ?? 0)}
                  detail={isActive ? "Live lap count" : "No laps detected"}
                />
                <HeroMetric
                  label="Connection"
                  value={`${capture.status?.ip ?? capture.ip}:${capture.status?.port ?? capture.port}`}
                  detail="Telemetry endpoint"
                />
              </div>

              <div className="mt-8 border-t border-white/6 pt-6">
                <div className="flex flex-wrap items-end justify-between gap-6">
                  <div className="flex flex-wrap gap-x-6 gap-y-4">
                    <div>
                      <label className="mb-1 block text-xs text-text-muted">
                        IP Address
                      </label>
                      <input
                        type="text"
                        value={capture.ip}
                        disabled={isActive}
                        onChange={(event) => capture.setIp(event.target.value)}
                        className="w-36 border-x-0 border-b border-t-0 border-white/12 bg-transparent px-0 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs text-text-muted">
                        Port
                      </label>
                      <input
                        type="text"
                        value={capture.port}
                        disabled={isActive}
                        onChange={(event) => capture.setPort(event.target.value)}
                        className="w-28 border-x-0 border-b border-t-0 border-white/12 bg-transparent px-0 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                      />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={handleCaptureAction}
                      disabled={capture.busy}
                      className={`inline-flex items-center border px-4 py-2 text-sm font-medium uppercase tracking-[0.18em] transition-colors cursor-pointer disabled:opacity-50 [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)] ${
                        isActive
                          ? "border-danger/30 bg-danger/10 text-danger hover:bg-danger/18"
                          : "border-accent/30 bg-accent/12 text-accent hover:bg-accent/18"
                      }`}
                    >
                      {capture.busy ? "Working" : isActive ? "Stop Capture" : "Start Capture"}
                    </button>
                    <Link
                      to="/sessions"
                      className="inline-flex items-center border border-white/10 px-4 py-2 text-sm uppercase tracking-[0.18em] text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]"
                    >
                      View Library
                    </Link>
                  </div>
                </div>
              </div>

              {capture.error && (
                <p className="mt-4 text-sm text-danger">{capture.error}</p>
              )}
            </div>
          </div>

          <aside className="border-t border-white/5 bg-[linear-gradient(180deg,rgba(0,0,0,0.18),rgba(0,0,0,0.34))] px-6 py-6 lg:px-7 xl:border-l xl:border-t-0">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-[0.24em] text-text-muted">
                  Current Car
                </p>
                <h3 className="mt-4 max-w-[14rem] text-3xl font-semibold tracking-tight text-white">
                  {carNameLabel}
                </h3>
                <div className="mt-3 inline-flex border border-accent/25 bg-accent/12 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-accent [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]">
                  {carClassLabel}
                </div>
              </div>
              {isActive ? (
                <span className="rounded-full bg-success/12 px-2.5 py-1 text-[11px] font-medium text-success">
                  Live
                </span>
              ) : (
                <span className="rounded-full bg-white/5 px-2.5 py-1 text-[11px] font-medium text-text-muted">
                  Idle
                </span>
              )}
            </div>

            <div className="mt-8 flex items-end justify-between border-b border-white/8 pb-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                  Driver Context
                </p>
                <p className="mt-2 text-sm text-text-secondary">
                  {activeLocation !== "--" ? activeLocation : "Location unavailable"}
                </p>
              </div>
              <p className="text-5xl font-semibold tracking-tight text-white/90">
                {String(capture.status?.laps_detected ?? 0).padStart(2, "0")}
              </p>
            </div>

            <div className="mt-6 space-y-3">
              <DetailRow label="Track" value={activeTrack} />
              <DetailRow label="Layout" value={activeLayout} />
              <DetailRow
                label="Car Ordinal"
                value={
                  activeCarOrdinal !== null && activeCarOrdinal !== undefined
                    ? String(activeCarOrdinal)
                    : "--"
                }
              />
              <DetailRow
                label="Session"
                value={capture.status?.session_id ?? "Waiting"}
              />
            </div>

            {!isActive && (
              <p className="mt-6 text-sm leading-6 text-text-secondary">
                The layout is ready for a real Forza-style car name and class panel. Right now
                the app only exposes `car_ordinal`, so this block uses a graceful fallback until
                richer vehicle metadata is available.
              </p>
            )}
          </aside>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total Sessions"
          value={String(kpis.totalSessions)}
          hint="All raw and processed sessions discovered in the library"
        />
        <StatCard
          label="Total Laps"
          value={String(kpis.totalLaps)}
          hint="Combined lap count across the full session catalog"
        />
        <StatCard
          label="Processed Sessions"
          value={String(kpis.processedSessions)}
          hint="Sessions with at least one processed lap ready for review"
        />
        <StatCard
          label="Unique Tracks"
          value={String(kpis.uniqueTracks)}
          hint="Distinct circuits represented in the current dataset"
        />
      </div>

      <section className="rounded-[28px] border border-white/6 bg-white/[0.02] p-5">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
              Track Breakdown
            </p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight">
              Most-used tracks
            </h3>
          </div>
          <p className="text-sm text-text-muted">
            Ranked by session count, with laps as supporting context
          </p>
        </div>

        {trackBreakdown.length === 0 ? (
          <div className="mt-5 rounded-3xl border border-dashed border-white/8 bg-black/20 p-8 text-center text-sm text-text-secondary">
            Track distribution will appear once sessions are available.
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            {trackBreakdown.map((track, index) => (
              <div key={track.name} className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="text-xs font-medium text-text-muted">
                      {(index + 1).toString().padStart(2, "0")}
                    </span>
                    <span className="truncate text-sm font-medium text-white">
                      {track.name}
                    </span>
                  </div>
                  <span className="text-xs text-text-secondary">
                    {track.sessions} sessions • {track.laps} laps
                  </span>
                </div>
                <div className="h-2 rounded-full bg-black/30">
                  <div
                    className="h-2 rounded-full bg-accent"
                    style={{ width: `${Math.max(track.share * 100, 8)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-[28px] border border-white/6 bg-white/[0.02] p-5">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
              Recent Sessions
            </p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight">
              Jump back into your latest telemetry
            </h3>
          </div>
          {!sessionsLoading && (
            <p className="text-sm text-text-muted">
              {recentSessions.length} of {sessions.length} shown
            </p>
          )}
        </div>

        {sessionsError && (
          <p className="mt-4 text-sm text-danger">{sessionsError}</p>
        )}

        {sessionsLoading ? (
          <p className="mt-5 text-sm text-text-muted">Loading dashboard data...</p>
        ) : recentSessions.length === 0 ? (
          <div className="mt-5 rounded-3xl border border-dashed border-white/8 bg-black/20 p-8 text-center text-sm text-text-secondary">
            No recent sessions yet. Start a capture or add raw data to begin reviewing.
          </div>
        ) : (
          <div className="mt-5 overflow-hidden rounded-3xl border border-white/5">
            {recentSessions.map((session) => (
              <Link
                key={session.session_id}
                to={`/sessions/${session.session_id}`}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-black/20 px-4 py-4 transition-colors hover:bg-white/[0.03] last:border-b-0"
              >
                <div className="min-w-0">
                  <p className="font-mono text-sm font-medium text-white">
                    {formatSessionTimestamp(session.session_id)}
                  </p>
                  <p className="mt-1 truncate text-sm text-text-secondary">
                    {session.track_circuit || "Unknown Track"}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">
                    {formatSessionDateLabel(session)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-text-muted">
                    {session.total_laps} laps
                  </span>
                  <StatusBadge processed={session.has_processed} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
