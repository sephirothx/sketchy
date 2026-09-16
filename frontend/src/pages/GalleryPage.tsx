import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { GalleryPost, GalleryThumbnail } from "../components/GalleryDrawings";
import { ReportDrawingDialog } from "../components/ReportDrawingDialog";
import { ChevronUpIcon } from "../components/icons";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  fetchGallery,
  fetchThisWeek,
  galleryFiltersFromParams,
  paramsFromGalleryFilters,
  type GalleryEntry,
  type GalleryFilters,
  type GallerySort,
  type GalleryWindow,
} from "../lib/gallery";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

const SORTS: readonly GallerySort[] = ["hot", "new", "top"];
const WINDOWS: readonly GalleryWindow[] = ["all", "month", "week"];
/** Below this the rail folds away and the sort sits under the title. */
// Not copy: a media query.
const NARROW = "(max-width: 899px)";
/** How far down the reader has to be before Back to top is offered. */
const BACK_TO_TOP_AFTER_PX = 600;

/**
 * The Gallery (#524): every kept drawing from a public game, in one of three
 * orders (R-GAL-04), for anyone with a session (R-GAL-02). A feed of framed
 * posts, one column, with a sticky rail beside it on a wide screen holding
 * the sort and This week; on a phone the plain feed with the sort under the
 * title. Loads more as the reader scrolls; opening a post reuses the recap
 * gallery, and a registered viewer reacts from there through the gallery
 * door (R-GAL-06).
 */
export function GalleryPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const narrow = useMediaQuery(NARROW);
  // A visitor with no session gets no page and makes no request (R-GAL-02):
  // the server would answer `account_required`, and asking anyway would
  // paint that refusal where a sentence of our own reads better.
  const signedOut = hasResolved && user === null;

  const filters = galleryFiltersFromParams(searchParams);
  const filterKey = paramsFromGalleryFilters(filters).toString();
  // Who the rows were read for: `myReaction` and `drawnByMe` are answers
  // about one viewer, so signing out or in here must not keep showing the
  // last account's picks.
  const reader = user?.id ?? "";

  // Keyed by what it was loaded for, so "still loading" and "showing
  // something else" are read off the data rather than cleared by an effect,
  // which would paint the previous order's rows for a frame.
  const [page, setPage] = useState<
    { key: string; reader: string; entries: GalleryEntry[]; cursor: string | null } | null
  >(null);
  const [week, setWeek] = useState<{ reader: string; entries: GalleryEntry[] } | null>(null);
  // The views with an automatic page on its way; the button below is
  // disabled while the current one is among them.
  const [loadingViews, setLoadingViews] = useState<ReadonlySet<string>>(() => new Set());
  const [failure, setFailure] = useState<{ view: string; text: string } | null>(null);
  // Which view a failed automatic page load belongs to (see `showMore`).
  const [stalledView, setStalledView] = useState<string | null>(null);
  const [reporting, setReporting] = useState<string | null>(null);
  const [pastTheTop, setPastTheTop] = useState(false);
  const sentinel = useRef<HTMLDivElement | null>(null);

  const current = page?.key === filterKey && page.reader === reader ? page : null;
  const entries = current?.entries ?? [];
  const cursor = current?.cursor ?? null;
  const loading = current === null;
  const weekEntries = week?.reader === reader ? week.entries : null;

  useEffect(() => {
    if (!hasResolved || signedOut) return;
    let cancelled = false;
    const askedView = `${reader}\u0000${filterKey}`;
    const asked = galleryFiltersFromParams(new URLSearchParams(filterKey));
    void fetchGallery(asked, null)
      .then((fetched) => {
        if (cancelled) return;
        setPage({ key: filterKey, reader, entries: fetched.entries, cursor: fetched.nextCursor });
        // A fresh first page is a fresh start for this view's paging too.
        setStalledView((held) => (held === askedView ? null : held));
        setFailure(null);
      })
      .catch((loadError) => {
        if (!cancelled) setFailure({ view: askedView, text: refusalText(loadError, ui.galleryPage.couldNotLoadTheGallery) });
      });
    return () => { cancelled = true; };
  }, [filterKey, reader, hasResolved, signedOut]);


  // The rail's This week: the lobby shelf's own read, once. A failure leaves
  // the card out rather than putting an error beside a feed that works.
  useEffect(() => {
    if (!hasResolved || signedOut || narrow) return;
    let cancelled = false;
    void fetchThisWeek()
      .then((fetched) => { if (!cancelled) setWeek({ reader, entries: fetched.entries }); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [reader, hasResolved, signedOut, narrow]);

  const applyFilters = useCallback((next: GalleryFilters) => {
    setSearchParams(paramsFromGalleryFilters(next), { replace: true });
  }, [setSearchParams]);

  // One request at a time *per view*, held in a ref so the observer below
  // never has to be rebuilt around it. A set of views rather than a single
  // flag: a page still on its way for an abandoned order must not stop the
  // new order's first automatic load, which the sentinel asks for once and
  // does not ask for again while it stays on screen - and coming back to
  // the abandoned order must not ask for its page twice. Below: which view a
  // failed automatic load belongs to, which stops the automatic loading of
  // *that* view until the reader asks again - another order is another
  // feed, and starts clean.
  const inFlight = useRef(new Set<string>());
  const view = `${reader}\u0000${filterKey}`;
  const stalled = stalledView === view;
  // An error belongs to the view it happened in; another view starts clean.
  const error = failure?.view === view ? failure.text : null;
  // What the page is asking for right now, readable from a reply that comes
  // back later: a page that lands after the reader changed the order or
  // signed out describes rows that are no longer on screen, and is dropped.
  const askingRef = useRef(view);
  useEffect(() => {
    askingRef.current = view;
  }, [view]);

  const showMore = useCallback(async () => {
    if (!cursor || inFlight.current.has(view)) return;
    const asked = view;
    inFlight.current.add(asked);
    setLoadingViews((held) => new Set(held).add(asked));
    try {
      const fetched = await fetchGallery(filters, cursor);
      if (askingRef.current !== asked) return;
      setPage((held) => (held && held.key === filterKey && held.reader === reader
        ? { ...held, entries: [...held.entries, ...fetched.entries], cursor: fetched.nextCursor }
        : held));
      setStalledView(null);
      setFailure(null);
    } catch (moreError) {
      if (askingRef.current !== asked) return;
      // A failed page is not retried on its own: the sentinel is still on
      // screen, and an observer that asked again would ask forever. The
      // reader gets a button instead.
      setStalledView(asked);
      setFailure({ view: asked, text: refusalText(moreError, ui.galleryPage.couldNotLoadTheGallery) });
    } finally {
      // Only this view's own entry: other views' pages stay on their way.
      inFlight.current.delete(asked);
      setLoadingViews((held) => {
        const next = new Set(held);
        next.delete(asked);
        return next;
      });
    }
    // `filters` is derived from `filterKey`; the key is the dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, view, filterKey, reader]);

  // Loads the next page as the end of the feed comes into view, until a load
  // fails. Without an IntersectionObserver the Show more button below does
  // the same by hand.
  useEffect(() => {
    if (!cursor || stalled || typeof IntersectionObserver === "undefined") return;
    const element = sentinel.current;
    if (!element) return;
    const observer = new IntersectionObserver((records) => {
      if (records.some((record) => record.isIntersecting)) void showMore();
    }, { rootMargin: "400px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [cursor, stalled, showMore]);

  // Back to top is offered once the reader is well past the top, and taken
  // away again there: at the top it would be a button that does nothing.
  useEffect(() => {
    const onScroll = () => setPastTheTop(window.scrollY > BACK_TO_TOP_AFTER_PX);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const sortLabel: Record<GallerySort, string> = {
    hot: ui.galleryPage.hot,
    new: ui.galleryPage.new,
    top: ui.galleryPage.top,
  };
  const windowLabel: Record<GalleryWindow, string> = {
    all: ui.galleryPage.allTime,
    month: ui.galleryPage.thisMonth,
    week: ui.galleryPage.thisWeek,
  };

  const sortControl = (
    <div className="gallery-filters">
      {/* Three orders, all on screen: a menu that has to be opened to find
          out it holds three things is a menu for nothing. */}
      <span
        className="gallery-sort"
        role="group"
        aria-label={ui.galleryPage.sortBy}
        data-testid="gallery-sort"
      >
        {SORTS.map((sort) => (
          <button
            key={sort}
            type="button"
            aria-pressed={filters.sort === sort}
            onClick={() => applyFilters({ ...filters, sort })}
          >{sortLabel[sort]}</button>
        ))}
      </span>
      {/* The window only means something under Top (R-GAL-04); Hot has
          its own horizon and New is New. */}
      {filters.sort === "top" && (
        <span
          className="gallery-window"
          role="group"
          aria-label={ui.galleryPage.window}
          data-testid="gallery-window"
        >
          {WINDOWS.map((window) => (
            <button
              key={window}
              type="button"
              className="gallery-pill"
              aria-pressed={filters.window === window}
              onClick={() => applyFilters({ ...filters, window })}
            >{windowLabel[window]}</button>
          ))}
        </span>
      )}
    </div>
  );

  // What the end of the feed says. Hot stops at its horizon and the other
  // orders at the catalogue's depth, so the scroll ends with a sentence
  // rather than a spinner that never resolves.
  const theEnd = (
    <div className="gallery-end" data-testid="gallery-end">
      <p className="gallery-end-title">{ui.galleryPage.thatIsAllOfIt}</p>
      <p className="gallery-end-body">
        {filters.sort === "hot" ? ui.galleryPage.endOfHot : ui.galleryPage.endOfTheRest}
        {filters.sort === "hot" && (
          <>
            {" "}
            <button
              type="button"
              className="gallery-link"
              onClick={() => applyFilters({ sort: "top", window: "all" })}
            >{ui.galleryPage.tryTopOverAllTime}</button>
          </>
        )}
      </p>
    </div>
  );

  const feed = (
    <>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      {narrow && <div className="gallery-sticky-sort">{sortControl}</div>}
      {!hasResolved || loading
        ? <ul className="gallery-feed" aria-busy="true">
            <li className="gallery-post-skeleton" />
            <li className="gallery-post-skeleton" />
          </ul>
        : entries.length === 0
          ? <div className="gallery-empty-state" data-testid="gallery-empty">
              <p className="gallery-end-title">{ui.galleryPage.nothingHereYet}</p>
              <p className="gallery-end-body">{ui.galleryPage.nothingHereYetBody}</p>
              <button type="button" className="btn btn-primary" onClick={() => navigate("/")}>
                {ui.galleryPage.findARoom}
              </button>
            </div>
          : <ul className="gallery-feed" data-testid="gallery-feed">
              {entries.map((entry) => (
                <GalleryPost
                  key={entry.turnId}
                  entry={entry}
                  onOpen={() => navigate(`/gallery/${encodeURIComponent(entry.turnId)}`)}
                  onReport={user && !entry.drawnByMe ? () => setReporting(entry.turnId) : undefined}
                />
              ))}
            </ul>}
      {!loading && entries.length > 0 && (cursor
        ? <div ref={sentinel} className="gallery-more">
            {stalled || typeof IntersectionObserver === "undefined"
              ? <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  disabled={loadingViews.has(view)}
                  data-testid="gallery-show-more"
                  onClick={() => void showMore()}
                >{stalled ? ui.galleryPage.tryAgain : ui.galleryPage.showMore}</button>
              : <span className="gallery-loading"><span className="gallery-spinner" aria-hidden="true" />{ui.galleryPage.loading}</span>}
          </div>
        : theEnd)}
    </>
  );

  return (
    <div className="page gallery-page">
      <AppHeader title={ui.galleryPage.gallery} backLabel={ui.galleryPage.backToLobby} languageSwitch />

      {signedOut ? (
        <>
          <div className="gallery-head">
            <p className="section-label">{ui.galleryPage.eyebrow}</p>
            <h1>{ui.galleryPage.gallery}</h1>
          </div>
          <div className="gallery-empty-state" data-testid="gallery-signed-out">
            <p className="gallery-end-title">{ui.galleryPage.signInToSeeTheGallery}</p>
            <p className="gallery-end-body">{ui.galleryPage.signInBody}</p>
            <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
              {ui.galleryPage.backToLobby}
            </button>
          </div>
        </>
      ) : (
        <div className={narrow ? "gallery-layout is-narrow" : "gallery-layout"}>
          <div className="gallery-column">
            {/* A heading block rather than a card, as the community catalogue
                introduces its lists. */}
            <div className="gallery-head">
              <p className="section-label">{ui.galleryPage.eyebrow}</p>
              <h1>{ui.galleryPage.gallery}</h1>
              {!narrow && <p>{ui.galleryPage.drawingsFromPublicGames}</p>}
            </div>
            {feed}
          </div>
          {!narrow && (
            <aside className="gallery-rail">
              <section className="surface-card gallery-rail-card">
                <p className="section-label">{ui.galleryPage.sortBy}</p>
                {sortControl}
              </section>
              {/* Once the week has been read the card stays, empty week included
                  (R-GAL-07): an absent shelf and an empty week must not look alike. */}
              {weekEntries && (
                <section className="surface-card gallery-rail-card" data-testid="gallery-rail-week">
                  <div className="gallery-rail-head">
                    <h2>{ui.galleryPage.thisWeek}</h2>
                    <button
                      type="button"
                      className="gallery-link"
                      onClick={() => applyFilters({ sort: "top", window: "week" })}
                    >{ui.galleryPage.topOfTheWeek}</button>
                  </div>
                  {weekEntries.length === 0
                    ? <p className="gallery-empty" data-testid="gallery-rail-week-empty">{ui.galleryPage.nothingThisWeek}</p>
                    : <ul className="gallery-rail-list">
                    {weekEntries.map((entry) => (
                      <li key={entry.turnId}>
                        <button
                          type="button"
                          className="gallery-rail-item"
                          onClick={() => navigate(`/gallery/${encodeURIComponent(entry.turnId)}`)}
                        >
                          <span className="gallery-rail-thumb"><GalleryThumbnail entry={entry} /></span>
                          <span className="gallery-rail-text">
                            <span className="gallery-rail-prompt">{entry.prompt}</span>
                            <span className="gallery-rail-byline">
                              {ui.galleryPage.byDrawerPrefix}{" "}
                              <strong
                                className="colored-player-name"
                                style={entry.drawerNameColor ? { color: entry.drawerNameColor } : undefined}
                              >{entry.drawerDisplayName}</strong>
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>}
                </section>
              )}
            </aside>
          )}
        </div>
      )}

      {pastTheTop && (
        <button
          type="button"
          className="btn btn-icon gallery-back-to-top"
          aria-label={ui.galleryPage.backToTop}
          title={ui.galleryPage.backToTop}
          data-testid="gallery-back-to-top"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        >
          <ChevronUpIcon size={20} />
        </button>
      )}

      {reporting && (
        <ReportDrawingDialog turnId={reporting} onClose={() => setReporting(null)} />
      )}
    </div>
  );
}
