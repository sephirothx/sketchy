/** What a suspended account is told, and how the app finds out.

A suspension arrives by two routes and they must say the same thing. A player
mid-game hears it on the socket, because the alternative is their screen going
quiet and their next click failing. Everybody else learns from the first
request that is refused, which is the moment they would otherwise have been
signed out with no explanation at all.

Both feed one notice, kept here rather than in a component so that `api.ts` can
raise it without importing React. */

export type ReportedMessage = {
  text: string;
  at: string | null;
};

export type Suspension = {
  reason: string | null;
  /** ISO instant, or null for a suspension with no end date. */
  expiresAt: string | null;
  /** The messages the report behind this was about - their own words, which
      is what makes the reason something they can weigh rather than just be
      told. Empty when the suspension was issued without a report. */
  messages: ReportedMessage[];
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
    messages: reportedMessages(body.messages),
  };
}

/** Keep only entries shaped like a message; a malformed one is dropped rather
than rendered as "undefined" in front of somebody already having a bad day. */
export function reportedMessages(value: unknown): ReportedMessage[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const row = entry as Record<string, unknown>;
    if (typeof row.text !== "string") return [];
    return [{ text: row.text, at: typeof row.at === "string" ? row.at : null }];
  });
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
