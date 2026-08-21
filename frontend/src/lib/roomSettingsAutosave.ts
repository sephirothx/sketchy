import type { AckResponse, EditableRoomSettings } from "../types";

export type RoomSettingsPatch = Partial<EditableRoomSettings>;

export type SaveStatus = "idle" | "pending" | "saving" | "saved" | "failed";

/**
 * How long a change waits before it is sent.
 *
 * A switch or a chip is one deliberate act, so it goes out on the next tick -
 * long enough to fold in a dependent field (scoring downgrading a hint mode,
 * say) and no longer, because a host who flips a switch and immediately starts
 * the game must not outrun their own change. A stepper waits a little, since
 * holding + produces a run of values on the way to one. Typing waits longest,
 * so a room name is not sent letter by letter.
 */
export const IMMEDIATE_SAVE_DELAY_MS = 0;
export const STEPPER_SAVE_DELAY_MS = 250;
export const TYPING_SAVE_DELAY_MS = 800;

/** How long "Saved" stays on screen before the status line goes quiet again. */
export const SAVED_STATUS_MS = 2_000;

export interface RoomSettingsSaverEnvironment {
  /** Send one patch and resolve with the server's acknowledgement. */
  send(patch: RoomSettingsPatch): Promise<AckResponse>;
  onStatus(status: SaveStatus): void;
  /** The server refused this patch, and said why. */
  onRejected(message: string): void;
  setTimeout(handler: () => void, delayMs: number): number;
  clearTimeout(timeoutId: number): void;
}

export interface RoomSettingsSaver {
  /** Record a change and schedule it. */
  queue(patch: RoomSettingsPatch, delayMs?: number): void;
  /** Send whatever is pending right now, without waiting out the timer. */
  flush(): void;
  /** Drop anything pending and stop the timers (teardown). */
  reset(): void;
}

function browserEnvironment(
  partial: Omit<RoomSettingsSaverEnvironment, "setTimeout" | "clearTimeout">,
): RoomSettingsSaverEnvironment {
  return {
    ...partial,
    setTimeout: (handler, delayMs) => window.setTimeout(handler, delayMs),
    clearTimeout: (timeoutId) => window.clearTimeout(timeoutId),
  };
}

/**
 * Turn a stream of setting changes into a well-behaved stream of saves.
 *
 * Changes coalesce, because a host working a stepper produces a dozen of them
 * and each one is a request. What they do not do is queue behind one another:
 * `flush` has to put everything the host has changed on the socket there and
 * then, because the press that triggers it is very often the press that starts
 * the game, and a patch waiting on an earlier reply would arrive after it. The
 * server applies patches in the order it receives them - the room is locked
 * across each one - so several in the air at once is safe.
 *
 * A refusal and a dropped connection are handled differently on purpose. A
 * refusal means the value itself is wrong, so the patch is discarded and the
 * caller told - it has to go and find out what the room actually holds. A
 * transport failure says nothing about the value, so the patch is kept and
 * goes out again on the next flush: the host's edit survives a reconnect
 * rather than silently vanishing. A kept patch remembers when it was sent, so
 * that a retry cannot put an old value back over a newer one that got through.
 */
export function createRoomSettingsSaver(
  environment:
    | RoomSettingsSaverEnvironment
    | Omit<RoomSettingsSaverEnvironment, "setTimeout" | "clearTimeout">,
): RoomSettingsSaver {
  const env: RoomSettingsSaverEnvironment =
    "setTimeout" in environment ? environment : browserEnvironment(environment);

  let pending: RoomSettingsPatch | null = null;
  let pendingDelayMs = IMMEDIATE_SAVE_DELAY_MS;
  let outstanding = 0;
  let timeoutId: number | null = null;
  let savedTimeoutId: number | null = null;
  let status: SaveStatus = "idle";
  // Bumped by reset, so a request that was already in flight cannot report
  // back into a form that has since been torn down or reloaded.
  let generation = 0;
  let nextSequence = 1;
  // Patches the transport lost, by the sequence they were sent in.
  const unsent = new Map<number, RoomSettingsPatch>();
  // The newest request each field went out in. A lost patch only keeps the
  // fields nothing newer has been sent for: the rest the host has already
  // changed their mind about, and retrying those would put an old value back
  // over a newer one.
  const latestSend = new Map<string, number>();

  function setStatus(next: SaveStatus): void {
    if (savedTimeoutId !== null) {
      env.clearTimeout(savedTimeoutId);
      savedTimeoutId = null;
    }
    if (next === "saved") {
      savedTimeoutId = env.setTimeout(() => {
        savedTimeoutId = null;
        // Anything queued since means the line has already moved on.
        if (status === "saved") setStatus("idle");
      }, SAVED_STATUS_MS);
    }
    if (status === next) return;
    status = next;
    env.onStatus(next);
  }

  function disarm(): void {
    if (timeoutId === null) return;
    env.clearTimeout(timeoutId);
    timeoutId = null;
  }

  /**
   * Everything owed to the server, oldest value first so the newest wins.
   *
   * A change still waiting out its delay is only taken when the caller is the
   * delay itself, or a flush. A reply arriving for some earlier change is
   * neither: sweeping the pending patch up with it would put a half-typed room
   * name on the wire for every acknowledgement that happened to land.
   */
  function collect(takePending: boolean): RoomSettingsPatch | null {
    const owed = takePending && pending;
    if (unsent.size === 0 && !owed) return null;
    const patch: RoomSettingsPatch = {};
    for (const [, lost] of [...unsent.entries()].sort(([a], [b]) => a - b)) {
      for (const [field, value] of Object.entries(lost)) {
        // A change still waiting out its delay is the newer intent even though
        // it has not been sent yet, so a lost value underneath it is not worth
        // recovering: putting it back would show everyone the old setting for
        // as long as the delay has left to run.
        if (pending && field in pending) continue;
        Object.assign(patch, { [field]: value });
      }
    }
    unsent.clear();
    if (owed) {
      Object.assign(patch, pending);
      pending = null;
    }
    return Object.keys(patch).length > 0 ? patch : null;
  }

  function settled(): SaveStatus {
    if (pending) return "pending";
    if (unsent.size > 0) return "failed";
    return outstanding > 0 ? "saving" : "saved";
  }

  function send(takePending: boolean): void {
    const patch = collect(takePending);
    if (!patch) return;
    if (takePending) disarm();
    const sequence = nextSequence++;
    for (const field of Object.keys(patch)) latestSend.set(field, sequence);
    outstanding += 1;
    setStatus("saving");
    const sentAt = generation;
    void env.send(patch).then(
      (response) => {
        if (sentAt !== generation) return;
        outstanding -= 1;
        if (!response.ok) env.onRejected(response.error || "Could not save room settings");
        setStatus(response.ok ? settled() : (pending ? "pending" : "idle"));
        // A reply that got through says the connection is working, so anything
        // the transport lost can go out again now. Nothing else does.
        send(false);
      },
      () => {
        if (sentAt !== generation) return;
        outstanding -= 1;
        // The values are fine; the connection was not. Keep the ones this was
        // still the newest word on - the others have been said again since.
        const stillCurrent = Object.fromEntries(
          Object.entries(patch).filter(([field]) => latestSend.get(field) === sequence),
        );
        if (Object.keys(stillCurrent).length > 0) unsent.set(sequence, stillCurrent);
        setStatus(unsent.size > 0 ? "failed" : settled());
      },
    );
  }

  return {
    queue(patch: RoomSettingsPatch, delayMs: number = IMMEDIATE_SAVE_DELAY_MS): void {
      pending = { ...(pending || {}), ...patch };
      // A quick toggle must not be held back by a slower field's window, so
      // the shortest delay asked for while a patch is pending is the one used.
      pendingDelayMs = timeoutId === null ? delayMs : Math.min(pendingDelayMs, delayMs);
      setStatus("pending");
      disarm();
      timeoutId = env.setTimeout(() => {
        timeoutId = null;
        send(true);
      }, pendingDelayMs);
    },
    flush(): void {
      disarm();
      send(true);
    },
    reset(): void {
      disarm();
      if (savedTimeoutId !== null) {
        env.clearTimeout(savedTimeoutId);
        savedTimeoutId = null;
      }
      pending = null;
      unsent.clear();
      latestSend.clear();
      pendingDelayMs = IMMEDIATE_SAVE_DELAY_MS;
      outstanding = 0;
      generation += 1;
      status = "idle";
    },
  };
}
