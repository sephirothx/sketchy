import { useState } from "react";
import { EmptyState } from "./ui/EmptyState";
import { DrawingThumbnail } from "./DrawingThumbnail";
import { DrawingReactionControl } from "./DrawingReactionControl";
import { DrawingViewer } from "./DrawingViewer";
import { GalleryFavoriteControl } from "./GalleryFavoriteControl";
import { ReactionTally } from "./ReactionTally";
import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "./icons";
import { refusalText } from "../lib/refusals.ts";
import { fetchFavoriteDrawing, setGalleryReaction } from "../lib/profile";
import { moveFavorite, favoritesAsRecapEntries, withoutFavorite } from "../lib/favorites";
import type { ProfileFavorite } from "../lib/favorites";
import { reactionEligibility } from "../lib/reactions";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/profile.css";

interface FavoritesShelfProps {
  /** Whose shelf: the bytes are fetched through this profile's favorite route. */
  userId: string;
  favorites: ProfileFavorite[];
  /** The owner sees the controls; everyone else a gallery. */
  isOwner: boolean;
  /**
   * Replace the shelf with a new ordered list. The server takes the whole
   * list (R-PIN-02), so move and unfavorite both come through here. Resolves once
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
 * door (R-PIN-08, R-GAL-06) - a favorite is a public-game drawing, so
 * the Gallery shows it already - and the tally counts every reaction while
 * naming only the room's own.
 */
export function FavoritesShelf({
  userId,
  favorites,
  isOwner,
  onReorder,
  disabled = false,
  viewerIsRegistered = false,
  onRequestAccount,
}: FavoritesShelfProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the viewer's own reactions from here left behind, by turn: the
  // shelf's entries come from the parent, and a reaction changes only these.
  const [reacted, setReacted] = useState<
    Record<string, { reactionCounts: Record<string, number>; myReaction: string | null }>
  >({});
  const turnIds = favorites.map((favorite) => favorite.turnId);
  const shown = (favorite: ProfileFavorite): ProfileFavorite =>
    reacted[favorite.turnId] ? { ...favorite, ...reacted[favorite.turnId] } : favorite;

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
      setError(refusalText(changeError, ui.profilePage.couldNotUpdateFavorites));
    } finally {
      setBusy(false);
    }
  };

  // The profile's one empty-state recipe, as the history and the statistics
  // use it: three empty panels on a new profile wore two looks (#1280).
  if (favorites.length === 0) {
    return <EmptyState compact title={ui.profilePage.noFavoritesYet} />;
  }

  return (
    <>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      <ul className="profile-shelf" data-testid="favorites">
        {favorites.map((favorite, index) => (
          <li key={favorite.turnId} className="profile-shelf-item">
            <button
              type="button"
              className="profile-shelf-open"
              onClick={() => setOpenIndex(index)}
              aria-label={ui.profilePage.openFavorite({
                prompt: favorite.prompt,
                drawer: favorite.drawerDisplayName,
              })}
            >
              <FavoriteThumbnail key={favorite.turnId} userId={userId} favorite={favorite} />
            </button>
            <div className="profile-shelf-caption">
              <span className="profile-shelf-prompt">{favorite.prompt}</span>
              <span className="profile-shelf-byline">
                <strong
                  className="colored-player-name"
                  style={favorite.drawerNameColor ? { color: favorite.drawerNameColor } : undefined}
                >
                  {favorite.drawerDisplayName}
                </strong>
                <ReactionTally reactions={favorite.reactions} counts={shown(favorite).reactionCounts} />
              </span>
            </div>
            {isOwner && onReorder && (
              <div className="profile-shelf-controls" role="group" aria-label={favorite.prompt}>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || disabled || index === 0}
                  aria-label={ui.profilePage.moveLeft}
                  title={ui.profilePage.moveLeft}
                  onClick={() => void change(moveFavorite(turnIds, index, -1))}
                >
                  <ChevronLeftIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-compact"
                  disabled={busy || disabled || index === favorites.length - 1}
                  aria-label={ui.profilePage.moveRight}
                  title={ui.profilePage.moveRight}
                  onClick={() => void change(moveFavorite(turnIds, index, 1))}
                >
                  <ChevronRightIcon size={16} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact profile-shelf-unfavorite"
                  disabled={busy || disabled}
                  onClick={() => void change(withoutFavorite(turnIds, favorite.turnId))}
                >
                  <XIcon size={14} />
                  {ui.profilePage.unfavorite}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {openIndex !== null && (
        <DrawingViewer
          entries={favoritesAsRecapEntries(favorites)}
          initialIndex={openIndex}
          onClose={() => setOpenIndex(null)}
          loadEntry={(entry) => fetchFavoriteDrawing(userId, favorites[entry.index].turnId)}
          renderActions={(entry) => {
            // Somebody's favorite is a Gallery drawing, so any registered
            // viewer may make it one of theirs too (#1501); the owner sees
            // theirs filled in, and pressing it takes it off this shelf.
            const favorite = favorites[entry.index];
            return favorite && viewerIsRegistered ? <GalleryFavoriteControl turnId={favorite.turnId} /> : null;
          }}
          renderReactions={(entry) => {
            const favorite = favorites[entry.index];
            if (!favorite) return null;
            const current = shown(favorite);
            return (
              <DrawingReactionControl
                reactions={favorite.reactions.map((reaction) => ({
                  playerId: reaction.seatId,
                  emoji: reaction.emoji,
                }))}
                myReactorId={null}
                counts={current.reactionCounts}
                mine={current.myReaction}
                eligibility={reactionEligibility({
                  isRegistered: viewerIsRegistered,
                  isDrawer: favorite.drawnByMe,
                })}
                onReact={(emoji) => react(favorite.turnId, emoji)}
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

/** One shelf slot, drawn at the slot's size once the shelf is near the
    viewport (`DrawingThumbnail`). Fetched directly rather than through the
    gallery's cache because the shelf shows all six at once, and the gallery
    opens on one. */
function FavoriteThumbnail({ userId, favorite }: { userId: string; favorite: ProfileFavorite }) {
  return (
    <DrawingThumbnail
      drawingKey={`${userId}:${favorite.turnId}`}
      load={() => fetchFavoriteDrawing(userId, favorite.turnId)}
      label={ui.drawingRecapGallery.drawingLabel({
        prompt: favorite.prompt,
        drawer: favorite.drawerDisplayName,
      })}
      className="profile-shelf-canvas"
      noteClassName="profile-note"
      failedText={ui.profilePage.couldNotLoadThisDrawing}
    />
  );
}
