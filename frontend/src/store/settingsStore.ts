import { create } from "zustand";

import { DEFAULT_TIME_FORMAT, isTimeFormat, type TimeFormat } from "../lib/clock.ts";
import {
  BRUSH_CURSOR_KEY,
  LEGACY_BRUSH_CURSOR_KEY,
  dropRetiredKeys,
  migrateKeyBindings,
  readStoredBrushCursor,
} from "./settingsMigrations.ts";

export type BrushCursorStyle = "crosshair" | "circle";
export type AppTheme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export interface KeyBindings {
  brush: string[];
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
  brush: ["p", "1"],
  fill: ["f", "2"],
  eraser: ["e", "3"],
  rectangle: ["r", "4"],
  triangle: ["t", "5"],
  ellipse: ["c", "6"],
  brushDecrease: ["["],
  brushIncrease: ["]"],
  undo: ["z"],
};

export const DEFAULT_BRUSH_CURSOR: BrushCursorStyle = "crosshair";
export const DEFAULT_THEME: AppTheme = "system";
export const DEFAULT_VOLUME = 0.7;
export type { TimeFormat };

/**
 * The thirteen colours a registered player may wear on their name.
 *
 * The same list as `NAME_COLORS` in backend/app/rooms.py, which is the one
 * that counts: the server refuses anything that vanishes on either theme's
 * player list (#571), and every entry here was chosen to clear that. The
 * swatches in Settings are the only control that picks one, so the interface
 * cannot produce an unreadable name in the first place.
 */
export const NAME_COLOR_PALETTE = [
  "#e11d48",
  "#f97316",
  "#eab308",
  "#84cc16",
  "#16a34a",
  "#0d9488",
  "#38bdf8",
  "#2563eb",
  "#6366f1",
  "#a855f7",
  "#d946ef",
  "#f472b6",
  "#a0522d",
] as const;

export function isPaletteColor(value: string | null | undefined): boolean {
  return NAME_COLOR_PALETTE.includes(value as (typeof NAME_COLOR_PALETTE)[number]);
}

export function randomNameColor(exclude?: string): string {
  const choices = NAME_COLOR_PALETTE.filter((color) => color !== exclude);
  return choices[Math.floor(Math.random() * choices.length)] ?? NAME_COLOR_PALETTE[0];
}

export const ACTION_LABELS: Record<keyof KeyBindings, string> = {
  brush: "Brush tool",
  fill: "Fill tool",
  eraser: "Eraser tool",
  rectangle: "Rectangle tool",
  triangle: "Triangle tool",
  ellipse: "Ellipse tool",
  brushDecrease: "Decrease brush size",
  brushIncrease: "Increase brush size",
  undo: "Undo stroke",
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
  /* Mobile browser chrome follows the theme the player actually chose, not
     their OS. Read --paper back rather than repeating the hex, so this cannot
     drift from theme.css. index.html does the same before first paint. */
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const paper = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();
    if (paper) meta.setAttribute("content", paper);
  }
}

function loadStoredKeyBindings(): KeyBindings {
  try {
    const raw = localStorage.getItem("sketchy_keybindings");
    if (!raw) return DEFAULT_KEY_BINDINGS;
    return migrateKeyBindings(JSON.parse(raw), DEFAULT_KEY_BINDINGS);
  } catch {
    return DEFAULT_KEY_BINDINGS;
  }
}

function loadStoredBrushCursor(): BrushCursorStyle {
  try {
    const raw = readStoredBrushCursor(localStorage);
    if (raw === "circle" || raw === "crosshair") return raw;
    return DEFAULT_BRUSH_CURSOR;
  } catch {
    return DEFAULT_BRUSH_CURSOR;
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

function loadStoredTimeFormat(): TimeFormat {
  try {
    const raw = localStorage.getItem("sketchy_timeformat");
    return isTimeFormat(raw) ? raw : DEFAULT_TIME_FORMAT;
  } catch {
    return DEFAULT_TIME_FORMAT;
  }
}

function loadStoredFlag(key: string, defaultValue = true): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? defaultValue : raw !== "false";
  } catch {
    return defaultValue;
  }
}

function loadStoredVolume(): number {
  try {
    const raw = localStorage.getItem("sketchy_volume");
    if (raw !== null) {
      const parsed = parseFloat(raw);
      if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) return parsed;
    }
    return DEFAULT_VOLUME;
  } catch {
    return DEFAULT_VOLUME;
  }
}

/**
 * The colour this browser last chose, or a fresh one from the palette.
 *
 * A stored value outside the palette is one picked before the palette was the
 * only choice; the server would refuse it now, so it is replaced rather than
 * carried into a room and bounced there.
 */
function loadStoredNameColor(): string {
  try {
    const raw = localStorage.getItem("sketchy_namecolor")?.toLowerCase();
    if (raw && isPaletteColor(raw)) return raw;
    const generated = randomNameColor();
    localStorage.setItem("sketchy_namecolor", generated);
    return generated;
  } catch {
    return randomNameColor();
  }
}

interface SettingsStore {
  keyBindings: KeyBindings;
  brushCursor: BrushCursorStyle;
  theme: AppTheme;
  confettiEffects: boolean;
  soundEffects: boolean;
  volume: number;
  colorblindSafeColors: boolean;
  timeFormat: TimeFormat;
  nameColor: string;
  /** Adopt an account's copy wholesale, as login and registration do (R-SET-03). */
  setAllSettings: (payload: {
    keyBindings: KeyBindings;
    brushCursor: BrushCursorStyle;
    theme?: AppTheme;
    confettiEffects?: boolean;
    soundEffects?: boolean;
    volume?: number;
    colorblindSafeColors?: boolean;
    timeFormat?: TimeFormat;
    nameColor: string;
  }) => void;
  setKeyBinding: (action: keyof KeyBindings, keys: string[]) => void;
  setBrushCursor: (brushCursor: BrushCursorStyle) => void;
  setNameColor: (nameColor: string) => void;
  setTheme: (theme: AppTheme) => void;
  setConfettiEffects: (enabled: boolean) => void;
  setSoundEffects: (enabled: boolean) => void;
  setVolume: (volume: number) => void;
  setColorblindSafeColors: (enabled: boolean) => void;
  setTimeFormat: (timeFormat: TimeFormat) => void;
  resetKeyBindings: () => void;
}

// Storage is read once, so what has been retired is cleared once, first.
try {
  dropRetiredKeys(localStorage);
} catch {
  // No storage, nothing to clear.
}

const initialTheme = loadStoredTheme();
applyThemeToDocument(initialTheme);

export const useSettingsStore = create<SettingsStore>((set) => ({
  keyBindings: loadStoredKeyBindings(),
  brushCursor: loadStoredBrushCursor(),
  theme: initialTheme,
  confettiEffects: loadStoredFlag("sketchy_confettieffects"),
  soundEffects: loadStoredFlag("sketchy_soundeffects"),
  volume: loadStoredVolume(),
  colorblindSafeColors: loadStoredFlag("sketchy_colorblindsafecolors", false),
  timeFormat: loadStoredTimeFormat(),
  nameColor: loadStoredNameColor(),
  setAllSettings: ({
    keyBindings,
    brushCursor,
    theme = DEFAULT_THEME,
    confettiEffects = true,
    soundEffects = true,
    volume = DEFAULT_VOLUME,
    colorblindSafeColors = false,
    timeFormat = DEFAULT_TIME_FORMAT,
    nameColor,
  }) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(keyBindings));
      localStorage.setItem(BRUSH_CURSOR_KEY, brushCursor);
      localStorage.removeItem(LEGACY_BRUSH_CURSOR_KEY);
      localStorage.setItem("sketchy_theme", theme);
      localStorage.setItem("sketchy_confettieffects", String(confettiEffects));
      localStorage.setItem("sketchy_soundeffects", String(soundEffects));
      localStorage.setItem("sketchy_volume", String(volume));
      localStorage.setItem("sketchy_colorblindsafecolors", String(colorblindSafeColors));
      localStorage.setItem("sketchy_timeformat", timeFormat);
      localStorage.setItem("sketchy_namecolor", nameColor);
      applyThemeToDocument(theme);
      return {
        keyBindings,
        brushCursor,
        theme,
        confettiEffects,
        soundEffects,
        volume,
        colorblindSafeColors,
        timeFormat,
        nameColor,
      };
    }),
  setKeyBinding: (action, keys) =>
    set((state) => {
      const updated = { ...state.keyBindings, [action]: keys };
      localStorage.setItem("sketchy_keybindings", JSON.stringify(updated));
      return { keyBindings: updated };
    }),
  setBrushCursor: (brushCursor) =>
    set(() => {
      localStorage.setItem(BRUSH_CURSOR_KEY, brushCursor);
      // The pre-rename key is retired the first time the new one is written,
      // so it cannot resurface if the new one is ever cleared.
      localStorage.removeItem(LEGACY_BRUSH_CURSOR_KEY);
      return { brushCursor };
    }),
  setNameColor: (nameColor) =>
    set(() => {
      localStorage.setItem("sketchy_namecolor", nameColor);
      return { nameColor };
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
  setColorblindSafeColors: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_colorblindsafecolors", String(enabled));
      return { colorblindSafeColors: enabled };
    }),
  setTimeFormat: (timeFormat) =>
    set(() => {
      localStorage.setItem("sketchy_timeformat", timeFormat);
      return { timeFormat };
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
