/** A drawer's own view of their drawings shared by somebody else (#1430).

Somebody who played a public game may share its drawings to the Gallery
without asking (R-SHARE-02), so the drawer is told once per drawing, and can
take it back out from where they are told (R-SHARE-09). Anybody may call
these: they only ever answer about the caller. */

import { apiRequest } from "./api.ts";

export interface ShareNotice {
  id: string;
  turnId: string;
  prompt: string;
  /** The sharer as they were in that game. */
  sharerDisplayName: string;
  sharerNameColor: string | null;
  sharerIsAnonymous: boolean;
  createdAt: string;
}

/** The newest few still to be told, and how many there are in all: what the
    catch-up read and the socket push both carry. */
export interface PendingShareNotices {
  notices: ShareNotice[];
  total: number;
}

export function fetchPendingShareNotices(): Promise<PendingShareNotices> {
  return apiRequest("/api/share-notices/pending");
}

/** Settles the notice and every older one: the card listed the newest and
    counted the rest, so all of them were told. */
export function acknowledgeShareNotices(noticeId: string): Promise<{ ok: boolean }> {
  return apiRequest(`/api/share-notices/${encodeURIComponent(noticeId)}/acknowledge`, {
    method: "POST",
  });
}

/** Whether a payload is one this client can show: the push is untyped JSON. */
export function pendingShareNoticesFrom(payload: unknown): PendingShareNotices | null {
  if (!payload || typeof payload !== "object") return null;
  const { notices, total } = payload as Partial<PendingShareNotices>;
  if (!Array.isArray(notices) || typeof total !== "number") return null;
  return { notices, total };
}

/** What a newer read adds to the card on screen: the newest wins, since it
    lists everything the older one did that is still true. */
export function laterOf(
  current: PendingShareNotices | null,
  arriving: PendingShareNotices,
): PendingShareNotices | null {
  if (arriving.notices.length === 0) return current;
  if (!current) return arriving;
  const newest = (read: PendingShareNotices) => read.notices[0]?.createdAt ?? "";
  return newest(arriving) >= newest(current) ? arriving : current;
}
