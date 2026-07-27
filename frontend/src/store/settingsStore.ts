import { create } from "zustand";

export type PenCursorStyle = "crosshair" | "circle";

export interface KeyBindings {
  pen: string[];
  fill: string[];
  eraser: string[];
  rectangle: string[];
  triangle: string[];
  ellipse: string[];
  brushDecrease: string[];
  brushIncrease: string[];
  undo: string[];
}

export const DEFAULT_KEY_BINDINGS: KeyBindings = {
  pen: ["p", "1"],
  fill: ["f", "2"],
  eraser: ["e", "3"],
  rectangle: ["r", "4"],
  triangle: ["t", "5"],
  ellipse: ["c", "6"],
  brushDecrease: ["["],
  brushIncrease: ["]"],
  undo: ["z"],
};

export const DEFAULT_PEN_CURSOR: PenCursorStyle = "crosshair";

export const ACTION_LABELS: Record<keyof KeyBindings, string> = {
  pen: "Pen Tool",
  fill: "Fill Tool",
  eraser: "Eraser Tool",
  rectangle: "Rectangle Tool",
  triangle: "Triangle Tool",
  ellipse: "Ellipse Tool",
  brushDecrease: "Decrease Brush Size",
  brushIncrease: "Increase Brush Size",
  undo: "Undo Stroke",
};

function loadStoredKeyBindings(): KeyBindings {
  try {
    const raw = localStorage.getItem("sketchy_keybindings");
    if (!raw) return DEFAULT_KEY_BINDINGS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_KEY_BINDINGS, ...parsed };
  } catch {
    return DEFAULT_KEY_BINDINGS;
  }
}

function loadStoredPenCursor(): PenCursorStyle {
  try {
    const raw = localStorage.getItem("sketchy_pencursor");
    if (raw === "circle" || raw === "crosshair") return raw;
    return DEFAULT_PEN_CURSOR;
  } catch {
    return DEFAULT_PEN_CURSOR;
  }
}

function loadStoredConfetti(): boolean {
  try {
    const raw = localStorage.getItem("sketchy_confettieffects");
    if (raw === "false") return false;
    return true;
  } catch {
    return true;
  }
}

function loadStoredSoundEffects(): boolean {
  try {
    const raw = localStorage.getItem("sketchy_soundeffects");
    if (raw === "false") return false;
    return true;
  } catch {
    return true;
  }
}

function loadStoredVolume(): number {
  try {
    const raw = localStorage.getItem("sketchy_volume");
    if (raw !== null) {
      const parsed = parseFloat(raw);
      if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) return parsed;
    }
    return 0.7;
  } catch {
    return 0.7;
  }
}

interface SettingsStore {
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  keyBindings: KeyBindings;
  penCursor: PenCursorStyle;
  confettiEffects: boolean;
  soundEffects: boolean;
  volume: number;
  setAllSettings: (payload: {
    keyBindings: KeyBindings;
    penCursor: PenCursorStyle;
    confettiEffects?: boolean;
    soundEffects?: boolean;
    volume?: number;
  }) => void;
  setKeyBinding: (action: keyof KeyBindings, keys: string[]) => void;
  setPenCursor: (penCursor: PenCursorStyle) => void;
  setConfettiEffects: (enabled: boolean) => void;
  setSoundEffects: (enabled: boolean) => void;
  setVolume: (volume: number) => void;
  resetKeyBindings: () => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  isSettingsOpen: false,
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  keyBindings: loadStoredKeyBindings(),
  penCursor: loadStoredPenCursor(),
  confettiEffects: loadStoredConfetti(),
  soundEffects: loadStoredSoundEffects(),
  volume: loadStoredVolume(),
  setAllSettings: ({ keyBindings, penCursor, confettiEffects = true, soundEffects = true, volume = 0.7 }) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(keyBindings));
      localStorage.setItem("sketchy_pencursor", penCursor);
      localStorage.setItem("sketchy_confettieffects", String(confettiEffects));
      localStorage.setItem("sketchy_soundeffects", String(soundEffects));
      localStorage.setItem("sketchy_volume", String(volume));
      return { keyBindings, penCursor, confettiEffects, soundEffects, volume };
    }),
  setKeyBinding: (action, keys) =>
    set((state) => {
      const updated = { ...state.keyBindings, [action]: keys };
      localStorage.setItem("sketchy_keybindings", JSON.stringify(updated));
      return { keyBindings: updated };
    }),
  setPenCursor: (penCursor) =>
    set(() => {
      localStorage.setItem("sketchy_pencursor", penCursor);
      return { penCursor };
    }),
  setConfettiEffects: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_confettieffects", String(enabled));
      return { confettiEffects: enabled };
    }),
  setSoundEffects: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_soundeffects", String(enabled));
      return { soundEffects: enabled };
    }),
  setVolume: (volume) =>
    set(() => {
      localStorage.setItem("sketchy_volume", String(volume));
      return { volume };
    }),
  resetKeyBindings: () =>
    set(() => {
      localStorage.removeItem("sketchy_keybindings");
      return { keyBindings: DEFAULT_KEY_BINDINGS };
    }),
}));
