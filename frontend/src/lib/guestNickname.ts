import type { User } from "./username";

export const DEFAULT_GUEST_DISPLAY_NAME = "Guest";

/** Name used for create/join: registered username, stored nickname, or persisted guest display name. */
export function resolvedPlayName(nickname: string, user: User | null | undefined): string {
  if (user && !user.isAnonymous) {
    return (user.username || nickname).trim();
  }
  const stored = nickname.trim();
  if (stored) return stored;
  const display = user?.displayName?.trim() ?? "";
  if (display && display.toLowerCase() !== DEFAULT_GUEST_DISPLAY_NAME.toLowerCase()) {
    return display;
  }
  return "";
}

export function needsGuestNickname(nickname: string, user: User | null | undefined): boolean {
  return !resolvedPlayName(nickname, user);
}

export function registeredNicknameTakenMessage(nickname: string): string {
  return `The nickname '${nickname}' is already taken by a registered account`;
}
