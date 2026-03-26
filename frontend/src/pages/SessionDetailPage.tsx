import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SessionDetail } from "../types";
import { StatusBadge } from "../components/StatusBadge";

function formatTime(seconds: number | null): string {
  if (seconds === null) return "--";
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
}

export function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [processing, setProcessing] = useState(false);
  const [deletingSession, setDeletingSession] = useState(false);
  const [deletingLapNumber, setDeletingLapNumber] = useState<number | null>(null);
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

  const handleProcess = async () => {
    if (!sessionId) return;
    setProcessing(true);
    try {
      await api.processSession(sessionId);
      load();
    } catch (err: any) {
      setError(err.message);
    }
    setProcessing(false);
  };

  const handleDeleteSession = async () => {
    if (!sessionId) return;
    const confirmed = window.confirm(
      `Delete session "${sessionId}" and all associated files?`,
    );
    if (!confirmed) return;

    setDeletingSession(true);
    try {
      await api.deleteSession(sessionId);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete session");
      setDeletingSession(false);
    }
  };

  const handleDeleteLap = async (lapNumber: number) => {
    if (!sessionId) return;
    const confirmed = window.confirm(
      `Delete lap ${lapNumber} from session "${sessionId}"?`,
    );
    if (!confirmed) return;

    setDeletingLapNumber(lapNumber);
    try {
      await api.deleteLap(sessionId, lapNumber);
      const detail = await api.getSession(sessionId);
      setSession(detail);
    } catch (err) {
      if (err instanceof Error && err.message === "Session not found") {
        navigate("/");
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
          to="/"
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
            className="rounded-3xl border border-white/5 bg-white/[0.02] p-4"
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
          <button
            onClick={handleProcess}
            disabled={processing}
            className="rounded-full bg-accent/12 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/18 disabled:opacity-50 cursor-pointer"
          >
            {processing ? "Processing..." : "Process Session"}
          </button>
        )}
        <button
          onClick={handleDeleteSession}
          disabled={deletingSession}
          className="rounded-full bg-danger/10 px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger/16 disabled:opacity-50 cursor-pointer"
        >
          {deletingSession ? "Deleting..." : "Delete Session"}
        </button>
      </div>

      <div className="overflow-hidden rounded-3xl border border-white/5 bg-white/[0.02]">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/5 text-[11px] uppercase tracking-[0.16em] text-text-muted">
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
                className="border-b border-white/4 transition-colors hover:bg-white/[0.03]"
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
                    <span className="rounded-full bg-white/5 px-2.5 py-1 text-[11px]">
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
                    <button
                      type="button"
                      onClick={() => handleDeleteLap(lap.lap_number)}
                      disabled={deletingLapNumber === lap.lap_number}
                      className="text-danger text-xs font-medium hover:underline disabled:no-underline disabled:opacity-50 cursor-pointer"
                    >
                      {deletingLapNumber === lap.lap_number
                        ? "Deleting..."
                        : "Delete"}
                    </button>
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
