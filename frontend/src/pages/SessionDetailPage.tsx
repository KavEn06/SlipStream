import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { SurfaceMessage, SurfaceSkeleton } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { useCaptureController } from "../hooks/useCaptureController";
import type { LapSummary, SessionDetail } from "../types";
import {
  applySessionDisplayNameOverride,
  getSessionTitle,
  saveSessionDisplayNameOverride,
} from "../utils/sessions";

type LapFilter = "all" | "processed" | "raw" | "valid" | "invalid";

function formatTime(seconds: number | null): string {
  if (seconds === null) return "--";
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
}

function matchesLapFilter(lap: LapSummary, filter: LapFilter): boolean {
  switch (filter) {
    case "processed":
      return lap.has_processed;
    case "raw":
      return lap.has_raw;
    case "valid":
      return lap.is_valid === true;
    case "invalid":
      return lap.is_valid === false;
    case "all":
    default:
      return true;
  }
}

function SplitDeleteButton({
  confirming,
  busy,
  idleLabel,
  busyLabel,
  onStart,
  onConfirm,
  onCancel,
  compact = false,
}: {
  confirming: boolean;
  busy: boolean;
  idleLabel: string;
  busyLabel: string;
  onStart: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  compact?: boolean;
}) {
  const idleWidthClass = compact ? "w-[4.75rem]" : "w-[8.5rem]";
  const confirmWidthClass = compact ? "w-[8.75rem]" : "w-[13.75rem]";
  const textClass = compact ? "text-xs" : "text-sm";
  const heightClass = compact ? "h-8" : "h-10";
  const paddingClass = compact ? "px-3" : "px-4";
  const deleteToneClass =
    "border-red-500/28 bg-red-500/10 text-red-500 hover:bg-red-500/18";
  const confirmToneClass =
    "border-r border-red-500/18 bg-red-500/14 text-red-500 hover:bg-red-500/22";

  return (
    <div
      className={`inline-grid overflow-hidden rounded-full border border-red-500/24 bg-surface-1/82 transition-all duration-200 ease-out ${
        confirming ? `grid-cols-2 ${confirmWidthClass}` : `grid-cols-1 ${idleWidthClass}`
      }`}
    >
      {confirming ? (
        <>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={`motion-safe-color inline-flex ${heightClass} items-center justify-center ${paddingClass} ${textClass} ${confirmToneClass} font-medium disabled:opacity-50 cursor-pointer`}
          >
            {busy ? busyLabel : "Confirm"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className={`motion-safe-color inline-flex ${heightClass} items-center justify-center ${paddingClass} ${textClass} bg-surface-1/84 font-medium text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:opacity-50 cursor-pointer`}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className={`motion-safe-color inline-flex ${heightClass} items-center justify-center ${paddingClass} ${textClass} ${deleteToneClass} font-medium cursor-pointer`}
        >
          {idleLabel}
        </button>
      )}
    </div>
  );
}

function SessionMetaCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="density-detail-card rounded-2xl border border-border/70 bg-surface-2/78">
      <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
        {label}
      </p>
      <p className="mt-2 text-sm font-medium text-text-primary">{value}</p>
    </div>
  );
}

export function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const capture = useCaptureController();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [savingDisplayName, setSavingDisplayName] = useState(false);
  const [deletingSession, setDeletingSession] = useState(false);
  const [confirmingSessionDelete, setConfirmingSessionDelete] = useState(false);
  const [deletingLapNumber, setDeletingLapNumber] = useState<number | null>(null);
  const [confirmingLapDelete, setConfirmingLapDelete] = useState<number | null>(
    null,
  );
  const [lapFilter, setLapFilter] = useState<LapFilter>("all");
  const [editingDisplayName, setEditingDisplayName] = useState(false);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!sessionId) return;

    setLoading(true);
    setError(null);

    try {
      const detail = await api.getSession(sessionId);
      const resolvedDetail = applySessionDisplayNameOverride(detail);
      setSession(resolvedDetail);
      setDisplayNameDraft(resolvedDetail.display_name ?? "");
      setEditingDisplayName(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [sessionId]);

  const isLiveSession =
    Boolean(sessionId) &&
    (capture.status?.is_active ?? false) &&
    capture.status?.session_id === sessionId;

  const filteredLaps = useMemo(
    () => session?.laps.filter((lap) => matchesLapFilter(lap, lapFilter)) ?? [],
    [lapFilter, session],
  );
  const sessionTitle = session ? getSessionTitle(session) : "";

  const openLapReview = (lapNumber: number) => {
    if (!sessionId) {
      return;
    }

    navigate(`/sessions/${sessionId}/laps/${lapNumber}`);
  };

  const handleProcess = async () => {
    if (!sessionId) return;
    if (isLiveSession) {
      setError("Stop capture before processing this session");
      return;
    }

    setProcessing(true);
    try {
      await api.processSession(sessionId);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to process session",
      );
    } finally {
      setProcessing(false);
    }
  };

  const handleSaveDisplayName = async () => {
    if (!sessionId) {
      return;
    }

    const nextDisplayName = displayNameDraft.trim() || null;

    setSavingDisplayName(true);
    setError(null);
    saveSessionDisplayNameOverride(sessionId, nextDisplayName);
    setSession((current) =>
      current
        ? {
            ...current,
            display_name: nextDisplayName,
          }
        : current,
    );
    setDisplayNameDraft(nextDisplayName ?? "");
    setEditingDisplayName(false);

    try {
      const updatedSession = await api.updateSession(sessionId, {
        display_name: nextDisplayName,
      });
      const resolvedSession = applySessionDisplayNameOverride(updatedSession);
      setSession(resolvedSession);
      setDisplayNameDraft(resolvedSession.display_name ?? "");
    } catch (err) {
      setError(
        err instanceof Error
          ? `Saved locally. Backend sync failed: ${err.message}`
          : "Saved locally. Backend sync failed.",
      );
    } finally {
      setSavingDisplayName(false);
    }
  };

  const handleCancelDisplayName = () => {
    setDisplayNameDraft(session?.display_name ?? "");
    setEditingDisplayName(false);
  };

  const handleDeleteSession = async () => {
    if (!sessionId) return;

    setDeletingSession(true);
    try {
      await api.deleteSession(sessionId);
      navigate("/sessions");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete session");
      setDeletingSession(false);
    }
  };

  const handleDeleteLap = async (lapNumber: number) => {
    if (!sessionId) return;

    setDeletingLapNumber(lapNumber);
    try {
      await api.deleteLap(sessionId, lapNumber);
      await load();
      setConfirmingLapDelete(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Session not found") {
        navigate("/sessions");
      } else {
        setError(err instanceof Error ? err.message : "Failed to delete lap");
      }
    } finally {
      setDeletingLapNumber(null);
    }
  };

  if (loading && !session) {
    return (
      <div className="max-w-5xl space-y-5">
        <SurfaceSkeleton rows={4} />
        <SurfaceSkeleton rows={6} />
      </div>
    );
  }

  if (error && !session) {
    return (
      <SurfaceMessage
        title="Could not load session"
        message={error}
        actionLabel="Retry"
        onAction={() => void load()}
        tone="danger"
        className="max-w-5xl"
      />
    );
  }

  if (!session) {
    return null;
  }

  return (
    <div className="density-detail-stack max-w-5xl">
      <section className="sticky top-4 z-20 overflow-hidden rounded-[28px] border border-border/70 bg-surface-1/92 backdrop-blur-xl relative">
        <div className="hero-overlay pointer-events-none absolute inset-0" />
        <div className="hero-band pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg]" />
        <div className="density-detail-panel relative">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                {editingDisplayName ? (
                  <div className="flex min-w-0 max-w-xl flex-1 flex-col gap-3">
                    <input
                      type="text"
                      value={displayNameDraft}
                      onChange={(event) => setDisplayNameDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void handleSaveDisplayName();
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          handleCancelDisplayName();
                        }
                      }}
                      placeholder="Session name"
                      maxLength={80}
                      className="h-11 w-full rounded-2xl border border-border/70 bg-surface-1/88 px-4 text-base font-medium text-text-primary outline-none transition-colors focus:border-border-strong"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={handleSaveDisplayName}
                        disabled={savingDisplayName}
                        className="motion-safe-color inline-flex h-9 items-center rounded-full border border-accent/24 bg-accent/12 px-4 text-sm font-medium text-accent hover:bg-accent/18 disabled:opacity-50 cursor-pointer"
                      >
                        {savingDisplayName ? "Saving..." : "Save Name"}
                      </button>
                      <button
                        type="button"
                        onClick={handleCancelDisplayName}
                        disabled={savingDisplayName}
                        className="motion-safe-color inline-flex h-9 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-sm font-medium text-text-secondary hover:bg-surface-3 hover:text-text-primary disabled:opacity-50 cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <h2 className="min-w-0 truncate text-3xl font-semibold tracking-tight text-text-primary">
                      {sessionTitle}
                    </h2>
                    <button
                      type="button"
                      onClick={() => {
                        setDisplayNameDraft(session.display_name ?? "");
                        setEditingDisplayName(true);
                      }}
                      className="motion-safe-color inline-flex h-9 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-xs font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
                    >
                      Rename
                    </button>
                  </>
                )}
                <StatusBadge processed={session.has_processed} />
                {isLiveSession && (
                  <span className="inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-accent">
                    <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
                    Capture Live
                  </span>
                )}
              </div>
              {!editingDisplayName && session.display_name && (
                <p className="mt-2 truncate font-mono text-xs text-text-muted">
                  {session.session_id}
                </p>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Link
                to={`/compare/laps?${new URLSearchParams({ sessionId: session.session_id }).toString()}`}
                className="inline-flex h-10 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-sm font-medium text-text-secondary transition-colors hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
              >
                Compare Laps
              </Link>
              {!session.has_processed && (
                <button
                  type="button"
                  onClick={handleProcess}
                  disabled={processing || isLiveSession}
                  className="inline-flex h-10 items-center rounded-full bg-accent/12 px-4 text-sm font-medium text-accent transition-colors hover:bg-accent/18 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                  title={
                    isLiveSession
                      ? "Stop capture before processing this session"
                      : undefined
                  }
                >
                  {processing ? "Processing..." : "Process Session"}
                </button>
              )}
              <SplitDeleteButton
                confirming={confirmingSessionDelete}
                busy={deletingSession}
                idleLabel="Delete Session"
                busyLabel="Deleting..."
                onStart={() => setConfirmingSessionDelete(true)}
                onConfirm={handleDeleteSession}
                onCancel={() => setConfirmingSessionDelete(false)}
              />
            </div>
          </div>

          {isLiveSession && (
            <p className="mt-4 text-xs uppercase tracking-[0.14em] text-text-muted">
              Stop capture to process this session
            </p>
          )}

          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
            <SessionMetaCard
              label="Track"
              value={session.track_circuit || "Unknown"}
            />
            <SessionMetaCard
              label="Layout"
              value={session.track_layout || "--"}
            />
            <SessionMetaCard
              label="Location"
              value={session.track_location || "--"}
            />
            <SessionMetaCard
              label="Laps"
              value={String(session.total_laps)}
            />
          </div>
        </div>
      </section>

      {error && (
        <SurfaceMessage
          title="Session action failed"
          message={error}
          actionLabel="Retry"
          onAction={() => void load()}
          tone="danger"
          className="text-left"
        />
      )}

      <section className="density-detail-panel rounded-[28px] border border-border/70 bg-surface-1/85">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ["all", "All"],
                ["processed", "Processed"],
                ["raw", "Raw"],
                ["valid", "Valid"],
                ["invalid", "Invalid"],
              ] as const
            ).map(([value, label]) => {
              const active = lapFilter === value;

              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => setLapFilter(value)}
                  className={`motion-safe-color inline-flex h-9 items-center rounded-full border px-4 text-xs font-medium uppercase tracking-[0.14em] cursor-pointer ${
                    active
                      ? "border-accent/24 bg-accent/12 text-accent"
                      : "border-border/70 bg-surface-2/84 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
            {filteredLaps.length} shown / {session.laps.length} total
          </p>
        </div>
      </section>

      {filteredLaps.length === 0 ? (
        <SurfaceMessage
          title="No laps match the current filter"
          message="Choose a different lap filter to view more session data."
        />
      ) : (
        <div className="overflow-hidden rounded-3xl border border-border/70 bg-surface-1/85">
          <div className="density-detail-table-shell overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-[11px] uppercase tracking-[0.16em] text-text-muted">
                  <th className="density-detail-table-cell text-left font-medium">Lap</th>
                  <th className="density-detail-table-cell text-left font-medium">Time</th>
                  <th className="density-detail-table-cell text-left font-medium">Valid</th>
                  <th className="density-detail-table-cell text-left font-medium">Data</th>
                  <th className="density-detail-table-cell" />
                </tr>
              </thead>
              <tbody>
                {filteredLaps.map((lap) => (
                  <tr
                    key={lap.lap_number}
                    tabIndex={0}
                    role="link"
                    aria-label={`Open Lap ${lap.lap_number} review`}
                    onClick={() => openLapReview(lap.lap_number)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openLapReview(lap.lap_number);
                      }
                    }}
                    className="cursor-pointer border-b border-border/60 transition-colors hover:bg-surface-2/78 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-[-2px]"
                  >
                    <td className="density-detail-table-cell font-medium text-text-primary">
                      Lap {lap.lap_number}
                    </td>
                    <td className="density-detail-table-cell font-mono text-text-secondary">
                      {formatTime(lap.lap_time_s)}
                    </td>
                    <td className="density-detail-table-cell">
                      {lap.is_valid === null ? (
                        <span className="text-text-muted">--</span>
                      ) : lap.is_valid ? (
                        <span className="text-xs font-medium text-success">
                          Valid
                        </span>
                      ) : (
                        <span className="text-xs font-medium text-danger">
                          Invalid
                        </span>
                      )}
                    </td>
                    <td className="density-detail-table-cell space-x-2">
                      {lap.has_raw && (
                        <span className="rounded-full border border-border/70 bg-surface-2/86 px-2.5 py-1 text-[11px] text-text-secondary">
                          Raw
                        </span>
                      )}
                      {lap.has_processed && (
                        <span className="rounded-full bg-accent/10 px-2.5 py-1 text-[11px] text-accent">
                          Processed
                        </span>
                      )}
                    </td>
                    <td
                      className="density-detail-table-cell text-right"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-3">
                        <Link
                          to={`/sessions/${session.session_id}/laps/${lap.lap_number}`}
                          className="text-xs font-medium text-accent hover:underline"
                        >
                          Review
                        </Link>
                        <Link
                          to={`/compare/laps?${new URLSearchParams({
                            sessionId: session.session_id,
                            lapNumber: String(lap.lap_number),
                          }).toString()}`}
                          className="text-xs font-medium text-text-secondary hover:text-text-primary hover:underline"
                        >
                          Compare
                        </Link>
                        <SplitDeleteButton
                          confirming={confirmingLapDelete === lap.lap_number}
                          busy={deletingLapNumber === lap.lap_number}
                          idleLabel="Delete"
                          busyLabel="..."
                          onStart={() => setConfirmingLapDelete(lap.lap_number)}
                          onConfirm={() => handleDeleteLap(lap.lap_number)}
                          onCancel={() => setConfirmingLapDelete(null)}
                          compact
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
