import { create } from "zustand";

/** Set when a new identity is made - a guest's first name, or an account made
from nothing - and cleared once the question has been answered or set aside
(#1219). Per identity, not per browser: a second guest or a second account on
the same browser is somebody new to ask. Kept in storage only so a question
due when a room took the player straight in survives to the lobby. */
const DUE_KEY = "sketchy_playlanguages_question_due";

function readDue(): boolean {
  try {
    return localStorage.getItem(DUE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeDue(on: boolean): void {
  try {
    if (on) localStorage.setItem(DUE_KEY, "1");
    else localStorage.removeItem(DUE_KEY);
  } catch {
    // No storage: the question is asked from memory, this page only.
  }
}

interface PlayLanguagesQuestionStore {
  /** Whether the player now here is still to be asked which languages they
      play in: the lobby asks it when nothing else is under way. */
  due: boolean;
  /** A new identity: a first name stuck on, or an account made from nothing. */
  markDue: () => void;
  /** Answered or set aside: this identity is not asked again. */
  markAsked: () => void;
  /** Signed in to an account that already exists: its languages are its
      own, so a question a guest was due goes with the guest. */
  cancelDue: () => void;
}

export const usePlayLanguagesQuestionStore = create<PlayLanguagesQuestionStore>((set) => ({
  due: readDue(),
  markDue: () => {
    writeDue(true);
    set({ due: true });
  },
  markAsked: () => {
    writeDue(false);
    set({ due: false });
  },
  cancelDue: () => {
    writeDue(false);
    set({ due: false });
  },
}));
