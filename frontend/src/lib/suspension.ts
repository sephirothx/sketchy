/** What a suspended account is told, and how the app finds out.

A suspension arrives by two routes and they must say the same thing. A player
mid-game hears it on the socket, because the alternative is their screen going
quiet and their next click failing. Everybody else learns from the first
request that is refused, which is the moment they would otherwise have been
signed out with no explanation at all.

Both feed one notice, kept here rather than in a component so that `api.ts` can
raise it without importing React. */

export type Suspension = {
  reason: string | null;
  /** ISO instant, or null for a suspension with no end date. */
  expiresAt: string | null;
};

type Listener = (suspension: Suspension) => void;

const listeners = new Set<Listener>();
let latest: Suspension | null = null;

export function onSuspended(listener: Listener): () => void {
  listeners.add(listener);
  // A refusal that arrived before anything was listening still counts - the
  // first API call can easily lose that race with the first render.
  if (latest) listener(latest);
  return () => listeners.delete(listener);
}

export function reportSuspended(suspension: Suspension): void {
  latest = suspension;
  for (const listener of [...listeners]) listener(suspension);
}

/** Recognise the refusal the server sends for a suspended account. */
export function suspensionFromPayload(payload: unknown): Suspension | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as Record<string, unknown>;
  if (body.suspended !== true) return null;
  return {
    reason: typeof body.reason === "string" ? body.reason : null,
    expiresAt: typeof body.expiresAt === "string" ? body.expiresAt : null,
  };
}

/** One sentence saying how long this lasts.

Deliberately not "forever": a suspension with no end date is one nobody has put
an end on, which is what it says. */
export function suspensionDuration(
  suspension: Suspension,
  now: Date = new Date(),
): string {
  if (!suspension.expiresAt) return "This suspension has no end date.";
  const ends = new Date(suspension.expiresAt);
  if (Number.isNaN(ends.getTime())) return "This suspension has no end date.";
  if (ends <= now) return "This suspension has ended; try signing in again.";
  return `This suspension lasts until ${ends.toLocaleString()}.`;
}
