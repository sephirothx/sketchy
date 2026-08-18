import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, RoomPreviewResponse } from "../types";

export function useRoomEntry(code: string) {
  const nickname = useGameStore((state) => state.nickname);
  const setNickname = useGameStore((state) => state.setNickname);
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const machineRef = useRef<RoomEntryMachine | null>(null);
  const [snapshot, setSnapshot] = useState<RoomEntrySnapshot>({
    state: { status: "loading" },
    nicknameInput: nickname,
  });

  useEffect(() => {
    const machine = new RoomEntryMachine(code, nickname, {
      reconnect: ({ code: roomCode, nickname: playerNickname }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
          nameColor,
          // Ask only whether this account already holds a seat. Without this
          // the server would seat the visitor before they had chosen between
          // playing and spectating.
          resumeOnly: true,
        }),
      preview: (roomCode) =>
        emitWithAck<RoomPreviewResponse>("get_room_preview", { code: roomCode }),
      join: ({ code: roomCode, nickname: playerNickname, mode }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
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
  }, [code, nameColor, nickname, setNickname, setSession]);

  function setNicknameInput(value: string) {
    machineRef.current?.setNicknameInput(value);
  }

  function join(mode: RoomJoinMode) {
    return machineRef.current?.join(mode) ?? Promise.resolve();
  }

  return { ...snapshot, setNicknameInput, join };
}
