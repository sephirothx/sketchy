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
