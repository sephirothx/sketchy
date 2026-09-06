/** Replaying a drawer's unconfirmed actions without exceeding the allowance
they spend, and noticing when a finished action was never confirmed (#597).

Recovery used to resend every saved frame in one synchronous loop. Those frames
spend the same drawing budget as live drawing, and nobody awaits a `draw`, so
the refusal is silent: a six-second stroke replayed as 152 frames had exactly
100 accepted, the end dropped, and the path left open on the server with no
event that would ever close it. A larger allowance is not a fix - a longer
stroke exceeds any live allowance - and repeating the burst fails at the same
frame.

Three parts, all pure so they can be tested without a socket:

- `repackDrawFrames` turns a saved path's 40 ms batches back into the fewest
  codec-valid frames. Both histories store a path as one point list, so the
  batch boundaries were never part of the record: the same points in the same
  order produce the same canonical action and the same hash. 150 one-point
  batches become one 150-point frame.
- `RecoverySender` sends repacked frames at a pace under the allowance the
  server advertised in `client_config`, keeping a reserve for the controls a
  person may press meanwhile, and coalesces repeated requests for the same
  sequence so two `request_canvas_actions` for one gap cost one replay.
- `CompletionWatch` gives a finished-but-unconfirmed action a deadline. The
  server answers a resend of a committed action by replaying its stored
  commit, and accepts one it never saw, so one resend resolves either a lost
  end frame or a lost commit. Three tries with backoff, then authoritative
  state: the drawing that exists is the one the room has. */

import { decodeLiveDrawing, encodePathPoints } from "./liveDrawing.ts";
import type { DrawingFrame } from "./liveDrawing.ts";

const MAX_POINTS_PER_FRAME = 256;

/** The share of the allowance left for live controls while replaying. */
export const REPLAY_RESERVE = 0.25;
/** Frames a replay may send at once before pacing kicks in. */
export const REPLAY_BURST = 8;
/** Points one recovery may replay before it is cheaper to take server truth. */
export const MAX_REPLAY_POINTS = 5_000;
/** Backoff before each resend of an unconfirmed action, then give up. */
export const COMPLETION_RETRIES_MS = [2_000, 4_000, 8_000] as const;

export interface DrawingAllowance {
  drawingFramesPerWindow: number;
  drawingWindowSeconds: number;
}

/** A path's saved frames, repacked into the fewest frames the codec allows.

Anything that is not `start, move*, end` - a shape, a fill, a clear, or a path
still open - comes back as it was. Order and points are untouched. */
export function repackDrawFrames(frames: DrawingFrame[]): DrawingFrame[] {
  if (frames.length < 2) return frames;
  const packets = frames.map((frame) => decodeLiveDrawing(frame));
  const first = packets[0];
  const last = packets.at(-1);
  if (!first || first.event !== "draw_start" || !last || last.event !== "draw_end") return frames;
  const points: { x: number; y: number }[] = [];
  for (const packet of packets.slice(1, -1)) {
    if (!packet || packet.event !== "draw_move") return frames;
    points.push(...packet.payload.points);
  }
  const repacked: DrawingFrame[] = [frames[0]];
  for (let index = 0; index < points.length; index += MAX_POINTS_PER_FRAME) {
    repacked.push(encodePathPoints({ points: points.slice(index, index + MAX_POINTS_PER_FRAME) }));
  }
  repacked.push(frames.at(-1)!);
  return repacked;
}

export function pointCount(frames: DrawingFrame[]): number {
  let total = 0;
  for (const frame of frames) {
    const packet = decodeLiveDrawing(frame);
    if (packet?.event === "draw_move") total += packet.payload.points.length;
  }
  return total;
}

export interface QueuedMutation {
  sequence: number;
  frames: DrawingFrame[];
  identity: [number, number];
}

export interface SenderDependencies {
  /** Put one frame on the wire; `identity` only on the opener. */
  emit(frame: DrawingFrame, identity?: [number, number]): void;
  allowance(): DrawingAllowance;
  now(): number;
  schedule(callback: () => void, delayMs: number): unknown;
  cancel(handle: unknown): void;
  /** Called once when a queue exceeds `MAX_REPLAY_POINTS`; the queue is dropped. */
  tooLarge(): void;
}

/** Sends queued mutations under the advertised allowance, oldest first.

Pacing: after `REPLAY_BURST` frames inside the current window, one frame every
`windowSeconds / (framesPerWindow × (1 − reserve))` seconds. The window is the
server's, so this is what the server would accept from a client that had not
been drawing live - and a stalled client has not. */
export class RecoverySender {
  private queue: QueuedMutation[] = [];
  private inFlight: { mutation: QueuedMutation; index: number } | null = null;
  private timer: unknown = null;
  private sentAt: number[] = [];
  private readonly deps: SenderDependencies;

  constructor(deps: SenderDependencies) {
    this.deps = deps;
  }

  /** Queue a mutation; a sequence already queued is replaced, not doubled. */
  enqueue(mutation: QueuedMutation): void {
    if (this.inFlight?.mutation.sequence === mutation.sequence) return;
    this.queue = this.queue.filter((queued) => queued.sequence !== mutation.sequence);
    this.queue.push(mutation);
    this.queue.sort((left, right) => left.sequence - right.sequence);
    const points = this.queue.reduce((total, queued) => total + pointCount(queued.frames), 0);
    if (points > MAX_REPLAY_POINTS) {
      this.cancel();
      this.deps.tooLarge();
      return;
    }
    this.pump();
  }

  /** Forget everything queued; nothing further is sent. */
  cancel(): void {
    this.queue = [];
    this.inFlight = null;
    if (this.timer !== null) {
      this.deps.cancel(this.timer);
      this.timer = null;
    }
  }

  get pending(): number {
    return this.queue.length + (this.inFlight ? 1 : 0);
  }

  /** Sending starts on the next tick, not inside `enqueue`: recovery queues a
  run of sequences in one pass, and they must leave in sequence order. */
  private pump(): void {
    if (this.timer !== null) return;
    this.timer = this.deps.schedule(() => {
      this.timer = null;
      this.drain();
    }, 0);
  }

  private drain(): void {
    if (this.timer !== null) return;
    while (this.inFlight || this.queue.length > 0) {
      if (!this.inFlight) this.inFlight = { mutation: this.queue.shift()!, index: 0 };
      const wait = this.waitMs();
      if (wait > 0) {
        this.timer = this.deps.schedule(() => {
          this.timer = null;
          this.drain();
        }, wait);
        return;
      }
      const { mutation, index } = this.inFlight;
      this.deps.emit(mutation.frames[index], index === 0 ? mutation.identity : undefined);
      this.sentAt.push(this.deps.now());
      if (index + 1 >= mutation.frames.length) this.inFlight = null;
      else this.inFlight.index = index + 1;
    }
  }

  private waitMs(): number {
    const { drawingFramesPerWindow, drawingWindowSeconds } = this.deps.allowance();
    const windowMs = drawingWindowSeconds * 1000;
    const now = this.deps.now();
    this.sentAt = this.sentAt.filter((at) => now - at < windowMs);
    const allowed = Math.max(1, Math.floor(drawingFramesPerWindow * (1 - REPLAY_RESERVE)));
    if (this.sentAt.length >= allowed) {
      // The window's share is spent: wait for the oldest send to leave it.
      return Math.max(1, Math.ceil(this.sentAt[0] + windowMs - now));
    }
    if (this.sentAt.length < REPLAY_BURST) return 0;
    const due = this.sentAt.at(-1)! + windowMs / allowed;
    return Math.max(0, Math.ceil(due - now));
  }
}

export interface WatchDependencies {
  schedule(callback: () => void, delayMs: number): unknown;
  cancel(handle: unknown): void;
  /** Resend the action; the server replays its commit or accepts it. */
  resend(sequence: number): void;
  /** Retries exhausted: take authoritative state. */
  giveUp(sequence: number): void;
}

/** Deadlines for finished actions the server has not confirmed. */
export class CompletionWatch {
  private readonly armed = new Map<number, { attempt: number; handle: unknown }>();
  private readonly deps: WatchDependencies;

  constructor(deps: WatchDependencies) {
    this.deps = deps;
  }

  /** Start (or restart) the clock for a finished action. */
  arm(sequence: number): void {
    this.confirm(sequence);
    this.schedule(sequence, 0);
  }

  /** The server confirmed it; nothing more to do. */
  confirm(sequence: number): void {
    const entry = this.armed.get(sequence);
    if (entry) {
      this.deps.cancel(entry.handle);
      this.armed.delete(sequence);
    }
  }

  /** The server reports its committed sequence: anything at or below it that
  is still armed was committed, and its confirmation was lost. Resend now
  rather than at the deadline - the answer is the stored commit. */
  serverCommitted(sequence: number): void {
    for (const armed of [...this.armed.keys()]) {
      if (armed <= sequence) this.fire(armed);
    }
  }

  isArmed(sequence: number): boolean {
    return this.armed.has(sequence);
  }

  cancelAll(): void {
    for (const sequence of [...this.armed.keys()]) this.confirm(sequence);
  }

  private schedule(sequence: number, attempt: number): void {
    const delay = COMPLETION_RETRIES_MS[attempt];
    const handle = this.deps.schedule(() => this.fire(sequence), delay);
    this.armed.set(sequence, { attempt, handle });
  }

  private fire(sequence: number): void {
    const entry = this.armed.get(sequence);
    if (!entry) return;
    this.deps.cancel(entry.handle);
    const next = entry.attempt + 1;
    if (next >= COMPLETION_RETRIES_MS.length) {
      this.armed.delete(sequence);
      this.deps.giveUp(sequence);
      return;
    }
    this.schedule(sequence, next);
    this.deps.resend(sequence);
  }
}

/** The canvas sequence the server last reported in a heartbeat, for whoever
holds the pending actions. The heartbeat and the protocol are different hooks
on different lifetimes; a small subject is the least coupling between them. */
type SequenceListener = (generation: number, sequence: number) => void;
const sequenceListeners = new Set<SequenceListener>();

export function observeServerCanvasSequence(generation: unknown, sequence: unknown): void {
  if (!Number.isSafeInteger(generation) || !Number.isSafeInteger(sequence)) return;
  sequenceListeners.forEach((listener) => listener(generation as number, sequence as number));
}

export function onServerCanvasSequence(listener: SequenceListener): () => void {
  sequenceListeners.add(listener);
  return () => {
    sequenceListeners.delete(listener);
  };
}

/** Recovery gave up: every sync attempt was lost or refused, so the seat
binding itself is in question. The reconnect hook owns that decision and
answers with a transport restart, after which the server pushes a fresh
snapshot and the protocol starts clean. */
type RebindListener = () => void;
const rebindListeners = new Set<RebindListener>();

export function requestSessionRebind(): void {
  rebindListeners.forEach((listener) => listener());
}

export function onSessionRebindRequested(listener: RebindListener): () => void {
  rebindListeners.add(listener);
  return () => {
    rebindListeners.delete(listener);
  };
}

/** What to do about a `canvas_stale` notice (#562).

The server no longer pushes the whole history at a refused opening, a stale
generation or a disagreement: it sends one small notice per window and the
client asks through its sync transaction, which is budgeted and can claim a
verified prefix. Every reason but `deferred` means this client applied
something the server refused, so its pending work is a guess to discard;
`deferred` only means "ask again in a moment" and pending work stays. */
export interface StaleNoticeAction {
  discardPending: boolean;
  delayMs: number;
}

export function staleNoticeAction(payload: unknown, ownGeneration: number | null): StaleNoticeAction | null {
  if (!Array.isArray(payload) || payload.length < 4) return null;
  const [generation, , reason, retryAfterMs] = payload;
  if (!Number.isSafeInteger(generation) || typeof reason !== "string") return null;
  const delayMs = typeof retryAfterMs === "number" && Number.isFinite(retryAfterMs) && retryAfterMs > 0
    ? retryAfterMs
    : 0;
  if (reason === "deferred") return { discardPending: false, delayMs };
  // A notice about another generation still says this canvas is behind.
  void ownGeneration;
  return { discardPending: true, delayMs: 0 };
}
