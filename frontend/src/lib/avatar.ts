/** Letter avatars derived from a name — no network request, no upload. */

const REGISTERED_COLORS = [
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

export const GUEST_AVATAR_COLOR = "#888888";

export function avatarInitial(name: string): string {
  const trimmed = name.trim();
  // Names are restricted to ASCII letters, digits, - and _, so the first
  // character is always safe to show on its own.
  return trimmed ? trimmed[0].toUpperCase() : "?";
}

/**
 * Pick a stable colour for a name.
 *
 * Deterministic so the same account keeps the same avatar across sessions and
 * devices without storing anything. Guests are always grey: the colour is part
 * of what marks a name as unclaimed.
 */
export function avatarColor(name: string, isAnonymous: boolean): string {
  if (isAnonymous) return GUEST_AVATAR_COLOR;
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return REGISTERED_COLORS[hash % REGISTERED_COLORS.length];
}
