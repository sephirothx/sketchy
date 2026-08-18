import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useAuthStore } from "../store/authStore";
import type { AckResponse, RoomPreviewResponse } from "../types";

export function useRoomEntry(code: string) {
  const user = useAuthStore((state) => state.user);
  const isRegistered = Boolean(user && !user.isAnonymous);
  const storedNickname = useGameStore((state) => state.nickname);
  const effectiveInitialNickname = isRegistered ? (user?.username || "Player") : storedNickname;
  const setNickname = useGameStore((state) => state.setNickname);
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const machineRef = useRef<RoomEntryMachine | null>(null);
  const [snapshot, setSnapshot] = useState<RoomEntrySnapshot>({
    state: { status: "loading" },
    nicknameInput: effectiveInitialNickname,
  });

  useEffect(() => {
    const machine = new RoomEntryMachine(code, effectiveInitialNickname, {
      preview: (roomCode) =>
        emitWithAck<RoomPreviewResponse>("get_room_preview", { code: roomCode }),
      join: ({ code: roomCode, nickname: playerNickname, mode }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: isRegistered ? (user?.username || playerNickname) : playerNickname,
          nameColor,
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
  }, [code, effectiveInitialNickname, isRegistered, nameColor, setNickname, setSession, user?.username]);

  function setNicknameInput(value: string) {
    machineRef.current?.setNicknameInput(value);
  }

  function join(mode: RoomJoinMode) {
    return machineRef.current?.join(mode) ?? Promise.resolve();
  }

  return { ...snapshot, setNicknameInput, join, isRegistered, username: user?.username };
}
