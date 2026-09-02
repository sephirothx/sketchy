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
  /** Resolved when the ledger is read, never stored in the entry - so an
      erased account stops being named while the entry still stands. Null when
      the subject is gone or was never a named thing. */
  actorName: string | null;
  targetName: string | null;
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

// ---------------------------------------------------------------- signals

export type LoopStatus = {
  running: boolean;
  consecutiveFailures: number;
  totalFailures: number;
  secondsSinceSuccess: number | null;
  secondsSinceFailure: number | null;
};

export type QueueDepth = { pending: number; oldestSeconds: number | null };

export type PoolGauges = {
  size: number;
  checkedOut: number;
  checkedIn: number;
  overflow: number;
  capacity: number;
};

/** Sixty per-minute points, oldest first; null where the minute recorded nothing. */
export type MinuteSeries = (number | null)[];

/** The process signals the overview draws: rates and percentiles over the
    trailing window (`windowMinutes`), the series behind the sparklines, the
    two durable queues and the supervised loops. All of it is process memory
    that vanishes on restart, like the live counts. */
export type ServerSignals = {
  generatedAt: string;
  windowMinutes: number;
  http: {
    perMinute: number;
    errorRate: number;
    p50Ms: number | null;
    p95Ms: number | null;
    p99Ms: number | null;
    inFlight: number;
    total: number;
  };
  socket: {
    perMinute: number;
    errorRate: number;
    refusedRate: number;
    throttledPerMinute: number;
    p95Ms: number | null;
    connected: number | null;
    total: number;
  };
  process: {
    loopLagMs: number | null;
    loopLagP95Ms: number | null;
    cpuPercent: number | null;
    rssBytes: number | null;
    rssIsPeak: boolean;
    uptimeSeconds: number;
    startedAt: string;
    diskFreeBytes: number | null;
    diskTotalBytes: number | null;
    diskPath: string;
  };
  database: {
    pool: PoolGauges | null;
    queriesPerMinute: number;
    queryP95Ms: number | null;
    queryErrors: number;
    historyWritesAbandoned: {
      total: number;
      lastHour: number;
      byReason: { timeout: number; error: number };
    };
    readiness: { ok: boolean; reason: string | null; checkedAgoSeconds: number } | null;
  };
  queues: {
    mailOutbox: QueueDepth & { sweepSeconds: number };
    dataExports: QueueDepth;
  };
  loops: Record<string, LoopStatus>;
  series: {
    httpPerMinute: MinuteSeries;
    socketPerMinute: MinuteSeries;
    httpP95Ms: MinuteSeries;
    socketP95Ms: MinuteSeries;
    loopLagMaxMs: MinuteSeries;
    rssBytes: MinuteSeries;
  };
};

export type LiveSnapshot = LiveMetrics & ServerSignals;

export function readLiveSnapshot(): Promise<LiveSnapshot> {
  return apiRequest<LiveSnapshot>("/api/admin/metrics");
}

// ---------------------------------------------------------------- formatting

export function formatBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${whole} s`;
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest === 0 ? `${hours} h` : `${hours} h ${String(rest).padStart(2, "0")} min`;
  const days = Math.floor(hours / 24);
  const hoursLeft = hours % 24;
  return hoursLeft === 0 ? `${days} d` : `${days} d ${hoursLeft} h`;
}

export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return "—";
  if (ms < 1) return "< 1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

/** A ratio (0–1) as a percentage with as much precision as it needs. */
export function formatPercent(rate: number | null): string {
  if (rate === null || !Number.isFinite(rate)) return "—";
  const percent = rate * 100;
  if (percent === 0) return "0 %";
  if (percent < 0.1) return "< 0.1 %";
  return `${percent < 10 ? percent.toFixed(1) : Math.round(percent)} %`;
}

export function formatRate(perMinute: number | null): string {
  if (perMinute === null || !Number.isFinite(perMinute)) return "—";
  return perMinute >= 100 ? String(Math.round(perMinute)) : perMinute.toFixed(1);
}

/** How full the pool is, 0–1, or null when the engine keeps no pool count. */
export function poolFill(pool: PoolGauges | null): number | null {
  if (pool === null || pool.capacity <= 0) return null;
  return pool.checkedOut / pool.capacity;
}

// ---------------------------------------------------------------- attention

/** The lines an operator is asked to act on, and where each is drawn from. */
export const ATTENTION = {
  loopLagP95Ms: 250,
  httpErrorRate: 0.01,
  socketErrorRate: 0.01,
  mailOldestFactor: 2,
  exportOldestSeconds: 600,
  poolFillRatio: 1,
  abandonmentPercent: 25,
} as const;

export type AttentionCard = "recorder" | "traffic" | "process" | "database" | "queues";

export type AttentionReason = {
  key: string;
  card: AttentionCard;
  /** Short enough for the status banner. */
  headline: string;
  /** A full sentence for the attention list. */
  text: string;
};

/** Everything on the snapshot that needs an operator, most urgent first.

Ordered by what it means rather than by where it is drawn: data already lost
(a dropped observation, a stopped loop, an abandoned history write) outranks a
dependency that is down, which outranks latency, which outranks a queue that
is merely slow. The banner shows the first; the attention list shows all. */
export function attentionReasons(live: LiveSnapshot): AttentionReason[] {
  const reasons: AttentionReason[] = [];
  const add = (key: string, card: AttentionCard, headline: string, text: string) =>
    reasons.push({ key, card, headline, text });

  if (live.recorder.dropped > 0) {
    add(
      "recorder-dropped",
      "recorder",
      "Recorder dropped observations",
      `${live.recorder.dropped} observations were dropped by a full buffer.`,
    );
  }
  const loops = Object.entries(live.loops ?? {});
  for (const [name, loop] of loops) {
    if (!loop.running) {
      add(`loop-stopped:${name}`, "queues", `${name} loop stopped`, `The ${name} loop has stopped and will not come back without a restart.`);
    }
  }
  for (const [name, loop] of loops) {
    if (loop.running && loop.consecutiveFailures > 0) {
      add(
        `loop-failing:${name}`,
        "queues",
        `${name} loop failing`,
        `The ${name} loop has failed ${loop.consecutiveFailures} times in a row.`,
      );
    }
  }
  const lost = live.database?.historyWritesAbandoned;
  if (lost && lost.lastHour > 0) {
    add(
      "history-lost",
      "database",
      "Finished games not saved",
      `${lost.lastHour} finished-game or prompt-usage writes were abandoned in the last hour.`,
    );
  }
  const readiness = live.database?.readiness;
  if (readiness && !readiness.ok) {
    add(
      "database-down",
      "database",
      "Database unreachable",
      `The last readiness probe failed: ${readiness.reason ?? "no reason given"}.`,
    );
  }
  const lag = live.process?.loopLagP95Ms;
  if (lag !== null && lag !== undefined && lag > ATTENTION.loopLagP95Ms) {
    add("loop-lag", "process", "Event loop lagging", `Event-loop lag p95 is ${formatMs(lag)} over the last ${live.windowMinutes} minutes.`);
  }
  if (live.http && live.http.errorRate > ATTENTION.httpErrorRate) {
    add("http-errors", "traffic", "Requests failing", `${formatPercent(live.http.errorRate)} of requests answered with a server error.`);
  }
  if (live.socket && live.socket.errorRate > ATTENTION.socketErrorRate) {
    add("socket-errors", "traffic", "Commands failing", `${formatPercent(live.socket.errorRate)} of client commands raised an error.`);
  }
  const fill = poolFill(live.database?.pool ?? null);
  if (fill !== null && fill >= ATTENTION.poolFillRatio) {
    add("pool-saturated", "database", "Connection pool saturated", "Every database connection is in use; new queries are waiting.");
  }
  const mail = live.queues?.mailOutbox;
  if (mail && mail.oldestSeconds !== null && mail.oldestSeconds > mail.sweepSeconds * ATTENTION.mailOldestFactor) {
    add("mail-backlog", "queues", "Mail is backing up", `The oldest undelivered message has waited ${formatDuration(mail.oldestSeconds)}.`);
  }
  const exports = live.queues?.dataExports;
  if (exports && exports.oldestSeconds !== null && exports.oldestSeconds > ATTENTION.exportOldestSeconds) {
    add("export-stuck", "queues", "An export is stuck", `The oldest unfinished account export has waited ${formatDuration(exports.oldestSeconds)}.`);
  }
  const rate = abandonmentRate(live.games);
  if (rate !== null && rate >= ATTENTION.abandonmentPercent) {
    add("abandonment", "recorder", "Games being abandoned", `Abandoned games sit at ${rate}% this window.`);
  }
  return reasons;
}
