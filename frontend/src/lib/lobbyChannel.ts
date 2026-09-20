/** How long to wait before asking for the lobby baseline again.

`watch_lobby` is now the *only* way a lobby is told anything. The poll it
replaced retried by construction — a failed fetch was followed four seconds
later by another — so nothing had to be written down. A subscription has no
such second chance: one refused or timed-out acknowledgement on an otherwise
healthy socket leaves the lobby on its loading state for the life of that
connection, because a quiet server sends no delta either and there is nothing
to notice the gap.

Doubling from a second, capped at half a minute. The cap is the point: a
server refusing every subscription still hears from each open lobby, so the
interval has to stop growing somewhere a recovery is noticed promptly, and it
must not shrink to a retry loop that is itself the outage. */
export const FIRST_RETRY_MS = 1000;
export const MAX_RETRY_MS = 30_000;

export function resubscribeDelayMs(attempt: number): number {
  // Total on purpose. The caller only ever passes its own counter, but a
  // schedule that can answer `NaN` is a `setTimeout` that fires immediately
  // and for ever - the one failure mode a backoff exists to prevent.
  if (!Number.isFinite(attempt) || attempt < 1) return FIRST_RETRY_MS;
  return Math.min(FIRST_RETRY_MS * 2 ** (attempt - 1), MAX_RETRY_MS);
}

/** Deltas that arrive before the baseline they apply to (#600).

The server joins the channel first and reads its baselines last, so a delta
sent during its lookups arrives before the acknowledgement, and is never newer
than the baselines in it. This is the client's half of that guarantee: a delta
that arrives while the acknowledgement is pending is held, and once the
baseline lands every held delta newer than it is applied, in order. A delta
at or below the baseline's revision is already inside it and is dropped.

Bounded. A lobby that cannot get its acknowledgement while the room list
churns would otherwise hold deltas for ever; past the cap the buffer is
emptied and the caller asks for a fresh baseline instead, since what it
holds no longer joins onto anything. */
export const MAX_HELD_DELTAS = 64;

export type LobbyFeed = "presence" | "rooms" | "chat";

export interface HeldDelta {
  feed: LobbyFeed;
  /** `revision` for the two state feeds, `seq` for chat. */
  at: number;
  payload: unknown;
}

export interface BaselineRevisions {
  presence: number;
  rooms: number;
  chatSeq: number;
}

export interface PendingDeltas {
  /** Keep a delta for after the baseline. Returns false once the buffer
  overflowed: the caller should ask for a fresh baseline and start over. */
  hold(feed: LobbyFeed, payload: unknown): boolean;
  /** The held deltas newer than the baseline, oldest first, and empty the buffer. */
  drain(baseline: BaselineRevisions): HeldDelta[];
  /** Forget everything (a new connection, a teardown). */
  clear(): void;
  readonly size: number;
}

function sequenceOf(feed: LobbyFeed, payload: unknown): number | null {
  if (!payload || typeof payload !== "object") return null;
  const value = (payload as Record<string, unknown>)[feed === "chat" ? "seq" : "revision"];
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function createPendingDeltas(limit: number = MAX_HELD_DELTAS): PendingDeltas {
  let held: HeldDelta[] = [];
  let overflowed = false;
  return {
    hold(feed, payload) {
      if (overflowed) return false;
      const at = sequenceOf(feed, payload);
      if (at === null) return true; // not a delta this feed can place; nothing to keep
      held.push({ feed, at, payload });
      if (held.length > limit) {
        held = [];
        overflowed = true;
        return false;
      }
      return true;
    },
    drain(baseline) {
      const floor: Record<LobbyFeed, number> = {
        presence: baseline.presence,
        rooms: baseline.rooms,
        chat: baseline.chatSeq,
      };
      const newer = held
        .filter((delta) => delta.at > floor[delta.feed])
        .sort((a, b) => a.at - b.at);
      held = [];
      overflowed = false;
      return newer;
    },
    clear() {
      held = [];
      overflowed = false;
    },
    get size() {
      return held.length;
    },
  };
}


/** How long a lobby tab may sit hidden before it leaves the channel (#886).

A hidden tab was still a watcher: it took every presence tick, every room
change and every chat line for as long as it stayed open, which on a desktop
is most of the day. Long enough that an alt-tab costs nothing, short enough
that a tab left in the background is not a subscription. Coming back
re-subscribes, and the acknowledgement is the whole baseline again - cheap
since #885, which sends only the chat the tab does not already hold. */
export const LOBBY_HIDDEN_GRACE_MS = 30_000;

export interface HiddenWatch {
  /** The tab's visibility moved. */
  noteVisibility(hidden: boolean): void;
  /** Stop watching (the lobby unmounted). */
  stop(): void;
  /** Whether this tab is still a watcher. */
  readonly watching: boolean;
}

/** Leave the channel after the grace, and rejoin on return (#886).

A state machine rather than three flags in the hook: hidden, shown again
before the grace is up, shown again after it, and unmounted in any of those.
Timers are passed in, so this is testable without a tab to hide. */
export function createHiddenWatch(options: {
  graceMs?: number;
  leave: () => void;
  rejoin: () => void;
  setTimeout: (handler: () => void, delayMs: number) => number;
  clearTimeout: (id: number) => void;
}): HiddenWatch {
  const grace = options.graceMs ?? LOBBY_HIDDEN_GRACE_MS;
  let timer: number | null = null;
  let watching = true;
  const stopTimer = () => {
    if (timer === null) return;
    options.clearTimeout(timer);
    timer = null;
  };
  return {
    noteVisibility(hidden) {
      if (hidden) {
        if (!watching || timer !== null) return;
        timer = options.setTimeout(() => {
          timer = null;
          watching = false;
          options.leave();
        }, grace);
        return;
      }
      stopTimer();
      if (watching) return;
      watching = true;
      options.rejoin();
    },
    stop() {
      stopTimer();
    },
    get watching() {
      return watching;
    },
  };
}
