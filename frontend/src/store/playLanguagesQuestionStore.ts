import { create } from "zustand";

/** Set when a first identity is made and the question has not been asked
here; cleared, for good, once it has (#1219). Per browser: the answer lives
in the settings, which follow an account anyway (#1209). */
const DUE_KEY = "sketchy_playlanguages_question_due";
const ASKED_KEY = "sketchy_playlanguages_question_asked";

function read(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function write(key: string, on: boolean): void {
  try {
    if (on) localStorage.setItem(key, "1");
    else localStorage.removeItem(key);
  } catch {
    // No storage: the question is asked this once, in memory.
  }
}

interface PlayLanguagesQuestionStore {
  /** Whether a first-time player is still to be asked which languages they
      play in: the lobby asks it when nothing else is under way. */
  due: boolean;
  /** A first name stuck on, or an account made from nothing: ask, unless
      this browser already has. */
  markDue: () => void;
  /** Answered or set aside: never again on this browser. */
  markAsked: () => void;
}

export const usePlayLanguagesQuestionStore = create<PlayLanguagesQuestionStore>((set) => ({
  due: read(DUE_KEY) && !read(ASKED_KEY),
  markDue: () => {
    if (read(ASKED_KEY)) return;
    write(DUE_KEY, true);
    set({ due: true });
  },
  markAsked: () => {
    write(ASKED_KEY, true);
    write(DUE_KEY, false);
    set({ due: false });
  },
}));
