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
  /**
   * The server refused this patch, and said why. The refused keys come along
   * so a caller that tracks confirmed values can revert just those.
   */
  onRejected(message: string, keys: (keyof EditableRoomSettings)[]): void;
  /** The server took this patch: these values are now the confirmed ones. */
  onConfirmed?(patch: RoomSettingsPatch): void;
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
 * Three things have to hold at once. Changes must coalesce, because a host
 * dragging a stepper produces a dozen of them and each one costs the server a
 * prompt-list read. Only one request may be in flight, because two overlapping
 * `update_room_settings` calls resolve their omitted fields against the room as
 * it was when each started, so the later reply can undo the earlier one. And a
 * change made while a request is outstanding must not be lost - it merges into
 * the next patch instead.
 *
 * A refusal and a dropped connection are handled differently on purpose. A
 * refusal means the value itself is wrong, so the patch is discarded and the
 * caller reverts. A transport failure says nothing about the value, so the
 * patch stays pending and goes out again on the next flush - the host's edit
 * survives a reconnect rather than silently vanishing.
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
  let inFlight = false;
  let timeoutId: number | null = null;
  let savedTimeoutId: number | null = null;
  let status: SaveStatus = "idle";
  // Bumped by reset, so a request that was already in flight cannot report
  // back into a form that has since been torn down or reloaded.
  let generation = 0;

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

  function send(): void {
    if (inFlight || !pending) return;
    const patch = pending;
    pending = null;
    disarm();
    inFlight = true;
    setStatus("saving");
    const sentAt = generation;
    void env.send(patch).then(
      (response) => {
        if (sentAt !== generation) return;
        inFlight = false;
        if (response.ok) {
          env.onConfirmed?.(patch);
          setStatus(pending ? "pending" : "saved");
        } else {
          env.onRejected(
            response.error || "Could not save room settings",
            Object.keys(patch) as (keyof EditableRoomSettings)[],
          );
          setStatus(pending ? "pending" : "idle");
        }
        send();
      },
      () => {
        if (sentAt !== generation) return;
        inFlight = false;
        // The value is fine; the connection was not. Keep it - anything the
        // host changed meanwhile wins, since it is the more recent intent.
        pending = { ...patch, ...(pending || {}) };
        setStatus("failed");
      },
    );
  }

  return {
    queue(patch: RoomSettingsPatch, delayMs: number = IMMEDIATE_SAVE_DELAY_MS): void {
      pending = { ...(pending || {}), ...patch };
      // A quick toggle must not be held back by a slower field's window, so
      // the shortest delay asked for while a patch is pending is the one used.
      pendingDelayMs = timeoutId === null ? delayMs : Math.min(pendingDelayMs, delayMs);
      setStatus(inFlight ? "saving" : "pending");
      if (inFlight) return;
      disarm();
      timeoutId = env.setTimeout(() => {
        timeoutId = null;
        send();
      }, pendingDelayMs);
    },
    flush(): void {
      disarm();
      send();
    },
    reset(): void {
      disarm();
      if (savedTimeoutId !== null) {
        env.clearTimeout(savedTimeoutId);
        savedTimeoutId = null;
      }
      pending = null;
      pendingDelayMs = IMMEDIATE_SAVE_DELAY_MS;
      inFlight = false;
      generation += 1;
      status = "idle";
    },
  };
}
