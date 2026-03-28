import type { SessionSummary } from "../types";

const SESSION_ID_PATTERN =
  /^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/;

export type SessionLibrarySort = "newest" | "oldest" | "laps" | "track";

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

export function getSessionCarLabel(
  carOrdinal: number | null | undefined,
): string | null {
  if (carOrdinal === null || carOrdinal === undefined) {
    return null;
  }

  return `Car #${carOrdinal}`;
}

export function getSessionVehicleTrackLabel(
  session: Pick<SessionSummary, "car_ordinal" | "track_circuit">,
): string {
  const carLabel = getSessionCarLabel(session.car_ordinal);
  const trackLabel = getSessionTrackName(session);

  return carLabel ? `${carLabel} // ${trackLabel}` : trackLabel;
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

export function matchesSessionQuery(
  session: Pick<
    SessionSummary,
    "session_id" | "track_circuit" | "track_layout" | "track_location" | "car_ordinal"
  >,
  query: string,
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  const searchable = [
    session.session_id,
    session.track_circuit,
    session.track_layout,
    session.track_location,
    getSessionCarLabel(session.car_ordinal),
    session.car_ordinal?.toString(),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return searchable.includes(normalizedQuery);
}

function compareSessions(
  left: SessionSummary,
  right: SessionSummary,
  sort: SessionLibrarySort,
): number {
  switch (sort) {
    case "oldest":
      return (
        getSessionSortValue(left) - getSessionSortValue(right) ||
        left.session_id.localeCompare(right.session_id)
      );
    case "laps":
      return (
        right.total_laps - left.total_laps ||
        getSessionSortValue(right) - getSessionSortValue(left) ||
        right.session_id.localeCompare(left.session_id)
      );
    case "track":
      return (
        getSessionTrackName(left).localeCompare(getSessionTrackName(right)) ||
        getSessionSortValue(right) - getSessionSortValue(left) ||
        right.session_id.localeCompare(left.session_id)
      );
    case "newest":
    default:
      return (
        getSessionSortValue(right) - getSessionSortValue(left) ||
        right.session_id.localeCompare(left.session_id)
      );
  }
}

export function sortSessionsForLibrary(
  sessions: SessionSummary[],
  sort: SessionLibrarySort,
  activeSessionId?: string | null,
): SessionSummary[] {
  return [...sessions].sort((left, right) => {
    const leftIsActive = activeSessionId !== null && activeSessionId !== undefined
      ? left.session_id === activeSessionId
      : false;
    const rightIsActive = activeSessionId !== null && activeSessionId !== undefined
      ? right.session_id === activeSessionId
      : false;

    if (leftIsActive !== rightIsActive) {
      return leftIsActive ? -1 : 1;
    }

    return compareSessions(left, right, sort);
  });
}
