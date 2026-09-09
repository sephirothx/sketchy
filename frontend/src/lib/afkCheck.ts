/** Answering the room's question about whether anybody is still there (#677).

The server marks a seat AFK after it has sent nothing a person sent for the
inactivity window, so that a room stops waiting on somebody who left and stops
spending a turn a rotation on their blank canvas. The trouble with measuring
that on the server alone is that watching a drawing *is* playing: a guesser can
follow three turns without typing a word, and every command they might have
sent is one they had no reason to send.

So the server asks rather than assumes. `afk_check` is a question, and this is
the part that answers it:

* if this client has seen a pointer or a key inside `afkInputWindowMs`, it
  answers immediately and says nothing to the player. Somebody is there, and
  interrupting them to prove it would be the whole cost of the feature landing
  on the people it is not for;
* otherwise it shows the **AFK check** — a countdown the player dismisses —
  and answers if they touch anything before it runs out.

Two things this deliberately is not. It is not a periodic report: nothing is
sent until the server asks, so a client that is being used costs exactly one
event per idle window rather than a heartbeat for ever. And it is not a
visibility check — a hidden tab is not an absent player, and this never looks
at `document.visibilityState`. A hidden tab is marked in the end because it
cannot answer, which is the inactivity rule reaching it rather than a rule
about hiding.

Pure: time and the last input are passed in, and the hook owns the timer and
the listeners. */

/** Events that count as a person being at the controls.

Deliberately not `mousemove` alone: a laptop trackpad reports movement from a
resting palm, and a browser fires pointer events for programmatic scrolling.
These are all things somebody did. */
export const INPUT_EVENTS = [
  "pointerdown",
  "pointermove",
  "keydown",
  "wheel",
  "touchstart",
] as const;

/** How often the countdown re-renders. The player is reading a number of
seconds, so anything finer is work nobody can see. */
export const COUNTDOWN_TICK_MS = 250;

export interface AfkCheckRequest {
  /** How long the server will hold the check open, in seconds. */
  seconds: number;
}

/** What to do about a check that just arrived. */
export type AfkCheckResponse =
  | { kind: "answer" }
  | { kind: "ask"; deadline: number };

/** Read an `afk_check` payload, or `null` if it is not one.

A malformed payload is ignored rather than defaulted: the check is the server's
question, and answering a question that was not asked would clear a countdown
that is not running. */
export function parseAfkCheck(payload: unknown): AfkCheckRequest | null {
  if (typeof payload !== "object" || payload === null) return null;
  const seconds = (payload as Record<string, unknown>).seconds;
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  return { seconds };
}

/** Answer for the player, or ask them.

`lastInputAt` is `null` when this client has seen no input at all since it
loaded — a tab opened and left, which is exactly the case the check is for. */
export function respondToCheck(
  request: AfkCheckRequest,
  options: { now: number; lastInputAt: number | null; inputWindowMs: number },
): AfkCheckResponse {
  const { now, lastInputAt, inputWindowMs } = options;
  if (lastInputAt !== null && now - lastInputAt <= inputWindowMs) {
    return { kind: "answer" };
  }
  return { kind: "ask", deadline: now + request.seconds * 1000 };
}

/** Whole seconds left on an open check, floored at zero.

Rounded up, so a countdown started at 25.0 s reads "25" rather than flicking
to "24" before a frame has passed, and reaches "0" only when the time really
is gone. */
export function secondsLeft(deadline: number, now: number): number {
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

/** Whether an open check has run out.

The client never marks itself AFK on this — the server owns the flag and will
say so through `room_state`. This only decides when to stop showing a
countdown that has nothing left to count. */
export function hasLapsed(deadline: number, now: number): boolean {
  return now >= deadline;
}
