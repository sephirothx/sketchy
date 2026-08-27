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
  // Read inside effects only: the machine is seeded with whatever name is
  // known when it is built and told about later ones by the effect below,
  // rather than being rebuilt for each one.
  const nicknameRef = useRef(nickname);
  const [snapshot, setSnapshot] = useState<RoomEntrySnapshot>({
    state: { status: "loading" },
    nicknameInput: nickname,
  });

  useEffect(() => {
    const machine = new RoomEntryMachine(code, nicknameRef.current, {
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
    // Deliberately not rebuilt when the nickname changes. Becoming somebody
    // used to tear this down mid-join and build another that had to fetch the
    // preview again, which meant the join was aimed at a disposed machine and
    // went nowhere at all. The name is pushed in below instead.
  }, [code, colorblindSafeColors, nameColor, setSession]);

  useEffect(() => {
    nicknameRef.current = nickname;
    machineRef.current?.setNicknameInput(nickname);
  }, [nickname]);

  function setNicknameInput(value: string) {
    machineRef.current?.setNicknameInput(value);
  }

  async function join(mode: RoomJoinMode) {
    const machine = machineRef.current;
    if (!machine) return;
    // The machine checks the nickname before it calls anything, and a
    // first-time visitor's is empty: the invite screen has no field of its
    // own, so the name they typed is sitting in the shared draft. Becoming
    // somebody is what fills it in - and the machine survives that now, so
    // the name can simply be handed to it.
    if (needsIdentity(useAuthStore.getState().user)) {
      try {
        const account = await useAuthStore.getState().ensureIdentity();
        // Handed over here rather than left to the effect below, so the
        // join does not depend on React having flushed it first.
        machine.setNicknameInput(account.displayName);
      } catch {
        // An empty or invalid draft: let the machine say so in its own words,
        // which are the words this screen already shows for a bad name.
        machine.setNicknameInput(useAuthStore.getState().nameDraft);
      }
    }
    return machine.join(mode);
  }

  return { ...snapshot, setNicknameInput, join };
}
