/** The account's own view of a role change: what it was told, and the receipt.

The staff surfaces live in `operations.ts` and `adminControls.ts`; this is the
other end of the same action. Anybody can call these — they only ever answer
about the caller — which is why they are not in either of those modules. */

import { apiRequest } from "./api.ts";

export interface PendingRoleNotice {
  id: string;
  /** The role the account holds now, not the step it took. */
  role: "user" | "moderator";
  createdAt: string;
}

/** The caller's newest unacknowledged notice — the catch-up route for
somebody who was offline when an administrator acted. */
export function fetchPendingRoleNotice(): Promise<{
  notice: PendingRoleNotice | null;
}> {
  return apiRequest("/api/role-notices/pending");
}

export function acknowledgeRoleNotice(noticeId: string): Promise<{ ok: boolean }> {
  return apiRequest(`/api/role-notices/${noticeId}/acknowledge`, { method: "POST" });
}

/** What is still to be shown once an acknowledgement lands.

Only the notice that was acknowledged goes. An administrator can act twice -
promote, then think better of it - and the second push arrives on the socket
while the receipt for the first is still in flight; clearing whatever is on
screen would take that newer notice down with it, and the player would not see
it again until a later visit. The server settles by age for the same reason:
what came after is still pending. */
export function noticeAfterAcknowledgement(
  current: PendingRoleNotice | null,
  acknowledgedId: string,
): PendingRoleNotice | null {
  return current && current.id === acknowledgedId ? null : current;
}
