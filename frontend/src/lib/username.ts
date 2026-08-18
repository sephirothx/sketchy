export interface User {
  id: string;
  username: string | null;
  displayName: string;
  nameColor: string | null;
  avatarUrl: string | null;
  isAnonymous: boolean;
  createdAt: string;
  lastLoginAt: string;
}

export function suggestUsername(displayName: string): string {
  const cleaned = displayName
    .trim()
    .replace(/ /g, "_")
    .replace(/[^a-zA-Z0-9_-]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
  if (!/^[a-zA-Z0-9_-]{3,32}$/.test(cleaned)) return "";
  return cleaned;
}
