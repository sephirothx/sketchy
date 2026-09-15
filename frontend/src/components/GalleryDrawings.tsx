import { useEffect, useRef, useState } from "react";
import { AuthDialog } from "./AccountMenu";
import { CanvasSnapshot } from "./CanvasSnapshot";
import { DrawingReactionControl } from "./DrawingReactionControl";
import { DrawingRecapGallery } from "./DrawingRecapGallery";
import { ReactionTally } from "./ReactionTally";
import { ReportDrawingDialog } from "./ReportDrawingDialog";
import { FlagIcon } from "./icons";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { fetchGalleryDrawing, galleryEntriesAsRecap, type GalleryEntry } from "../lib/gallery";
import { setGalleryReaction } from "../lib/profile";
import { reactionEligibility } from "../lib/reactions";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

/**
 * The pieces the Gallery page and the lobby's **This week** shelf share
 * (#524): a card that replays a drawing small once it is on screen, and the
 * viewer that opens one with the reaction picker through the gallery door.
 */

/** One card: the picture as a button, then the prompt and the byline. */
export function GalleryCard({
  entry,
  onOpen,
}: {
  entry: GalleryEntry;
  onOpen: () => void;
}) {
  return (
    <li className="gallery-card" data-testid="gallery-card">
      <button
        type="button"
        className="gallery-card-open"
        onClick={onOpen}
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
  );
}

/**
 * The recap viewer over a list of gallery entries, with the reaction picker
 * through the gallery door (R-GAL-06). `onReacted` hands back the entry as
 * the server now describes it, so the caller keeps its own list current.
 * A guest who presses the picker is offered an account here, with the
 * dialog the rest of the app uses.
 */
export function GalleryViewer({
  entries,
  openIndex,
  onClose,
  onReacted,
}: {
  entries: GalleryEntry[];
  openIndex: number;
  onClose: () => void;
  onReacted: (entry: GalleryEntry) => void;
}) {
  const user = useAuthStore((state) => state.user);
  const register = useAuthStore((state) => state.register);
  const login = useAuthStore((state) => state.login);
  const registered = Boolean(user && !user.isAnonymous);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  // Which drawing is being reported, by turn: the viewer pages between
  // entries, and a dialog keyed to the one it was opened on stays about it.
  const [reporting, setReporting] = useState<string | null>(null);

  const react = async (entry: GalleryEntry, emoji: string | null) => {
    const result = await setGalleryReaction(entry.turnId, emoji);
    onReacted({ ...entry, reactionCounts: result.reactionCounts, myReaction: result.myReaction });
  };

  if (entries.length === 0) return null;
  return (
    <>
      <DrawingRecapGallery
        entries={galleryEntriesAsRecap(entries)}
        initialIndex={Math.min(openIndex, entries.length - 1)}
        onClose={onClose}
        loadEntry={(entry) => fetchGalleryDrawing(entries[entry.index].turnId)}
        renderActions={(entry) => {
          const shown = entries[entry.index];
          // Anyone signed in, a guest included (R-MOD-01): the server takes
          // a report from every live account, and a guest who sees something
          // wrong is no less a witness. Never the drawer's own work - there
          // is nothing to complain to themselves about.
          if (!shown || !user || shown.drawnByMe) return null;
          return (
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              data-testid="gallery-report"
              onClick={() => setReporting(shown.turnId)}
            >
              <FlagIcon size={14} />
              {ui.reportDrawingDialog.report}
            </button>
          );
        }}
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
              onReact={(emoji) => react(shown, emoji)}
              onRequestAccount={() => setAuthMode("claim")}
              placement="panel"
            />
          );
        }}
      />
      {reporting && (
        <ReportDrawingDialog turnId={reporting} onClose={() => setReporting(null)} />
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
    </>
  );
}

/**
 * One card's picture: the frame fetched and replayed at thumbnail size, but
 * only once the card has scrolled into view. A page is 24 frames and Show
 * more adds 24 more; replaying every one on arrival is a cost nobody asked
 * for. Without an `IntersectionObserver` (an old browser, a test runtime)
 * it fetches at once, as the pinned shelf does.
 */
export function GalleryThumbnail({ entry }: { entry: GalleryEntry }) {
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
