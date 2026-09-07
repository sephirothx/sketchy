/** When a seated client asks the server whether it is still where it thinks
it is (#564).

`session_ping` is the room's liveness probe: every five seconds a visible,
seated client asks and compares the answer's phase and round with its own.
Under the release load gate it was the most frequent command of all - 83
request/acknowledgement pairs a second at 400 seats - and most of those
answers say what the seat had just been told anyway: the server sends a
`turn_starting`, `turn_started`, `turn_ended`, `sync_game` or `room_state`
whenever the phase or round moves, and each carries the phase and round the
probe would confirm.

So a probe is skipped when one of *those* events reached this seat inside the
last interval and agrees with what the seat holds now. Nothing else counts:
draw frames, chat, a client-config notice and an Engine.IO pong all prove
the transport is alive and nothing about the seat - the phase, the round or
the binding may be stale under a healthy stream of drawing - which is why a
"silence only" rule was refused in the issue. And whatever the events say, a
probe is forced at least every `MAX_GAP_MS`: the transport's own ping
timeout is 20 s, and a silent one-way failure has to be noticed before it.

A reply is judged against the state the seat holds *when it lands*, not the
one it held when the probe left: the two can differ across a turn change,
and comparing an old answer with an old snapshot is how a correct seat
rebinds for nothing. A reply from another socket, room or seat than the
probe was sent from is not judged at all.

Pure: time is passed in, and the hook owns the timer. */

export const HEARTBEAT_MS = 5000;
export const MAX_GAP_MS = 15_000;

export interface SeatState {
  phase: string;
  round: number;
}

export interface ProbeScope {
  socketId: string | undefined;
  code: string;
  playerId: string;
  sentAt: number;
}

export interface HeartbeatSchedule {
  /** An authoritative event landed carrying this phase and round. */
  noteAuthoritative(state: SeatState, at: number): void;
  /** A probe was sent. */
  noteProbe(at: number): void;
  /** Whether the timer's tick should send a probe now. */
  shouldProbe(now: number, local: SeatState): boolean;
  /** How many ticks were skipped, for the report and the tests. */
  skipped(): number;
}

export function createHeartbeatSchedule(options: {
  intervalMs?: number;
  maxGapMs?: number;
} = {}): HeartbeatSchedule {
  const interval = options.intervalMs ?? HEARTBEAT_MS;
  const maxGap = options.maxGapMs ?? MAX_GAP_MS;
  let lastAuthoritative: { state: SeatState; at: number } | null = null;
  let lastProbeAt = Number.NEGATIVE_INFINITY;
  let skips = 0;

  return {
    noteAuthoritative(state, at) {
      lastAuthoritative = { state: { ...state }, at };
    },
    noteProbe(at) {
      lastProbeAt = at;
    },
    shouldProbe(now, local) {
      // The cap first: however much the seat has been told, it asks at
      // least this often, so a silent one-way failure is noticed in time.
      if (now - lastProbeAt >= maxGap) return true;
      const recent = lastAuthoritative;
      const covered = recent !== null
        && now - recent.at < interval
        && recent.state.phase === local.phase
        && recent.state.round === local.round;
      if (covered) {
        skips += 1;
        return false;
      }
      // The cadence is counted from the last probe, not from its answer:
      // an answer lands after the probe, and a tick that is a few
      // milliseconds short of the interval since it must not slip a tick.
      return now - lastProbeAt >= interval - interval / 10;
    },
    skipped: () => skips,
  };
}

/** Whether a probe's answer may be judged: the same socket, room and seat it
was sent from, and no authoritative event has moved the seat since - a reply
older than a local phase change says nothing about the state it lands on. */
export function replyIsCurrent(
  scope: ProbeScope,
  now: {
    socketId: string | undefined;
    code: string | null;
    playerId: string | null;
    lastAuthoritativeAt: number | null;
  },
): boolean {
  if (now.socketId !== scope.socketId) return false;
  if (now.code !== scope.code || now.playerId !== scope.playerId) return false;
  if (now.lastAuthoritativeAt !== null && now.lastAuthoritativeAt > scope.sentAt) return false;
  return true;
}
