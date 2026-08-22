import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AccountMenu } from "../components/AccountMenu";
import { ApiError } from "../lib/api";
import {
  createOwnedPromptList,
  deleteOwnedPromptList,
  getOwnedPromptList,
  listOwnedPromptLists,
  updateOwnedPromptList,
  type PromptListDraft,
} from "../lib/promptLists";
import { promptEntriesFromQuickInput } from "../lib/promptListDrafts";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { useAuthStore } from "../store/authStore";
import type { OwnedPromptList, PromptLanguage } from "../types";

const LANGUAGES: PromptLanguage[] = ["de", "en", "es", "fr", "it", "nl", "pt"];
const EMPTY_DRAFT: PromptListDraft = {
  name: "",
  description: "",
  language: "en",
  visibility: "private",
  prompts: [{ prompt: "", aliases: [] }],
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
  const [draft, setDraft] = useState<PromptListDraft>(() => ({
    ...EMPTY_DRAFT,
    prompts: promptEntriesFromQuickInput(initialQuickPrompts),
  }));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
    setDraft({ ...EMPTY_DRAFT, prompts: [{ prompt: "", aliases: [] }] });
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
      setDraft(draftFromList(loaded));
    } catch {
      setError("Could not open that prompt list.");
    } finally {
      setLoading(false);
    }
  }

  function updatePrompt(index: number, value: string) {
    setDraft((current) => ({
      ...current,
      prompts: current.prompts.map((prompt, position) =>
        position === index ? { ...prompt, prompt: value } : prompt
      ),
    }));
  }

  async function save() {
    if (busy) return;
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
    <header className="site-header">
      <Link to="/" className="back-link">← Lobby</Link>
      <AccountMenu />
    </header>
    <section className="prompt-list-manager-card">
      <div className="prompt-list-manager-heading">
        <div><p>Your library</p><h1>Reusable prompt lists</h1></div>
        {user && !user.isAnonymous && <button type="button" onClick={beginNew}>New list</button>}
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
              <span>{item.promptCount} prompts · {item.visibility}</span>
            </button>)}
          </aside>
          <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
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
              <button type="button" onClick={() => void navigator.clipboard.writeText(shareCode).catch(() => setError("Could not copy the share code."))}>Copy</button>
            </div>}
            <div className="prompt-list-entry-heading"><h2>Prompts</h2><span>{draft.prompts.length}/500</span></div>
            <div className="prompt-list-entry-editor">
              {draft.prompts.map((prompt, index) => <div key={prompt.conceptId ?? `new-${index}`}>
                <label><span className="sr-only">Prompt {index + 1}</span><input value={prompt.prompt} maxLength={32} required onChange={(event) => updatePrompt(index, event.target.value)} /></label>
                <button type="button" aria-label={`Remove prompt ${index + 1}`} disabled={draft.prompts.length === 1} onClick={() => setDraft({ ...draft, prompts: draft.prompts.filter((_, position) => position !== index) })}>Remove</button>
              </div>)}
            </div>
            <button type="button" disabled={draft.prompts.length >= 500} onClick={() => setDraft({ ...draft, prompts: [...draft.prompts, { prompt: "", aliases: [] }] })}>Add prompt</button>
            {error && <p className="auth-error" role="alert">{error}</p>}
            {notice && <p className="prompt-list-manager-notice" role="status">{notice}</p>}
            <div className="prompt-list-manager-actions">
              {selectedId && <button type="button" className="danger-button" disabled={busy} onClick={() => void remove()}>Delete</button>}
              <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save list"}</button>
            </div>
          </form>
        </div>
      )}
    </section>
  </main>;
}
