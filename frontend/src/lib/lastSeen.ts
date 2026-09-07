import type { PublicProfile } from "./profile";

/**
 * "online", or how long ago the player went: the question a profile answers
 * is "are they around?", so a fresh absence is minutes and an old one is
 * days, never a clock time. Null for an account that never connected.
 */
export function lastSeenLabel(
  profile: Pick<PublicProfile, "isOnline" | "lastSeenAt">,
  now: Date = new Date(),
): string | null {
  if (profile.isOnline) return "online";
  if (!profile.lastSeenAt) return null;
  const seconds = Math.max(0, (now.getTime() - new Date(profile.lastSeenAt).getTime()) / 1000);
  if (seconds < 60) return "last seen just now";
  const units: [number, string][] = [
    [60, "minute"],
    [60, "hour"],
    [24, "day"],
  ];
  let value = seconds;
  let unit = "second";
  for (const [size, name] of units) {
    if (value < size) break;
    value /= size;
    unit = name;
  }
  const count = Math.floor(value);
  return `last seen ${count} ${unit}${count === 1 ? "" : "s"} ago`;
}
