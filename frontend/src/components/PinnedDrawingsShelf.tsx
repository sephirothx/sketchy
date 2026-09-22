import { useEffect, useRef, useState } from "react";
import { CanvasSnapshot } from "./CanvasSnapshot";
import { DrawingReactionControl } from "./DrawingReactionControl";
import { DrawingRecapGallery } from "./DrawingRecapGallery";
import { ReactionTally } from "./ReactionTally";
import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "./icons";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { refusalText } from "../lib/refusals.ts";
import { fetchPinnedDrawing, setGalleryReaction } from "../lib/profile";
import { movePin, pinsAsRecapEntries, withoutPin } from "../lib/pinnedDrawings";
import type { ProfilePin } from "../lib/pinnedDrawings";
import { reactionEligibility } from "../lib/reactions";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/profile.css";

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
  /** The owner's controls held while the shelf is read or another write is out. */
  disabled?: boolean;
  /** Whether the viewer may react: a registered account (R-REACT-01). */
  viewerIsRegistered?: boolean;
  /** Guests: how to become able to react. */
  onRequestAccount?: () => void;
}

/**
 * The drawings a profile chose to show (#440), up to six, in the owner's
 * order. Each is the stored frame replayed small (R-HIST-15 rules out a
 * server-side picture); opening one reuses the recap gallery with the shelf
 * as its entries. A registered viewer reacts from there through the gallery
 * door (R-PIN-08, R-GAL-06) - a pinned drawing is a public-game drawing, so
 * the Gallery shows it already - and the tally counts every reaction while
 * naming only the room's own.
 */
export function PinnedDrawingsShelf({
  userId,
  pins,
  isOwner,
  onReorder,
  disabled = false,
  viewerIsRegistered = false,
  onRequestAccount,
}: PinnedDrawingsShelfProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the viewer's own reactions from here left behind, by turn: the
  // shelf's entries come from the parent, and a reaction changes only these.
  const [reacted, setReacted] = useState<
    Record<string, { reactionCounts: Record<string, number>; myReaction: string | null }>
  >({});
  const turnIds = pins.map((pin) => pin.turnId);
  const shown = (pin: ProfilePin): ProfilePin =>
    reacted[pin.turnId] ? { ...pin, ...reacted[pin.turnId] } : pin;

  const react = async (turnId: string, emoji: string | null) => {
    const result = await setGalleryReaction(turnId, emoji);
    setReacted((current) => ({
      ...current,
      [turnId]: { reactionCounts: result.reactionCounts, myReaction: result.myReaction },
    }));
  };

  const change = async (next: string[]) => {
    if (!onReorder || busy || disabled) return;
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
                <ReactionTally reactions={pin.reactions} counts={shown(pin).reactionCounts} />
              </span>
            </div>
            {isOwner && onReorder && (
              <div className="profile-shelf-controls" role="group" aria-label={pin.prompt}>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || disabled || index === 0}
                  aria-label={ui.profilePage.moveLeft}
                  title={ui.profilePage.moveLeft}
                  onClick={() => void change(movePin(turnIds, index, -1))}
                >
                  <ChevronLeftIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || disabled || index === pins.length - 1}
                  aria-label={ui.profilePage.moveRight}
                  title={ui.profilePage.moveRight}
                  onClick={() => void change(movePin(turnIds, index, 1))}
                >
                  <ChevronRightIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact profile-shelf-unpin"
                  disabled={busy || disabled}
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
          renderReactions={(entry) => {
            const pin = pins[entry.index];
            if (!pin) return null;
            const current = shown(pin);
            return (
              <DrawingReactionControl
                reactions={pin.reactions.map((reaction) => ({
                  playerId: reaction.seatId,
                  emoji: reaction.emoji,
                }))}
                myReactorId={null}
                counts={current.reactionCounts}
                mine={current.myReaction}
                eligibility={reactionEligibility({
                  isRegistered: viewerIsRegistered,
                  isDrawer: pin.drawnByMe,
                })}
                onReact={(emoji) => react(pin.turnId, emoji)}
                onRequestAccount={onRequestAccount}
                placement="panel"
              />
            );
          }}
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
