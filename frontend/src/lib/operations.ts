import { apiRequest } from "./api.ts";

export type LiveMetrics = {
  live: { rooms: number; players: number; activeGames: number };
  peak: { rooms: number; players: number; activeGames: number };
  recorder: {
    buffered: number;
    dropped: number;
    storedEvents: number;
    startedAt: string;
  };
  totals: Record<string, number>;
  games: { finished: number; abandoned: number; shutdown: number };
};

export type DailyTotal = {
  date: string;
  metric: string;
  occurrences: number;
  valueSum: number;
  valueMax: number | null;
};

export type RuntimeEventRow = {
  id: string;
  eventType: string;
  occurredAt: string;
  roomId: string | null;
  userId: string | null;
  value: number | null;
  details: Record<string, unknown>;
};

export type AuditEntry = {
  id: string;
  eventType: string;
  createdAt: string;
  actorUserId: string | null;
  targetUserId: string | null;
  targetType: string | null;
  targetId: string | null;
  details: Record<string, unknown>;
};

/** One day's worth of one metric, for a sparkline. */
export type Series = { date: string; value: number }[];

/** Collapse the daily rows into one metric's series, oldest first.

The API returns newest first because that is the useful order for a table; a
chart reads the other way, and sorting here keeps both callers honest about
which they wanted. */
export function seriesFor(days: DailyTotal[], metric: string): Series {
  return days
    .filter((day) => day.metric === metric)
    .map((day) => ({ date: day.date, value: day.occurrences }))
    .sort((left, right) => left.date.localeCompare(right.date));
}

/** The share of games that stopped without ending, as a percentage.

Worth watching rather than the raw count: ten abandoned games out of twelve is
a problem, out of a thousand it is a Tuesday. */
export function abandonmentRate(games: LiveMetrics["games"]): number | null {
  const total = games.finished + games.abandoned + games.shutdown;
  if (total === 0) return null;
  return Math.round((games.abandoned / total) * 1000) / 10;
}

/** Points for a sparkline polyline, normalised into the given box. */
export function sparklinePoints(
  series: Series,
  width: number,
  height: number,
): string {
  if (series.length === 0) return "";
  if (series.length === 1) return `0,${height / 2} ${width},${height / 2}`;
  const peak = Math.max(...series.map((point) => point.value), 1);
  const step = width / (series.length - 1);
  return series
    .map((point, index) => {
      const x = Math.round(index * step * 100) / 100;
      // SVG y grows downward, so a bigger value has to sit closer to zero.
      const y = Math.round((height - (point.value / peak) * height) * 100) / 100;
      return `${x},${y}`;
    })
    .join(" ");
}

export function readLiveMetrics(): Promise<LiveMetrics> {
  return apiRequest<LiveMetrics>("/api/admin/metrics");
}

export function readDailyTotals(days = 30): Promise<{ days: DailyTotal[] }> {
  return apiRequest(`/api/admin/metrics/daily?days=${days}`);
}

export function readRuntimeEvents(
  params: { limit?: number; eventType?: string; roomId?: string } = {},
): Promise<{ events: RuntimeEventRow[] }> {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.eventType) query.set("eventType", params.eventType);
  if (params.roomId) query.set("roomId", params.roomId);
  return apiRequest(`/api/admin/metrics/events?${query.toString()}`);
}

export function readPlayerActivity(
  userId: string,
): Promise<{ player: { id: string; displayName: string }; events: RuntimeEventRow[] }> {
  return apiRequest(`/api/admin/players/${userId}/activity`);
}

export function readAuditLedger(
  params: { limit?: number; eventType?: string; targetType?: string; targetId?: string } = {},
): Promise<{ entries: AuditEntry[] }> {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.eventType) query.set("eventType", params.eventType);
  if (params.targetType) query.set("targetType", params.targetType);
  if (params.targetId) query.set("targetId", params.targetId);
  return apiRequest(`/api/admin/audit?${query.toString()}`);
}
