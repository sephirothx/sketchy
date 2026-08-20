export interface CanvasSyncRequestEnvironment {
  /** Ask the server for the authoritative canvas history. */
  requestSync(): void;
  setTimeout(handler: () => void, delayMs: number): number;
  clearTimeout(timeoutId: number): void;
}

/**
 * How long to wait for a sync before assuming the request was dropped.
 *
 * The server answers `request_sync_strokes` only for a socket that currently
 * resolves to a room member with a live game, and says nothing at all
 * otherwise - so a request issued while the session is rebinding (the moment
 * right after a transport drop, which is exactly when a sync is most needed)
 * is silently discarded. Nothing else would ever release the latch.
 *
 * Comfortably longer than a healthy sync so a slow but arriving history is not
 * requested twice, and short enough that a client cannot stay desynchronized
 * for a whole turn. Releasing early only costs a redundant history; releasing
 * late leaves the canvas wrong.
 */
export const CANVAS_SYNC_TIMEOUT_MS = 10_000;

export interface CanvasSyncRequester {
  /** Ask for a sync, coalescing while one is already outstanding. */
  request(): void;
  /** A sync arrived: stop waiting on the outstanding request. */
  arrived(): void;
  /** Issue the follow-up that was coalesced away, if there was one. */
  drainQueued(): void;
  /** Forget any outstanding request (new generation, or teardown). */
  reset(): void;
}

function browserEnvironment(requestSync: () => void): CanvasSyncRequestEnvironment {
  return {
    requestSync,
    setTimeout: (handler, delayMs) => window.setTimeout(handler, delayMs),
    clearTimeout: (timeoutId) => window.clearTimeout(timeoutId),
  };
}

/**
 * Track one outstanding canvas-sync request at a time.
 *
 * Two requests in flight would have the server send the whole history twice,
 * so a second ask while one is outstanding is coalesced into a single
 * follow-up. The timeout is what keeps that coalescing from becoming a trap:
 * without it a request the server never answers leaves the latch closed
 * forever, and every later ask - a failed commit hash, an undecodable frame,
 * the pending-mutation ceiling - is silently swallowed with it.
 *
 * `arrived` and `drainQueued` are deliberately separate. The follow-up has to
 * wait until the arriving history has been applied, or it would ask again
 * from the state it is about to replace.
 */
export function createCanvasSyncRequester(
  environment: CanvasSyncRequestEnvironment | (() => void),
  timeoutMs: number = CANVAS_SYNC_TIMEOUT_MS,
): CanvasSyncRequester {
  const env = typeof environment === "function"
    ? browserEnvironment(environment)
    : environment;

  let inFlight = false;
  let queued = false;
  let timeoutId: number | null = null;

  function stopWaiting(): void {
    if (timeoutId !== null) {
      env.clearTimeout(timeoutId);
      timeoutId = null;
    }
    inFlight = false;
  }

  function request(): void {
    if (inFlight) {
      queued = true;
      return;
    }
    inFlight = true;
    queued = false;
    timeoutId = env.setTimeout(() => {
      timeoutId = null;
      inFlight = false;
      // Something asked again while this request was outstanding, so the need
      // for a sync outlived the request that went unanswered. Anything else
      // waits for the next genuine trigger rather than polling a server that
      // may simply have no canvas to send.
      if (queued) {
        queued = false;
        request();
      }
    }, timeoutMs);
    env.requestSync();
  }

  return {
    request,
    arrived: stopWaiting,
    drainQueued(): void {
      if (!queued) return;
      queued = false;
      request();
    },
    reset(): void {
      stopWaiting();
      queued = false;
    },
  };
}
