import { useEffect } from "react";
import { emitWithAck, socket, waitForConnect } from "../lib/socket";
import { setRoomBindingStatus } from "../lib/roomSessionBinding";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useAuthStore } from "../store/authStore";
import type { AckResponse } from "../types";

const STALL_GRACE_MS = 2500;
const STALL_CHECK_MS = 1000;
const HEARTBEAT_MS = 5000;
const HEARTBEAT_TIMEOUT_MS = 5000;
const ACTIVE_PHASES = new Set(["choosing_word", "drawing", "round_end"]);
const PHASE_BY_CODE = ["idle", "choosing_word", "drawing", "round_end", "game_end"] as const;

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
    let hardRebindAfterDisconnect = false;

    async function joinWithSession(soft = false) {
      const state = useGameStore.getState();
      const { playerId, roomId, code, nickname, players } = state;
      if (!playerId || !code) {
        setRoomBindingStatus("ready");
        return;
      }
      const isGuest = Boolean(useAuthStore.getState().user?.isAnonymous ?? true);
      const nameColor = isGuest ? undefined : useSettingsStore.getState().nameColor;
      const reconnectNickname =
        nickname.trim()
        || players.find((player) => player.playerId === playerId)?.nickname
        || "Player";
      const response = await emitWithAck<AckResponse>("join_room", {
        code,
        roomId,
        nickname: reconnectNickname,
        nameColor,
        reconnectOnly: true,
        soft,
      });
      if (cancelled) return;
      if (response.ok && response.roomId && response.code && response.playerId) {
        useGameStore.getState().setSession({
          roomId: response.roomId,
          code: response.code,
          playerId: response.playerId,
        });
        setRoomBindingStatus("ready");
        return;
      }
      if (response.sessionExpired) {
        useGameStore.getState().clearSession();
        useGameStore.getState().reset();
        setRoomBindingStatus("failed");
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
      const forceTransportRestart = hardRebindAfterDisconnect;
      hardRebindAfterDisconnect = false;
      queueRebind({ forceTransportRestart });
    }

    function onDisconnect() {
      const { playerId, code } = useGameStore.getState();
      if (playerId && code) {
        hardRebindAfterDisconnect = true;
        setRoomBindingStatus("rejoining");
      }
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

    function onBrowserOffline() {
      if (socket.connected) socket.disconnect();
    }

    function onBrowserOnline() {
      void waitForConnect();
    }

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("offline", onBrowserOffline);
    window.addEventListener("online", onBrowserOnline);
    const stallTimer = window.setInterval(checkPhaseStall, STALL_CHECK_MS);
    const heartbeatTimer = window.setInterval(() => {
      void runHeartbeat();
    }, HEARTBEAT_MS);
    if (socket.connected) onConnect();
    if (typeof navigator !== "undefined" && !navigator.onLine && socket.connected) {
      socket.disconnect();
    }

    return () => {
      cancelled = true;
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("offline", onBrowserOffline);
      window.removeEventListener("online", onBrowserOnline);
      window.clearInterval(stallTimer);
      window.clearInterval(heartbeatTimer);
    };
  }, []);
}
