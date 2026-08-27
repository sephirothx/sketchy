import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { needsIdentity, useAuthStore } from "../store/authStore";
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
      join: ({ code: roomCode, nickname: playerNickname, mode }) =>
        emitWithAck<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
          nameColor,
          colorblindSafeColors,
          asSpectator: mode === "spectator",
        }),
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

  /**
   * The machine, once it is showing the room again.
   *
   * Becoming somebody changes the nickname this hook is built on, so the
   * effect above tears the machine down and builds a new one that has to
   * fetch the preview afresh. Joining through the old one does nothing at
   * all: it is disposed, and its refusal goes nowhere.
   */
  async function machineShowingPreview(): Promise<RoomEntryMachine | null> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const machine = machineRef.current;
      if (machine?.getSnapshot().state.status === "preview") return machine;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return null;
  }

  async function join(mode: RoomJoinMode) {
    // The machine checks the nickname before it calls anything, and a
    // first-time visitor's is empty: the invite screen has no field of its
    // own, so the name they typed is sitting in the shared draft. Becoming
    // somebody is what fills it in.
    if (needsIdentity(useAuthStore.getState().user)) {
      try {
        await useAuthStore.getState().ensureIdentity();
      } catch {
        // An empty or invalid draft: let the machine say so in its own words,
        // which are the words this screen already shows for a bad name.
        machineRef.current?.setNicknameInput(useAuthStore.getState().nameDraft);
        return machineRef.current?.join(mode);
      }
      const rebuilt = await machineShowingPreview();
      return rebuilt?.join(mode);
    }
    return machineRef.current?.join(mode) ?? Promise.resolve();
  }

  return { ...snapshot, setNicknameInput, join };
}
