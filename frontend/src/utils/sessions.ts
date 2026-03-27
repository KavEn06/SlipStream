import type { SessionSummary } from "../types";

const SESSION_ID_PATTERN =
  /^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/;

export interface DashboardKpis {
  totalSessions: number;
  totalLaps: number;
  processedSessions: number;
  uniqueTracks: number;
}

export interface TrackBreakdownItem {
  name: string;
  sessions: number;
  laps: number;
  share: number;
}

function parseSessionDate(session: SessionSummary): Date | null {
  if (session.created_at_utc) {
    const parsed = new Date(session.created_at_utc);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed;
    }
  }

  const match = session.session_id.match(SESSION_ID_PATTERN);
  if (!match) {
    return null;
  }

  const [, year, month, day, hour, minute, second] = match;
  return new Date(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    ),
  );
}

export function getSessionDateValue(session: SessionSummary): string {
  const parsed = parseSessionDate(session);
  return parsed ? parsed.toISOString().slice(0, 10) : "";
}

export function getSessionSortValue(session: SessionSummary): number {
  const parsed = parseSessionDate(session);
  return parsed ? parsed.getTime() : -1;
}

export function formatSessionTimestamp(sessionId: string): string {
  const match = sessionId.match(SESSION_ID_PATTERN);
  if (!match) return sessionId;
  const [, year, month, day, hour, minute, second] = match;
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

export function formatSessionDateLabel(session: SessionSummary): string {
  const parsed = parseSessionDate(session);
  if (!parsed) return "Unknown date";

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

export function getSessionTrackName(session: Pick<SessionSummary, "track_circuit">): string {
  return session.track_circuit?.trim() || "Unknown Track";
}

export function deriveDashboardKpis(sessions: SessionSummary[]): DashboardKpis {
  return sessions.reduce<DashboardKpis>(
    (acc, session) => {
      acc.totalSessions += 1;
      acc.totalLaps += session.total_laps;
      if (session.has_processed) {
        acc.processedSessions += 1;
      }
      return acc;
    },
    {
      totalSessions: 0,
      totalLaps: 0,
      processedSessions: 0,
      uniqueTracks: new Set(sessions.map(getSessionTrackName)).size,
    },
  );
}

export function deriveTrackBreakdown(
  sessions: SessionSummary[],
  limit = 5,
): TrackBreakdownItem[] {
  const grouped = new Map<string, { sessions: number; laps: number }>();

  sessions.forEach((session) => {
    const key = getSessionTrackName(session);
    const current = grouped.get(key) ?? { sessions: 0, laps: 0 };
    current.sessions += 1;
    current.laps += session.total_laps;
    grouped.set(key, current);
  });

  const items = Array.from(grouped.entries())
    .map(([name, values]) => ({
      name,
      sessions: values.sessions,
      laps: values.laps,
      share: 0,
    }))
    .sort(
      (left, right) =>
        right.sessions - left.sessions ||
        right.laps - left.laps ||
        left.name.localeCompare(right.name),
    )
    .slice(0, limit);

  const maxSessions = items[0]?.sessions ?? 1;
  return items.map((item) => ({
    ...item,
    share: item.sessions / maxSessions,
  }));
}

export function getRecentSessions(
  sessions: SessionSummary[],
  limit = 5,
): SessionSummary[] {
  return [...sessions]
    .sort(
      (left, right) =>
        getSessionSortValue(right) - getSessionSortValue(left) ||
        right.session_id.localeCompare(left.session_id),
    )
    .slice(0, limit);
}
