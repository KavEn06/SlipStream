import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { SessionCard } from "../components/SessionCard";
import { CapturePanel } from "../components/CapturePanel";
import type { SessionSummary } from "../types";

type StatusFilter = "all" | "processed" | "raw";

function getSessionDateValue(session: SessionSummary): string {
  if (session.created_at_utc) {
    const parsedDate = new Date(session.created_at_utc);
    if (!Number.isNaN(parsedDate.getTime())) {
      return parsedDate.toISOString().slice(0, 10);
    }
  }

  const match = session.session_id.match(
    /^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/,
  );
  if (!match) {
    return "";
  }

  const [, year, month, day] = match;
  return `${year}-${month}-${day}`;
}

export function SessionsPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dateFilter, setDateFilter] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);

  const refresh = () => {
    api
      .getSessions()
      .then(setSessions)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleDeleteSession = async (sessionId: string) => {
    const confirmed = window.confirm(
      `Delete session "${sessionId}" and all associated files?`,
    );
    if (!confirmed) return;

    setDeletingSessionId(sessionId);
    try {
      await api.deleteSession(sessionId);
      setSessions((current) =>
        current.filter((session) => session.session_id !== sessionId),
      );
    } catch (error) {
      console.error(error);
      window.alert(
        error instanceof Error ? error.message : "Failed to delete session",
      );
    } finally {
      setDeletingSessionId(null);
    }
  };

  const filteredSessions = sessions.filter((session) => {
    const matchesStatus =
      statusFilter === "all"
        ? true
        : statusFilter === "processed"
          ? session.has_processed
          : !session.has_processed;
    const matchesDate =
      !dateFilter || getSessionDateValue(session) === dateFilter;
    return matchesStatus && matchesDate;
  });

  const dateOptions = useMemo(() => {
    return Array.from(
      new Set(
        sessions
          .map((session) => getSessionDateValue(session))
          .filter((value) => value.length > 0),
      ),
    ).sort((left, right) => right.localeCompare(left));
  }, [sessions]);

  return (
    <div className="max-w-6xl space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">Sessions</h2>
        <p className="mt-2 text-sm text-text-secondary">
          Browse and review captured telemetry sessions
        </p>
      </div>

      <CapturePanel onCaptureChange={refresh} />

      <div className="relative">
        <button
          type="button"
          onClick={() => setFilterOpen((current) => !current)}
          className="inline-flex items-center gap-2 rounded-full border border-white/6 bg-white/[0.02] px-4 py-2 text-sm text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
        >
          <span>Filter</span>
          <svg
            className={`h-4 w-4 transition-transform ${filterOpen ? "rotate-180" : ""}`}
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

        {filterOpen && (
          <div className="absolute left-0 top-full z-10 mt-3 min-w-[280px] rounded-3xl border border-white/6 bg-[#0b0b0c] p-4 shadow-2xl shadow-black/40">
            <div className="space-y-4">
              <div className="space-y-2">
                <label
                  htmlFor="status-filter"
                  className="block text-[11px] uppercase tracking-[0.16em] text-text-muted"
                >
                  Status
                </label>
                <div className="relative">
                  <select
                    id="status-filter"
                    value={statusFilter}
                    onChange={(event) =>
                      setStatusFilter(event.target.value as StatusFilter)
                    }
                    className="w-full appearance-none rounded-full border border-white/6 bg-black/30 px-4 py-2 pr-10 text-sm text-text-secondary focus:border-accent focus:outline-none"
                  >
                    <option value="all">All sessions</option>
                    <option value="processed">Processed</option>
                    <option value="raw">Raw only</option>
                  </select>
                  <svg
                    className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
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
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="date-filter"
                  className="block text-[11px] uppercase tracking-[0.16em] text-text-muted"
                >
                  Date
                </label>
                <div className="relative">
                  <select
                    id="date-filter"
                    value={dateFilter}
                    onChange={(event) => setDateFilter(event.target.value)}
                    className="w-full appearance-none rounded-full border border-white/6 bg-black/30 px-4 py-2 pr-10 text-sm text-text-secondary focus:border-accent focus:outline-none"
                  >
                    <option value="">All dates</option>
                    {dateOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                  <svg
                    className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
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
              </div>

              <div className="flex items-center justify-between pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setStatusFilter("all");
                    setDateFilter("");
                  }}
                  className="rounded-full px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-white cursor-pointer"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => setFilterOpen(false)}
                  className="rounded-full bg-accent/12 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/18 cursor-pointer"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {!loading && sessions.length > 0 && (
        <p className="text-sm text-text-muted">
          Showing {filteredSessions.length} of {sessions.length} sessions
        </p>
      )}

      {loading ? (
        <p className="text-text-muted">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <div className="rounded-3xl border border-white/5 bg-white/[0.02] p-12 text-center">
          <p className="text-text-secondary">No sessions found</p>
          <p className="mt-1 text-sm text-text-muted">
            Start a capture or place raw session data in data/raw/
          </p>
        </div>
      ) : filteredSessions.length === 0 ? (
        <div className="rounded-3xl border border-white/5 bg-white/[0.02] p-12 text-center">
          <p className="text-text-secondary">No sessions match this filter</p>
          <p className="mt-1 text-sm text-text-muted">
            Try a different status or clear the selected date
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredSessions.map((s) => (
            <SessionCard
              key={s.session_id}
              session={s}
              isDeleting={deletingSessionId === s.session_id}
              onDelete={handleDeleteSession}
            />
          ))}
        </div>
      )}
    </div>
  );
}
