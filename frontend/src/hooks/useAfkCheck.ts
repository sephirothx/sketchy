import { useCallback, useEffect, useRef, useState } from "react";

import {
  COUNTDOWN_TICK_MS,
  INPUT_EVENTS,
  hasLapsed,
  parseAfkCheck,
  respondToCheck,
  secondsLeft,
} from "../lib/afkCheck";
import { emitTransient, socket } from "../lib/socket";
import { useClientConfig } from "./useClientConfig";

/** The room asking whether anybody is still there, and this client answering.

The listener is armed for the whole time a seat is held rather than only
during a game: the waiting room is where an absent host holds a room nobody
can start, and that is half of what the check is for.

Input is tracked in a ref rather than in state on purpose. It changes on every
pointer move, and a state write per move would re-render the room several
hundred times a minute to hold a number nothing renders. The listeners are
passive and attached once, for the same reason.

The answer is `toggle_afk {afk: false}` — the command that already means "I am
not AFK", so the check adds no inbound name to the wire. Sent **transiently**,
which R-CONN-06 requires of toggling AFK by name: an ordinary emit is buffered
while the socket is down and delivered on reconnect, so an answer racing a
disconnect would arrive into a seat that had since been marked AFK — by the
deadline it outlived, or by the player themselves — and silently undo it. A
dropped answer costs nothing: the next sweep asks again. */
export interface AfkCheckState {
  /** Seconds left, or `null` when nothing is being asked. */
  secondsLeft: number | null;
  /** Answer now — the dialog's button, and any input while it is open. */
  answer: () => void;
}

export function useAfkCheck(active: boolean): AfkCheckState {
  const { afkInputWindowMs } = useClientConfig();
  const [deadline, setDeadline] = useState<number | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const lastInputAt = useRef<number | null>(null);
  // Read by the socket handler, which is registered once and must not close
  // over a stale window when the server ships a new one. Kept in a ref rather
  // than in the handler's dependencies so that a cadence change does not tear
  // down and re-arm the listener mid-check.
  const inputWindow = useRef(afkInputWindowMs);
  useEffect(() => {
    inputWindow.current = afkInputWindowMs;
  }, [afkInputWindowMs]);

  const answer = useCallback(() => {
    setDeadline(null);
    setRemaining(null);
    emitTransient("toggle_afk", { afk: false });
  }, []);

  // Every pointer or key, whether or not a check is open: the answer depends
  // on input the client saw *before* the question arrived, so the recording
  // cannot start when the question does.
  useEffect(() => {
    if (!active) return;
    const note = () => {
      lastInputAt.current = Date.now();
    };
    for (const event of INPUT_EVENTS) {
      window.addEventListener(event, note, { passive: true });
    }
    return () => {
      for (const event of INPUT_EVENTS) window.removeEventListener(event, note);
    };
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const onCheck = (payload: unknown) => {
      const request = parseAfkCheck(payload);
      if (!request) return;
      const response = respondToCheck(request, {
        now: Date.now(),
        lastInputAt: lastInputAt.current,
        inputWindowMs: inputWindow.current,
      });
      if (response.kind === "answer") {
        // Somebody is here. Answered without a word to them, which is the
        // whole point: the cost of the check must not land on the people it
        // is not for.
        emitTransient("toggle_afk", { afk: false });
        return;
      }
      setDeadline(response.deadline);
      setRemaining(secondsLeft(response.deadline, Date.now()));
    };
    socket.on("afk_check", onCheck);
    // A check belongs to the connection it was asked down. A reconnect is
    // itself something a person did, and the server's ledger starts fresh for
    // the new socket, so a countdown from the old one has nothing to resolve.
    const onDisconnect = () => {
      setDeadline(null);
      setRemaining(null);
    };
    socket.on("disconnect", onDisconnect);
    return () => {
      socket.off("afk_check", onCheck);
      socket.off("disconnect", onDisconnect);
    };
  }, [active]);

  // While a check is open, any input answers it. Attached only then, so the
  // ordinary case is the passive recorder above and nothing else.
  useEffect(() => {
    if (deadline === null) return;
    const onInput = () => {
      lastInputAt.current = Date.now();
      answer();
    };
    for (const event of INPUT_EVENTS) {
      window.addEventListener(event, onInput, { passive: true });
    }
    return () => {
      for (const event of INPUT_EVENTS) {
        window.removeEventListener(event, onInput);
      }
    };
  }, [deadline, answer]);

  useEffect(() => {
    if (deadline === null) return;
    const tick = window.setInterval(() => {
      const now = Date.now();
      setRemaining(secondsLeft(deadline, now));
      // The server owns the flag and says so through `room_state`; this only
      // stops counting what has nothing left to count.
      if (hasLapsed(deadline, now)) {
        setDeadline(null);
        setRemaining(null);
      }
    }, COUNTDOWN_TICK_MS);
    return () => window.clearInterval(tick);
  }, [deadline]);

  return { secondsLeft: remaining, answer };
}
