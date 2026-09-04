import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { PlusIcon, TrashIcon, XIcon } from "../components/icons";
import { ApiError } from "../lib/api";
import {
  createOwnedPromptList,
  deleteOwnedPromptList,
  getOwnedPromptList,
  listOwnedPromptLists,
  updateOwnedPromptList,
  type PromptListDraft,
} from "../lib/promptLists";
import {
  describePromptMerge,
  mergePromptEntries,
  promptEntriesFromQuickInput,
  MAX_LIST_PROMPTS,
} from "../lib/promptListDrafts";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { useAuthStore } from "../store/authStore";
import type { OwnedPromptList, PromptLanguage } from "../types";

const LANGUAGES: PromptLanguage[] = ["de", "en", "es", "fr", "it", "nl", "pt"];
const EMPTY_DRAFT: PromptListDraft = {
  name: "",
  description: "",
  language: "en",
  visibility: "private",
  prompts: [],
};

function draftFromList(promptList: OwnedPromptList): PromptListDraft {
  return {
    name: promptList.name,
    description: promptList.description,
    language: promptList.language,
    visibility: promptList.visibility,
    prompts: promptList.prompts.map((prompt) => ({
      conceptId: prompt.conceptId,
      prompt: prompt.prompt,
      aliases: prompt.aliases,
    })),
  };
}

export function MyPromptListsPage() {
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const userId = user?.id;
  const isAnonymous = user?.isAnonymous;
  const initialQuickPrompts = (location.state as { quickPrompts?: string } | null)?.quickPrompts;
  const [lists, setLists] = useState<OwnedPromptList[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [shareCode, setShareCode] = useState<string | null>(null);
  const [moderationState, setModerationState] = useState<OwnedPromptList["moderationState"]>("active");
  const [promptModeration, setPromptModeration] = useState<Record<string, OwnedPromptList["moderationState"]>>({});
  const [draft, setDraft] = useState<PromptListDraft>(() => ({
    ...EMPTY_DRAFT,
    prompts: promptEntriesFromQuickInput(initialQuickPrompts),
  }));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [bulkInput, setBulkInput] = useState("");
  const [promptSearch, setPromptSearch] = useState("");
  const [showFlaggedOnly, setShowFlaggedOnly] = useState(false);
  const [mergeSummary, setMergeSummary] = useState<string | null>(null);

  useEffect(() => {
    if (!userId || isAnonymous) return;
    let cancelled = false;
    void listOwnedPromptLists()
      .then((loaded) => {
        if (!cancelled) setLists(loaded);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your prompt lists.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [userId, isAnonymous]);

  function beginNew() {
    setSelectedId(null);
    setVersion(null);
    setShareCode(null);
    setModerationState("active");
    setPromptModeration({});
    setDraft({ ...EMPTY_DRAFT, prompts: [] });
    setBulkInput("");
    setMergeSummary(null);
    setError(null);
    setNotice(null);
  }

  async function openList(id: string) {
    setLoading(true);
    setError(null);
    try {
      const loaded = await getOwnedPromptList(id);
      setSelectedId(loaded.id);
      setVersion(loaded.version);
      setShareCode(loaded.shareCode);
      setModerationState(loaded.moderationState);
      setPromptModeration(Object.fromEntries(
        loaded.prompts.map((prompt) => [prompt.conceptId, prompt.moderationState]),
      ));
      setDraft(draftFromList(loaded));
      setBulkInput("");
      setMergeSummary(null);
    } catch {
      setError("Could not open that prompt list.");
    } finally {
      setLoading(false);
    }
  }

  function removePrompt(prompt: string) {
    const key = prompt.toLocaleLowerCase();
    setDraft((current) => ({
      ...current,
      prompts: current.prompts.filter(
        (entry) => entry.prompt.toLocaleLowerCase() !== key,
      ),
    }));
  }

  function addBulkPrompts() {
    const result = mergePromptEntries(draft.prompts, bulkInput);
    if (!result.added && !result.duplicates && !result.tooLong.length && !result.overLimit) {
      return;
    }
    setDraft((current) => ({ ...current, prompts: result.entries }));
    setBulkInput("");
    setError(null);
    // Silence on a clean import: the list itself is the feedback. Anything
    // dropped has to be said, or a paste quietly loses entries.
    setMergeSummary(describePromptMerge(result));
  }

  const flaggedCount = draft.prompts.filter(
    (prompt) => prompt.conceptId && promptModeration[prompt.conceptId] !== "active",
  ).length;
  const promptQuery = promptSearch.trim().toLocaleLowerCase();
  const visiblePrompts = draft.prompts.filter((prompt) => {
    if (showFlaggedOnly && !(prompt.conceptId && promptModeration[prompt.conceptId] !== "active")) {
      return false;
    }
    return !promptQuery || prompt.prompt.toLocaleLowerCase().includes(promptQuery);
  });

  async function save() {
    if (busy) return;
    if (draft.prompts.length === 0) {
      setError("Add at least one prompt before saving.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const cleaned = {
        ...draft,
        name: draft.name.trim(),
        description: draft.description.trim(),
        prompts: draft.prompts.map((prompt) => ({
          ...prompt,
          prompt: prompt.prompt.trim(),
        })),
      };
      const saved = selectedId && version
        ? await updateOwnedPromptList(selectedId, version, {
            name: cleaned.name,
            description: cleaned.description,
            visibility: cleaned.visibility,
            prompts: cleaned.prompts,
          })
        : await createOwnedPromptList(cleaned);
      setSelectedId(saved.id);
      setVersion(saved.version);
      setShareCode(saved.shareCode);
      setModerationState(saved.moderationState);
      setPromptModeration(Object.fromEntries(
        saved.prompts.map((prompt) => [prompt.conceptId, prompt.moderationState]),
      ));
      setDraft(draftFromList(saved));
      setLists((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setNotice("Prompt list saved.");
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.message
          : "Could not save this prompt list.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selectedId || busy) return;
    if (!window.confirm("Delete this prompt list and all of its revisions?")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteOwnedPromptList(selectedId);
      setLists((current) => current.filter((item) => item.id !== selectedId));
      beginNew();
      setNotice("Prompt list deleted.");
    } catch {
      setError("Could not delete this prompt list.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="prompt-list-manager-page">
    <AppHeader page="My prompt lists" />
    <section className="prompt-list-manager-card">
      <div className="prompt-list-manager-heading">
        <div><p>Your library</p><h1>Reusable prompt lists</h1></div>
        {user && !user.isAnonymous && <button type="button" className="btn btn-primary" onClick={beginNew}><PlusIcon size={15} />New list</button>}
      </div>
      {!user || user.isAnonymous ? (
        <div className="prompt-list-manager-empty">
          <p>Create an account to save, revise, and share prompt lists. Quick room prompts stay local and ephemeral.</p>
        </div>
      ) : (
        <div className="prompt-list-manager-layout">
          <aside aria-label="Your prompt lists">
            {loading && lists.length === 0 && <p>Loading…</p>}
            {lists.length === 0 && !loading && <p>No saved lists yet.</p>}
            {lists.map((item) => <button
              type="button"
              key={item.id}
              className={selectedId === item.id ? "is-selected" : ""}
              onClick={() => void openList(item.id)}
            >
              <strong>{item.name}</strong>
              <span>{item.promptCount} prompts · {item.visibility}{item.moderationState !== "active" ? ` · ${item.moderationState.replace("_", " ")}` : ""}</span>
            </button>)}
          </aside>
          <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
            {moderationState !== "active" && <p className="prompt-list-moderation-warning" role="status">
              This list is {moderationState.replace("_", " ")} and cannot be used in new games. Editing does not automatically restore it; a moderator must review the list.
            </p>}
            <label>Name<input value={draft.name} maxLength={64} required onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
            <label>Description<input value={draft.description} maxLength={255} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            <div className="prompt-list-manager-meta">
              <label>Language<select value={draft.language} disabled={Boolean(selectedId)} onChange={(event) => setDraft({ ...draft, language: event.target.value as PromptLanguage })}>
                {LANGUAGES.map((language) => <option key={language} value={language}>{promptLanguageLabel(language)}</option>)}
              </select></label>
              <label>Visibility<select value={draft.visibility} onChange={(event) => setDraft({ ...draft, visibility: event.target.value as "private" | "unlisted" })}>
                <option value="private">Private</option>
                <option value="unlisted">Anyone with code</option>
              </select></label>
            </div>
            {draft.visibility === "unlisted" && shareCode && <div className="prompt-list-share-code">
              <span>Share code</span><code>{shareCode}</code>
              <button type="button" className="btn btn-secondary btn-compact" onClick={() => void navigator.clipboard.writeText(shareCode).catch(() => setError("Could not copy the share code."))}>Copy</button>
            </div>}
            <div className="prompt-list-bulk-add">
              <label htmlFor="prompt-bulk-input">Add prompts</label>
              <textarea
                id="prompt-bulk-input"
                value={bulkInput}
                placeholder={"One prompt per line\nor separate entries with commas"}
                aria-describedby="prompt-bulk-summary"
                onChange={(event) => setBulkInput(event.target.value)}
              />
              <div className="prompt-list-bulk-actions">
                <p id="prompt-bulk-summary" className="prompt-list-bulk-summary" aria-live="polite">
                  {mergeSummary ?? `${draft.prompts.length} of ${MAX_LIST_PROMPTS} prompts in this list`}
                </p>
                <button
                  type="button"
                  className="btn btn-primary btn-compact"
                  disabled={!bulkInput.trim() || draft.prompts.length >= MAX_LIST_PROMPTS}
                  onClick={addBulkPrompts}
                >
                  Add to list
                </button>
              </div>
            </div>
            <div className="prompt-list-collection">
            {draft.prompts.length === 0 ? (
              <p className="prompt-list-manager-empty">No prompts yet. Paste some above to get started.</p>
            ) : (
              <>
                <div className="prompt-list-entry-filters">
                  <h3>In this list</h3>
                  <label>
                    <span className="visually-hidden">Search prompts</span>
                    <input
                      type="search"
                      value={promptSearch}
                      placeholder="Search prompts"
                      onChange={(event) => setPromptSearch(event.target.value)}
                    />
                  </label>
                  {flaggedCount > 0 && (
                    <label className="prompt-list-entry-flagged">
                      <input
                        type="checkbox"
                        checked={showFlaggedOnly}
                        onChange={(event) => setShowFlaggedOnly(event.target.checked)}
                      />
                      Needs review ({flaggedCount})
                    </label>
                  )}
                  <span className="prompt-list-entry-count">
                    {visiblePrompts.length === draft.prompts.length
                      ? `${draft.prompts.length} prompts`
                      : `${visiblePrompts.length} of ${draft.prompts.length}`}
                  </span>
                </div>
                {visiblePrompts.length === 0 ? (
                  <p className="prompt-list-manager-empty">Nothing matches that search.</p>
                ) : (
                  <ul className="prompt-list-entry-editor">
                    {visiblePrompts.map((prompt, index) => {
                      const flagged = prompt.conceptId && promptModeration[prompt.conceptId] !== "active";
                      return (
                        <li
                          key={prompt.conceptId ?? `new-${index}-${prompt.prompt}`}
                          className={flagged ? "is-flagged" : undefined}
                        >
                          <span className="prompt-list-entry-text">{prompt.prompt}</span>
                          {flagged && <span className="prompt-list-entry-moderation">{promptModeration[prompt.conceptId!]?.replace("_", " ")}</span>}
                          <button type="button" aria-label={`Remove ${prompt.prompt}`} onClick={() => removePrompt(prompt.prompt)}><XIcon size={13} /></button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </>
            )}
            </div>
            {error && <p className="auth-error" role="alert">{error}</p>}
            {notice && <p className="prompt-list-manager-notice" role="status">{notice}</p>}
            <div className="prompt-list-manager-actions">
              {selectedId && <button type="button" className="btn btn-danger-ghost" disabled={busy} onClick={() => void remove()}><TrashIcon size={14} />Delete list…</button>}
              <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save list"}</button>
            </div>
          </form>
        </div>
      )}
    </section>
  </main>;
}
