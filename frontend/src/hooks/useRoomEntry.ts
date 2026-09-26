import { useEffect, useRef, useState } from "react";
import { RoomEntryMachine, type RoomEntrySnapshot, type RoomJoinMode } from "../lib/roomEntryState";
import { emitEntry, emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { needsIdentity, useAuthStore } from "../store/authStore";
import { useSettingsStore } from "../store/settingsStore";
import { useRoomEntryStore } from "../store/roomEntryStore";
import type { AckResponse, RoomPreviewResponse } from "../types";

export function useRoomEntry(code: string) {
  const nickname = useAuthStore((state) => state.user?.displayName ?? "");
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const colorblindSafeColors = useSettingsStore((state) => state.colorblindSafeColors);
  // The language this player plays in, fixed on the seat when it is made: a
  // mixed-language room plays each seat in its own (#1182).
  const seatLanguage = useSettingsStore((state) => state.promptLanguage);
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
        emitEntry<AckResponse>("join_room", {
          code: roomCode,
          nickname: playerNickname,
          nameColor,
          colorblindSafeColors,
          seatLanguage,
          asSpectator: mode === "spectator",
        }).then((response) => {
          // Somebody who arrived first holds this guest's name (R-ACCT-09):
          // the refusal says so, and the name field it asks for appears.
          if (response.errorCode === "name_in_use") useAuthStore.getState().markNameInUse();
          return response;
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
  }, [code, colorblindSafeColors, nameColor, seatLanguage, setSession]);

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
    // The app's one-entry-at-a-time lock (store/roomEntryStore.ts), taken
    // before the machine moves to "joining": while something else holds it -
    // a Quick play still answering, a friend's invitation - the press does
    // nothing at all, rather than turning into a refusal the room never gave.
    // The page disables its controls on the same state, so this is the guard
    // behind them.
    const token = useRoomEntryStore
      .getState()
      .begin("invite-link", mode === "spectator" ? "spectate" : "join");
    if (token === null) return;
    try {
      await joinHoldingTheLock(machine, mode);
    } finally {
      useRoomEntryStore.getState().end(token);
    }
  }

  async function joinHoldingTheLock(machine: RoomEntryMachine, mode: RoomJoinMode) {
    // The machine checks the nickname before it calls anything, and a
    // first-time visitor's is empty: the invite screen's name field writes
    // the shared draft, not the machine, so the name they typed is there. Becoming
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
