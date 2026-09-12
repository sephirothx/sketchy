import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { PromptContentReportDialog } from "../components/PromptContentReportDialog";
import {
  ChevronDownIcon,
  GlobeIcon,
  RoundsIcon,
  StarIcon,
} from "../components/icons";
import {
  DEFAULT_FILTERS,
  filtersFromParams,
  isFiltered,
  paramsFromFilters,
  queryFromFilters,
  withTag,
  type CatalogueFilters,
} from "../lib/communityLists";
import { promptLanguageLabel } from "../lib/promptLanguages";
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

const LANGUAGES: PromptLanguage[] = ["de", "en", "es", "fr", "it", "nl", "pt"];

/** A tag's name in the reader's language, by the slug that never changes. */
function tagName(slug: string): string {
  return (ui.promptTags as Record<string, string>)[slug] ?? slug;
}

export function CommunityCataloguePage() {
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
  // Open whenever a tag is already on, so a filter carried in on a link is
  // visible rather than hidden behind a count somebody has to find.
  const [tagsOpen, setTagsOpen] = useState(requested.tags.length > 0);

  const current = page?.key === filterKey && page.reader === reader ? page : null;
  const lists = current?.lists ?? [];
  const cursor = current?.cursor ?? null;
  const loading = current === null;
  const detail =
    loaded && loaded.reader === reader && loaded.list.id === selectedId
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
      .then((opened) => { if (!cancelled) setLoaded({ reader, list: opened }); })
      .catch((openError) => {
        if (!cancelled) setError(refusalText(openError, ui.communityCataloguePage.couldNotOpenThatList));
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
      setNotice(ui.communityCataloguePage.copiedToYourLists);
    } catch (forkError) {
      setError(refusalText(forkError, ui.communityCataloguePage.couldNotCopyThatList));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page community-catalogue-page">
      <AppHeader backLabel={ui.communityCataloguePage.backToLobby} languageSwitch />

      {/* A heading block rather than a card. The lobby introduces its list of
          rooms the same way, and three stacked panels - a title, a filter
          set, then the results - read as three empty boxes before they read
          as a page. */}
      <div className="community-catalogue-head">
        <p className="section-label">{ui.communityCataloguePage.community}</p>
        <h1>{ui.communityCataloguePage.communityCatalogue}</h1>
        <p>{ui.communityCataloguePage.listsPlayersPublished}</p>
      </div>

      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      {notice && <p className="community-catalogue-notice" role="status">{notice}</p>}

      <div className="community-catalogue-filters">
        <span className="community-catalogue-field">
          <GlobeIcon size={15} />
          <select
            aria-label={ui.communityCataloguePage.language}
            value={filters.language ?? ""}
            onChange={(event) => applyFilters({
              ...filters,
              language: event.target.value ? (event.target.value as PromptLanguage) : null,
            })}
          >
            <option value="">{ui.communityCataloguePage.everyLanguage}</option>
            {LANGUAGES.map((language) => (
              <option key={language} value={language}>{promptLanguageLabel(language)}</option>
            ))}
          </select>
          <ChevronDownIcon size={13} />
        </span>

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

      <div className="community-catalogue-body">
        <div className="community-catalogue-results">
          {loading ? <p className="community-catalogue-empty">{ui.communityCataloguePage.loading}</p>
            : lists.length === 0
              ? <p className="community-catalogue-empty">{isFiltered(filters)
                  ? ui.communityCataloguePage.nothingMatchesThoseFilters
                  : ui.communityCataloguePage.nothingPublishedYet}</p>
              : <ul className="community-catalogue-list">
                  {lists.map((list) => (
                    <li key={list.id}>
                      {/* The card opens the list; the star is the one thing
                          you can do to it without opening it, so it is the
                          one control that sits outside. */}
                      <button
                        type="button"
                        className={list.id === selectedId
                          ? "community-catalogue-row is-selected"
                          : "community-catalogue-row"}
                        aria-current={list.id === selectedId || undefined}
                        onClick={() => openList(list.id)}
                      >
                        <span className="community-catalogue-row-main">
                          <span className="community-catalogue-row-name">{list.name}</span>
                          <span className="community-catalogue-by">
                            {ui.communityCataloguePage.byOwner({ owner: list.ownerDisplayName })}
                          </span>
                          <span className="community-catalogue-facts">
                            <span>
                              <RoundsIcon size={14} />
                              {ui.communityCataloguePage.promptCount({ count: list.promptCount })}
                            </span>
                            <span className={list.starredByMe ? "is-starred" : undefined}>
                              <StarIcon size={14} />
                              {ui.communityCataloguePage.starCount({ count: list.starCount })}
                            </span>
                            <span>
                              <GlobeIcon size={14} />
                              {promptLanguageLabel(list.language)}
                            </span>
                          </span>
                          {list.tags.length > 0 && <span className="community-catalogue-row-tags">
                            {list.tags.map((slug) => (
                              <span key={slug} className="chip chip-neutral">{tagName(slug)}</span>
                            ))}
                          </span>}
                        </span>
                      </button>
                      {registered && <button
                        type="button"
                        className={list.starredByMe ? "star-button is-on" : "star-button"}
                        aria-label={list.starredByMe
                          ? ui.communityCataloguePage.unstarThisList
                          : ui.communityCataloguePage.starThisList}
                        aria-pressed={Boolean(list.starredByMe)}
                        disabled={busy}
                        onClick={() => void toggleStar(list)}
                      ><StarIcon size={17} /></button>}
                    </li>
                  ))}
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

        {detail && <div className="community-catalogue-preview">
          <section className="panel">
            <header className="community-catalogue-preview-head">
              <p className="section-label">{ui.communityCataloguePage.whatIsInIt}</p>
              <h2>{detail.name}</h2>
              <p className="community-catalogue-by">
                {ui.communityCataloguePage.byOwner({ owner: detail.ownerDisplayName })}
                {` · ${promptLanguageLabel(detail.language)} · ${ui.communityCataloguePage.starCount({ count: detail.starCount })}`}
              </p>
              {detail.description && <p className="community-catalogue-description">{detail.description}</p>}
            </header>
            <div className="community-catalogue-actions">
              {/* Playing needs no account: a guest can open a room. */}
              <button
                type="button"
                className="btn btn-primary btn-compact"
                onClick={() => navigate(`/create?list=${encodeURIComponent(detail.id)}`)}
              >{ui.communityCataloguePage.playThisList}</button>
              {registered ? <>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  disabled={busy}
                  onClick={() => void toggleStar(detail)}
                >{detail.starredByMe
                  ? ui.communityCataloguePage.unstar
                  : ui.communityCataloguePage.star}</button>
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
            {/* Prompts are words, so they are drawn as words. Two dozen
                one-word rows in a numbered list is a column of bullets with
                a word each, and it tells you nothing about the list. */}
            <div className="community-catalogue-prompts">
              {detail.prompts.map((entry) => (
                <span key={entry.promptVersionId} className="community-catalogue-prompt">{entry.prompt}</span>
              ))}
            </div>
          </section>
        </div>}
      </div>

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
