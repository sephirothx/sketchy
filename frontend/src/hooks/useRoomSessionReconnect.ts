import { useEffect } from "react";
import { emitWithAck, socket } from "../lib/socket";
import { setRoomBindingStatus } from "../lib/roomSessionBinding";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse } from "../types";

const STALL_GRACE_MS = 2500;
const STALL_CHECK_MS = 1000;
const HEARTBEAT_MS = 5000;
const HEARTBEAT_TIMEOUT_MS = 5000;
const ACTIVE_PHASES = new Set(["choosing_word", "drawing", "round_end"]);
const PHASE_BY_CODE = ["idle", "choosing_word", "drawing", "round_end", "game_end"] as const;

function waitForConnect(timeoutMs = 8000): Promise<void> {
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
    let lastStallRecoveryAt = 0;
    let heartbeatInFlight = false;
    let consecutiveHeartbeatFailures = 0;

    async function joinWithSession(soft = false) {
      const { roomId, code, nickname, playerId } = useGameStore.getState();
      if (!playerId || !code) {
        setRoomBindingStatus("ready");
        return;
      }
      const nameColor = useSettingsStore.getState().nameColor;
      const response = await emitWithAck<AckResponse>("join_room", {
        code,
        roomId,
        nickname,
        nameColor,
        soft,
      });
      if (cancelled) return;
      if (
        response.ok
        && response.roomId
        && response.code
        && response.playerId
      ) {
        useGameStore.getState().setSession({
          roomId: response.roomId,
          code: response.code,
          playerId: response.playerId,
        });
        setRoomBindingStatus("ready");
        return;
      }
      throw new Error(response.error || "join_room failed");
    }

    async function rebindSession(
      options: { forceTransportRestart?: boolean; soft?: boolean } = {},
    ) {
      const { forceTransportRestart = false, soft = false } = options;
      const { playerId, code } = useGameStore.getState();
      if (!playerId || !code) {
        setRoomBindingStatus("ready");
        return;
      }

      setRoomBindingStatus("rejoining");

      try {
        if (forceTransportRestart || !socket.connected) {
          if (socket.connected) socket.disconnect();
          await waitForConnect();
          if (cancelled) return;
        }
        await joinWithSession(soft);
      } catch {
        if (cancelled) return;
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
      options: { forceTransportRestart?: boolean; soft?: boolean } = {},
    ) {
      if (inFlight) return;
      inFlight = rebindSession(options).finally(() => {
        inFlight = null;
      });
    }

    function onConnect() {
      const { playerId, code } = useGameStore.getState();
      if (!playerId || !code) {
        setRoomBindingStatus("ready");
        return;
      }
      queueRebind();
    }

    function onDisconnect() {
      const { playerId, code } = useGameStore.getState();
      if (playerId && code) setRoomBindingStatus("rejoining");
    }

    function onVisibility() {
      if (document.visibilityState !== "visible") return;
      const { playerId, code, phase, roomState } = useGameStore.getState();
      if (!playerId || !code) return;
      if (!ACTIVE_PHASES.has(phase) && roomState !== "playing") return;
      queueRebind({ soft: true });
    }

    function checkPhaseStall() {
      const state = useGameStore.getState();
      if (!state.playerId || !state.code) return;
      if (!ACTIVE_PHASES.has(state.phase)) return;
      if (!state.phaseSeconds || !state.phaseStartedAt) return;
      const remainingMs = state.phaseSeconds * 1000 - (Date.now() - state.phaseStartedAt);
      if (remainingMs > -STALL_GRACE_MS) return;
      if (Date.now() - lastStallRecoveryAt < 10_000) return;
      lastStallRecoveryAt = Date.now();
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
        const serverPhase = PHASE_BY_CODE[response[1] ?? 0] ?? "idle";
        const serverRound = response[2] ?? 0;
        const localPhase = ACTIVE_PHASES.has(state.phase) ? state.phase : "idle";
        const phaseMismatch =
          ACTIVE_PHASES.has(localPhase)
          && ACTIVE_PHASES.has(serverPhase)
          && localPhase !== serverPhase;
        const roundMismatch =
          serverRound > 0
          && state.roundNumber > 0
          && serverRound !== state.roundNumber
          && ACTIVE_PHASES.has(localPhase);

        if (phaseMismatch || roundMismatch) {
          queueRebind({ soft: true });
        }
      } catch {
        if (cancelled) return;
        consecutiveHeartbeatFailures += 1;
        // Only escalate after repeated failures so a busy canvas under throttle
        // does not hard-reconnect (and re-dump history) on every missed ping.
        if (consecutiveHeartbeatFailures >= 3) {
          queueRebind({ forceTransportRestart: true });
          consecutiveHeartbeatFailures = 0;
        }
      } finally {
        heartbeatInFlight = false;
      }
    }

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    document.addEventListener("visibilitychange", onVisibility);
    const stallTimer = window.setInterval(checkPhaseStall, STALL_CHECK_MS);
    const heartbeatTimer = window.setInterval(() => {
      void runHeartbeat();
    }, HEARTBEAT_MS);
    if (socket.connected) onConnect();

    return () => {
      cancelled = true;
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(stallTimer);
      window.clearInterval(heartbeatTimer);
    };
  }, []);
}
