import assert from "node:assert/strict";
import test from "node:test";

import {
  abandonmentRate,
  seriesFor,
} from "../src/lib/operations.ts";

const days = [
  { date: "2026-08-24", metric: "game.finished", occurrences: 5, valueSum: 0, valueMax: null },
  { date: "2026-08-22", metric: "game.finished", occurrences: 1, valueSum: 0, valueMax: null },
  { date: "2026-08-23", metric: "game.abandoned", occurrences: 9, valueSum: 0, valueMax: null },
  { date: "2026-08-23", metric: "game.finished", occurrences: 3, valueSum: 0, valueMax: null },
];

test("a series is one metric, oldest first", () => {
  // The API answers newest-first because that is what a table wants; a chart
  // reads the other way, and mixing them up draws time backwards.
  assert.deepEqual(seriesFor(days, "game.finished"), [
    { date: "2026-08-22", value: 1 },
    { date: "2026-08-23", value: 3 },
    { date: "2026-08-24", value: 5 },
  ]);
  assert.deepEqual(seriesFor(days, "nothing.recorded"), []);
});

test("abandonment is a share, because the count alone says nothing", () => {
  // Ten abandoned out of twelve is a problem; out of a thousand it is a Tuesday.
  assert.equal(abandonmentRate({ finished: 90, abandoned: 10, shutdown: 0 }), 10);
  assert.equal(abandonmentRate({ finished: 2, abandoned: 10, shutdown: 0 }), 83.3);
  assert.equal(abandonmentRate({ finished: 0, abandoned: 0, shutdown: 0 }), null);
});

// ---------------------------------------------------------------- signals

import {
  ATTENTION,
  attentionReasons,
  formatBytes,
  formatDuration,
  formatMs,
  formatPercent,
  poolFill,
} from "../src/lib/operations.ts";

function healthy(overrides = {}) {
  const base = {
    live: { rooms: 1, players: 2, activeGames: 1 },
    peak: { rooms: 1, players: 2, activeGames: 1 },
    recorder: { buffered: 0, dropped: 0, storedEvents: 10, startedAt: "2026-09-02T00:00:00Z" },
    totals: {},
    games: { finished: 100, abandoned: 1, shutdown: 0 },
    generatedAt: "2026-09-02T01:00:00Z",
    windowMinutes: 5,
    http: { perMinute: 10, errorRate: 0, p50Ms: 3, p95Ms: 20, p99Ms: 50, inFlight: 0, total: 100 },
    socket: { perMinute: 100, errorRate: 0, refusedRate: 0, throttledPerMinute: 0, p95Ms: 2, connected: 4, total: 1000 },
    process: {
      loopLagMs: 1, loopLagP95Ms: 3, cpuPercent: 2, rssBytes: 100e6, rssIsPeak: false,
      uptimeSeconds: 3600, startedAt: "2026-09-02T00:00:00Z", diskFreeBytes: 1e9, diskTotalBytes: 2e9, diskPath: "/srv",
    },
    database: {
      pool: { size: 5, checkedOut: 1, checkedIn: 4, overflow: 0, capacity: 10 },
      queriesPerMinute: 50, queryP95Ms: 2, queryErrors: 0,
      historyWritesAbandoned: { total: 0, lastHour: 0, byReason: { timeout: 0, error: 0 } },
      readiness: { ok: true, reason: null, checkedAgoSeconds: 2 },
    },
    queues: { mailOutbox: { pending: 0, oldestSeconds: null, sweepSeconds: 30 }, dataExports: { pending: 0, oldestSeconds: null } },
    loops: { mail_delivery: { running: true, consecutiveFailures: 0, totalFailures: 0, secondsSinceSuccess: 5, secondsSinceFailure: null } },
    series: { httpPerMinute: [], socketPerMinute: [], httpP95Ms: [], socketP95Ms: [], loopLagMaxMs: [], rssBytes: [] },
  };
  return deepMerge(base, overrides);
}

function deepMerge(target, source) {
  const out = { ...target };
  for (const [key, value] of Object.entries(source)) {
    out[key] = value && typeof value === "object" && !Array.isArray(value) && typeof out[key] === "object"
      ? deepMerge(out[key], value)
      : value;
  }
  return out;
}

test("a healthy snapshot needs nobody", () => {
  assert.deepEqual(attentionReasons(healthy()), []);
});

test("what is already lost outranks what is merely slow", () => {
  // A stopped loop and a lagging loop at once: the operator is told about the
  // stopped one first, because it will not fix itself.
  const reasons = attentionReasons(
    healthy({
      loops: { mail_delivery: { running: false, consecutiveFailures: 0, totalFailures: 0, secondsSinceSuccess: null, secondsSinceFailure: null } },
      process: { loopLagP95Ms: 900 },
      http: { errorRate: 0.5 },
    }),
  );
  assert.deepEqual(
    reasons.map((reason) => reason.key),
    ["loop-stopped:mail_delivery", "loop-lag", "http-errors"],
  );
  assert.equal(reasons[0].headline, "mail_delivery loop stopped");
  assert.equal(reasons[0].card, "queues");
});

test("each threshold is a threshold, not a suggestion", () => {
  const at = (overrides) => attentionReasons(healthy(overrides)).map((reason) => reason.key);
  assert.deepEqual(at({ process: { loopLagP95Ms: ATTENTION.loopLagP95Ms } }), []);
  assert.deepEqual(at({ process: { loopLagP95Ms: ATTENTION.loopLagP95Ms + 1 } }), ["loop-lag"]);
  assert.deepEqual(at({ http: { errorRate: ATTENTION.httpErrorRate } }), []);
  assert.deepEqual(at({ http: { errorRate: ATTENTION.httpErrorRate + 0.001 } }), ["http-errors"]);
  // Mail may wait two sweeps; a third is a backlog.
  assert.deepEqual(at({ queues: { mailOutbox: { pending: 1, oldestSeconds: 60 } } }), []);
  assert.deepEqual(at({ queues: { mailOutbox: { pending: 1, oldestSeconds: 61 } } }), ["mail-backlog"]);
  assert.deepEqual(at({ database: { pool: { checkedOut: 10 } } }), ["pool-saturated"]);
  assert.deepEqual(at({ database: { historyWritesAbandoned: { lastHour: 1 } } }), ["history-lost"]);
  assert.deepEqual(at({ database: { readiness: { ok: false, reason: "timed out" } } }), ["database-down"]);
  assert.deepEqual(at({ recorder: { dropped: 3 } }), ["recorder-dropped"]);
  assert.deepEqual(at({ games: { finished: 3, abandoned: 1 } }), ["abandonment"]);
});

test("numbers are shown in the unit an operator thinks in", () => {
  assert.equal(formatBytes(null), "—");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(187_000_000), "178 MB");
  assert.equal(formatBytes(1.5 * 1024 ** 3), "1.5 GB");
  assert.equal(formatDuration(45), "45 s");
  assert.equal(formatDuration(720), "12 min");
  assert.equal(formatDuration(3 * 3600 + 4 * 60), "3 h 04 min");
  assert.equal(formatDuration(2 * 86400 + 5 * 3600), "2 d 5 h");
  assert.equal(formatMs(0.4), "< 1 ms");
  assert.equal(formatMs(28.4), "28 ms");
  assert.equal(formatMs(1300), "1.3 s");
  assert.equal(formatPercent(0), "0 %");
  assert.equal(formatPercent(0.0004), "< 0.1 %");
  assert.equal(formatPercent(0.0024), "0.2 %");
  assert.equal(formatPercent(0.5), "50 %");
  assert.equal(poolFill(null), null);
  assert.equal(poolFill({ size: 5, checkedOut: 5, checkedIn: 0, overflow: 0, capacity: 10 }), 0.5);
});
