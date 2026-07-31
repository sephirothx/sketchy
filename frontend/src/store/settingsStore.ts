import { create } from "zustand";

export type PenCursorStyle = "crosshair" | "circle";
export type AppTheme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

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
export const DEFAULT_THEME: AppTheme = "system";
export const NAME_COLOR_PALETTE = [
  "#e11d48",
  "#c2410c",
  "#a16207",
  "#15803d",
  "#0f766e",
  "#0369a1",
  "#4f46e5",
  "#7e22ce",
  "#be185d",
] as const;

export function randomNameColor(exclude?: string): string {
  const choices = NAME_COLOR_PALETTE.filter((color) => color !== exclude);
  return choices[Math.floor(Math.random() * choices.length)] ?? NAME_COLOR_PALETTE[0];
}

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

export function getSystemTheme(): ResolvedTheme {
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

export function resolveTheme(theme: AppTheme): ResolvedTheme {
  return theme === "system" ? getSystemTheme() : theme;
}

export function applyThemeToDocument(theme: AppTheme) {
  if (typeof document === "undefined") return;
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

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

function loadStoredTheme(): AppTheme {
  try {
    const raw = localStorage.getItem("sketchy_theme");
    if (raw === "dark" || raw === "light" || raw === "system") return raw;
  } catch {
    // Fall through to the default system preference when storage is unavailable.
  }

  return DEFAULT_THEME;
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

function loadStoredNameColor(): string {
  try {
    const raw = localStorage.getItem("sketchy_namecolor");
    if (raw && /^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toLowerCase();
    const generated = randomNameColor();
    localStorage.setItem("sketchy_namecolor", generated);
    return generated;
  } catch {
    return randomNameColor();
  }
}

interface SettingsStore {
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  keyBindings: KeyBindings;
  penCursor: PenCursorStyle;
  theme: AppTheme;
  confettiEffects: boolean;
  soundEffects: boolean;
  volume: number;
  nameColor: string;
  setAllSettings: (payload: {
    keyBindings: KeyBindings;
    penCursor: PenCursorStyle;
    theme?: AppTheme;
    confettiEffects?: boolean;
    soundEffects?: boolean;
    volume?: number;
    nameColor: string;
  }) => void;
  setKeyBinding: (action: keyof KeyBindings, keys: string[]) => void;
  setPenCursor: (penCursor: PenCursorStyle) => void;
  setTheme: (theme: AppTheme) => void;
  setConfettiEffects: (enabled: boolean) => void;
  setSoundEffects: (enabled: boolean) => void;
  setVolume: (volume: number) => void;
  resetKeyBindings: () => void;
}

const initialTheme = loadStoredTheme();
applyThemeToDocument(initialTheme);

export const useSettingsStore = create<SettingsStore>((set) => ({
  isSettingsOpen: false,
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  keyBindings: loadStoredKeyBindings(),
  penCursor: loadStoredPenCursor(),
  theme: initialTheme,
  confettiEffects: loadStoredConfetti(),
  soundEffects: loadStoredSoundEffects(),
  volume: loadStoredVolume(),
  nameColor: loadStoredNameColor(),
  setAllSettings: ({
    keyBindings,
    penCursor,
    theme = DEFAULT_THEME,
    confettiEffects = true,
    soundEffects = true,
    volume = 0.7,
    nameColor,
  }) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(keyBindings));
      localStorage.setItem("sketchy_pencursor", penCursor);
      localStorage.setItem("sketchy_theme", theme);
      localStorage.setItem("sketchy_confettieffects", String(confettiEffects));
      localStorage.setItem("sketchy_soundeffects", String(soundEffects));
      localStorage.setItem("sketchy_volume", String(volume));
      localStorage.setItem("sketchy_namecolor", nameColor);
      applyThemeToDocument(theme);
      return {
        keyBindings,
        penCursor,
        theme,
        confettiEffects,
        soundEffects,
        volume,
        nameColor,
      };
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
  setTheme: (theme) =>
    set(() => {
      localStorage.setItem("sketchy_theme", theme);
      applyThemeToDocument(theme);
      return { theme };
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

if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const syncSystemTheme = () => {
    if (useSettingsStore.getState().theme === "system") {
      applyThemeToDocument("system");
    }
  };
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", syncSystemTheme);
  } else if (typeof media.addListener === "function") {
    media.addListener(syncSystemTheme);
  }
}
