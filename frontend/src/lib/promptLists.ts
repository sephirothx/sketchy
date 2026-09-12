import { apiRequest } from "./api";
import type {
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
  shareCode: string;
  reason: PromptContentReportReason;
  details: string;
}): Promise<{ id: string; status: "pending"; createdAt: string }> {
  return apiRequest("/api/prompt-content-reports", {
    method: "POST",
    body: input,
  });
}
