import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SessionDetail } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { useCaptureController } from "../hooks/useCaptureController";

function formatTime(seconds: number | null): string {
  if (seconds === null) return "--";
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
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
  const paddingClass = compact ? "px-3 py-1.5" : "px-3.5 py-2";
  const deleteToneClass =
    "border-[#ff4d57]/28 bg-[#ff4d57]/10 text-[#ff4d57] hover:bg-[#ff4d57]/18";
  const confirmToneClass =
    "border-r border-[#ff4d57]/18 bg-[#ff4d57]/14 text-[#ff4d57] hover:bg-[#ff4d57]/22";

  return (
    <div
      className={`inline-grid overflow-hidden rounded-full border border-[#ff4d57]/24 bg-surface-1/82 transition-all duration-200 ease-out ${
        confirming ? `grid-cols-2 ${confirmWidthClass}` : `grid-cols-1 ${idleWidthClass}`
      }`}
    >
      {confirming ? (
        <>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={`motion-safe-color ${paddingClass} ${textClass} ${confirmToneClass} font-medium disabled:opacity-50 cursor-pointer`}
          >
            {busy ? busyLabel : "Confirm"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className={`motion-safe-color ${paddingClass} ${textClass} bg-surface-1/84 font-medium text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:opacity-50 cursor-pointer`}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className={`motion-safe-color ${paddingClass} ${textClass} ${deleteToneClass} font-medium cursor-pointer`}
        >
          {idleLabel}
        </button>
      )}
    </div>
  );
}

export function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const capture = useCaptureController();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [processing, setProcessing] = useState(false);
  const [deletingSession, setDeletingSession] = useState(false);
  const [confirmingSessionDelete, setConfirmingSessionDelete] = useState(false);
  const [deletingLapNumber, setDeletingLapNumber] = useState<number | null>(null);
  const [confirmingLapDelete, setConfirmingLapDelete] = useState<number | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!sessionId) return;
    setError(null);
    api
      .getSession(sessionId)
      .then(setSession)
      .catch((err) => setError(err.message));
  };

  useEffect(load, [sessionId]);

  const isLiveSession =
    Boolean(sessionId) &&
    (capture.status?.is_active ?? false) &&
    capture.status?.session_id === sessionId;

  const handleProcess = async () => {
    if (!sessionId) return;
    if (isLiveSession) {
      setError("Stop capture before processing this session");
      return;
    }
    setProcessing(true);
    try {
      await api.processSession(sessionId);
      load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to process session",
      );
    }
    setProcessing(false);
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
      const detail = await api.getSession(sessionId);
      setSession(detail);
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

  if (error)
    return (
      <p className="text-danger p-8">
        {error}
      </p>
    );
  if (!session)
    return <p className="text-text-muted p-8">Loading...</p>;

  return (
    <div className="max-w-5xl space-y-8">
      <div>
        <Link
          to="/sessions"
          className="text-sm text-text-muted transition-colors hover:text-text-secondary"
        >
          &larr; Sessions
        </Link>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight">
          {session.session_id}
        </h2>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: "Track", value: session.track_circuit || "Unknown" },
          { label: "Layout", value: session.track_layout || "--" },
          { label: "Location", value: session.track_location || "--" },
          { label: "Laps", value: String(session.total_laps) },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-3xl border border-border/70 bg-surface-1/85 p-4"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
              {item.label}
            </p>
            <p className="mt-2 text-sm font-medium">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge processed={session.has_processed} />
        {!session.has_processed && (
          <>
            <button
              onClick={handleProcess}
              disabled={processing || isLiveSession}
              className="rounded-full bg-accent/12 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/18 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
              title={isLiveSession ? "Stop capture before processing this session" : undefined}
            >
              {processing ? "Processing..." : "Process Session"}
            </button>
            {isLiveSession && (
              <p className="text-xs uppercase tracking-[0.14em] text-text-muted">
                Stop capture to process this session
              </p>
            )}
          </>
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

      <div className="overflow-hidden rounded-3xl border border-border/70 bg-surface-1/85">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-[0.16em] text-text-muted">
              <th className="text-left p-3 font-medium">Lap</th>
              <th className="text-left p-3 font-medium">Time</th>
              <th className="text-left p-3 font-medium">Valid</th>
              <th className="text-left p-3 font-medium">Data</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {session.laps.map((lap) => (
              <tr
                key={lap.lap_number}
                className="border-b border-border/60 transition-colors hover:bg-surface-2/78"
              >
                <td className="p-3 font-medium">Lap {lap.lap_number}</td>
                <td className="p-3 font-mono text-text-secondary">
                  {formatTime(lap.lap_time_s)}
                </td>
                <td className="p-3">
                  {lap.is_valid === null ? (
                    <span className="text-text-muted">--</span>
                  ) : lap.is_valid ? (
                    <span className="text-success text-xs font-medium">
                      Valid
                    </span>
                  ) : (
                    <span className="text-danger text-xs font-medium">
                      Invalid
                    </span>
                  )}
                </td>
                <td className="p-3 space-x-2">
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
                <td className="p-3 text-right">
                  <div className="flex items-center justify-end gap-3">
                    <Link
                      to={`/sessions/${session.session_id}/laps/${lap.lap_number}`}
                      className="text-accent text-xs hover:underline font-medium"
                    >
                      Review
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
  );
}
