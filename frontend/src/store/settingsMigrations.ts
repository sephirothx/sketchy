/**
 * Moving stored settings onto the current vocabulary without losing them.
 *
 * The brush tool was called the pen when these keys were written, and they live
 * in the player's browser rather than in our database. Renaming them in place
 * would not be a rename at all: the old value stays in storage under a name
 * nothing reads any more, and the player silently gets the default back. So the
 * new name is read first, the old one is accepted as a fallback, and the next
 * save writes only the new one.
 */
import type { KeyBindings } from "./settingsStore.ts";

export const BRUSH_CURSOR_KEY = "sketchy_brushcursor";
/** What {@link BRUSH_CURSOR_KEY} was called before the tool became the brush. */
export const LEGACY_BRUSH_CURSOR_KEY = "sketchy_pencursor";

/** The binding for the brush tool, under the name it used to be stored as. */
const LEGACY_BRUSH_ACTION = "pen";

/**
 * Merge stored key bindings over the defaults, keeping only known actions.
 *
 * Unknown entries are dropped rather than carried, which is what retires the
 * legacy `pen` binding: it is read once, applied to `brush`, and then absent
 * from the next save.
 */
export function migrateKeyBindings(parsed: unknown, defaults: KeyBindings): KeyBindings {
  if (typeof parsed !== "object" || parsed === null) return defaults;
  const stored = parsed as Record<string, unknown>;

  const keysFor = (action: string): string[] | null => {
    const value = stored[action];
    if (!Array.isArray(value)) return null;
    const keys = value.filter((key): key is string => typeof key === "string");
    return keys.length > 0 ? keys : null;
  };

  const migrated = { ...defaults };
  for (const action of Object.keys(defaults) as (keyof KeyBindings)[]) {
    const keys = keysFor(action);
    if (keys) migrated[action] = keys;
  }

  // A binding stored before the rename only ever appears under the old name,
  // and only counts when the player has not since bound the brush directly.
  if (!keysFor("brush")) {
    const legacy = keysFor(LEGACY_BRUSH_ACTION);
    if (legacy) migrated.brush = legacy;
  }


  return migrated;
}

/** Read the brush cursor, accepting the pre-rename key for players who set one. */
export function readStoredBrushCursor(storage: Pick<Storage, "getItem">): string | null {
  return storage.getItem(BRUSH_CURSOR_KEY) ?? storage.getItem(LEGACY_BRUSH_CURSOR_KEY);
}

/**
 * Keys for settings that no longer exist (R-SET-04, R-SET-07).
 *
 * Retiring a setting is the opposite problem to renaming one: nothing reads
 * these any more, so left alone they would sit in storage indefinitely, hand a
 * data export a field the document no longer has, and come back the moment
 * somebody grepped for the name. Cleared once on load, here, so storage has
 * exactly one owner.
 */
export const RETIRED_SETTINGS_KEYS = [
  // The guess field always clears after a correct guess now; it was never a
  // decision worth asking a player to make.
  "sketchy_autoclearchatonguess",
  // Custom brush presets were stored, bounded and synced with nothing in the
  // interface able to create one.
  "sketchy_custombrushpresets",
] as const;

export function dropRetiredKeys(storage: Pick<Storage, "removeItem">): void {
  for (const key of RETIRED_SETTINGS_KEYS) {
    try {
      storage.removeItem(key);
    } catch {
      // A browser refusing storage has nothing to clean up.
    }
  }
}
