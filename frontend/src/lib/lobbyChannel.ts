/** How long to wait before asking for the lobby baseline again.

`watch_lobby` is now the *only* way a lobby is told anything. The poll it
replaced retried by construction — a failed fetch was followed four seconds
later by another — so nothing had to be written down. A subscription has no
such second chance: one refused or timed-out acknowledgement on an otherwise
healthy socket leaves the lobby on its loading state for the life of that
connection, because a quiet server sends no delta either and there is nothing
to notice the gap.

Doubling from a second, capped at half a minute. The cap is the point: a
server refusing every subscription still hears from each open lobby, so the
interval has to stop growing somewhere a recovery is noticed promptly, and it
must not shrink to a retry loop that is itself the outage. */
export const FIRST_RETRY_MS = 1000;
export const MAX_RETRY_MS = 30_000;

export function resubscribeDelayMs(attempt: number): number {
  // Total on purpose. The caller only ever passes its own counter, but a
  // schedule that can answer `NaN` is a `setTimeout` that fires immediately
  // and for ever - the one failure mode a backoff exists to prevent.
  if (!Number.isFinite(attempt) || attempt < 1) return FIRST_RETRY_MS;
  return Math.min(FIRST_RETRY_MS * 2 ** (attempt - 1), MAX_RETRY_MS);
}
