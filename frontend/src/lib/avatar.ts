/**
 * Utilities for user avatars and initials.
 */

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function getAvatarColor(isAnonymous: boolean, nameColor?: string | null): string {
  if (isAnonymous) {
    return "#888888";
  }
  return nameColor || "#3b82f6";
}
