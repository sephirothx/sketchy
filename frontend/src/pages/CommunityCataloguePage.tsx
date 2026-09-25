import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { CommunityPromptsDialog } from "../components/CommunityPromptsDialog";
import { CopiedFromCredit } from "../components/CopiedFromCredit";
import { ANY_LANGUAGE, LanguagePicker } from "../components/LanguagePicker";
import { PromptContentReportDialog } from "../components/PromptContentReportDialog";
import {
  BackIcon,
  CopyIcon,
  DeckIcon,
  Flag,
  SearchIcon,
  StarIcon,
} from "../components/icons";
import {
  DEFAULT_FILTERS,
  PREVIEW_PROMPTS,
  filtersFromParams,
  isFiltered,
  paramsFromFilters,
  queryFromFilters,
  withTag,
  type CatalogueFilters,
} from "../lib/communityLists";
import { promptLanguageLabel, SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import {
  forkPromptList,
  listCommunityPromptLists,
  listPromptTags,
  readCommunityPromptList,
  setPromptListStarred,
} from "../lib/promptLists";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import type {
  CommunityPromptList,
  CommunityPromptListDetail,
  PromptLanguage,
  PromptTag,
} from "../types";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { EmptyState } from "../components/ui/EmptyState";
import "../styles/lazy/community-lists.css";

/** A tag's name in the reader's language, by the slug that never changes. */
function tagName(slug: string): string {
  return (ui.promptTags as Record<string, string>)[slug] ?? slug;
}

export function CommunityCataloguePage() {
  useDocumentTitle(ui.communityCataloguePage.communityCatalogue);
  const navigate = useNavigate();
  const params = useParams<{ listId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const registered = Boolean(user && !user.isAnonymous);

  const requested = filtersFromParams(searchParams);
  // A starred-only view is a question only a signed-in reader can ask, and
  // the route refuses it from anyone else. Dropping it rather than sending it
  // means a link to somebody's shortlist opens the catalogue for a guest
  // instead of an error, and that signing out here stops filtering by a
  // shortlist that is no longer theirs.
  const filters = registered ? requested : { ...requested, starred: false };
  const selectedId = params.listId ?? null;
  const filterKey = paramsFromFilters(filters).toString();
  // Who the rows were read for. `starredByMe` and a starred-only view are
  // answers about one reader, so they are keyed by that reader as well as by
  // the filters: signing out does not unmount this page, and the next person
  // at the browser must not be shown the last account's shortlist.
  const reader = registered ? user?.id ?? "" : "guest";

  // Both of these are keyed by what they were loaded for, so "still loading"
  // and "showing something else" are read off the data rather than cleared by
  // an effect - which would paint the previous filter's rows for a frame.
  const [page, setPage] = useState<
    { key: string; reader: string; lists: CommunityPromptList[]; cursor: string | null } | null
  >(null);
  const [loaded, setLoaded] = useState<
    { reader: string; list: CommunityPromptListDetail } | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [vocabulary, setVocabulary] = useState<PromptTag[]>([]);
  // Bumped to ask for the rows again when a star landed against a view that
  // is no longer the one on screen. Nothing else re-reads then: the filters
  // and the reader are both unchanged from the new view's point of view.
  const [revalidate, setRevalidate] = useState(0);
  const [reporting, setReporting] = useState(false);
  // Which list the "all prompts" view was opened for. An id rather than a flag,
  // so choosing another list closes it without an effect having to.
  const [exploringId, setExploringId] = useState<string | null>(null);
  // The last list that could not be opened, and why. Held apart from the
  // page's own `error`: the catalogue and the open list are two requests that
  // succeed and fail independently, and the catalogue loading must not wipe
  // out the reason its neighbour could not open.
  const [openFailure, setOpenFailure] = useState<
    { id: string; reader: string; sentence: string } | null
  >(null);
  const idPrefix = useId();
  // Open whenever a tag is already on, so a filter carried in on a link is
  // visible rather than hidden behind a count somebody has to find.
  const [tagsOpen, setTagsOpen] = useState(requested.tags.length > 0);

  const current = page?.key === filterKey && page.reader === reader ? page : null;
  const lists = current?.lists ?? [];
  const cursor = current?.cursor ?? null;
  const loading = current === null;
  const openFailed =
    openFailure && openFailure.id === selectedId && openFailure.reader === reader
      ? openFailure
      : null;
  // A list read earlier stands in while it is read again - going back and
  // forth between cards should not flash a loading pane - but never once the
  // server has said it is gone. Unpublished or hidden since, its prompts and
  // its Play button must not stay on screen.
  const detail =
    loaded && loaded.reader === reader && loaded.list.id === selectedId && !openFailed
      ? loaded.list
      : null;

  useEffect(() => {
    let cancelled = false;
    const asked = filtersFromParams(new URLSearchParams(filterKey));
    void listCommunityPromptLists(queryFromFilters(asked, null))
      .then((fetched) => {
        if (cancelled) return;
        setPage({ key: filterKey, reader, lists: fetched.lists, cursor: fetched.nextCursor });
        setError(null);
      })
      .catch((loadError) => {
        if (!cancelled) setError(refusalText(loadError, ui.communityCataloguePage.couldNotLoadTheCatalogue));
      });
    return () => { cancelled = true; };
  }, [filterKey, reader, revalidate]);

  useEffect(() => {
    let cancelled = false;
    // The vocabulary is a fixed set; a failure leaves the tag filter hidden
    // rather than showing an error over a page that otherwise works.
    void listPromptTags()
      .then((loaded) => { if (!cancelled) setVocabulary(loaded.tags); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    void readCommunityPromptList(selectedId)
      .then((opened) => {
        if (cancelled) return;
        setLoaded({ reader, list: opened });
        setOpenFailure((held) => (held?.id === selectedId ? null : held));
      })
      .catch((openError) => {
        if (cancelled) return;
        // The copy read before is not a fallback: whatever changed, the
        // server no longer serves this list to this reader.
        setLoaded((held) => (held?.list.id === selectedId ? null : held));
        setOpenFailure({
          id: selectedId,
          reader,
          sentence: refusalText(openError, ui.communityCataloguePage.couldNotOpenThatList),
        });
      });
    return () => { cancelled = true; };
  }, [selectedId, reader]);

  // What the page is asking for right now, readable from a reply that comes
  // back later. A filter control stays live while a star is in flight, so the
  // view a reply belongs to is not always the view it arrives in.
  const askingRef = useRef({ reader, key: filterKey });
  useEffect(() => {
    askingRef.current = { reader, key: filterKey };
  }, [reader, filterKey]);

  const applyFilters = useCallback((next: CatalogueFilters) => {
    setSearchParams(paramsFromFilters(next), { replace: true });
  }, [setSearchParams]);

  function openList(id: string) {
    const query = paramsFromFilters(filters).toString();
    navigate(`/community-lists/${encodeURIComponent(id)}${query ? `?${query}` : ""}`);
  }

  // Back to the cards, keeping the filters they were chosen from. Only offered
  // on a narrow screen, where the open list replaces the cards instead of
  // standing beside them.
  function closeList() {
    const query = paramsFromFilters(filters).toString();
    navigate(`/community-lists${query ? `?${query}` : ""}`);
  }

  /** The star that is also the count. One control says how many, whether one
   * of them is yours, and how to change that - so the count and the button can
   * never disagree. A guest sees the same count, not pressable. */
  function starControl(list: CommunityPromptList | CommunityPromptListDetail) {
    if (!registered) {
      return <span className="community-catalogue-star is-static">
        <StarIcon size={14} />
        <span aria-hidden="true">{list.starCount}</span>
        <span className="visually-hidden">{ui.communityCataloguePage.starCount({ count: list.starCount })}</span>
      </span>;
    }
    return <button
      type="button"
      className={list.starredByMe ? "community-catalogue-star is-on" : "community-catalogue-star"}
      aria-pressed={Boolean(list.starredByMe)}
      aria-label={ui.communityCataloguePage.starButton({
        count: list.starCount,
        starred: Boolean(list.starredByMe),
      })}
      disabled={busy}
      onClick={() => void toggleStar(list)}
    ><StarIcon size={14} />{list.starCount}</button>;
  }

  /** A list's language, as the lobby's room card shows a room's: the flag,
   * named for whoever cannot see it and on hover for whoever can. */
  function languageFlag(language: PromptLanguage, width?: number) {
    return <span className="community-catalogue-flag" title={promptLanguageLabel(language)}>
      <Flag language={language} width={width} />
      <span className="visually-hidden">{promptLanguageLabel(language)}</span>
    </span>;
  }

  /** How many prompts, without the word: the deck is the genre's image for
   * prompts. The pane writes the word beside it, which is where it is learnt. */
  function promptCount(count: number) {
    return <span className="community-catalogue-count" title={ui.communityCataloguePage.promptCount({ count })}>
      <DeckIcon size={14} />
      <span aria-hidden="true">{count}</span>
      <span className="visually-hidden">{ui.communityCataloguePage.promptCount({ count })}</span>
    </span>;
  }

  async function showMore() {
    if (!cursor || busy) return;
    setBusy(true);
    try {
      const fetched = await listCommunityPromptLists(queryFromFilters(filters, cursor));
      setPage((held) => (held && held.key === filterKey && held.reader === reader
        ? { ...held, lists: [...held.lists, ...fetched.lists], cursor: fetched.nextCursor }
        : held));
    } catch (moreError) {
      setError(refusalText(moreError, ui.communityCataloguePage.couldNotLoadTheCatalogue));
    } finally {
      setBusy(false);
    }
  }

  async function toggleStar(list: CommunityPromptList | CommunityPromptListDetail) {
    if (!registered || busy) return;
    setBusy(true);
    setError(null);
    // Who asked, and of which view. A star is one account's answer about one
    // list, so a reply that lands after the reader signed out or the filters
    // moved describes rows that are no longer on screen - writing it anyway
    // would put this account's star on the next account's row, or drop a row
    // out of a view that never asked for starred lists only.
    const asked = { reader, key: filterKey, starred: filters.starred };
    try {
      const result = await setPromptListStarred(list.id, !list.starredByMe);
      const apply = <T extends CommunityPromptList>(row: T): T =>
        row.id === list.id
          ? { ...row, starCount: result.starCount, starredByMe: result.starredByMe }
          : row;
      // The reader moved to another view while this was in flight. The rows
      // on screen were fetched around the mutation, so they may or may not
      // know about it - reading them again is the only answer that is right
      // either way, and it costs a request only in this narrow case.
      if (askingRef.current.reader === asked.reader && askingRef.current.key !== asked.key) {
        setRevalidate((count) => count + 1);
      }
      setPage((held) => {
        if (!held || held.reader !== asked.reader || held.key !== asked.key) return held;
        // In a starred-only view an unstarred list has stopped answering the
        // question the view asks, so it leaves rather than sitting there with
        // an empty star until the next reload.
        const dropped = asked.starred && !result.starredByMe;
        return {
          ...held,
          lists: dropped
            ? held.lists.filter((row) => row.id !== list.id)
            : held.lists.map(apply),
        };
      });
      setLoaded((held) =>
        held && held.reader === asked.reader && held.list.id === list.id
          ? { ...held, list: apply(held.list) }
          : held,
      );
    } catch (starError) {
      setError(refusalText(starError, ui.communityCataloguePage.couldNotChangeTheStar));
    } finally {
      setBusy(false);
    }
  }

  async function copyList(list: CommunityPromptListDetail) {
    if (!registered || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await forkPromptList(list.id);
      const counted = <T extends CommunityPromptList>(row: T): T =>
        row.id === list.id ? { ...row, copyCount: row.copyCount + 1 } : row;
      setPage((held) => (held ? { ...held, lists: held.lists.map(counted) } : held));
      setLoaded((held) => (held && held.list.id === list.id ? { ...held, list: counted(held.list) } : held));
      setNotice(ui.communityCataloguePage.copiedToYourLists);
    } catch (forkError) {
      setError(refusalText(forkError, ui.communityCataloguePage.couldNotCopyThatList));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={selectedId ? "page community-catalogue-page has-selection" : "page community-catalogue-page"}>
      <AppHeader backLabel={ui.communityCataloguePage.backToLobby} languageSwitch />

      {/* A heading block rather than a card. The lobby introduces its list of
          rooms the same way, and three stacked panels - a title, a filter
          set, then the results - read as three empty boxes before they read
          as a page. */}
      <div className="community-catalogue-head">
        <h1>{ui.communityCataloguePage.communityCatalogue}</h1>
        <p>{ui.communityCataloguePage.listsPlayersPublished}</p>
      </div>

      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      {notice && <p className="community-catalogue-notice" role="status">{notice}</p>}

      <div className="community-catalogue-filters">
        {/* The app's one language control, as the lobby's room filter uses it.
            A native select cannot draw a flag in its popup, and a list's
            language is shown as a flag everywhere else on this page. */}
        <LanguagePicker
          label={ui.communityCataloguePage.language}
          value={filters.language ?? ANY_LANGUAGE}
          options={SUPPORTED_PROMPT_LANGUAGES}
          includeAny
          compact
          onChange={(choice) => applyFilters({
            ...filters,
            language: choice === ANY_LANGUAGE ? null : choice,
          })}
        />

        {/* Two orders, so both are on screen: a menu that has to be opened to
            find out it holds two things is a menu for nothing. */}
        <span className="community-catalogue-sort" role="group" aria-label={ui.communityCataloguePage.sortBy}>
          <button
            type="button"
            aria-pressed={filters.sort === "stars"}
            onClick={() => applyFilters({ ...filters, sort: "stars" })}
          >{ui.communityCataloguePage.mostStarred}</button>
          <button
            type="button"
            aria-pressed={filters.sort === "newest"}
            onClick={() => applyFilters({ ...filters, sort: "newest" })}
          >{ui.communityCataloguePage.newest}</button>
        </span>

        {registered && <button
          type="button"
          className="community-catalogue-pill"
          aria-pressed={filters.starred}
          aria-label={ui.communityCataloguePage.onlyOnesIStarred}
          onClick={() => applyFilters({ ...filters, starred: !filters.starred })}
        >
          <StarIcon size={14} />
          {ui.communityCataloguePage.starred}
        </button>}

        {/* Fifteen tags would outweigh every other filter on the bar, so they
            fold behind a count. Open whenever any of them is on, because a
            filter nobody can see is a filter nobody can turn off. */}
        {vocabulary.length > 0 && <button
          type="button"
          className="community-catalogue-pill"
          aria-pressed={tagsOpen}
          aria-expanded={tagsOpen}
          onClick={() => setTagsOpen(!tagsOpen)}
        >
          {ui.communityCataloguePage.tags}
          {filters.tags.length > 0 && <span className="community-catalogue-pill-count">{filters.tags.length}</span>}
        </button>}

        {isFiltered(filters) && <button
          type="button"
          className="btn btn-ghost btn-compact"
          onClick={() => applyFilters(DEFAULT_FILTERS)}
        >{ui.communityCataloguePage.clearFilters}</button>}
      </div>

      {tagsOpen && vocabulary.length > 0 && <div className="community-catalogue-tags">
        {vocabulary.map((tag) => (
          <button
            type="button"
            key={tag.slug}
            className={filters.tags.includes(tag.slug) ? "toggle-chip is-selected" : "toggle-chip"}
            aria-pressed={filters.tags.includes(tag.slug)}
            onClick={() => applyFilters(withTag(filters, tag.slug, vocabulary.map((entry) => entry.slug)))}
          >{tagName(tag.slug)}</button>
        ))}
      </div>}

      <div className={[
        "community-catalogue-body",
        // Nothing to choose from and nothing asked for by name: the message
        // takes the whole width instead of a card-sized column beside an
        // empty pane.
        !loading && lists.length === 0 && !selectedId ? "is-empty" : "",
      ].filter(Boolean).join(" ")}>
        <div className="community-catalogue-results">
          {loading ? <p className="loading-note" role="status">{ui.communityCataloguePage.loading}</p>
            : lists.length === 0
              ? <EmptyState title={isFiltered(filters)
                  ? ui.communityCataloguePage.nothingMatchesThoseFilters
                  : ui.communityCataloguePage.nothingPublishedYet} />
              : <ul className="community-catalogue-list">
                  {lists.map((list) => {
                    const selected = list.id === selectedId;
                    const metaId = `${idPrefix}-${list.id}`;
                    return <li
                      key={list.id}
                      className={selected ? "community-catalogue-card is-selected" : "community-catalogue-card"}
                    >
                      {/* The name is the card's one real control, stretched
                          over the card, and the star is raised above it: a
                          button cannot hold a button, but it can sit on one.
                          The line under it describes it, so a screen reader
                          hears the author and the count with the name. */}
                      <button
                        type="button"
                        className="community-catalogue-card-open"
                        aria-current={selected || undefined}
                        aria-describedby={metaId}
                        onClick={() => openList(list.id)}
                      >{list.name}</button>
                      <div className="community-catalogue-card-foot">
                        <span className="community-catalogue-meta" id={metaId}>
                          {languageFlag(list.language)}
                          <span className="community-catalogue-author">
                            {ui.communityCataloguePage.byOwner({ owner: list.ownerDisplayName })}
                          </span>
                          <span className="community-catalogue-dot" aria-hidden="true">·</span>
                          {promptCount(list.promptCount)}
                        </span>
                        {starControl(list)}
                      </div>
                    </li>;
                  })}
                </ul>}
          {cursor && !loading && <div className="community-catalogue-more">
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              disabled={busy}
              onClick={() => void showMore()}
            >{ui.communityCataloguePage.showMore}</button>
          </div>}
        </div>

        <div className="community-catalogue-pane-slot">
          {selectedId && detail ? <section className="panel community-catalogue-pane">
            <button type="button" className="btn btn-ghost btn-compact community-catalogue-back" onClick={closeList}>
              <BackIcon size={15} />{ui.communityCataloguePage.allLists}
            </button>
            <header className="community-catalogue-pane-head">
              <div className="community-catalogue-pane-title">
                <p className="section-label">{ui.communityCataloguePage.whatIsInIt}</p>
                <h2>{detail.name} {languageFlag(detail.language, 22)}</h2>
                <p className="community-catalogue-by">
                  <span>{ui.communityCataloguePage.byOwner({ owner: detail.ownerDisplayName })}</span>
                  <span className="community-catalogue-dot" aria-hidden="true">·</span>
                  {/* Written out here, beside the same deck the cards show on
                      its own - this is where the icon is learnt. */}
                  <span className="community-catalogue-count">
                    <DeckIcon size={14} />
                    {ui.communityCataloguePage.promptCount({ count: detail.promptCount })}
                  </span>
                  <span className="community-catalogue-dot" aria-hidden="true">·</span>
                  <span className="community-catalogue-count">
                    <CopyIcon size={14} />
                    {ui.communityCataloguePage.copyCount({ count: detail.copyCount })}
                  </span>
                </p>
                {detail.copiedFrom && <CopiedFromCredit
                  credit={detail.copiedFrom}
                  className="community-catalogue-credit"
                  sentence={ui.communityCataloguePage.copiedFrom}
                  deletedSentence={ui.communityCataloguePage.copiedFromADeletedList}
                />}
              </div>
              {starControl(detail)}
            </header>
            {detail.tags.length > 0 && <div className="community-catalogue-pane-tags">
              {detail.tags.map((slug) => <span key={slug} className="chip chip-primary">{tagName(slug)}</span>)}
            </div>}
            {detail.description && <p className="community-catalogue-description">{detail.description}</p>}
            <div className="community-catalogue-actions">
              {/* Playing needs no account: a guest can open a room. */}
              <button
                type="button"
                className="btn btn-primary btn-compact"
                onClick={() => navigate(`/create?list=${encodeURIComponent(detail.id)}`)}
              >{ui.communityCataloguePage.playThisList}</button>
              {registered && detail.isMine ? <>
                {/* Your own list is edited, not copied or reported: a copy
                    would count and credit you to yourself (R-LIST-17), and
                    My prompt lists duplicates it without either. */}
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => navigate("/my-prompt-lists", { state: { openListId: detail.id } })}
                >{ui.communityCataloguePage.editInMyPromptLists}</button>
                <p className="community-catalogue-signed-out">{ui.communityCataloguePage.thisIsYourList}</p>
              </> : registered ? <>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  disabled={busy}
                  onClick={() => void copyList(detail)}
                >{ui.communityCataloguePage.makeACopy}</button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  onClick={() => setReporting(true)}
                >{ui.communityCataloguePage.report}</button>
              </> : <p className="community-catalogue-signed-out">
                {ui.communityCataloguePage.signInToStarCopyOrReport}
              </p>}
            </div>
            <div className="community-catalogue-prompts-head">
              <h3 className="section-label">{ui.communityCataloguePage.promptsHeading}</h3>
              <span>{ui.communityCataloguePage.inTheAuthorsOrder}</span>
            </div>
            <ul className="community-catalogue-prompts">
              {detail.prompts.slice(0, PREVIEW_PROMPTS).map((entry) => (
                <li key={entry.promptVersionId} className="community-catalogue-prompt" title={entry.prompt}>{entry.prompt}</li>
              ))}
            </ul>
            {detail.prompts.length > PREVIEW_PROMPTS && <div className="community-catalogue-explore">
              <span>{ui.communityCataloguePage.shownOfTotal({
                shown: PREVIEW_PROMPTS,
                total: detail.prompts.length,
              })}</span>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => setExploringId(detail.id)}
              ><SearchIcon size={15} />{ui.communityCataloguePage.exploreAll({ count: detail.prompts.length })}</button>
            </div>}
          </section>
            : openFailed
              // Said where the list would have been, with the way out beside
              // it. On a phone the cards are hidden while a list is named in
              // the address, so without this button the page is a dead end.
              ? <section className="panel community-catalogue-pane is-failed">
                  <p className="community-catalogue-failure" role="alert">{openFailed.sentence}</p>
                  <button type="button" className="btn btn-secondary btn-compact" onClick={closeList}>
                    <BackIcon size={15} />{ui.communityCataloguePage.allLists}
                  </button>
                </section>
            : selectedId
              ? <section className="panel community-catalogue-pane">
                  <p className="loading-note" role="status">{ui.communityCataloguePage.loading}</p>
                </section>
              // Nothing chosen: ask, rather than open a list the reader did
              // not pick. Only where there is a choice to make.
              : !loading && lists.length > 0 && <div className="community-catalogue-placeholder">
                  <DeckIcon size={30} strokeWidth={1.7} />
                  <p className="community-catalogue-placeholder-title">{ui.communityCataloguePage.chooseAList}</p>
                  <p>{ui.communityCataloguePage.chooseAListBody}</p>
                </div>}
        </div>
      </div>

      {exploringId && detail && exploringId === detail.id && <CommunityPromptsDialog
        list={detail}
        onClose={() => setExploringId(null)}
      />}
      {reporting && detail && <PromptContentReportDialog
        promptList={{ id: detail.id, name: detail.name, prompts: detail.prompts }}
        onClose={() => setReporting(false)}
        onSubmitted={() => {
          setReporting(false);
          setNotice(ui.communityCataloguePage.reportSent);
        }}
      />}
    </div>
  );
}
