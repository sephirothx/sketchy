import { DrawingThumbnail } from "./DrawingThumbnail";
import { ReactionTally } from "./ReactionTally";
import { FlagIcon } from "./icons";
import { fetchGalleryDrawing, galleryAge, type GalleryEntry } from "../lib/gallery";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/gallery.css";

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

/** One card's picture, fetched once the card is within a screen of view and
    drawn at the card's size (`DrawingThumbnail`). */
export function GalleryThumbnail({ entry }: { entry: GalleryEntry }) {
  return (
    <DrawingThumbnail
      drawingKey={entry.turnId}
      load={() => fetchGalleryDrawing(entry.turnId)}
      label={ui.drawingRecapGallery.drawingLabel({
        prompt: entry.prompt,
        drawer: entry.drawerDisplayName,
      })}
      className="gallery-card-canvas"
      noteClassName="gallery-card-note"
      failedText={ui.galleryPage.couldNotLoadThisDrawing}
    />
  );
}
