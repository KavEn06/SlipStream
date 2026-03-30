import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { SessionLibraryRow } from "../components/SessionLibraryRow";
import { useCaptureController } from "../hooks/useCaptureController";
import type { SessionSummary } from "../types";
import {
  type SessionLibrarySort,
  getSessionDateValue,
  matchesSessionQuery,
  sortSessionsForLibrary,
} from "../utils/sessions";

type StatusFilter = "all" | "processed" | "raw";

function LibraryStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="density-library-stat min-w-[104px] rounded-2xl border border-border/70 bg-surface-2/78 px-4 py-3">
      <p className="text-[10px] uppercase tracking-[0.2em] text-text-muted">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
        {value}
      </p>
    </div>
  );
}

export function SessionsPage() {
  const capture = useCaptureController();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [processingSessionId, setProcessingSessionId] = useState<string | null>(
    null,
  );
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dateFilter, setDateFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<SessionLibrarySort>("newest");
  const [showCaptureSettings, setShowCaptureSettings] = useState(false);

  const loadSessions = async (showLoading = false) => {
    if (showLoading) {
      setLoading(true);
    }

    try {
      const result = await api.getSessions();
      setSessions(result);
      setSessionsError(null);
    } catch (error) {
      setSessionsError(
        error instanceof Error ? error.message : "Failed to load sessions",
      );
    } finally {
      if (showLoading) {
        setLoading(false);
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

  const processedCount = useMemo(
    () => sessions.filter((session) => session.has_processed).length,
    [sessions],
  );
  const rawCount = sessions.length - processedCount;

  const dateOptions = useMemo(() => {
    return Array.from(
      new Set(
        sessions
          .map((session) => getSessionDateValue(session))
          .filter((value) => value.length > 0),
      ),
    ).sort((left, right) => right.localeCompare(left));
  }, [sessions]);

  const activeSessionId =
    capture.status?.is_active && capture.status.session_id
      ? capture.status.session_id
      : null;
  const captureSettingsId = "sessions-capture-settings";

  const filteredSessions = useMemo(() => {
    const matchingSessions = sessions.filter((session) => {
      const matchesStatus =
        statusFilter === "all"
          ? true
          : statusFilter === "processed"
            ? session.has_processed
            : !session.has_processed;
      const matchesDate =
        !dateFilter || getSessionDateValue(session) === dateFilter;
      const matchesQuery = matchesSessionQuery(session, searchQuery);

      return matchesStatus && matchesDate && matchesQuery;
    });

    return sortSessionsForLibrary(matchingSessions, sortBy, activeSessionId);
  }, [activeSessionId, dateFilter, searchQuery, sessions, sortBy, statusFilter]);

  const hasActiveControls =
    searchQuery.trim().length > 0 ||
    statusFilter !== "all" ||
    dateFilter.length > 0 ||
    sortBy !== "newest";

  const liveSessionPinned = filteredSessions.some(
    (session) => session.session_id === activeSessionId,
  );

  const handleCaptureAction = async () => {
    setActionError(null);

    const result = capture.status?.is_active
      ? await capture.stopCapture()
      : await capture.startCapture();

    if (!result) return;
    await loadSessions(false);
  };

  const handleProcessSession = async (sessionId: string) => {
    if (sessionId === activeSessionId) {
      setActionError("Stop capture before processing this session");
      return;
    }

    setProcessingSessionId(sessionId);
    setActionError(null);

    try {
      await api.processSession(sessionId);
      await loadSessions(false);
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : "Failed to process session",
      );
    } finally {
      setProcessingSessionId(null);
    }
  };

  const clearControls = () => {
    setSearchQuery("");
    setStatusFilter("all");
    setDateFilter("");
    setSortBy("newest");
  };

  const isCaptureActive = capture.status?.is_active ?? false;
  const liveSessionLabel = isCaptureActive ? capture.status?.session_id ?? "Idle" : "Idle";
  const liveLapCount = isCaptureActive ? capture.status?.laps_detected ?? 0 : 0;

  return (
    <div className="max-w-7xl space-y-5">
      <section className="overflow-hidden rounded-[30px] border border-border/70 bg-surface-1/85">
        <div className="density-library-hero relative px-6 py-6 lg:px-8 lg:py-7">
          <div className="hero-overlay pointer-events-none absolute inset-0" />
          <div className="hero-band pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg]" />

          <div className="relative flex flex-wrap items-start justify-between gap-6">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center border border-border/70 bg-surface-0/55 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-text-secondary [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)]">
                  SlipStream // Session Library
                </span>
                <div className="flex items-center gap-2">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      isCaptureActive ? "bg-success animate-pulse" : "bg-text-muted"
                    }`}
                  />
                  <span className="text-[10px] uppercase tracking-[0.22em] text-text-muted">
                    {isCaptureActive ? "Capture Live" : "Capture Standby"}
                  </span>
                </div>
              </div>

              <h2 className="mt-6 text-4xl font-semibold tracking-tight text-text-primary lg:text-[3.25rem] lg:leading-[1.02]">
                Telemetry Sessions.
              </h2>
            </div>

            <div className="flex flex-wrap gap-3 lg:justify-end">
              <LibraryStat label="Total" value={String(sessions.length)} />
              <LibraryStat label="Processed" value={String(processedCount)} />
              <LibraryStat label="Raw" value={String(rawCount)} />
            </div>
          </div>
        </div>
      </section>

      <section className="density-library-panel rounded-[28px] border border-border/70 bg-surface-1/85 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-3">
              <div
                className={`h-2.5 w-2.5 rounded-full ${
                  isCaptureActive ? "bg-success animate-pulse" : "bg-text-muted"
                }`}
              />
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
                  Capture
                </p>
                <p className="text-sm font-medium text-text-primary">
                  {isCaptureActive ? "Live" : "Standby"}
                </p>
              </div>
            </div>

            <div className="border-l border-border/70 pl-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
                Session
              </p>
              <p className="max-w-[240px] truncate font-mono text-sm text-text-primary">
                {liveSessionLabel}
              </p>
            </div>

            <div className="border-l border-border/70 pl-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
                Laps
              </p>
              <p className="text-sm font-medium text-text-primary">
                {liveLapCount}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setShowCaptureSettings((current) => !current)}
              aria-expanded={showCaptureSettings}
              aria-controls={captureSettingsId}
              className="density-library-control inline-flex items-center gap-2 border border-border/70 bg-surface-2/84 px-3 py-2 text-[11px] font-medium uppercase tracking-[0.16em] text-text-secondary transition-colors hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
            >
              <span>Capture Settings</span>
              <svg
                className={`h-4 w-4 transition-transform ${showCaptureSettings ? "rotate-180" : ""}`}
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

            <button
              type="button"
              onClick={handleCaptureAction}
              disabled={capture.busy}
              className={`density-library-control inline-flex items-center border px-4 py-2 text-[11px] font-medium uppercase tracking-[0.18em] transition-colors cursor-pointer disabled:opacity-50 [clip-path:polygon(0_0,100%_0,92%_100%,0_100%)] ${
                isCaptureActive
                  ? "border-danger/30 bg-danger/10 text-danger hover:bg-danger/18"
                  : "border-accent/30 bg-accent/12 text-accent hover:bg-accent/18"
              }`}
            >
              {capture.busy ? "Working" : isCaptureActive ? "Stop Capture" : "Start Capture"}
            </button>
          </div>
        </div>

        <div
          id={captureSettingsId}
          aria-hidden={!showCaptureSettings}
          className={`grid transition-all duration-300 ease-out ${
            showCaptureSettings
              ? "mt-4 grid-rows-[1fr] opacity-100"
              : "mt-0 grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="overflow-hidden">
            <div className="grid gap-4 border-t border-border/70 pt-4 md:grid-cols-[auto_auto_1fr]">
              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  IP Address
                </label>
                <input
                  type="text"
                  value={capture.ip}
                  disabled={!showCaptureSettings || isCaptureActive}
                  onChange={(event) => capture.setIp(event.target.value)}
                  className="w-full border-x-0 border-b border-t-0 border-border bg-transparent px-0 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 md:w-40"
                />
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">Port</label>
                <input
                  type="text"
                  value={capture.port}
                  disabled={!showCaptureSettings || isCaptureActive}
                  onChange={(event) => capture.setPort(event.target.value)}
                  className="w-full border-x-0 border-b border-t-0 border-border bg-transparent px-0 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 md:w-28"
                />
              </div>

              <div className="self-end">
                <p className="text-[10px] uppercase tracking-[0.16em] text-text-muted">
                  Endpoint
                </p>
                <p className="mt-2 text-sm text-text-secondary">
                  {capture.status?.ip ?? capture.ip}:{capture.status?.port ?? capture.port}
                </p>
              </div>
            </div>
          </div>
        </div>

        {(capture.error || actionError) && (
          <p className="mt-4 text-sm text-danger">{capture.error ?? actionError}</p>
        )}
      </section>

      <section className="density-library-panel rounded-[28px] border border-border/70 bg-surface-1/85 p-4 sm:p-5">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.6fr)_170px_170px_170px]">
          <label className="block">
            <span className="sr-only">Search sessions</span>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search session, track, layout, location"
              className="density-library-control w-full rounded-2xl border border-border/70 bg-surface-2/78 px-4 py-3 text-sm text-text-secondary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          </label>

          <label className="block">
            <span className="sr-only">Filter by status</span>
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                className="density-library-control w-full appearance-none rounded-2xl border border-border/70 bg-surface-2/78 px-4 py-3 pr-12 text-sm text-text-secondary focus:border-accent focus:outline-none"
              >
                <option value="all">All Statuses</option>
                <option value="processed">Processed</option>
                <option value="raw">Raw</option>
              </select>
              <svg
                className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
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
            </div>
          </label>

          <label className="block">
            <span className="sr-only">Filter by date</span>
            <div className="relative">
              <select
                value={dateFilter}
                onChange={(event) => setDateFilter(event.target.value)}
                className="density-library-control w-full appearance-none rounded-2xl border border-border/70 bg-surface-2/78 px-4 py-3 pr-12 text-sm text-text-secondary focus:border-accent focus:outline-none"
              >
                <option value="">All Dates</option>
                {dateOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <svg
                className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
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
            </div>
          </label>

          <label className="block">
            <span className="sr-only">Sort sessions</span>
            <div className="relative">
              <select
                value={sortBy}
                onChange={(event) =>
                  setSortBy(event.target.value as SessionLibrarySort)
                }
                className="density-library-control w-full appearance-none rounded-2xl border border-border/70 bg-surface-2/78 px-4 py-3 pr-12 text-sm text-text-secondary focus:border-accent focus:outline-none"
              >
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="laps">Most Laps</option>
                <option value="track">Track A-Z</option>
              </select>
              <svg
                className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
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
            </div>
          </label>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-text-muted">
            <span>{filteredSessions.length} shown</span>
            <span className="text-text-muted/55">/</span>
            <span>{sessions.length} total</span>
            {liveSessionPinned && (
              <>
                <span className="text-text-muted/55">/</span>
                <span className="text-accent">Live Pinned</span>
              </>
            )}
          </div>

          {hasActiveControls && (
            <button
              type="button"
              onClick={clearControls}
              className="density-library-control inline-flex items-center rounded-full border border-border/70 bg-surface-2/84 px-3 py-2 text-xs font-medium uppercase tracking-[0.16em] text-text-secondary transition-colors hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
            >
              Clear
            </button>
          )}
        </div>
      </section>

      {sessionsError && (
        <div className="rounded-[24px] border border-danger/20 bg-danger/8 px-4 py-3 text-sm text-danger">
          {sessionsError}
        </div>
      )}

      {loading ? (
        <div className="density-library-panel rounded-[28px] border border-border/70 bg-surface-1/85 px-5 py-8 text-sm text-text-muted">
          Loading sessions...
        </div>
      ) : sessions.length === 0 ? (
        <div className="density-library-panel rounded-[28px] border border-dashed border-border/70 bg-surface-1/85 px-5 py-10 text-center">
          <p className="text-sm font-medium text-text-secondary">
            No sessions in library.
          </p>
          <p className="mt-2 text-sm text-text-muted">Start capture to populate.</p>
        </div>
      ) : filteredSessions.length === 0 ? (
        <div className="density-library-panel rounded-[28px] border border-dashed border-border/70 bg-surface-1/85 px-5 py-10 text-center">
          <p className="text-sm font-medium text-text-secondary">No matches.</p>
          <button
            type="button"
            onClick={clearControls}
            className="density-library-control mt-3 inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-3 py-2 text-xs font-medium uppercase tracking-[0.16em] text-accent transition-colors hover:bg-accent/16 hover:text-text-primary cursor-pointer"
          >
            Clear Filters
          </button>
        </div>
      ) : (
        <section className="overflow-hidden rounded-[28px] border border-border/70 bg-surface-1/85">
          {filteredSessions.map((session) => (
            <SessionLibraryRow
              key={session.session_id}
              session={session}
              isLive={session.session_id === activeSessionId}
              isProcessing={processingSessionId === session.session_id}
              processDisabledReason={
                session.session_id === activeSessionId
                  ? "Stop capture to process"
                  : null
              }
              onProcess={handleProcessSession}
            />
          ))}
        </section>
      )}
    </div>
  );
}
