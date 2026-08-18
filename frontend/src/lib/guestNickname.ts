import type { User } from "./username";

export const DEFAULT_GUEST_DISPLAY_NAME = "Guest";
export const GUEST_NICKNAME_RULES_MESSAGE =
  "Nickname must be 3-16 characters and contain only letters, digits, underscores, or hyphens";

/** Keep in sync with backend NICKNAME_REGEX and MAX_NICKNAME_LENGTH. */
const NICKNAME_PATTERN = /^[a-zA-Z0-9_-]{3,16}$/;

export function isValidGuestNickname(nickname: string): boolean {
  return NICKNAME_PATTERN.test(nickname.trim());
}

/** Name used for create/join: registered username, stored nickname, or persisted guest display name. */
export function resolvedPlayName(nickname: string, user: User | null | undefined): string {
  if (user && !user.isAnonymous) {
    return (user.username || nickname).trim();
  }
  const stored = nickname.trim();
  if (isValidGuestNickname(stored)) return stored;
  const display = user?.displayName?.trim() ?? "";
  if (
    isValidGuestNickname(display)
    && display.toLowerCase() !== DEFAULT_GUEST_DISPLAY_NAME.toLowerCase()
  ) {
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
