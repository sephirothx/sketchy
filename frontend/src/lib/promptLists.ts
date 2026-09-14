import { apiRequest } from "./api";
import type {
  CommunityPromptList,
  CommunityPromptListDetail,
  OwnedPromptList,
  PromptLanguage,
  PromptTag,
  SharedPromptList,
} from "../types";

export interface PromptListDraftEntry {
  conceptId?: string;
  prompt: string;
  aliases: string[];
}

export interface PromptListDraft {
  name: string;
  description: string;
  language: PromptLanguage;
  visibility: "private" | "unlisted";
  prompts: PromptListDraftEntry[];
  /** Slugs from the vocabulary `listPromptTags` returns; a save refuses others. */
  tags: string[];
}

export interface PromptTagVocabulary {
  tags: PromptTag[];
  maxPerList: number;
}

/**
 * The tags a list may carry. Fetched rather than hardcoded: a client guessing
 * at the set would offer tags a save then refuses (R-LIST-18).
 */
export function listPromptTags(): Promise<PromptTagVocabulary> {
  return apiRequest("/api/prompt-tags");
}

export interface CommunityPromptListPage {
  lists: CommunityPromptList[];
  nextCursor: string | null;
}

export interface CommunityPromptListQuery {
  language?: PromptLanguage;
  tags?: string[];
  sort?: "stars" | "newest";
  /** Only the lists this account starred — its shortlist. Needs an account. */
  starred?: boolean;
  limit?: number;
  cursor?: string | null;
}

/**
 * Browse published lists. Separate from the official catalogue on purpose
 * (R-LIST-14): nobody reading `/api/prompt-lists` has to ask whether a row
 * was written by a stranger.
 *
 * A tag filter wants *every* tag given, not any of them.
 */
export function listCommunityPromptLists(
  query: CommunityPromptListQuery = {},
): Promise<CommunityPromptListPage> {
  const params = new URLSearchParams();
  if (query.language) params.set("language", query.language);
  for (const tag of query.tags ?? []) params.append("tag", tag);
  if (query.sort) params.set("sort", query.sort);
  if (query.starred) params.set("starred", "true");
  if (query.limit) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);
  const search = params.toString();
  return apiRequest(`/api/prompt-lists/community${search ? `?${search}` : ""}`);
}

/**
 * Take a copy of a published list into one of your own.
 *
 * The copy is private: a fork is content taken to work on, and publishing it
 * is a separate act (R-LIST-17). It counts against the account's list
 * allowance and is refused at the cap, having written nothing.
 */
export function forkPromptList(id: string): Promise<OwnedPromptList> {
  return apiRequest(`/api/prompt-lists/${encodeURIComponent(id)}/fork`, {
    method: "POST",
  });
}

export interface StarResult {
  starCount: number;
  starredByMe: boolean;
}

/**
 * Star or unstar a published list (R-LIST-16).
 *
 * Idempotent in both directions, so a double click or a retry is safe: the
 * row is keyed by (account, list), and the response carries the count after
 * the write rather than a delta to apply.
 */
export function setPromptListStarred(
  id: string,
  starred: boolean,
): Promise<StarResult> {
  return apiRequest(`/api/prompt-lists/${encodeURIComponent(id)}/star`, {
    method: starred ? "PUT" : "DELETE",
  });
}

/**
 * One published list and its prompts. Open to a signed-out reader, like the
 * listing: choosing a list to play or copy from a name and a count is
 * choosing blind.
 */
export function readCommunityPromptList(id: string): Promise<CommunityPromptListDetail> {
  return apiRequest(`/api/prompt-lists/community/${encodeURIComponent(id)}`);
}

export function listOwnedPromptLists(): Promise<OwnedPromptList[]> {
  return apiRequest("/api/prompt-lists/mine");
}

export function getOwnedPromptList(id: string): Promise<OwnedPromptList> {
  return apiRequest(`/api/prompt-lists/mine/${encodeURIComponent(id)}`);
}

export function createOwnedPromptList(draft: PromptListDraft): Promise<OwnedPromptList> {
  return apiRequest("/api/prompt-lists/mine", { method: "POST", body: draft });
}

export function updateOwnedPromptList(
  id: string,
  expectedVersion: number,
  draft: Omit<PromptListDraft, "language">,
): Promise<OwnedPromptList> {
  return apiRequest(`/api/prompt-lists/mine/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: { ...draft, expectedVersion },
  });
}

/**
 * Put a list in the community catalogue, or take it back out.
 *
 * Separate calls rather than a `visibility` on the save, because publishing
 * is gated, rate-limited and audited (R-LIST-11): a field on the save would
 * be a way around all three, and an edit would take a list out of the
 * catalogue as a side effect of fixing a typo.
 */
export function setOwnedPromptListPublished(
  id: string,
  published: boolean,
): Promise<OwnedPromptList> {
  const action = published ? "publish" : "unpublish";
  return apiRequest(`/api/prompt-lists/mine/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function deleteOwnedPromptList(id: string): Promise<void> {
  return apiRequest(`/api/prompt-lists/mine/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function resolveSharedPromptList(code: string): Promise<SharedPromptList> {
  return apiRequest("/api/prompt-lists/shared", {
    method: "POST",
    body: { code: code.trim() },
  });
}


export type PromptContentReportReason =
  | "inappropriate"
  | "hateful_or_abusive"
  | "sexual_content"
  | "violence"
  | "spam"
  | "other";

export function submitPromptContentReport(input: {
  promptListId: string;
  promptVersionId?: string;
  shareCode?: string;
  reason: PromptContentReportReason;
  details: string;
}): Promise<{ id: string; status: "pending"; createdAt: string }> {
  return apiRequest("/api/prompt-content-reports", {
    method: "POST",
    body: input,
  });
}
