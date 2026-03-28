import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useCaptureController } from "../hooks/useCaptureController";
import type { SessionDetail, SessionSummary } from "../types";
import {
  deriveDashboardKpis,
  deriveFavoriteCar,
  deriveTrackBreakdown,
  formatSessionDateLabel,
  formatSessionTimestamp,
  getRecentSessions,
  getSessionCarLabel,
  getSessionVehicleTrackLabel,
} from "../utils/sessions";

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-3xl border border-white/5 bg-white/[0.02] p-5">
      <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
        {label}
      </p>
      <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
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

export function HomePage() {
  const capture = useCaptureController();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [showAdvancedCapture, setShowAdvancedCapture] = useState(false);

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
  const favoriteCar = useMemo(() => deriveFavoriteCar(sessions), [sessions]);
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
  const heroTrack =
    activeSession?.track_circuit ??
    activeSessionSummary?.track_circuit ??
    "Telemetry Workstation";
  const activeLayout =
    activeSession?.track_layout ?? activeSessionSummary?.track_layout ?? "--";
  const activeLocation =
    activeSession?.track_location ?? activeSessionSummary?.track_location ?? "--";
  const activeCarOrdinal =
    activeSession?.car_ordinal ?? activeSessionSummary?.car_ordinal;
  const carNameLabel =
    getSessionCarLabel(activeCarOrdinal) ?? "No Active Vehicle";
  const heroVehicleTrackLabel = getSessionVehicleTrackLabel({
    car_ordinal: activeCarOrdinal ?? null,
    track_circuit: heroTrack,
  });
  const liveSessionLabel = isActive ? capture.status?.session_id ?? "Idle" : "Idle";
  const liveLapCount = isActive ? capture.status?.laps_detected ?? 0 : 0;
  const captureSettingsId = "home-capture-settings";

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
    <div className="max-w-7xl space-y-6">
      <section className="space-y-4">
        <div className="overflow-hidden rounded-[30px] border border-white/6 bg-white/[0.02]">
          <div className="grid gap-0 xl:grid-cols-[minmax(0,1.8fr)_300px]">
            <div className="relative overflow-hidden px-6 py-6 lg:px-8 lg:py-8">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(209,75,75,0.22),transparent_32%),linear-gradient(118deg,rgba(255,255,255,0.03),transparent_44%),repeating-linear-gradient(135deg,rgba(255,255,255,0.03)_0px,rgba(255,255,255,0.03)_1px,transparent_1px,transparent_18px)]" />
              <div className="pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg] border-y border-white/8 bg-white/[0.02]" />

              <div className="relative">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="inline-flex items-center border border-white/8 bg-black/25 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-text-secondary [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]">
                      SlipStream // Review Station
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
                </div>

                <div className="mt-10">
                  <p className="text-sm uppercase tracking-[0.22em] text-text-muted">
                    {heroVehicleTrackLabel}
                  </p>
                  <h2 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight text-white lg:text-[3.5rem] lg:leading-[1.02]">
                    {isActive ? "Telemetry Online." : "Telemetry Ready."}
                  </h2>
                </div>

                <div className="mt-8 grid gap-4 rounded-[24px] border border-white/6 bg-black/18 p-5 md:grid-cols-[minmax(0,1.4fr)_140px_auto]">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                      Current Session
                    </p>
                    <p className="mt-2 truncate font-mono text-sm text-white">
                      {liveSessionLabel}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                      Laps
                    </p>
                    <p className="mt-2 text-3xl font-semibold tracking-tight text-white">
                      {liveLapCount}
                    </p>
                  </div>
                  <div className="flex items-end md:justify-end">
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
                  </div>
                </div>

                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => setShowAdvancedCapture((current) => !current)}
                    aria-expanded={showAdvancedCapture}
                    aria-controls={captureSettingsId}
                    className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.22em] text-text-muted transition-colors hover:text-text-secondary cursor-pointer"
                  >
                    <span>Capture Settings</span>
                    <svg
                      className={`h-4 w-4 transition-transform ${showAdvancedCapture ? "rotate-180" : ""}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.8}
                        d="M19 9l-7 7-7-7"
                      />
                    </svg>
                  </button>

                  <div
                    id={captureSettingsId}
                    aria-hidden={!showAdvancedCapture}
                    className={`grid transition-all duration-300 ease-out ${
                      showAdvancedCapture
                        ? "mt-4 grid-rows-[1fr] opacity-100"
                        : "mt-0 grid-rows-[0fr] opacity-0"
                    }`}
                  >
                    <div className="overflow-hidden">
                      <div className="grid gap-4 rounded-2xl border border-white/6 bg-black/16 p-4 md:grid-cols-[auto_auto_1fr]">
                        <div>
                          <label className="mb-1 block text-xs text-text-muted">
                            IP Address
                          </label>
                          <input
                            type="text"
                            value={capture.ip}
                            disabled={!showAdvancedCapture || isActive}
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
                            disabled={!showAdvancedCapture || isActive}
                            onChange={(event) => capture.setPort(event.target.value)}
                            className="w-28 border-x-0 border-b border-t-0 border-white/12 bg-transparent px-0 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                          />
                        </div>
                        <div className="self-end">
                          <p className="text-xs uppercase tracking-[0.16em] text-text-muted">
                            Endpoint
                          </p>
                          <p className="mt-2 text-sm text-text-secondary">
                            {capture.status?.ip ?? capture.ip}:{capture.status?.port ?? capture.port}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {capture.error && (
                  <p className="mt-4 text-sm text-danger">{capture.error}</p>
                )}
              </div>
            </div>

            <aside className="border-t border-white/5 bg-[linear-gradient(180deg,rgba(0,0,0,0.12),rgba(0,0,0,0.24))] px-6 py-6 lg:px-7 xl:border-l xl:border-t-0">
              <p className="text-[10px] uppercase tracking-[0.24em] text-text-muted">
                Vehicle Context
              </p>
              <h3 className="mt-4 text-2xl font-semibold tracking-tight text-white">
                {carNameLabel}
              </h3>
              <p className="mt-2 text-sm text-text-muted">
                {activeCarOrdinal !== null && activeCarOrdinal !== undefined
                  ? `Ordinal ${activeCarOrdinal}`
                  : "No vehicle data"}
              </p>

              <div className="mt-6 space-y-3">
                <DetailRow label="Layout" value={activeLayout} />
                <DetailRow label="Location" value={activeLocation} />
                <DetailRow
                  label="Status"
                  value={isActive ? "Capture Live" : "Standby"}
                />
              </div>
            </aside>
          </div>
        </div>

        <section className="rounded-[28px] border border-white/6 bg-white/[0.02] p-5">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
                Recent Sessions
              </p>
              <h3 className="mt-2 text-xl font-semibold tracking-tight">
                Latest Sessions
              </h3>
            </div>
            <Link
              to="/sessions"
              className="text-sm text-text-secondary transition-colors hover:text-white"
            >
              All Sessions
            </Link>
          </div>

          {sessionsError && (
            <p className="mt-4 text-sm text-danger">{sessionsError}</p>
          )}

          {sessionsLoading ? (
            <p className="mt-5 text-sm text-text-muted">Loading...</p>
          ) : recentSessions.length === 0 ? (
            <div className="mt-5 rounded-3xl border border-dashed border-white/8 bg-black/20 p-8 text-center text-sm text-text-secondary">
              No sessions
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
                      {getSessionVehicleTrackLabel(session)}
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
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total Sessions"
          value={String(kpis.totalSessions)}
        />
        <StatCard
          label="Total Laps"
          value={String(kpis.totalLaps)}
        />
        <StatCard
          label="Processed Sessions"
          value={String(kpis.processedSessions)}
        />
        <StatCard
          label="Unique Tracks"
          value={String(kpis.uniqueTracks)}
        />
      </div>

      <section className="rounded-[28px] border border-white/6 bg-white/[0.02] p-5">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
            Track Breakdown
          </p>
          <h3 className="mt-2 text-xl font-semibold tracking-tight">
            Most-used tracks
          </h3>
        </div>

        {trackBreakdown.length === 0 ? (
          <div className="mt-5 rounded-3xl border border-dashed border-white/8 bg-black/20 p-8 text-center text-sm text-text-secondary">
            No tracks
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

      <section className="overflow-hidden rounded-[28px] border border-white/6 bg-white/[0.02]">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1.3fr)_360px]">
          <div className="relative overflow-hidden px-5 py-6 lg:px-6">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(209,75,75,0.18),transparent_34%),linear-gradient(115deg,rgba(255,255,255,0.02),transparent_50%)]" />
            <div className="relative">
              <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
                Favourite Car
              </p>

              {favoriteCar ? (
                <>
                  <h3 className="mt-3 text-3xl font-semibold tracking-tight text-white lg:text-[2.5rem]">
                    {getSessionCarLabel(favoriteCar.carOrdinal)}
                  </h3>
                  <p className="mt-2 text-sm uppercase tracking-[0.2em] text-text-muted">
                    {favoriteCar.topTrack}
                  </p>

                  <div className="mt-6 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-2xl border border-white/6 bg-black/20 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Sessions
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
                        {favoriteCar.sessions}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/6 bg-black/20 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Laps
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
                        {favoriteCar.laps}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/6 bg-black/20 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Processed
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
                        {favoriteCar.processedSessions}
                      </p>
                    </div>
                  </div>
                </>
              ) : (
                <div className="mt-5 rounded-3xl border border-dashed border-white/8 bg-black/20 p-8 text-center text-sm text-text-secondary">
                  No vehicle data
                </div>
              )}
            </div>
          </div>

          <aside className="border-t border-white/5 bg-[linear-gradient(180deg,rgba(0,0,0,0.12),rgba(0,0,0,0.24))] px-5 py-6 lg:border-l lg:border-t-0 lg:px-6">
            <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
              Garage Focus
            </p>

            {favoriteCar ? (
              <div className="mt-5 space-y-3">
                <DetailRow
                  label="Vehicle"
                  value={getSessionCarLabel(favoriteCar.carOrdinal) ?? "--"}
                />
                <DetailRow label="Top Track" value={favoriteCar.topTrack} />
                <DetailRow
                  label="Usage"
                  value={`${favoriteCar.sessions} sessions`}
                />
              </div>
            ) : (
              <div className="mt-5 rounded-2xl border border-dashed border-white/8 bg-black/20 p-5 text-sm text-text-secondary">
                Capture and review more sessions to build vehicle trends.
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
}
