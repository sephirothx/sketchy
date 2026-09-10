import type { PublicProfile } from "./profile";
import { ui } from "../content/ui/index.ts";

/** The units a "last seen" reads in; a second is never one of them. */
type LastSeenUnit = "minute" | "hour" | "day";

/**
 * "online", or how long ago the player went: the question a profile answers
 * is "are they around?", so a fresh absence is minutes and an old one is
 * days, never a clock time. Null for an account that never connected.
 */
export function lastSeenLabel(
  profile: Pick<PublicProfile, "isOnline" | "lastSeenAt">,
  now: Date = new Date(),
): string | null {
  if (profile.isOnline) return ui.lastSeen.online;
  if (!profile.lastSeenAt) return null;
  const seconds = Math.max(0, (now.getTime() - new Date(profile.lastSeenAt).getTime()) / 1000);
  if (seconds < 60) return ui.lastSeen.justNow;
  const units: [number, LastSeenUnit][] = [
    [60, "minute"],
    [60, "hour"],
    [24, "day"],
  ];
  let value = seconds;
  let unit: LastSeenUnit = "minute";
  for (const [size, name] of units) {
    if (value < size) break;
    value /= size;
    unit = name;
  }
  const count = Math.floor(value);
  return ui.lastSeen.lastSeenAgo({ count, unit });
}
