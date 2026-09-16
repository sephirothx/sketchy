import { useEffect, useRef, useState } from "react";
import { CanvasSnapshot } from "./CanvasSnapshot";
import { ReactionTally } from "./ReactionTally";
import { FlagIcon } from "./icons";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { fetchGalleryDrawing, galleryAge, type GalleryEntry } from "../lib/gallery";
import { ui } from "../content/ui/index.ts";

/**
 * The pieces the Gallery's feed and rail share (#524): a card that replays
 * a drawing small once it is on screen. Opening one is a page of its own,
 * `/gallery/{turnId}`, where the drawing replays and the picker lives.
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
 * One post of the Gallery's feed: a framed card - the picture on a mat, the
 * prompt as the title, "by Name" and how long ago beside it, the tally and
 * Report on the mat. The picture is the one control that opens the viewer;
 * the tally is read-only here because the picker lives in the viewer.
 */
export function GalleryPost({
  entry,
  onOpen,
  onReport,
}: {
  entry: GalleryEntry;
  onOpen: () => void;
  /** Absent when the viewer may not report this drawing (their own, or signed out). */
  onReport?: () => void;
}) {
  const age = galleryAge(entry.finishedAt);
  return (
    <li className="gallery-post surface-card" data-testid="gallery-card">
      <button
        type="button"
        className="gallery-post-open"
        onClick={onOpen}
        aria-label={ui.galleryPage.openDrawing({
          prompt: entry.prompt,
          drawer: entry.drawerDisplayName,
        })}
      >
        <GalleryThumbnail key={entry.turnId} entry={entry} />
      </button>
      <div className="gallery-post-mat">
        <div className="gallery-post-caption">
          <h2 className="gallery-post-prompt">{entry.prompt}</h2>
          <span className="gallery-post-byline">
            {ui.galleryPage.byDrawerPrefix}{" "}
            <strong
              className="colored-player-name"
              style={entry.drawerNameColor ? { color: entry.drawerNameColor } : undefined}
            >
              {entry.drawerDisplayName}
            </strong>
            <span className="gallery-post-dot" aria-hidden="true">·</span>
            <span className="gallery-post-age">
              {age ? ui.galleryPage.ago(age) : ui.galleryPage.justNow}
            </span>
          </span>
        </div>
        <div className="gallery-post-actions">
          <ReactionTally reactions={[]} counts={entry.reactionCounts} />
          {onReport && (
            <button
              type="button"
              className="btn btn-ghost btn-compact btn-icon gallery-post-report"
              aria-label={ui.reportDrawingDialog.reportThisDrawing}
              title={ui.reportDrawingDialog.reportThisDrawing}
              data-testid="gallery-post-report"
              onClick={onReport}
            >
              <FlagIcon size={14} />
            </button>
          )}
        </div>
      </div>
    </li>
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
