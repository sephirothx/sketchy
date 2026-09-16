import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { AppHeader } from "../components/AppHeader";
import { CanvasSnapshot } from "../components/CanvasSnapshot";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { ReactionTally } from "../components/ReactionTally";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import {
  fetchGallery,
  fetchGalleryDrawing,
  galleryEntriesAsRecap,
  galleryFiltersFromParams,
  paramsFromGalleryFilters,
  type GalleryEntry,
  type GalleryFilters,
  type GallerySort,
  type GalleryWindow,
} from "../lib/gallery";
import { setGalleryReaction } from "../lib/profile";
import { reactionEligibility } from "../lib/reactions";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

const SORTS: readonly GallerySort[] = ["hot", "new", "top"];
const WINDOWS: readonly GalleryWindow[] = ["all", "month", "week"];

/**
 * The Gallery (#524): every kept drawing from a public game, in one of three
 * orders (R-GAL-04), for anyone with a session (R-GAL-02). Each card is the
 * stored frame replayed small once it scrolls into view; opening one reuses
 * the recap gallery with the page as its entries, and a registered viewer
 * reacts from there through the gallery door (R-GAL-06).
 */
export function GalleryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const register = useAuthStore((state) => state.register);
  const login = useAuthStore((state) => state.login);
  const registered = Boolean(user && !user.isAnonymous);
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);

  const current = page?.key === filterKey && page.reader === reader ? page : null;
  const entries = current?.entries ?? [];
  const cursor = current?.cursor ?? null;
  const loading = current === null;

  useEffect(() => {
    if (!hasResolved || signedOut) return;
    let cancelled = false;
    const asked = galleryFiltersFromParams(new URLSearchParams(filterKey));
    void fetchGallery(asked, null)
      .then((fetched) => {
        if (cancelled) return;
        setPage({ key: filterKey, reader, entries: fetched.entries, cursor: fetched.nextCursor });
        setError(null);
      })
      .catch((loadError) => {
        if (!cancelled) setError(refusalText(loadError, ui.galleryPage.couldNotLoadTheGallery));
      });
    return () => { cancelled = true; };
  }, [filterKey, reader, hasResolved, signedOut]);

  const applyFilters = useCallback((next: GalleryFilters) => {
    setSearchParams(paramsFromGalleryFilters(next), { replace: true });
  }, [setSearchParams]);

  async function showMore() {
    if (!cursor || busy) return;
    setBusy(true);
    try {
      const fetched = await fetchGallery(filters, cursor);
      setPage((held) => (held && held.key === filterKey && held.reader === reader
        ? { ...held, entries: [...held.entries, ...fetched.entries], cursor: fetched.nextCursor }
        : held));
    } catch (moreError) {
      setError(refusalText(moreError, ui.galleryPage.couldNotLoadTheGallery));
    } finally {
      setBusy(false);
    }
  }

  const react = async (turnId: string, emoji: string | null) => {
    const result = await setGalleryReaction(turnId, emoji);
    // A reaction changes one entry's counts and the viewer's pick, whichever
    // page holds it now; a reply for a page no longer on screen is dropped.
    setPage((held) => (held
      ? {
          ...held,
          entries: held.entries.map((entry) => (entry.turnId === turnId
            ? { ...entry, reactionCounts: result.reactionCounts, myReaction: result.myReaction }
            : entry)),
        }
      : held));
  };

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

  return (
    <div className="page gallery-page">
      <AppHeader backLabel={ui.galleryPage.backToLobby} languageSwitch />

      {/* A heading block rather than a card, as the community catalogue
          introduces its lists: a title, a filter set, then the results. */}
      <div className="gallery-head">
        <p className="section-label">{ui.galleryPage.eyebrow}</p>
        <h1>{ui.galleryPage.gallery}</h1>
        <p>{ui.galleryPage.drawingsFromPublicGames}</p>
      </div>

      {signedOut ? (
        <p className="gallery-empty" data-testid="gallery-signed-out">{ui.galleryPage.signInToSeeTheGallery}</p>
      ) : (
        <>
          {error && <p className="lobby-action-error" role="alert">{error}</p>}

          <div className="gallery-filters">
            {/* Three orders, all on screen: a menu that has to be opened to
                find out it holds three things is a menu for nothing. */}
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

            {/* The window only means something under Top (R-GAL-04); Hot
                has its own horizon and New is New. */}
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

          {!hasResolved || loading
            ? <p className="gallery-empty">{ui.galleryPage.loading}</p>
            : entries.length === 0
              ? <p className="gallery-empty">{ui.galleryPage.nothingHereYet}</p>
              : <ul className="gallery-grid" data-testid="gallery-grid">
                  {entries.map((entry, index) => (
                    <li key={entry.turnId} className="gallery-card" data-testid="gallery-card">
                      <button
                        type="button"
                        className="gallery-card-open"
                        onClick={() => setOpenIndex(index)}
                        aria-label={ui.galleryPage.openDrawing({
                          prompt: entry.prompt,
                          drawer: entry.drawerDisplayName,
                        })}
                      >
                        <GalleryThumbnail key={entry.turnId} entry={entry} />
                      </button>
                      <div className="gallery-card-caption">
                        <span className="gallery-card-prompt">{entry.prompt}</span>
                        <span className="gallery-card-byline">
                          <strong
                            className="colored-player-name"
                            style={entry.drawerNameColor ? { color: entry.drawerNameColor } : undefined}
                          >
                            {entry.drawerDisplayName}
                          </strong>
                          <ReactionTally reactions={[]} counts={entry.reactionCounts} />
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>}

          {cursor && !loading && <div className="gallery-more">
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              disabled={busy}
              onClick={() => void showMore()}
            >{ui.galleryPage.showMore}</button>
          </div>}
        </>
      )}

      {openIndex !== null && entries.length > 0 && (
        <DrawingRecapGallery
          entries={galleryEntriesAsRecap(entries)}
          initialIndex={Math.min(openIndex, entries.length - 1)}
          onClose={() => setOpenIndex(null)}
          loadEntry={(entry) => fetchGalleryDrawing(entries[entry.index].turnId)}
          renderReactions={(entry) => {
            const shown = entries[entry.index];
            if (!shown) return null;
            return (
              <DrawingReactionControl
                reactions={[]}
                myReactorId={null}
                counts={shown.reactionCounts}
                mine={shown.myReaction}
                eligibility={reactionEligibility({
                  isRegistered: registered,
                  isDrawer: shown.drawnByMe,
                })}
                onReact={(emoji) => react(shown.turnId, emoji)}
                onRequestAccount={() => setAuthMode("claim")}
                placement="panel"
              />
            );
          }}
        />
      )}

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={authMode === "claim" ? user?.displayName ?? "" : ""}
          onClose={() => setAuthMode(null)}
          onSubmit={authSubmitter(authMode, login, register)}
          onSwitchMode={setAuthMode}
        />
      )}
    </div>
  );
}

/**
 * One card's picture: the frame fetched and replayed at thumbnail size, but
 * only once the card has scrolled into view. A page is 24 frames and Show
 * more adds 24 more; replaying every one on arrival is a cost nobody asked
 * for. Without an `IntersectionObserver` (an old browser, a test runtime)
 * it fetches at once, as the pinned shelf does.
 */
function GalleryThumbnail({ entry }: { entry: GalleryEntry }) {
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  const wrapper = useRef<HTMLDivElement | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    if (visible || typeof IntersectionObserver === "undefined") return;
    const element = wrapper.current;
    if (!element) return;
    const observer = new IntersectionObserver((records) => {
      if (records.some((record) => record.isIntersecting)) setVisible(true);
    }, { rootMargin: "200px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  // Keyed by turn id from the parent, so a different entry is a fresh
  // thumbnail rather than one that has to reset its own state in an effect.
  useEffect(() => {
    if (!visible) return;
    const mine = ++generation.current;
    void (async () => {
      try {
        const bytes = await fetchGalleryDrawing(entry.turnId);
        if (mine !== generation.current) return;
        const decoded = decodeCanvasHistory(bytes);
        if (!decoded) {
          setFailed(true);
          return;
        }
        setActions(decoded);
      } catch {
        if (mine !== generation.current) return;
        setFailed(true);
      }
    })();
    return () => {
      generation.current += 1;
    };
  }, [visible, entry.turnId]);

  return (
    <div ref={wrapper} className="gallery-card-canvas" aria-busy={actions === null && !failed}>
      {failed ? (
        <span className="gallery-card-note">{ui.galleryPage.couldNotLoadThisDrawing}</span>
      ) : actions === null ? null : (
        <CanvasSnapshot
          actions={actions}
          label={ui.drawingRecapGallery.drawingLabel({
            prompt: entry.prompt,
            drawer: entry.drawerDisplayName,
          })}
        />
      )}
    </div>
  );
}
