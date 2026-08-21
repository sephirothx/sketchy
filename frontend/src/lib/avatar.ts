/** Letter avatars derived from a name — no network request, no upload. */

import { NAME_COLOR_PALETTE } from "../store/settingsStore";

export const GUEST_AVATAR_COLOR = "#888888";

export function avatarInitial(name: string): string {
  const trimmed = name.trim();
  // Names are restricted to ASCII letters, digits, - and _, so the first
  // character is always safe to show on its own.
  return trimmed ? trimmed[0].toUpperCase() : "?";
}

/**
 * Pick a stable color for a name.
 *
 * Deterministic so the same account keeps the same avatar across sessions and
 * devices without storing anything. Guests are always grey: the color is part
 * of what marks a name as unclaimed.
 */
export function avatarColor(name: string, isAnonymous: boolean): string {
  if (isAnonymous) return GUEST_AVATAR_COLOR;
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return NAME_COLOR_PALETTE[hash % NAME_COLOR_PALETTE.length];
}

/**
 * The color that stands for a player, wherever they appear.
 *
 * Their chosen color from Settings when the account carries one; otherwise
 * the deterministic fallback above, so a name is never left to inherit
 * whatever the surrounding element happens to paint. Guests stay grey - the
 * color is part of what marks a name as unclaimed, so a guest never has one
 * of their own to apply.
 */
export function identityColor(
  name: string,
  isAnonymous: boolean,
  nameColor?: string | null,
): string {
  if (isAnonymous) return GUEST_AVATAR_COLOR;
  return nameColor || avatarColor(name, isAnonymous);
}
