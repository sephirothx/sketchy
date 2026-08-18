import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { resolvedPlayName } from "../lib/guestNickname";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, RoomPreviewResponse } from "../types";

export function useRoomEntry(code: string) {
  const nickname = useGameStore((state) => state.nickname);
  const setNickname = useGameStore((state) => state.setNickname);
  const setSession = useGameStore((state) => state.setSession);
  const hasActiveRoomSession = useGameStore((state) => state.hasActiveRoomSession);
  const clearSession = useGameStore((state) => state.clearSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const user = useAuthStore((state) => state.user);
  const isRegistered = Boolean(user && !user.isAnonymous);
  const joinNickname = resolvedPlayName(nickname, user);
  const machineRef = useRef<RoomEntryMachine | null>(null);
  const [snapshot, setSnapshot] = useState<RoomEntrySnapshot>({
    state: { status: "loading" },
    nicknameInput: joinNickname,
  });

  useEffect(() => {
    const machine = new RoomEntryMachine(code, joinNickname, {
      hasActiveRoomSession,
      clearSession,
      reconnect: ({ code: roomCode, nickname: playerNickname }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
          nameColor: isRegistered ? nameColor : undefined,
          reconnectOnly: true,
        }),
      preview: (roomCode) =>
        emitWithAck<RoomPreviewResponse>("get_room_preview", { code: roomCode }),
      join: ({ code: roomCode, nickname: playerNickname, mode }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
          nameColor: isRegistered ? nameColor : undefined,
          asSpectator: mode === "spectator",
        }),
      saveNickname: setNickname,
      acceptSession: setSession,
      requestErrorMessage: socketRequestErrorMessage,
    });
    machineRef.current = machine;
    const unsubscribe = machine.subscribe(setSnapshot);
    void machine.load();
    return () => {
      unsubscribe();
      machine.dispose();
      if (machineRef.current === machine) machineRef.current = null;
    };
  }, [clearSession, code, hasActiveRoomSession, isRegistered, joinNickname, nameColor, setNickname, setSession]);

  function setNicknameInput(value: string) {
    machineRef.current?.setNicknameInput(value);
  }

  function join(mode: RoomJoinMode) {
    return machineRef.current?.join(mode) ?? Promise.resolve();
  }

  return { ...snapshot, setNicknameInput, join, isRegistered };
}
