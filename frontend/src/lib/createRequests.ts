/** One `requestId` per press of "Create", kept across its retries (#879).

The server remembers the last `create_room` request id an account made, for a
minute, and answers a repeat by seating the socket back in that room rather
than making a second. That only helps if a retry repeats the id: a new id is a
new press. So the id is kept while the same settings are being retried and
nothing has succeeded, and replaced when either changes.

Pure: time is passed in. */

export const CREATE_REQUEST_REUSE_MS = 60_000;

export interface CreateRequestIds {
  /** The id for creating a room with these settings now. */
  idFor(settingsKey: string, now: number): string;
  /** A creation succeeded: the next press is a new request. */
  succeeded(): void;
}

export function createRequestIds(mint: () => string): CreateRequestIds {
  let current: { id: string; key: string; at: number } | null = null;
  return {
    idFor(settingsKey, now) {
      if (
        current === null
        || current.key !== settingsKey
        || now - current.at > CREATE_REQUEST_REUSE_MS
      ) {
        current = { id: mint(), key: settingsKey, at: now };
      }
      return current.id;
    },
    succeeded() {
      current = null;
    },
  };
}

/** A request id: 128 random bits as hex. `getRandomValues` rather than
`randomUUID`, which a page served over plain http does not have. */
export function mintRequestId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
