import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { SurfaceMessage, SurfaceSkeleton } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import {
  DEFAULT_CAPTURE_IP,
  DEFAULT_CAPTURE_PORT,
  useCaptureController,
} from "../hooks/useCaptureController";
import type { SessionDetail, SessionSummary } from "../types";
import {
  applySessionDisplayNameOverride,
  applySessionDisplayNameOverrides,
  deriveDashboardKpis,
  deriveFavoriteCar,
  deriveTrackBreakdown,
  formatSessionDateLabel,
  getRecentSessions,
  getSessionCarLabel,
  getSessionTitle,
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
    <div className="density-home-card rounded-3xl border border-border/70 bg-surface-1/85 p-5">
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
    <div className="density-home-detail-row flex items-center justify-between gap-3 border-b border-border/60 py-3 last:border-b-0">
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
      setSessions(applySessionDisplayNameOverrides(result));
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
          setActiveSession(applySessionDisplayNameOverride(result));
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
  const liveSessionLabel =
    isActive && activeSession
      ? getSessionTitle(activeSession)
      : isActive && activeSessionSummary
        ? getSessionTitle(activeSessionSummary)
      : isActive
        ? capture.status?.session_id ?? "Idle"
        : "Idle";
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

  const latestSessionsSection = (() => {
    if (sessionsLoading) {
      return <SurfaceSkeleton className="mt-5" rows={3} />;
    }

    if (sessionsError && recentSessions.length === 0) {
      return (
        <SurfaceMessage
          title="Could not load recent sessions"
          message={sessionsError}
          actionLabel="Retry"
          onAction={() => void loadSessions(true)}
          tone="danger"
          className="mt-5"
        />
      );
    }

    if (recentSessions.length === 0) {
      return (
        <div className="mt-5 rounded-3xl border border-dashed border-border/70 bg-surface-2/72 p-8 text-center text-sm text-text-secondary">
          No sessions
        </div>
      );
    }

    return (
      <div className="mt-5 overflow-hidden rounded-3xl border border-border/60">
        {recentSessions.map((session) => (
          <Link
            key={session.session_id}
            to={`/sessions/${session.session_id}`}
            className="density-home-list-row flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-surface-2/72 px-4 py-4 transition-colors hover:bg-surface-3/82 last:border-b-0"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-text-primary">
                {getSessionTitle(session)}
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
    );
  })();

  return (
    <div className="density-home-stack max-w-7xl">
      <section className="density-home-cluster">
        <div className="overflow-hidden rounded-[30px] border border-border/70 bg-surface-1/85">
          <div className="grid gap-0 xl:grid-cols-[minmax(0,1.8fr)_300px]">
            <div className="density-home-hero relative overflow-hidden px-6 py-6 lg:px-8 lg:py-8">
              <div className="hero-overlay pointer-events-none absolute inset-0" />
              <div className="hero-band pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg]" />

              <div className="relative">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <span className="inline-flex items-center border border-border/70 bg-surface-0/55 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-text-secondary [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]">
                    SlipStream
                  </span>
                </div>

                <div className="mt-10">
                  <p className="text-sm uppercase tracking-[0.22em] text-text-muted">
                    {heroVehicleTrackLabel}
                  </p>
                  <h2 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight text-text-primary lg:text-[3.5rem] lg:leading-[1.02]">
                    {isActive ? "Telemetry Online." : "Telemetry Ready."}
                  </h2>
                </div>

                <div className="density-home-card mt-8 grid gap-4 rounded-[24px] border border-border/70 bg-surface-2/78 p-5 md:grid-cols-[minmax(0,1.4fr)_140px_auto]">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                      Current Session
                    </p>
                    <p className="mt-2 truncate text-sm text-text-primary">
                      {liveSessionLabel}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                      Laps
                    </p>
                    <p className="mt-2 text-3xl font-semibold tracking-tight text-text-primary">
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
                      <div className="density-home-card grid gap-4 rounded-2xl border border-border/70 bg-surface-2/78 p-4 md:grid-cols-[auto_auto_1fr]">
                        <div>
                          <label className="mb-1 block text-xs text-text-muted">
                            IP Address
                          </label>
                          <input
                            type="text"
                            value={capture.ip}
                            placeholder={DEFAULT_CAPTURE_IP}
                            disabled={!showAdvancedCapture || isActive}
                            onChange={(event) => capture.setIp(event.target.value)}
                            className="capture-settings-input w-36 border-x-0 border-b border-t-0 border-border bg-transparent px-0 py-2 text-sm text-text-secondary placeholder:text-text-muted/60 focus:border-border focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-text-muted">
                            Port
                          </label>
                          <input
                            type="text"
                            value={capture.port}
                            placeholder={DEFAULT_CAPTURE_PORT}
                            disabled={!showAdvancedCapture || isActive}
                            onChange={(event) => capture.setPort(event.target.value)}
                            className="capture-settings-input w-28 border-x-0 border-b border-t-0 border-border bg-transparent px-0 py-2 text-sm text-text-secondary placeholder:text-text-muted/60 focus:border-border focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
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

            <aside className="density-home-section side-panel-surface border-t border-border/60 px-6 py-6 lg:px-7 xl:border-l xl:border-t-0">
              <p className="text-[10px] uppercase tracking-[0.24em] text-text-muted">
                Vehicle Context
              </p>
              <h3 className="mt-4 text-2xl font-semibold tracking-tight text-text-primary">
                {carNameLabel}
              </h3>

              <div className="mt-5 space-y-3">
                <DetailRow label="Layout" value={activeLayout} />
                <DetailRow label="Location" value={activeLocation} />
              </div>
            </aside>
          </div>
        </div>

        <section className="density-home-section rounded-[28px] border border-border/70 bg-surface-1/85 p-5">
          <div className="flex items-end justify-between gap-3">
            <h3 className="text-xl font-semibold tracking-tight">
              Latest Sessions
            </h3>
            <Link
              to="/sessions"
              className="text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              All Sessions
            </Link>
          </div>

          {sessionsError && recentSessions.length > 0 && (
            <p className="mt-4 text-sm text-danger">{sessionsError}</p>
          )}

          {latestSessionsSection}
        </section>
      </section>

      <div className="density-home-grid grid gap-4 md:grid-cols-2 xl:grid-cols-4">
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

      <section className="density-home-section rounded-[28px] border border-border/70 bg-surface-1/85 p-5">
        <h3 className="text-xl font-semibold tracking-tight">
          Tracks
        </h3>

        {trackBreakdown.length === 0 ? (
          <div className="mt-5 rounded-3xl border border-dashed border-border/70 bg-surface-2/72 p-8 text-center text-sm text-text-secondary">
            No tracks
          </div>
        ) : (
          <div className="density-home-cluster mt-5">
            {trackBreakdown.map((track, index) => (
              <div key={track.name} className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="text-xs font-medium text-text-muted">
                      {(index + 1).toString().padStart(2, "0")}
                    </span>
                    <span className="truncate text-sm font-medium text-text-primary">
                      {track.name}
                    </span>
                  </div>
                  <span className="text-xs text-text-secondary">
                    {track.sessions} sessions • {track.laps} laps
                  </span>
                </div>
                <div className="h-2 rounded-full bg-surface-3/82">
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

      <section className="overflow-hidden rounded-[28px] border border-border/70 bg-surface-1/85">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1.3fr)_360px]">
          <div className="density-home-hero relative overflow-hidden px-5 py-6 lg:px-6">
            <div className="hero-overlay pointer-events-none absolute inset-0 opacity-80" />
            <div className="relative">
              {favoriteCar ? (
                <>
                  <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
                    Favourite Car
                  </p>
                  <h3 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary lg:text-[2.5rem]">
                    {getSessionCarLabel(favoriteCar.carOrdinal)}
                  </h3>
                  <p className="mt-2 text-sm uppercase tracking-[0.2em] text-text-muted">
                    {favoriteCar.topTrack}
                  </p>

                  <div className="density-home-grid mt-6 grid gap-3 sm:grid-cols-3">
                    <div className="density-home-card rounded-2xl border border-border/70 bg-surface-2/76 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Sessions
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
                        {favoriteCar.sessions}
                      </p>
                    </div>
                    <div className="density-home-card rounded-2xl border border-border/70 bg-surface-2/76 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Laps
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
                        {favoriteCar.laps}
                      </p>
                    </div>
                    <div className="density-home-card rounded-2xl border border-border/70 bg-surface-2/76 p-4">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
                        Processed
                      </p>
                      <p className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
                        {favoriteCar.processedSessions}
                      </p>
                    </div>
                  </div>
                </>
              ) : (
                <div className="mt-5 rounded-3xl border border-dashed border-border/70 bg-surface-2/72 p-8 text-center text-sm text-text-secondary">
                  No vehicle data
                </div>
              )}
            </div>
          </div>

          <aside className="density-home-section side-panel-surface border-t border-border/60 px-5 py-6 lg:border-l lg:border-t-0 lg:px-6">
            {favoriteCar ? (
              <div className="space-y-3">
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
              <div className="rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-5 text-sm text-text-secondary">
                No vehicle data
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
}
