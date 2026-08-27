import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { useAuthStore } from "../store/authStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, RoomPreviewResponse } from "../types";

export function useRoomEntry(code: string) {
  const nickname = useAuthStore((state) => state.user?.displayName ?? "");
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const colorblindSafeColors = useSettingsStore((state) => state.colorblindSafeColors);
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
          colorblindSafeColors,
          // Ask only whether this account already holds a seat. Without this
          // the server would seat the visitor before they had chosen between
          // playing and spectating.
          reconnectOnly: true,
        }),
      preview: (roomCode) =>
        emitWithAck<RoomPreviewResponse>("get_room_preview", { code: roomCode }),
      join: async ({ code: roomCode, nickname: playerNickname, mode }) => {
        // A visitor who typed a name into the block above and pressed Join
        // means to play under it. Provisioning from that draft here is the
        // same flow its own button runs, reached by the button they pressed.
        const account = await useAuthStore.getState().ensureIdentity();
        return emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: account.displayName || playerNickname,
          nameColor,
          colorblindSafeColors,
          asSpectator: mode === "spectator",
        });
      },
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
  }, [code, colorblindSafeColors, nameColor, nickname, setSession]);

  function setNicknameInput(value: string) {
    machineRef.current?.setNicknameInput(value);
  }

  function join(mode: RoomJoinMode) {
    return machineRef.current?.join(mode) ?? Promise.resolve();
  }

  return { ...snapshot, setNicknameInput, join };
}
