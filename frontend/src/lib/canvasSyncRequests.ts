/** One canvas-sync transaction at a time, scoped to what it was asked for (#598).

The old latch tracked "a request is outstanding" and nothing else. Its two gaps:

- A reply was applied whatever it answered. A tail asked for while nothing was
  pending could arrive after the drawer had drawn again, and replacing history
  then cleared the new strokes as if they had never happened; a full reply to
  a request abandoned by a reset landed on the new turn.
- An unanswered request released the latch after ten seconds and retried only
  if something else had asked meanwhile. A lost or refused request on a quiet
  canvas had no next trigger, and the canvas stayed wrong for the turn.

A transaction carries an id the server echoes on its reply, the prefix it
claimed (so a tail can be checked against what it was cut for), and a retry
plan: a request the server refuses says when to try again (`retryAfterMs`); one
it never answers is retried with backoff; and after the attempts run out the
owner is told to hand the session over to a rebind, which pushes a fresh
snapshot and resets everything here. Triggers that arrive while a transaction
is outstanding are satisfied by its reply when the reply converges; only a
reply that failed to converge issues the follow-up. */

export interface PrefixClaim {
  generation: number;
  actionCount: number;
  historyHash: number;
}

export type SyncRefusal = { errorCode?: string; retryAfterMs?: number };

export interface CanvasSyncEnvironment {
  /** Send `request_sync_strokes` for this id; resolves with the server's
  acknowledgement, or rejects when the socket never answered. */
  send(requestId: number, claim: PrefixClaim | null): Promise<{ ok: boolean } & SyncRefusal>;
  /** What this client can honestly claim right now, or null. */
  claim(): PrefixClaim | null;
  /** Every attempt failed: the session, not the canvas, is in question. */
  exhausted(): void;
  setTimeout(handler: () => void, delayMs: number): number;
  clearTimeout(timeoutId: number): void;
}

/** How long a reply may take before the request is presumed lost. */
export const CANVAS_SYNC_TIMEOUT_MS = 10_000;
/** Waits before each retry of a lost or refused request, then give up. */
export const CANVAS_SYNC_RETRIES_MS = [2_000, 4_000, 8_000] as const;

export interface SyncReply {
  requestId: number;
  generation: number;
  /** For a tail: the prefix length it splices onto. */
  baseActionCount?: number;
}

export type ReplyVerdict = "matches" | "unsolicited" | "stale";

export interface CanvasSyncRequester {
  /** Ask for a sync; coalesced while one is outstanding. */
  request(): void;
  /** A reply arrived. `matches` names the outstanding transaction (and, for a
  tail, its claimed prefix); `unsolicited` is a server-pushed sync (id 0);
  `stale` answers a request this client has abandoned and must be ignored. */
  classify(reply: SyncReply): ReplyVerdict;
  /** The matching or unsolicited reply was applied; `converged` says whether
  it left the canvas right. A trigger coalesced meanwhile is discharged by a
  converged reply and re-issued by one that did not. */
  applied(converged: boolean): void;
  /** Forget everything (new generation, room change, teardown). */
  reset(): void;
  /** The id awaiting a reply, or null. */
  readonly outstanding: number | null;
}

export function createCanvasSyncRequester(
  env: CanvasSyncEnvironment,
  timeoutMs: number = CANVAS_SYNC_TIMEOUT_MS,
): CanvasSyncRequester {
  let nextId = 1;
  let outstanding: { id: number; claim: PrefixClaim | null; attempt: number } | null = null;
  let queued = false;
  let timer: number | null = null;

  function clearTimer(): void {
    if (timer !== null) {
      env.clearTimeout(timer);
      timer = null;
    }
  }

  function retryLater(delayMs: number): void {
    const failed = outstanding!;
    clearTimer();
    const attempt = failed.attempt + 1;
    if (attempt >= CANVAS_SYNC_RETRIES_MS.length) {
      outstanding = null;
      queued = false;
      env.exhausted();
      return;
    }
    const wait = Math.max(delayMs, CANVAS_SYNC_RETRIES_MS[attempt]);
    outstanding = { id: 0, claim: null, attempt };
    timer = env.setTimeout(() => {
      timer = null;
      issue(attempt);
    }, wait);
  }

  function issue(attempt: number): void {
    const id = nextId++;
    const claim = env.claim();
    outstanding = { id, claim, attempt };
    clearTimer();
    timer = env.setTimeout(() => {
      timer = null;
      if (outstanding?.id === id) retryLater(0);
    }, timeoutMs);
    env.send(id, claim).then(
      (answer) => {
        if (outstanding?.id !== id) return;
        if (answer.ok) return; // the reply is on its way; the timer guards it
        retryLater(answer.retryAfterMs ?? 0);
      },
      () => {
        if (outstanding?.id === id) retryLater(0);
      },
    );
  }

  return {
    request(): void {
      if (outstanding) {
        queued = true;
        return;
      }
      queued = false;
      issue(0);
    },
    classify(reply): ReplyVerdict {
      if (reply.requestId === 0) return "unsolicited";
      if (!outstanding || reply.requestId !== outstanding.id) return "stale";
      if (reply.baseActionCount !== undefined) {
        const claim = outstanding.claim;
        if (
          !claim
          || reply.generation !== claim.generation
          || reply.baseActionCount !== claim.actionCount
        ) return "stale";
      }
      return "matches";
    },
    applied(converged): void {
      clearTimer();
      outstanding = null;
      if (converged) {
        queued = false;
        return;
      }
      if (queued) {
        queued = false;
        issue(0);
      }
    },
    reset(): void {
      clearTimer();
      outstanding = null;
      queued = false;
    },
    get outstanding(): number | null {
      return outstanding && outstanding.id !== 0 ? outstanding.id : null;
    },
  };
}
