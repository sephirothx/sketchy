import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { CheckIcon, PlusIcon, TrashIcon, XIcon } from "../components/icons";
import {
  createOwnedPromptList,
  deleteOwnedPromptList,
  getOwnedPromptList,
  listOwnedPromptLists,
  listPromptTags,
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
import type { OwnedPromptList, PromptLanguage, PromptTag } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

const LANGUAGES: PromptLanguage[] = ["de", "en", "es", "fr", "it", "nl", "pt"];
const EMPTY_DRAFT: PromptListDraft = {
  name: "",
  description: "",
  language: "en",
  visibility: "private",
  prompts: [],
  tags: [],
};

/** A tag's name in the reader's language. The server's `name` is English and
kept for logs and API readers; the catalogue owns what a player reads
(R-I18N-01), keyed by the slug that never changes. */
function tagName(tag: PromptTag): string {
  return (ui.promptTags as Record<string, string>)[tag.slug] ?? tag.slug;
}

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
    tags: promptList.tags,
  };
}

export function MyPromptListsPage() {
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const userId = user?.id;
  const isAnonymous = user?.isAnonymous;
  const initialQuickPrompts = (location.state as { quickPrompts?: string } | null)?.quickPrompts;
  const [lists, setLists] = useState<OwnedPromptList[]>([]);
  const [tagVocabulary, setTagVocabulary] = useState<PromptTag[]>([]);
  const [maxTags, setMaxTags] = useState(0);
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
        if (!cancelled) setError(ui.myPromptListsPage.couldNotLoadYourPromptLists);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [userId, isAnonymous]);

  useEffect(() => {
    if (!userId || isAnonymous) return;
    let cancelled = false;
    // A failure here leaves the tag control hidden rather than showing an
    // error: tags are optional metadata, and a list still saves without them.
    void listPromptTags()
      .then((vocabulary) => {
        if (cancelled) return;
        setTagVocabulary(vocabulary.tags);
        setMaxTags(vocabulary.maxPerList);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [userId, isAnonymous]);

  // Named once: the chips read it three times, and "at the cap" is the state
  // the whole control changes shape around.
  const full = draft.tags.length >= maxTags;

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
      setError(ui.myPromptListsPage.couldNotOpenThatPromptList);
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
      setError(ui.myPromptListsPage.addAtLeastOnePromptBefore);
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
            tags: cleaned.tags,
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
      setNotice(ui.myPromptListsPage.promptListSaved);
    } catch (saveError) {
      setError(
        refusalText(saveError, ui.myPromptListsPage.couldNotSaveThisPromptList),
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selectedId || busy) return;
    if (!window.confirm(ui.myPromptListsPage.deleteThisPromptListAnd)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteOwnedPromptList(selectedId);
      setLists((current) => current.filter((item) => item.id !== selectedId));
      beginNew();
      setNotice(ui.myPromptListsPage.promptListDeleted);
    } catch {
      setError(ui.myPromptListsPage.couldNotDeleteThisPromptList);
    } finally {
      setBusy(false);
    }
  }

  return <main className="prompt-list-manager-page">
    <AppHeader backLabel={ui.myPromptListsPage.backToLobby} />
    <section className="prompt-list-manager-card">
      <div className="prompt-list-manager-heading">
        <div><p>{ui.myPromptListsPage.yourLibrary}</p><h1>{ui.myPromptListsPage.reusablePromptLists}</h1></div>
        {user && !user.isAnonymous && <button type="button" className="btn btn-primary" onClick={beginNew}><PlusIcon size={15} />{ui.myPromptListsPage.newList}</button>}
      </div>
      {!user || user.isAnonymous ? (
        <div className="prompt-list-manager-empty">
          <p>{ui.myPromptListsPage.createAccountSaveReviseSharePrompt}</p>
        </div>
      ) : (
        <div className="prompt-list-manager-layout">
          <aside aria-label={ui.myPromptListsPage.yourPromptLists}>
            {loading && lists.length === 0 && <p>{ui.myPromptListsPage.loading}</p>}
            {lists.length === 0 && !loading && <p>{ui.myPromptListsPage.noSavedListsYet}</p>}
            {lists.map((item) => <button
              type="button"
              key={item.id}
              className={selectedId === item.id ? "is-selected" : ""}
              onClick={() => void openList(item.id)}
            >
              <strong>{item.name}</strong>
              <span>
                  {ui.myPromptListsPage.listSummary({
                    prompts: item.promptCount,
                    visibility: item.visibility,
                    moderationState:
                      item.moderationState !== "active"
                        ? item.moderationState.replace("_", " ")
                        : null,
                  })}
                </span>
            </button>)}
          </aside>
          <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
            {moderationState !== "active" && <p className="prompt-list-moderation-warning" role="status">
              {ui.myPromptListsPage.listUnderReview({
                state: moderationState.replace("_", " "),
              })}
            </p>}
            <label>{ui.myPromptListsPage.name}<input value={draft.name} maxLength={64} required onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
            <label>{ui.myPromptListsPage.description}<input value={draft.description} maxLength={255} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            <div className="prompt-list-manager-meta">
              <label>{ui.myPromptListsPage.language}<select value={draft.language} disabled={Boolean(selectedId)} onChange={(event) => setDraft({ ...draft, language: event.target.value as PromptLanguage })}>
                {LANGUAGES.map((language) => <option key={language} value={language}>{promptLanguageLabel(language)}</option>)}
              </select></label>
              <label>{ui.myPromptListsPage.visibility}<select value={draft.visibility} onChange={(event) => setDraft({ ...draft, visibility: event.target.value as "private" | "unlisted" })}>
                <option value="private">{ui.myPromptListsPage.private}</option>
                <option value="unlisted">{ui.myPromptListsPage.anyoneWithCode}</option>
              </select></label>
            </div>
            {tagVocabulary.length > 0 && <fieldset className="prompt-list-tags">
              {/* Toggle chips rather than checkboxes: choosing several things
                  out of a fixed set is what `toggle-chip` is for, and the
                  room-creation form next door already picks its prompt lists
                  that way. A tag is also a label you read back at a glance,
                  which a column of checkbox rows is bad at. */}
              <legend>{ui.myPromptListsPage.tags}</legend>
              <div className="prompt-list-tags-head">
                <p className="prompt-list-tags-hint">{ui.myPromptListsPage.tagsAreHowListsAreFound}</p>
                <span className={full ? "prompt-list-tags-count is-full" : "prompt-list-tags-count"}>
                  {ui.myPromptListsPage.tagsChosen({ chosen: draft.tags.length, max: maxTags })}
                </span>
              </div>
              <div className="toggle-chips prompt-list-tag-chips">
                {tagVocabulary.map((tag) => {
                  const held = draft.tags.includes(tag.slug);
                  return <button
                    type="button"
                    key={tag.slug}
                    className={held ? "toggle-chip is-selected" : "toggle-chip"}
                    aria-pressed={held}
                    // At the cap the rest go quiet rather than disappearing:
                    // the vocabulary is the same fifteen either way, and a
                    // set that shrinks as you pick from it cannot be read.
                    disabled={!held && full}
                    onClick={() => setDraft({
                      ...draft,
                      tags: held
                        ? draft.tags.filter((slug) => slug !== tag.slug)
                        // Vocabulary order, so the chips and the saved list
                        // read the same way round.
                        : tagVocabulary
                            .map((entry) => entry.slug)
                            .filter((slug) => slug === tag.slug || draft.tags.includes(slug)),
                    })}
                  >
                    {held && <span className="toggle-chip-status"><CheckIcon size={13} /></span>}
                    <span className="toggle-chip-name">{tagName(tag)}</span>
                  </button>;
                })}
              </div>
            </fieldset>}
            {draft.visibility === "unlisted" && shareCode && <div className="prompt-list-share-code">
              <span>{ui.myPromptListsPage.shareCode}</span><code>{shareCode}</code>
              <button type="button" className="btn btn-secondary btn-compact" onClick={() => void navigator.clipboard.writeText(shareCode).catch(() => setError(ui.myPromptListsPage.couldNotCopyShareCode))}>{ui.myPromptListsPage.copy}</button>
            </div>}
            <div className="prompt-list-bulk-add">
              <label htmlFor="prompt-bulk-input">{ui.myPromptListsPage.addPrompts}</label>
              <textarea
                id="prompt-bulk-input"
                value={bulkInput}
                placeholder={ui.myPromptListsPage.onePromptPerLineSeparateEntries}
                aria-describedby="prompt-bulk-summary"
                onChange={(event) => setBulkInput(event.target.value)}
              />
              <div className="prompt-list-bulk-actions">
                <p id="prompt-bulk-summary" className="prompt-list-bulk-summary" aria-live="polite">
                  {mergeSummary ?? ui.myPromptListsPage.promptsCountOfMaxListPrompts({ promptsCount: draft.prompts.length, MAX_LIST_PROMPTS })}
                </p>
                <button
                  type="button"
                  className="btn btn-primary btn-compact"
                  disabled={!bulkInput.trim() || draft.prompts.length >= MAX_LIST_PROMPTS}
                  onClick={addBulkPrompts}
                >
                  {ui.myPromptListsPage.addList}
                </button>
              </div>
            </div>
            <div className="prompt-list-collection">
            {draft.prompts.length === 0 ? (
              <p className="prompt-list-manager-empty">{ui.myPromptListsPage.noPromptsYetPasteSomeAbove}</p>
            ) : (
              <>
                <div className="prompt-list-entry-filters">
                  <h3>{ui.myPromptListsPage.thisList}</h3>
                  <label>
                    <span className="visually-hidden">{ui.myPromptListsPage.searchPrompts}</span>
                    <input
                      type="search"
                      value={promptSearch}
                      placeholder={ui.myPromptListsPage.searchPrompts}
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
                      {ui.myPromptListsPage.needsReview({ count: flaggedCount })}
                    </label>
                  )}
                  <span className="prompt-list-entry-count">
                    {visiblePrompts.length === draft.prompts.length
                      ? ui.myPromptListsPage.promptCount({ count: draft.prompts.length })
                      : ui.myPromptListsPage.visibleOfTotal({
                        visible: visiblePrompts.length,
                        total: draft.prompts.length,
                      })}
                  </span>
                </div>
                {visiblePrompts.length === 0 ? (
                  <p className="prompt-list-manager-empty">{ui.myPromptListsPage.nothingMatchesThatSearch}</p>
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
                          <button type="button" aria-label={ui.myPromptListsPage.removePrompt({ prompt: prompt.prompt })} onClick={() => removePrompt(prompt.prompt)}><XIcon size={13} /></button>
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
              {selectedId && <button type="button" className="btn btn-danger-ghost" disabled={busy} onClick={() => void remove()}><TrashIcon size={14} />{ui.myPromptListsPage.deleteList}</button>}
              <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? ui.myPromptListsPage.saving : ui.myPromptListsPage.saveList}</button>
            </div>
          </form>
        </div>
      )}
    </section>
  </main>;
}
