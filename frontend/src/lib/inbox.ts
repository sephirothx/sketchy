/**
 * The account's inbox (#1436): what the bell counts and the panel lists.
 *
 * One read, `GET /api/inbox`, carries everything: a page of entries newest
 * first, the unread count, the warning that must be acknowledged before the
 * player can take a seat, and the role the account has been offered. The
 * socket's `inbox_changed` carries nothing and only asks for that read again,
 * so a push and a visit cannot disagree.
 *
 * Parsed defensively, entry by entry: an entry of a kind this build does not
 * know, or missing what its kind needs, is dropped rather than drawn as
 * "undefined" in front of the player.
 */
import { apiRequest } from "./api.ts";
import { asReportReason, parsePendingWarning, type PendingWarning, type ReportReason } from "./moderation.ts";

export interface InboxPerson {
  userId: string;
  displayName: string;
  nameColor: string | null;
}

interface EntryBase {
  id: string;
  createdAt: string;
  read: boolean;
}

export type InboxEntry =
  | (EntryBase & {
      kind: "warning";
      warning: {
        id: string;
        kind: "warning" | "avatar_removal";
        reason: string;
        category: ReportReason | null;
        acknowledged: boolean;
        uploadAgainAt: string | null;
      };
    })
  | (EntryBase & {
      kind: "drawing_shared";
      drawing: {
        turnId: string;
        prompt: string;
        inGallery: boolean;
        sharedBy: { displayName: string; nameColor: string | null; isAnonymous: boolean } | null;
      };
    })
  | (EntryBase & {
      kind: "friend_request" | "friend_accepted";
      person: InboxPerson;
      state: "pending" | "friends" | "gone";
    })
  | (EntryBase & { kind: "game_invite"; person: InboxPerson; expiresAt: string | null })
  | (EntryBase & { kind: "reports_reviewed"; count: number })
  | (EntryBase & {
      kind: "role";
      role: "moderator" | "user";
      change: "offered" | "granted" | "removed";
      offerOpen: boolean;
    });

export interface InboxPage {
  entries: InboxEntry[];
  unreadCount: number;
  next: string | null;
  mustAcknowledge: PendingWarning | null;
  pendingRole: string | null;
}

export const EMPTY_INBOX: InboxPage = {
  entries: [],
  unreadCount: 0,
  next: null,
  mustAcknowledge: null,
  pendingRole: null,
};

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function person(value: unknown): InboxPerson | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const userId = text(row.userId);
  const displayName = text(row.displayName);
  if (!userId || displayName === null) return null;
  return { userId, displayName, nameColor: text(row.nameColor) };
}

export function parseInboxEntry(value: unknown): InboxEntry | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = text(row.id);
  const createdAt = text(row.createdAt);
  if (!id || !createdAt) return null;
  const base = { id, createdAt, read: row.read === true };
  switch (row.kind) {
    case "warning": {
      const body = row.warning as Record<string, unknown> | undefined;
      const warningId = text(body?.id);
      if (!body || !warningId) return null;
      return {
        ...base,
        kind: "warning",
        warning: {
          id: warningId,
          kind: body.kind === "avatar_removal" ? "avatar_removal" : "warning",
          reason: text(body.reason) ?? "",
          category: asReportReason(body.category),
          acknowledged: body.acknowledged === true,
          uploadAgainAt: text(body.uploadAgainAt),
        },
      };
    }
    case "drawing_shared": {
      const body = row.drawing as Record<string, unknown> | undefined;
      const turnId = text(body?.turnId);
      const prompt = text(body?.prompt);
      if (!body || !turnId || prompt === null) return null;
      const sharer = body.sharedBy as Record<string, unknown> | null | undefined;
      const sharerName = text(sharer?.displayName);
      return {
        ...base,
        kind: "drawing_shared",
        drawing: {
          turnId,
          prompt,
          inGallery: body.inGallery === true,
          sharedBy:
            sharer && sharerName !== null
              ? { displayName: sharerName, nameColor: text(sharer.nameColor), isAnonymous: sharer.isAnonymous === true }
              : null,
        },
      };
    }
    case "friend_request":
    case "friend_accepted": {
      const who = person(row.person);
      if (!who) return null;
      const state = row.state === "pending" || row.state === "friends" ? row.state : "gone";
      return { ...base, kind: row.kind, person: who, state };
    }
    case "game_invite": {
      const who = person(row.person);
      if (!who) return null;
      return { ...base, kind: "game_invite", person: who, expiresAt: text(row.expiresAt) };
    }
    case "reports_reviewed": {
      const count = typeof row.count === "number" && row.count > 0 ? row.count : 1;
      return { ...base, kind: "reports_reviewed", count };
    }
    case "role": {
      if (row.role !== "moderator" && row.role !== "user") return null;
      if (row.change !== "offered" && row.change !== "granted" && row.change !== "removed") return null;
      return { ...base, kind: "role", role: row.role, change: row.change, offerOpen: row.offerOpen === true };
    }
    default:
      return null;
  }
}

export function parseInboxPage(payload: unknown): InboxPage {
  if (!payload || typeof payload !== "object") return EMPTY_INBOX;
  const body = payload as Record<string, unknown>;
  const entries = Array.isArray(body.entries)
    ? body.entries.map(parseInboxEntry).filter((entry): entry is InboxEntry => entry !== null)
    : [];
  return {
    entries,
    unreadCount: typeof body.unreadCount === "number" ? Math.max(0, body.unreadCount) : 0,
    next: text(body.next),
    mustAcknowledge: parsePendingWarning({ warning: body.mustAcknowledge }),
    pendingRole: text(body.pendingRole),
  };
}

export async function fetchInbox(before?: string): Promise<InboxPage> {
  const query = before ? `?before=${encodeURIComponent(before)}` : "";
  return parseInboxPage(await apiRequest(`/api/inbox${query}`));
}

/** Mark entries read, by id or all of them; answers the count left unread. */
export async function markInboxRead(read: { ids: string[] } | { all: true }): Promise<number> {
  const answer = await apiRequest<{ unreadCount?: number }>("/api/inbox/read", {
    method: "POST",
    body: read,
  });
  return typeof answer.unreadCount === "number" ? answer.unreadCount : 0;
}

/** Entries from a later page appended to what is shown, without repeats. */
export function withMore(shown: InboxEntry[], more: InboxEntry[]): InboxEntry[] {
  const seen = new Set(shown.map((entry) => entry.id));
  return [...shown, ...more.filter((entry) => !seen.has(entry.id))];
}

/** Whether an invitation in the inbox can still be answered: the card's own
    live invitation from the same friend, not yet run out. The token stays
    with the card; the entry only knows who asked and until when. */
export function invitationStillOpen(
  expiresAt: string | null,
  fromUserId: string,
  live: { fromUserId: string } | null,
  now: Date = new Date(),
): boolean {
  if (!live || live.fromUserId !== fromUserId || !expiresAt) return false;
  return new Date(expiresAt).getTime() > now.getTime();
}
