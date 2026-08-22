import { apiRequest } from "./api";
import type { OwnedPromptList, PromptLanguage, PromptListSummary } from "../types";

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

export function resolveSharedPromptList(code: string): Promise<PromptListSummary> {
  return apiRequest("/api/prompt-lists/shared", {
    method: "POST",
    body: { code: code.trim() },
  });
}
