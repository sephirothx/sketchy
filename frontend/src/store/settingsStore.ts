import { create } from "zustand";

export interface KeyBindings {
  pen: string[];
  eraser: string[];
  fill: string[];
  rectangle: string[];
  ellipse: string[];
  triangle: string[];
  brushDecrease: string[];
  brushIncrease: string[];
  undo: string[];
}

export const DEFAULT_KEY_BINDINGS: KeyBindings = {
  pen: ["p", "1"],
  eraser: ["e", "2"],
  fill: ["f", "3"],
  rectangle: ["r", "4"],
  ellipse: ["c", "5"],
  triangle: ["t", "6"],
  brushDecrease: ["["],
  brushIncrease: ["]"],
  undo: ["z"],
};

export const ACTION_LABELS: Record<keyof KeyBindings, string> = {
  pen: "Pen Tool",
  eraser: "Eraser Tool",
  fill: "Fill Tool",
  rectangle: "Rectangle Tool",
  ellipse: "Ellipse Tool",
  triangle: "Triangle Tool",
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

interface SettingsStore {
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  keyBindings: KeyBindings;
  setAllKeyBindings: (bindings: KeyBindings) => void;
  resetKeyBindings: () => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  isSettingsOpen: false,
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  keyBindings: loadStoredKeyBindings(),
  setAllKeyBindings: (bindings) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(bindings));
      return { keyBindings: bindings };
    }),
  resetKeyBindings: () =>
    set(() => {
      localStorage.removeItem("sketchy_keybindings");
      return { keyBindings: DEFAULT_KEY_BINDINGS };
    }),
}));
