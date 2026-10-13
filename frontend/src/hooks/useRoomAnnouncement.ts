import { useEffect } from "react";
import { create } from "zustand";

interface RoomAnnouncerState {
  sentence: string;
  say: (text: string) => void;
  clear: () => void;
  /** Take `text` back if it is still the one waiting or said: its card has
      gone, and the sentence should not outlive it - read later by somebody
      going through the page line by line - or be said after it. */
  withdraw: (text: string) => void;
}

let waiting: string | null = null;

let pending: ReturnType<typeof setTimeout> | null = null;

/** What the room's one always-mounted live region says (#1423).

A live region inserted into the page with its text already in it is announced
unreliably - NVDA and JAWS often say nothing - so a card that mounts with its
sentence (the turn results, the game over, the drawer's choice) hands the
sentence here, and the region that is already on the page changes its text.
Emptied first and refilled a moment later, so the same sentence twice in a
row - "Turn complete." for a spectator, every turn - is still a change. */
export const useRoomAnnouncer = create<RoomAnnouncerState>((set) => ({
  sentence: "",
  say: (text) => {
    if (pending !== null) clearTimeout(pending);
    set({ sentence: "" });
    waiting = text;
    pending = setTimeout(() => {
      pending = null;
      waiting = null;
      set({ sentence: text });
    }, 50);
  },
  clear: () => {
    if (pending !== null) clearTimeout(pending);
    pending = null;
    waiting = null;
    set({ sentence: "" });
  },
  withdraw: (text) => {
    if (waiting === text && pending !== null) {
      clearTimeout(pending);
      pending = null;
      waiting = null;
    }
    set((state) => (state.sentence === text ? { sentence: "" } : state));
  },
}));

/** Say `text` in the room's live region when it first appears or changes;
    `null` says nothing. */
export function useRoomAnnouncement(text: string | null): void {
  const say = useRoomAnnouncer((state) => state.say);
  const withdraw = useRoomAnnouncer((state) => state.withdraw);
  useEffect(() => {
    if (!text) return;
    say(text);
    return () => withdraw(text);
  }, [text, say, withdraw]);
}
