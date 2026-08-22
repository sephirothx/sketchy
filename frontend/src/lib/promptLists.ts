import { apiRequest } from "./api";
import type { OwnedPromptList, PromptLanguage, SharedPromptList } from "../types";

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
