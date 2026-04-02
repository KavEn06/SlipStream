import { Link } from "react-router-dom";
import type { SessionSummary } from "../types";
import {
  formatSessionDateLabel,
  formatSessionTimestamp,
  getSessionTrackName,
  getSessionTitle,
  getSessionVehicleTrackLabel,
} from "../utils/sessions";
import { StatusBadge } from "./StatusBadge";

interface Props {
  session: SessionSummary;
  isLive?: boolean;
  isProcessing?: boolean;
  processDisabledReason?: string | null;
  onProcess?: (sessionId: string) => void;
}

export function SessionLibraryRow({
  session,
  isLive = false,
  isProcessing = false,
  processDisabledReason = null,
  onProcess,
}: Props) {
  const sessionPath = `/sessions/${session.session_id}`;
  const processDisabled = isProcessing || Boolean(processDisabledReason);
  const showLayout =
    session.track_layout &&
    session.track_layout.trim().length > 0 &&
    session.track_layout !== getSessionTrackName(session);
  const sessionTitle = getSessionTitle(session);
  const showTimestampSubtitle =
    Boolean(session.display_name && session.display_name.trim().length > 0);

  return (
    <div
      className={`density-library-row group flex flex-col gap-4 border-b border-border/60 px-4 py-4 transition-colors last:border-b-0 sm:px-5 lg:flex-row lg:items-center lg:gap-6 ${
        isLive
          ? "bg-accent/[0.08] ring-1 ring-inset ring-accent/16"
          : "bg-surface-2/75 hover:bg-surface-3/85"
      }`}
    >
      <Link to={sessionPath} className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {isLive && (
            <span className="inline-flex items-center gap-2 border border-accent/20 bg-accent/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-accent">
              <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
              Live
            </span>
          )}
          <p className="truncate text-sm font-medium text-text-primary transition-colors group-hover:text-accent">
            {sessionTitle}
          </p>
        </div>

        {showTimestampSubtitle && (
          <p className="mt-1 font-mono text-xs text-text-muted">
            {formatSessionTimestamp(session.session_id)}
          </p>
        )}

        <p className="mt-1 truncate text-sm text-text-secondary">
          {getSessionVehicleTrackLabel(session)}
        </p>

        {(showLayout || session.track_location) && (
          <div className="density-library-row-meta mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
            {showLayout && <span>{session.track_layout}</span>}
            {session.track_location && <span>{session.track_location}</span>}
          </div>
        )}
      </Link>

      <div className="flex flex-wrap items-center gap-3 lg:ml-auto lg:flex-nowrap">
        <div className="min-w-[110px] lg:text-right">
          <p className="text-sm font-medium text-text-primary">{session.total_laps} laps</p>
          <p className="text-xs text-text-muted">{formatSessionDateLabel(session)}</p>
        </div>

        <StatusBadge processed={session.has_processed} />

        {!session.has_processed && onProcess && (
          <div className="flex flex-col items-start gap-1 lg:items-end">
            <button
              type="button"
              onClick={() => onProcess(session.session_id)}
              disabled={processDisabled}
              title={processDisabledReason ?? undefined}
              className="density-library-inline-action inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-3 py-2 text-[11px] font-medium uppercase tracking-[0.16em] text-accent transition-colors hover:bg-accent/16 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
            >
              {isProcessing ? "Working" : "Process"}
            </button>
            {processDisabledReason && (
              <p className="text-[10px] uppercase tracking-[0.14em] text-text-muted">
                {processDisabledReason}
              </p>
            )}
          </div>
        )}

        <Link
          to={sessionPath}
          className="density-library-icon-action inline-flex h-10 w-10 items-center justify-center rounded-full border border-border/70 bg-surface-1/82 text-text-secondary transition-colors hover:border-accent/20 hover:bg-accent/10 hover:text-text-primary"
          aria-label={`Open ${sessionTitle}`}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.8}
              d="M9 5l7 7-7 7"
            />
          </svg>
        </Link>
      </div>
    </div>
  );
}
