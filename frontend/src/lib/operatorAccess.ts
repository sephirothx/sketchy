/** Which staff surfaces an account is offered, and under what name.

This decides what to *show*, never what to allow. Every endpoint behind these
entries checks the role again for itself, and answers 404 to anyone else - so
getting this wrong shows somebody a door that will not open, rather than
opening one. Keeping it here, away from the menu, is what makes that testable. */

export type AccountRole = "user" | "moderator" | "admin";

export type OperatorEntry = {
  label: string;
  path: string;
};

const MODERATION: OperatorEntry = { label: "Moderation", path: "/moderation" };
const OPERATIONS: OperatorEntry = {
  label: "Server operations",
  path: "/admin/operations",
};
// Administrators only, and deliberately not beside Moderation: bug reports are
// about the software, carry build and diagnostic data, and have a different
// audience from anything in the safety queue.
const BUG_REPORTS: OperatorEntry = {
  label: "Bug reports",
  path: "/admin/bug-reports",
};

export function canModerate(role: string | null | undefined): boolean {
  return role === "moderator" || role === "admin";
}

export function canAdminister(role: string | null | undefined): boolean {
  return role === "admin";
}

/** The staff entries for a role, in the order they should appear.

A moderator reviews reports; an administrator does that and runs the server.
An unknown or missing role gets nothing, which is the safe direction: a stale
payload should hide a surface rather than advertise one. */
export function operatorEntries(
  role: string | null | undefined,
  { isAnonymous = false }: { isAnonymous?: boolean } = {},
): OperatorEntry[] {
  // A guest cannot hold a role, and treating one as staff because a stale
  // payload said so is the mistake worth being deliberate about.
  if (isAnonymous) return [];
  const entries: OperatorEntry[] = [];
  if (canModerate(role)) entries.push(MODERATION);
  if (canAdminister(role)) entries.push(OPERATIONS, BUG_REPORTS);
  return entries;
}


/** Keep only a payload shaped like a role notice.

Anything else is dropped rather than rendered as "undefined" in front of a
player, the way `WarningNotice` drops a malformed warning. `admin` is
deliberately not accepted: it can never be granted over the network, so a push
claiming it is a payload that should never have existed. */
export function roleNoticeFromPayload(payload: unknown): {
  id: string;
  role: "user" | "moderator";
  pending: boolean;
  createdAt: string;
} | null {
  if (!payload || typeof payload !== "object") return null;
  const body = (payload as { notice?: unknown }).notice;
  if (!body || typeof body !== "object") return null;
  const notice = body as Record<string, unknown>;
  if (typeof notice.id !== "string") return null;
  if (notice.role !== "user" && notice.role !== "moderator") return null;
  return {
    id: notice.id,
    role: notice.role,
    // Absent means granted: a payload from before the offer existed is a
    // role the account already holds.
    pending: notice.pending === true,
    createdAt: typeof notice.createdAt === "string" ? notice.createdAt : "",
  };
}

/** What the push says is still outstanding on the account.

Separate from the notice, and present even when there is none: a withdrawn
offer settles its notice and ends the offer in one act, so the only thing that
payload has to say is that nothing is waiting any more. Anything but a
grantable role reads as nothing, the way a malformed notice is dropped rather
than rendered. */
export function pendingRoleFromPayload(payload: unknown): "moderator" | null {
  if (!payload || typeof payload !== "object") return null;
  const offered = (payload as { pendingRole?: unknown }).pendingRole;
  return offered === "moderator" ? "moderator" : null;
}

/** A role as it is said to the person holding it, not as it is stored. */
export function roleName(role: string): string {
  return role === "admin" ? "administrator" : role;
}

/** What the account is told, in its own words rather than the ledger's.

The reason an administrator recorded is never shown here - it was written for
other administrators and can name a report or somebody else. What the player
needs is what changed and what it means for them. */
export function roleNoticeText(
  role: "user" | "moderator",
  { pending = false }: { pending?: boolean } = {},
): {
  title: string;
  body: string;
} {
  if (pending) {
    return {
      title: "The moderator role is waiting for you",
      body:
        "An administrator has offered you the moderator role. It takes effect " +
        "once you set up two-factor authentication: moderators sign in with a " +
        "code from an authenticator app, and the role starts the moment that " +
        "is in place. Your other devices are signed out when it does. Nothing " +
        "changes until you set it up, and the offer waits in Settings if now " +
        "is not the time.",
    };
  }
  if (role === "moderator") {
    return {
      title: "You are now a moderator",
      body:
        "An administrator gave you the moderator role. A Moderation entry has " +
        "appeared in your account menu: it is where reports about players and " +
        "prompts are reviewed. Nothing about how you play changes.",
    };
  }
  return {
    title: "You are no longer a moderator",
    body:
      "An administrator removed the moderator role from your account. The " +
      "Moderation entry has gone from your menu. Nothing else about your " +
      "account or your games is affected.",
  };
}
