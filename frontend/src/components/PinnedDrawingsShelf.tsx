import { useEffect, useRef, useState } from "react";
import { CanvasSnapshot } from "./CanvasSnapshot";
import { DrawingRecapGallery } from "./DrawingRecapGallery";
import { ReactionTally } from "./ReactionTally";
import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "./icons";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { refusalText } from "../lib/refusals.ts";
import { fetchPinnedDrawing } from "../lib/profile";
import { movePin, pinsAsRecapEntries, withoutPin } from "../lib/pinnedDrawings";
import type { ProfilePin } from "../lib/pinnedDrawings";
import { ui } from "../content/ui/index.ts";

interface PinnedDrawingsShelfProps {
  /** Whose shelf: the bytes are fetched through this profile's pin route. */
  userId: string;
  pins: ProfilePin[];
  /** The owner sees the controls; everyone else a gallery. */
  isOwner: boolean;
  /**
   * Replace the shelf with a new ordered list. The server takes the whole
   * list (R-PIN-02), so move and unpin both come through here. Resolves once
   * the parent has the server's answer; a rejection is shown by its code.
   */
  onReorder?: (turnIds: string[]) => Promise<void>;
}

/**
 * The drawings a profile chose to show (#440), up to six, in the owner's
 * order. Each is the stored frame replayed small (R-HIST-15 rules out a
 * server-side picture); opening one reuses the recap gallery with the shelf
 * as its entries, and nobody reacts from here - the tally is read-only,
 * because a viewer need not have been in the game.
 */
export function PinnedDrawingsShelf({ userId, pins, isOwner, onReorder }: PinnedDrawingsShelfProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const turnIds = pins.map((pin) => pin.turnId);

  const change = async (next: string[]) => {
    if (!onReorder || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onReorder(next);
    } catch (changeError) {
      // The server's sentence is for a log; the player's comes from the
      // catalogue by code, or is the generic one (R-I18N-01).
      setError(refusalText(changeError, ui.profilePage.couldNotUpdatePinnedDrawings));
    } finally {
      setBusy(false);
    }
  };

  if (pins.length === 0) {
    return (
      <p className="profile-note profile-shelf-empty">{ui.profilePage.nothingPinnedYet}</p>
    );
  }

  return (
    <>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      <ul className="profile-shelf" data-testid="pinned-drawings">
        {pins.map((pin, index) => (
          <li key={pin.turnId} className="profile-shelf-item">
            <button
              type="button"
              className="profile-shelf-open"
              onClick={() => setOpenIndex(index)}
              aria-label={ui.profilePage.openPinnedDrawing({
                prompt: pin.prompt,
                drawer: pin.drawerDisplayName,
              })}
            >
              <PinnedThumbnail key={pin.turnId} userId={userId} pin={pin} />
            </button>
            <div className="profile-shelf-caption">
              <span className="profile-shelf-prompt">{pin.prompt}</span>
              <span className="profile-shelf-byline">
                <strong
                  className="colored-player-name"
                  style={pin.drawerNameColor ? { color: pin.drawerNameColor } : undefined}
                >
                  {pin.drawerDisplayName}
                </strong>
                <ReactionTally reactions={pin.reactions} />
              </span>
            </div>
            {isOwner && onReorder && (
              <div className="profile-shelf-controls" role="group" aria-label={pin.prompt}>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || index === 0}
                  aria-label={ui.profilePage.moveLeft}
                  title={ui.profilePage.moveLeft}
                  onClick={() => void change(movePin(turnIds, index, -1))}
                >
                  <ChevronLeftIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || index === pins.length - 1}
                  aria-label={ui.profilePage.moveRight}
                  title={ui.profilePage.moveRight}
                  onClick={() => void change(movePin(turnIds, index, 1))}
                >
                  <ChevronRightIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact profile-shelf-unpin"
                  disabled={busy}
                  onClick={() => void change(withoutPin(turnIds, pin.turnId))}
                >
                  <XIcon size={14} />
                  {ui.profilePage.unpin}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {openIndex !== null && (
        <DrawingRecapGallery
          entries={pinsAsRecapEntries(pins)}
          initialIndex={openIndex}
          onClose={() => setOpenIndex(null)}
          loadEntry={(entry) => fetchPinnedDrawing(userId, pins[entry.index].turnId)}
          renderReactions={(entry) => (
            <ReactionTally reactions={pins[entry.index]?.reactions ?? []} />
          )}
        />
      )}
    </>
  );
}

/**
 * One shelf slot: the frame fetched and replayed at thumbnail size. Fetched
 * on mount rather than through the gallery's cache because the shelf shows
 * all six at once, and the gallery opens on one.
 */
function PinnedThumbnail({ userId, pin }: { userId: string; pin: ProfilePin }) {
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const generation = useRef(0);

  // Keyed by turn id from the parent, so a different pin is a fresh
  // thumbnail rather than one that has to reset its own state in an effect.
  useEffect(() => {
    const mine = ++generation.current;
    void (async () => {
      try {
        const bytes = await fetchPinnedDrawing(userId, pin.turnId);
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
  }, [userId, pin.turnId]);

  return (
    <div className="profile-shelf-canvas" aria-busy={actions === null && !failed}>
      {failed ? (
        <span className="profile-note">{ui.profilePage.couldNotLoadThisDrawing}</span>
      ) : actions === null ? null : (
        <CanvasSnapshot
          actions={actions}
          label={ui.drawingRecapGallery.drawingLabel({
            prompt: pin.prompt,
            drawer: pin.drawerDisplayName,
          })}
        />
      )}
    </div>
  );
}
