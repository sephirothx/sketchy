import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { AddEmailDialog } from "../components/AddEmailDialog";
import { AppHeader } from "../components/AppHeader";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { LanguageFace, LanguagePicker } from "../components/LanguagePicker";
import { TagPicker } from "../components/TagPicker";
import { AlertIcon, CopyIcon, PlusIcon, StarIcon, TrashIcon, XIcon } from "../components/icons";
import { CopiedFromCredit } from "../components/CopiedFromCredit";
import {
  createOwnedPromptList,
  deleteOwnedPromptList,
  duplicateOwnedPromptList,
  getOwnedPromptList,
  listOwnedPromptLists,
  listPromptTags,
  setOwnedPromptListPublished,
  updateOwnedPromptList,
  type PromptListDraft,
} from "../lib/promptLists";
import {
  describePromptMerge,
  duplicateName,
  emailPublishBlocker,
  mergePromptEntries,
  promptEntriesFromQuickInput,
  MAX_LIST_PROMPTS,
} from "../lib/promptListDrafts";
import { maskEmail } from "../lib/accountRecovery";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import { useEmailStateStore } from "../store/emailStateStore";
import type { CopiedFrom, OwnedPromptList, PromptLanguage, PromptTag } from "../types";
import { refusalCode, refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/community-lists.css";
import "../styles/lazy/prompt-lists.css";

const LANGUAGES: PromptLanguage[] = ["de", "en", "es", "fr", "it", "nl", "pt"];
const EMPTY_DRAFT: PromptListDraft = {
  name: "",
  description: "",
  language: "en",
  prompts: [],
  tags: [],
};

/** A tag's name in the reader's language. The server's `name` is English and
kept for logs and API readers; the catalogue owns what a player reads
(R-I18N-01), keyed by the slug that never changes. */
function tagName(tag: PromptTag): string {
  return (ui.promptTags as Record<string, string>)[tag.slug] ?? tag.slug;
}

/** Visibility as a reader says it. The sidebar used to print the stored value
in every locale. A list is private or published (R-LIST-02). */
function visibilityLabel(visibility: OwnedPromptList["visibility"]): string {
  return visibility === "public"
    ? ui.myPromptListsPage.published
    : ui.myPromptListsPage.private;
}

function draftFromList(promptList: OwnedPromptList): PromptListDraft {
  return {
    name: promptList.name,
    description: promptList.description,
    language: promptList.language,
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
  const arrival = location.state as { quickPrompts?: string; openListId?: string } | null;
  const initialQuickPrompts = arrival?.quickPrompts;
  const { notify } = useToast();
  const emailState = useEmailStateStore((state) => state.state);
  const [addingEmail, setAddingEmail] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const openOnArrival = useRef(arrival?.openListId);
  const [lists, setLists] = useState<OwnedPromptList[]>([]);
  const [tagVocabulary, setTagVocabulary] = useState<PromptTag[]>([]);
  const [maxTags, setMaxTags] = useState(0);
  const [published, setPublished] = useState(false);
  // What the community has done with this list: its stars and its copies.
  // Numbers only - who starred or copied it is disclosed to nobody, the owner
  // included (R-LIST-16, R-LIST-20).
  const [reach, setReach] = useState({ stars: 0, copies: 0 });
  // Where this list was copied from, if it was a copy (R-LIST-21).
  const [copiedFrom, setCopiedFrom] = useState<CopiedFrom | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [moderationState, setModerationState] = useState<OwnedPromptList["moderationState"]>("active");
  const [promptModeration, setPromptModeration] = useState<Record<string, OwnedPromptList["moderationState"]>>({});
  const [draft, setDraft] = useState<PromptListDraft>(() => ({
    ...EMPTY_DRAFT,
    prompts: promptEntriesFromQuickInput(initialQuickPrompts),
  }));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // Messages sit where the thing they are about happened: a
  // success is a toast and goes, a refusal stays beside the control that was
  // refused. The page is long, and one line above Save at the very bottom
  // said "could not publish" a screen away from the Publish button.
  const [listError, setListError] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  // `reload` when the refusal was a stale version: reloading is the fix.
  const [actionError, setActionError] = useState<{ sentence: string; reload: boolean } | null>(null);
  const [bulkInput, setBulkInput] = useState("");
  const [promptSearch, setPromptSearch] = useState("");
  const [showFlaggedOnly, setShowFlaggedOnly] = useState(false);
  const [mergeSummary, setMergeSummary] = useState<string | null>(null);

  useEffect(() => {
    if (!userId || isAnonymous) return;
    let cancelled = false;
    void listOwnedPromptLists()
      .then((loaded) => {
        if (cancelled) return;
        setLists(loaded);
        // Opened from the catalogue's "Edit in My prompt lists": that list,
        // if it is still one of this account's.
        if (openOnArrival.current && loaded.some((item) => item.id === openOnArrival.current)) {
          void openList(openOnArrival.current);
        }
        openOnArrival.current = undefined;
      })
      .catch(() => {
        if (!cancelled) setListError(ui.myPromptListsPage.couldNotLoadYourPromptLists);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
    // `openList` is read once, for the arrival: the load is keyed on the
    // account, and re-running it because a handler was redefined would reload
    // the lists on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function clearMessages() {
    setPublishError(null);
    setActionError(null);
  }

  /** Put a list the server just answered with on screen, whole. */
  function show(promptList: OwnedPromptList) {
    setSelectedId(promptList.id);
    setVersion(promptList.version);
    setPublished(promptList.visibility === "public");
    setReach({ stars: promptList.starCount, copies: promptList.copyCount });
    setCopiedFrom(promptList.copiedFrom);
    setModerationState(promptList.moderationState);
    setPromptModeration(Object.fromEntries(
      promptList.prompts.map((prompt) => [prompt.conceptId, prompt.moderationState]),
    ));
    setDraft(draftFromList(promptList));
  }

  function beginNew() {
    setSelectedId(null);
    setVersion(null);
    setPublished(false);
    setReach({ stars: 0, copies: 0 });
    setCopiedFrom(null);
    setModerationState("active");
    setPromptModeration({});
    setDraft({ ...EMPTY_DRAFT, prompts: [] });
    setBulkInput("");
    setMergeSummary(null);
    clearMessages();
  }

  async function togglePublished() {
    if (!selectedId) return;
    setBusy(true);
    clearMessages();
    try {
      const saved = await setOwnedPromptListPublished(selectedId, !published);
      show(saved);
      setLists((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      notify(saved.visibility === "public"
        ? ui.myPromptListsPage.promptListPublished
        : ui.myPromptListsPage.promptListUnpublished, "success");
    } catch (publishError) {
      // Written from the refusal's code, not the server's words: every reason
      // a publish is refused is something the owner can act on - confirm an
      // address, read a warning, wait for a moderator - so each has its own
      // sentence, in the reader's language (R-I18N-01).
      setPublishError(refusalText(publishError, ui.myPromptListsPage.couldNotChangePublication));
    } finally {
      setBusy(false);
    }
  }

  async function openList(id: string) {
    setLoading(true);
    clearMessages();
    try {
      show(await getOwnedPromptList(id));
      setBulkInput("");
      setMergeSummary(null);
    } catch {
      setActionError({ sentence: ui.myPromptListsPage.couldNotOpenThatPromptList, reload: false });
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
    setActionError(null);
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
      setActionError({ sentence: ui.myPromptListsPage.addAtLeastOnePromptBefore, reload: false });
      return;
    }
    setBusy(true);
    clearMessages();
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
            prompts: cleaned.prompts,
            tags: cleaned.tags,
          })
        : await createOwnedPromptList(cleaned);
      show(saved);
      setLists((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      notify(ui.myPromptListsPage.promptListSaved, "success");
    } catch (saveError) {
      setActionError({
        sentence: refusalText(saveError, ui.myPromptListsPage.couldNotSaveThisPromptList),
        reload: refusalCode(saveError) === "prompt_list_conflict",
      });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selectedId || busy) return;
    setConfirmingDelete(false);
    setBusy(true);
    clearMessages();
    try {
      await deleteOwnedPromptList(selectedId);
      setLists((current) => current.filter((item) => item.id !== selectedId));
      beginNew();
      notify(ui.myPromptListsPage.promptListDeleted, "success");
    } catch {
      setActionError({ sentence: ui.myPromptListsPage.couldNotDeleteThisPromptList, reload: false });
    } finally {
      setBusy(false);
    }
  }

  /** A new private list with this one's saved contents, and no history.

  It records no copy and credits nobody: it is the author's own content twice,
  which is what "Make a copy" in the catalogue refuses to count (R-LIST-17). The
  server builds it from the *saved* list, leaving out what a moderator hid, so
  what comes out is neither an edit nobody saved nor a takedown undone. */
  async function duplicate() {
    if (!selectedId || busy) return;
    setBusy(true);
    clearMessages();
    try {
      const saved = lists.find((item) => item.id === selectedId);
      const created = await duplicateOwnedPromptList(
        selectedId,
        duplicateName(saved?.name ?? draft.name),
      );
      show(created);
      setBulkInput("");
      setMergeSummary(null);
      setLists((current) => [created, ...current]);
      notify(ui.myPromptListsPage.listDuplicated({ name: created.name }), "success");
    } catch (duplicateError) {
      setActionError({
        sentence: refusalText(duplicateError, ui.myPromptListsPage.couldNotDuplicateThisList),
        reload: false,
      });
    } finally {
      setBusy(false);
    }
  }

  const publishBlocker = emailPublishBlocker(emailState, published);

  return <main className="prompt-list-manager-page">
    <AppHeader backLabel={ui.myPromptListsPage.backToLobby} />
    <section className="prompt-list-manager-card">
      <div className="prompt-list-manager-heading">
        <h1>{ui.myPromptListsPage.myPromptLists}</h1>
        {user && !user.isAnonymous && <button type="button" className="btn btn-primary" onClick={beginNew}><PlusIcon size={15} />{ui.myPromptListsPage.newList}</button>}
      </div>
      {!user || user.isAnonymous ? (
        <div className="prompt-list-manager-empty">
          <p>{ui.myPromptListsPage.createAccountSaveReviseSharePrompt}</p>
        </div>
      ) : (
        <div className="prompt-list-manager-layout">
          <aside aria-label={ui.myPromptListsPage.myPromptLists}>
            {loading && lists.length === 0 && <p>{ui.myPromptListsPage.loading}</p>}
            {listError
              ? <p className="prompt-list-alert is-error" role="alert"><AlertIcon size={14} /><span>{listError}</span></p>
              : lists.length === 0 && !loading && <p>{ui.myPromptListsPage.noSavedListsYet}</p>}
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
                    visibility: visibilityLabel(item.visibility),
                    moderationState:
                      item.moderationState !== "active"
                        ? item.moderationState.replace("_", " ")
                        : null,
                  })}
                </span>
            </button>)}
          </aside>
          <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
            {/* First, above the fields that can be changed: where a list came
                from is the one thing about it that editing never changes. */}
            {selectedId && copiedFrom && <CopiedFromCredit
              credit={copiedFrom}
              className="prompt-list-credit"
              sentence={ui.myPromptListsPage.copiedFrom}
              deletedSentence={ui.myPromptListsPage.copiedFromADeletedList}
            />}
            {moderationState !== "active" && <p className="prompt-list-moderation-warning" role="status">
              {ui.myPromptListsPage.listUnderReview({
                state: moderationState.replace("_", " "),
              })}
            </p>}
            {/* Name and language share a row when there is room for both, and
                the language wraps under the name when there is not. */}
            <div className="prompt-list-name-row">
              <label>{ui.myPromptListsPage.name}<input value={draft.name} maxLength={64} required onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
              {/* The picker every other language choice uses, flags included.
                  Once the list exists its language is fixed (R-LIST-05), so it
                  shows the same face without the control, as a room does. */}
              <div className="prompt-list-language">
                <span className="prompt-list-field-label">{ui.myPromptListsPage.language}</span>
                {selectedId
                  ? <span className="language-picker-static"><LanguageFace value={draft.language} /></span>
                  : <LanguagePicker
                    label={ui.myPromptListsPage.language}
                    value={draft.language}
                    options={LANGUAGES}
                    onChange={(next) => setDraft({ ...draft, language: next as PromptLanguage })}
                  />}
              </div>
            </div>
            <label>{ui.myPromptListsPage.description}<input value={draft.description} maxLength={255} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            {/* Beside the other facts about the list rather than below the
                publication panel: they are what the catalogue is filtered by.
                Hidden until the vocabulary has loaded - a list saves without
                tags, so a failed read is not worth an error. */}
            {tagVocabulary.length > 0 && <TagPicker
              vocabulary={tagVocabulary}
              chosen={draft.tags}
              max={maxTags}
              nameOf={tagName}
              onChange={(tags) => setDraft({ ...draft, tags })}
            />}
            {/* The one place a list's visibility is shown and changed. A list is
                private or published, and only publishing crosses between the
                two (R-LIST-02) - so there is no visibility field beside the
                others for a save to carry, and nothing for it to misreport. */}
            <div className="prompt-list-publication">
              <div>
                <strong>{published ? ui.myPromptListsPage.inCommunityCatalogue : ui.myPromptListsPage.notPublished}</strong>
                <p>{published
                  ? ui.myPromptListsPage.publishedExplainer
                  : publishBlocker === "no-address"
                    ? ui.myPromptListsPage.publishNeedsAnEmail
                    : publishBlocker === "pending" && emailState?.pendingAddress
                      // Masked, as every other place this address is shown
                      // outside Settings (R-SET-08).
                      ? ui.myPromptListsPage.publishNeedsConfirmation({ address: maskEmail(emailState.pendingAddress) })
                      : publishBlocker === "undeliverable"
                        ? ui.myPromptListsPage.publishNeedsEmailDelivery
                        : selectedId
                          ? ui.myPromptListsPage.unpublishedExplainer
                          : ui.myPromptListsPage.saveBeforePublishing}</p>
                {/* Shown once there is anything to show: a list that was never
                    published has neither, and a row of zeros under "Not
                    published" says nothing. A list taken back out keeps what
                    it gathered, so its numbers stay. */}
                {(published || reach.stars > 0 || reach.copies > 0) && <p className="prompt-list-reach">
                  <span><StarIcon size={14} />{ui.myPromptListsPage.starCount({ count: reach.stars })}</span>
                  <span><CopyIcon size={14} />{ui.myPromptListsPage.copyCount({ count: reach.copies })}</span>
                </p>}
              </div>
              <div className="prompt-list-publication-actions">
                {(publishBlocker === "no-address" || publishBlocker === "pending") && <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => setAddingEmail(true)}
                >{publishBlocker === "pending" ? ui.myPromptListsPage.changeEmail : ui.myPromptListsPage.addAnEmail}</button>}
                <button
                  type="button"
                  className={published ? "btn btn-secondary btn-compact" : "btn btn-primary btn-compact"}
                  disabled={busy || !selectedId || publishBlocker !== null}
                  onClick={() => void togglePublished()}
                >{published ? ui.myPromptListsPage.unpublish : ui.myPromptListsPage.publish}</button>
              </div>
              {/* A refusal of the act this panel performs belongs in the panel,
                  not at the bottom of the form a screen away from its button. */}
              {publishError && <p className="prompt-list-alert is-error prompt-list-publication-error" role="alert">
                <AlertIcon size={14} /><span>{publishError}</span>
              </p>}
            </div>
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
            {/* Pinned to the bottom of the viewport, so Save - and whatever
                stopped it - stays in reach however long the list gets. */}
            <div className="prompt-list-manager-actions">
              {actionError
                ? <p className="prompt-list-alert is-error" role="alert">
                  <AlertIcon size={14} /><span>{actionError.sentence}</span>
                  {actionError.reload && selectedId && <button
                    type="button"
                    className="prompt-list-alert-action"
                    disabled={busy}
                    onClick={() => void openList(selectedId)}
                  >{ui.myPromptListsPage.reload}</button>}
                </p>
                : <span />}
              <div className="prompt-list-manager-buttons">
                {selectedId && <button type="button" className="btn btn-danger-ghost btn-compact" disabled={busy} onClick={() => setConfirmingDelete(true)}><TrashIcon size={14} />{ui.myPromptListsPage.deleteList}</button>}
                {selectedId && !copiedFrom && moderationState === "active" && <button type="button" className="btn btn-secondary btn-compact" disabled={busy} onClick={() => void duplicate()}><CopyIcon size={14} />{ui.myPromptListsPage.duplicate}</button>}
                <button type="submit" className="btn btn-primary btn-compact" disabled={busy}>{busy ? ui.myPromptListsPage.saving : ui.myPromptListsPage.saveList}</button>
              </div>
            </div>
          </form>
        </div>
      )}
    </section>
    {confirmingDelete && <ConfirmationDialog
      title={ui.myPromptListsPage.deleteListTitle({ name: lists.find((item) => item.id === selectedId)?.name ?? draft.name })}
      description={ui.myPromptListsPage.deleteListDescription}
      confirmLabel={ui.myPromptListsPage.deleteListConfirm}
      onCancel={() => setConfirmingDelete(false)}
      onConfirm={() => void remove()}
    />}
    {addingEmail && <AddEmailDialog
      onClose={() => setAddingEmail(false)}
      onSaved={() => setAddingEmail(false)}
    />}
  </main>;
}
