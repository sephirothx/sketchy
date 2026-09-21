/** What only this client can see about its connection, told to the server (#876).

The server observes a connection's life on its own (R-OBS-18): why a socket
closed, how long it lived, the ping round trip, the transport. What it cannot
see is what happened on this side: a canvas tail it could not apply (its base,
its decoding, or a history that does not hash to what the server said), a sync
that ran out of retries, a fire-and-forget emit socket.io discarded because the
transport was not writable (down, or a long-polling POST in flight), the stall
watchdog putting polling first, an episode of a viewer's playback falling
behind (one per incident, not per batch it compressed), and
how long a late joiner looked at an empty canvas. Those are the inputs to the
resync backoff, the stall watchdog's 6 s, `MAX_LAG_MS` and the ack timeout,
which were otherwise chosen without field data.

A ledger and nothing else: counts since the last report, and the handful of
join-to-drawing times measured since. **Sent only when something happened**,
at most once a minute - every one of these is rare in normal play, so a healthy
session sends nothing at all, and the rate each needs as a denominator
(sessions, their length) the server already has. No identifier, no content, no
free text (R-OBS-20): a report says how often, never who, where or what.

Pure: the socket module owns the timer and the send, which is what lets a test
load this without a socket. */

/** Mirrors `MAX_HEALTH_COUNT` in `backend/app/handlers/payloads.py`. */
export const MAX_HEALTH_COUNT = 1000;
/** Mirrors `MAX_JOIN_TO_DRAWING_READINGS`. */
export const MAX_JOIN_TO_DRAWING_READINGS = 8;
/** Mirrors `MAX_JOIN_TO_DRAWING_MS`. */
export const MAX_JOIN_TO_DRAWING_MS = 60_000;
/** How often a report may go out. */
export const HEALTH_REPORT_INTERVAL_MS = 60_000;

export type HealthEvent =
  | "tailRejected"
  | "syncExhausted"
  | "droppedEmits"
  | "stallFallbacks"
  | "playbackCompressions";

const EVENTS: readonly HealthEvent[] = [
  "tailRejected",
  "syncExhausted",
  "droppedEmits",
  "stallFallbacks",
  "playbackCompressions",
];

/** The `client_health` payload. */
export type ClientHealthReport = Record<HealthEvent, number> & {
  joinToDrawingMs: number[];
};

export interface HealthLedger {
  note(event: HealthEvent): void;
  /** One mid-turn entry's wait for the drawing, in milliseconds. */
  noteJoinToDrawing(milliseconds: number): void;
  /** The report to send, or `null` when nothing happened; taking it clears it. */
  take(): ClientHealthReport | null;
}

function zeroCounts(): Record<HealthEvent, number> {
  return {
    tailRejected: 0,
    syncExhausted: 0,
    droppedEmits: 0,
    stallFallbacks: 0,
    playbackCompressions: 0,
  };
}

export function createHealthLedger(): HealthLedger {
  let counts = zeroCounts();
  let joins: number[] = [];

  const addJoin = (milliseconds: number) => {
    if (joins.length >= MAX_JOIN_TO_DRAWING_READINGS) return;
    if (!Number.isFinite(milliseconds)) return;
    joins.push(Math.min(MAX_JOIN_TO_DRAWING_MS, Math.max(0, Math.round(milliseconds))));
  };

  return {
    note(event) {
      counts[event] = Math.min(MAX_HEALTH_COUNT, counts[event] + 1);
    },
    noteJoinToDrawing: addJoin,
    take() {
      const happened = joins.length > 0 || EVENTS.some((event) => counts[event] > 0);
      if (!happened) return null;
      const report: ClientHealthReport = { ...counts, joinToDrawingMs: joins };
      counts = zeroCounts();
      joins = [];
      return report;
    },
  };
}

/** The page's ledger. Modules note into it; `socket.ts` sends from it. */
const ledger = createHealthLedger();

export function noteHealth(event: HealthEvent): void {
  ledger.note(event);
}

export function noteJoinToDrawing(milliseconds: number): void {
  ledger.noteJoinToDrawing(milliseconds);
}

export function takeHealthReport(): ClientHealthReport | null {
  return ledger.take();
}

