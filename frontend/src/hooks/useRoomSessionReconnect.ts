import { useEffect } from "react";
import { observeServerCanvasSequence, onSessionRebindRequested } from "../lib/canvasRecovery";
import {
  createHeartbeatSchedule,
  HEARTBEAT_MS,
  replyIsCurrent,
  shouldResyncOnReturn,
} from "../lib/heartbeatSchedule";
import { emitWithAck, restartExpected, socket, transportIsAlive } from "../lib/socket";
import { RESTART_PATIENCE_MS, afterFailedRebind, escalateHeartbeat, stallRecovery } from "../lib/reconnectPolicy";
import { setRoomBindingStatus } from "../lib/roomSessionBinding";
import { sessionFrom } from "../lib/roomEntryState";
import { useGameStore } from "../store/gameStore";
import { currentPlayerName } from "../store/authStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse } from "../types";
import { refusalCode, refusalText } from "../lib/refusals.ts";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { ui } from "../content/ui/index.ts";

/** How long a rebind waits for the socket. Longer when the server said it was
restarting (#872): a deploy is its drain plus a boot, and the ordinary 8 s
twice over showed the failed card before the replacement was listening. */
function connectPatienceMs(): number {
  return restartExpected() ? RESTART_PATIENCE_MS : 8000;
}

const STALL_GRACE_MS = 2500;
const STALL_CHECK_MS = 1000;
const HEARTBEAT_TIMEOUT_MS = 5000;
// The events that carry what a heartbeat would confirm (#564): each moves
// the local phase or round through the game store's own listeners.
const AUTHORITATIVE_EVENTS = ["turn_starting", "turn_started", "turn_ended", "sync_game", "room_state"] as const;
const ACTIVE_PHASES = new Set(["choosing_prompt", "drawing", "turn_results"]);
const PHASE_BY_CODE = ["idle", "choosing_prompt", "drawing", "turn_results", "game_end"] as const;

function waitForConnect(timeoutMs = connectPatienceMs()): Promise<void> {
  if (socket.connected) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      socket.off("connect", onConnect);
      reject(new Error("connect timeout"));
    }, timeoutMs);
    function onConnect() {
      window.clearTimeout(timer);
      resolve();
    }
    socket.once("connect", onConnect);
    socket.connect();
  });
}

/**
 * After a Socket.IO transport reconnect the client gets a new sid and is no
 * longer in any server room. Also recover from half-open sockets that look
 * connected but stop receiving phase/draw events (no disconnect banner).
 */
export function useRoomSessionReconnect() {
  useEffect(() => {
    let cancelled = false;
    let inFlight: Promise<void> | null = null;
    // How far a run of stall recoveries has escalated, and when the next may
    // go (#1009); reset once the phase is on time again.
    let stallEscalations = 0;
    let stallNotBefore = 0;
    let heartbeatInFlight = false;
    let consecutiveHeartbeatFailures = 0;
    // How far this run of missed probes has escalated, and when it may next
    // (#872): each escalation pushes the next one out.
    // When this tab was hidden, so a return knows how long it was away.
    let hiddenAt: number | null = null;
    let heartbeatEscalations = 0;
    let nextEscalationAt = 0;
    // Skips a probe when an authoritative event inside the last interval
    // already said what the probe would, forces one at the cap (#564).
    const schedule = createHeartbeatSchedule();
    let lastAuthoritativeAt: number | null = null;
    const onAuthoritative = () => {
      // After the store's listeners have applied the event: socket.io calls
      // listeners in order and the store's were registered first, but a
      // microtask makes the reading independent of that order.
      queueMicrotask(() => {
        const state = useGameStore.getState();
        const at = Date.now();
        lastAuthoritativeAt = at;
        schedule.noteAuthoritative({ phase: state.phase, round: state.roundNumber }, at);
      });
    };

    async function joinWithSession(soft = false) {
      const { roomId, code } = useGameStore.getState();
      if (!code) {
        setRoomBindingStatus("ready");
        return;
      }
      const nameColor = useSettingsStore.getState().nameColor;
      const colorblindSafeColors = useSettingsStore.getState().colorblindSafeColors;
      const response = await emitWithAck<AckResponse>("join_room", {
        code,
        roomId,
        nickname: currentPlayerName(),
        nameColor,
        colorblindSafeColors,
        soft,
      });
      if (cancelled) return;
      const session = sessionFrom(response);
      if (session) {
        useGameStore.getState().setSession(session);
        useServerNoticesStore.getState().set({ lostDuringDrain: false });
        setRoomBindingStatus("ready");
        return;
      }
      // Not a failure to retry: the room is gone - a server that restarted
      // takes its rooms with it - and asking again finds the same nothing. The
      // room says so and offers the lobby (#823), rather than a Reload that
      // cannot bring it back.
      const refused = refusalCode(response);
      if (refused === "room_not_found" || refused === "room_ended") {
        useServerNoticesStore.getState().markRoomEnded(code);
        setRoomBindingStatus("ready");
        return;
      }
      // Voted out while this tab was away (#1010): the seat is gone and the
      // room will not have this player back while it lives, so asking again
      // on every reconnect finds the same answer. Said on the stage, with
      // the lobby offered, like a room that ended.
      if (refused === "kicked_from_room") {
        useServerNoticesStore.getState().markKickedFromRoom(code);
        setRoomBindingStatus("ready");
        return;
      }
      throw new Error(refusalText(response, ui.useRoomSessionReconnect.joinRoomFailed));
    }

    async function rebindSession(
      options: { forceTransportRestart?: boolean; soft?: boolean; keepTransport?: boolean } = {},
    ) {
      const { forceTransportRestart = false, soft = false, keepTransport = false } = options;
      const { code } = useGameStore.getState();
      if (!code) {
        setRoomBindingStatus("ready");
        return;
      }

      setRoomBindingStatus("reconnecting");

      try {
        if (forceTransportRestart || !socket.connected) {
          if (socket.connected) socket.disconnect();
          await waitForConnect();
          if (cancelled) return;
        }
        await joinWithSession(soft);
      } catch {
        if (cancelled) return;
        // A heartbeat's soft rebind on a transport the server is still
        // keeping alive does not fall back to a restart: the server is slow,
        // not gone, and a teardown plus a full canvas is the most expensive
        // thing to ask of it (#872). The seat stays as it was and the next
        // backed-off escalation asks again - a restart only once the
        // transport has gone silent.
        if (afterFailedRebind({ keepTransport, transportAlive: transportIsAlive() }) === "keep") {
          setRoomBindingStatus("ready");
          return;
        }
        try {
          if (socket.connected) socket.disconnect();
          await waitForConnect();
          if (cancelled) return;
          await joinWithSession(false);
        } catch {
          if (!cancelled) setRoomBindingStatus("failed");
        }
      }
    }

    function queueRebind(
      options: { forceTransportRestart?: boolean; soft?: boolean; keepTransport?: boolean } = {},
    ) {
      if (inFlight) return;
      // A room the server already said is gone is not asked again: the answer
      // cannot change, and the heartbeat would otherwise keep asking (#823).
      const ended = useServerNoticesStore.getState().roomEnded;
      if (ended && ended.code === useGameStore.getState().code) return;
      inFlight = rebindSession(options).finally(() => {
        inFlight = null;
      });
    }

    function onConnect() {
      const { code } = useGameStore.getState();
      if (!code) {
        setRoomBindingStatus("ready");
        return;
      }
      queueRebind();
    }

    function onDisconnect() {
      const { code } = useGameStore.getState();
      if (code) setRoomBindingStatus("reconnecting");
    }

    function onVisibility() {
      if (document.visibilityState !== "visible") {
        hiddenAt = Date.now();
        return;
      }
      const wasHiddenAt = hiddenAt;
      hiddenAt = null;
      const { code, phase, roomState } = useGameStore.getState();
      if (!code) return;
      if (!ACTIVE_PHASES.has(phase) && roomState !== "playing") return;
      // Not on every return (#886): a hidden tab keeps its socket and keeps
      // receiving, so a short one with a phase event in it has nothing to
      // reconcile. It used to cost a `join_room` and a `sync_game` per seat
      // per alt-tab.
      if (
        wasHiddenAt !== null
        && socket.connected
        && !shouldResyncOnReturn({
          hiddenForMs: Date.now() - wasHiddenAt,
          heardWhileHidden: lastAuthoritativeAt !== null && lastAuthoritativeAt >= wasHiddenAt,
        })
      ) {
        return;
      }
      queueRebind({ soft: true });
    }

    function phaseIsStalled(): boolean {
      const state = useGameStore.getState();
      if (!state.playerId || !state.code) return false;
      if (!ACTIVE_PHASES.has(state.phase)) return false;
      if (!state.phaseSeconds || !state.phaseStartedAt) return false;
      const remainingMs = state.phaseSeconds * 1000 - (Date.now() - state.phaseStartedAt);
      return remainingMs <= -STALL_GRACE_MS;
    }

    function checkPhaseStall() {
      if (!phaseIsStalled()) {
        stallEscalations = 0;
        stallNotBefore = 0;
        return;
      }
      const next = stallRecovery({
        transportAlive: transportIsAlive(),
        restartApproved: useGameStore.getState().restartVote?.status === "approved",
        escalations: stallEscalations,
        notBefore: stallNotBefore,
        now: Date.now(),
        random: Math.random(),
      });
      stallEscalations = next.escalations;
      stallNotBefore = next.notBefore;
      if (next.action === "none") return;
      if (next.action === "soft") {
        queueRebind({ soft: true, keepTransport: true });
        return;
      }
      queueRebind({ forceTransportRestart: true });
    }

    async function runHeartbeat() {
      if (cancelled || heartbeatInFlight || inFlight) return;
      if (document.visibilityState === "hidden") return;
      const state = useGameStore.getState();
      if (!state.playerId || !state.code) return;
      if (!ACTIVE_PHASES.has(state.phase) && state.roomState !== "playing") return;
      if (!socket.connected) {
        queueRebind({ forceTransportRestart: true });
        return;
      }
      const sentAt = Date.now();
      if (!schedule.shouldProbe(sentAt, { phase: state.phase, round: state.roundNumber })) return;
      schedule.noteProbe(sentAt);
      // The probe's scope: a reply from another socket, room or seat, or one
      // older than a phase change that landed meanwhile, is not judged.
      const scope = { socketId: socket.id, code: state.code, playerId: state.playerId, sentAt };

      heartbeatInFlight = true;
      try {
        // Compact ack: [1, phaseCode, round, remaining, gen, seq] or [0]
        const response = await emitWithAck<number[]>(
          "session_ping",
          null,
          { timeoutMs: HEARTBEAT_TIMEOUT_MS },
        );
        if (cancelled) return;
        if (!Array.isArray(response) || response[0] !== 1) {
          consecutiveHeartbeatFailures += 1;
          if (consecutiveHeartbeatFailures >= 2) {
            queueRebind({ soft: true });
          }
          return;
        }

        consecutiveHeartbeatFailures = 0;
        heartbeatEscalations = 0;
        nextEscalationAt = 0;
        // The canvas protocol compares this with what it still holds pending
        // (#597); the two hooks share nothing else.
        observeServerCanvasSequence(response[4], response[5]);
        // Judged against the seat as it is *now*, not the snapshot the probe
        // left with: a turn can change while the answer is in flight, and an
        // old answer against an old snapshot would rebind a correct seat.
        const current = useGameStore.getState();
        const stillCurrent = replyIsCurrent(scope, {
          socketId: socket.id,
          code: current.code,
          playerId: current.playerId,
          lastAuthoritativeAt,
        });
        if (!stillCurrent) return;
        const serverPhase = PHASE_BY_CODE[response[1] ?? 0] ?? "idle";
        const serverRound = response[2] ?? 0;
        const localPhase = ACTIVE_PHASES.has(current.phase) ? current.phase : "idle";
        const phaseMismatch =
          ACTIVE_PHASES.has(localPhase)
          && ACTIVE_PHASES.has(serverPhase)
          && localPhase !== serverPhase;
        const roundMismatch =
          serverRound > 0
          && current.roundNumber > 0
          && serverRound !== current.roundNumber
          && ACTIVE_PHASES.has(localPhase);

        if (phaseMismatch || roundMismatch) {
          queueRebind({ soft: true });
        }
      } catch {
        if (cancelled) return;
        consecutiveHeartbeatFailures += 1;
        // A missed probe is a slow server at least as often as a dead
        // connection, and every seat misses together when the server is the
        // slow one - so tearing each transport down and asking for the whole
        // canvas was the most expensive answer at the worst moment (#872).
        // While Engine.IO's own pings still arrive, the connection is fine and
        // a soft rebind repairs the binding; only a silent one is restarted.
        // Either way the next escalation is pushed further out.
        const now = Date.now();
        const next = escalateHeartbeat({
          failures: consecutiveHeartbeatFailures,
          escalations: heartbeatEscalations,
          notBefore: nextEscalationAt,
          now,
          transportAlive: transportIsAlive(now),
          random: Math.random(),
        });
        if (next.action !== "none") {
          heartbeatEscalations = next.escalations;
          nextEscalationAt = next.notBefore;
          consecutiveHeartbeatFailures = 0;
          if (next.action === "restart") queueRebind({ forceTransportRestart: true });
          else queueRebind({ soft: true, keepTransport: true });
        }
      } finally {
        heartbeatInFlight = false;
      }
    }

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    for (const event of AUTHORITATIVE_EVENTS) socket.on(event, onAuthoritative);
    document.addEventListener("visibilitychange", onVisibility);
    // The canvas protocol exhausted its sync retries (#598): the seat binding
    // is suspect, and a transport restart is the one recovery that resets it.
    const stopRebindRequests = onSessionRebindRequested(() => {
      queueRebind({ forceTransportRestart: true });
    });
    const stallTimer = window.setInterval(checkPhaseStall, STALL_CHECK_MS);
    const heartbeatTimer = window.setInterval(() => {
      void runHeartbeat();
    }, HEARTBEAT_MS);
    if (socket.connected) onConnect();

    return () => {
      cancelled = true;
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      for (const event of AUTHORITATIVE_EVENTS) socket.off(event, onAuthoritative);
      document.removeEventListener("visibilitychange", onVisibility);
      stopRebindRequests();
      window.clearInterval(stallTimer);
      window.clearInterval(heartbeatTimer);
    };
  }, []);
}
