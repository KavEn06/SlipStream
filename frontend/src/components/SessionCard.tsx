import { Link } from "react-router-dom";
import type { SessionSummary } from "../types";
import { StatusBadge } from "./StatusBadge";
import { formatSessionTimestamp } from "../utils/sessions";

interface Props {
  session: SessionSummary;
  isDeleting?: boolean;
  onDelete?: (sessionId: string) => void;
}

export function SessionCard({ session, isDeleting = false, onDelete }: Props) {
  return (
    <div className="group rounded-3xl border border-white/5 bg-white/[0.02] p-5 transition-all hover:border-accent/20 hover:bg-white/[0.03]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <Link
          to={`/sessions/${session.session_id}`}
          className="min-w-0 pr-3"
        >
          <h3 className="font-mono text-sm font-medium text-white transition-colors group-hover:text-accent">
            {formatSessionTimestamp(session.session_id)}
          </h3>
        </Link>
        <div className="flex items-center gap-2">
          <StatusBadge processed={session.has_processed} />
          {onDelete && (
            <button
              type="button"
              disabled={isDeleting}
              onClick={() => onDelete(session.session_id)}
              className="rounded-full px-2.5 py-1 text-[11px] font-medium text-danger/85 transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-50 cursor-pointer"
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </button>
          )}
        </div>
      </div>

      <Link to={`/sessions/${session.session_id}`} className="block">
        {session.track_circuit && (
          <p className="text-sm text-text-secondary">{session.track_circuit}</p>
        )}
        {session.track_layout &&
          session.track_layout !== session.track_circuit && (
          <p className="mt-1 text-xs text-text-muted">
            {session.track_layout}
          </p>
        )}

        <div className="mt-4 flex items-center gap-3 text-xs text-text-muted">
          <span>{session.total_laps} laps</span>
          {session.track_location && <span>{session.track_location}</span>}
        </div>
      </Link>
    </div>
  );
}
