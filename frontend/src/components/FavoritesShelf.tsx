import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { EmptyState } from "./ui/EmptyState";
import { DrawingThumbnail } from "./DrawingThumbnail";
import { DrawingReactionControl } from "./DrawingReactionControl";
import { DrawingViewer } from "./DrawingViewer";
import { GalleryFavoriteControl } from "./GalleryFavoriteControl";
import { ReactionTally } from "./ReactionTally";
import { CheckIcon, GripIcon, StarIcon, XIcon } from "./icons";
import { refusalText } from "../lib/refusals.ts";
import { ApiError } from "../lib/api";
import { fetchGalleryDrawing } from "../lib/gallery";
import { fetchFavoriteDrawing, setGalleryReaction } from "../lib/profile";
import {
  FAVORITE_SLOTS,
  favoritesAsRecapEntries,
  hiddenPromptShape,
  moveFavoriteTo,
  withoutFavorite,
} from "../lib/favorites";
import type { ProfileFavorite } from "../lib/favorites";
import { reactionEligibility } from "../lib/reactions";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/profile.css";

/** How far a press travels before it becomes a drag, so a tap never moves anything. */
const DRAG_THRESHOLD_PX = 6;

interface FavoritesShelfProps {
  /** Whose shelf: the bytes are fetched through this profile's favorite route. */
  userId: string;
  favorites: ProfileFavorite[];
  /** The owner sees the prompts and arranges; everyone else guesses first. */
  isOwner: boolean;
  /**
   * Replace the shelf with a new ordered list. The server takes the whole
   * list (R-PIN-02), so a move and a removal both come through here. Resolves
   * once the parent has the server's answer; a rejection is shown by its code.
   */
  onReorder?: (turnIds: string[]) => Promise<void>;
  /** The owner's controls held while the shelf is read or another write is out. */
  disabled?: boolean;
  /** Whether the viewer may react: a registered account (R-REACT-01). */
  viewerIsRegistered?: boolean;
  /** Guests: how to become able to react. */
  onRequestAccount?: () => void;
}

interface Drag {
  turnId: string;
  pointerId: number;
  from: number;
  to: number;
  moving: boolean;
  startX: number;
  startY: number;
  dx: number;
  dy: number;
  /** Where each place on the shelf stood when the drag began. */
  slots: DOMRect[];
}

/** A `translate` value of x and y pixels. */
function cssOffset(x: number, y: number): string {
  return [x, y].map((value) => `${value}px`).join(" ");
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * A profile's **Favorites** (#440, #1501): up to six drawings in the owner's
 * order, framed three across (two on a phone).
 *
 * A visitor sees each prompt as blank letter tiles, the game's own mask, and
 * taps them to see it - a favorite is somebody's best drawing, and guessing
 * it first is the point of looking. Nothing is remembered: the next visit
 * guesses again. The owner sees the prompts, since they arrange by them.
 *
 * The owner arranges in a mode of its own (*Arrange*), so a swipe across the
 * shelf on a phone never moves a drawing by accident. In it a drawing is
 * dragged by any part of it with a mouse, a pen or a finger - the others make
 * room as it passes and slide into place when it lands - and every drawing
 * has a handle for everyone else: Space (or a tap) lifts it, the arrow keys
 * or a tap on another place move it there, Space drops it (WCAG 2.5.7's
 * single-pointer alternative, and a keyboard's way). Each landing is one
 * write of the whole list (R-PIN-02), and is announced.
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
  // The shelf as it was when the viewer opened: removing the drawing on
  // screen from one's own favorites must not slide the viewer onto the next
  // one, whose star a second press would then take off too.
  const [viewing, setViewing] = useState<{ favorites: ProfileFavorite[]; index: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [arrangeOn, setArranging] = useState(false);
  // The order while a drawing is lifted or a write is out; null is the shelf's own.
  const [draft, setDraft] = useState<string[] | null>(null);
  const [lifted, setLifted] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(() => new Set());
  const [announcement, setAnnouncement] = useState("");
  // What the viewer's own reactions from here left behind, by turn: the
  // shelf's entries come from the parent, and a reaction changes only these.
  const [reacted, setReacted] = useState<
    Record<string, { reactionCounts: Record<string, number>; myReaction: string | null }>
  >({});
  const itemRefs = useRef(new Map<string, HTMLLIElement>());
  const handleRefs = useRef(new Map<string, HTMLButtonElement>());
  const dragRef = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const drawnAt = useRef(new Map<string, DOMRect>());
  const arrangeButton = useRef<HTMLButtonElement | null>(null);
  // Where the keyboard goes once a removal has re-rendered the shelf.
  const refocus = useRef<string | null>(null);

  const byId = new Map(favorites.map((favorite) => [favorite.turnId, favorite]));
  const turnIds = favorites.map((favorite) => favorite.turnId);
  // The order while something is lifted or written, with any favorite that
  // arrived meanwhile after it rather than left out of the next write.
  const order = draft
    ? [...draft.filter((id) => byId.has(id)), ...turnIds.filter((id) => !draft.includes(id))]
    : turnIds;
  const preview = drag?.moving ? moveFavoriteTo(order, drag.turnId, drag.to) : order;
  const canArrange = isOwner && Boolean(onReorder);
  // An emptied shelf ends the mode, however it was emptied - the last
  // removal here, a star elsewhere, a drawing leaving the Gallery - so it
  // does not come back on its own when the shelf fills again.
  const [shelfWasEmpty, setShelfWasEmpty] = useState(favorites.length === 0);
  if ((favorites.length === 0) !== shelfWasEmpty) {
    setShelfWasEmpty(favorites.length === 0);
    if (favorites.length === 0) setArranging(false);
  }
  const arranging = arrangeOn && canArrange && favorites.length > 0;
  const held = busy || disabled;
  const shown = (favorite: ProfileFavorite): ProfileFavorite =>
    reacted[favorite.turnId] ? { ...favorite, ...reacted[favorite.turnId] } : favorite;
  const promptShown = (turnId: string) => isOwner || revealed.has(turnId);
  const reveal = (turnId: string) => setRevealed((current) => new Set(current).add(turnId));

  // Every drawing slides from where it was drawn to its new place (FLIP),
  // except the one under the pointer, which stays with it.
  const orderKey = preview.join(",");
  useLayoutEffect(() => {
    const before = drawnAt.current;
    const now = new Map<string, DOMRect>();
    for (const [turnId, item] of itemRefs.current) now.set(turnId, item.getBoundingClientRect());
    drawnAt.current = now;
    if (prefersReducedMotion()) return;
    for (const [turnId, item] of itemRefs.current) {
      const from = before.get(turnId);
      const to = now.get(turnId);
      if (!from || !to || turnId === dragRef.current?.turnId) continue;
      const dx = from.left - to.left;
      const dy = from.top - to.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
      item.style.transition = "none";
      item.style.translate = cssOffset(dx, dy);
      void item.offsetHeight;
      item.style.transition = "";
      item.style.translate = "";
    }
  }, [orderKey]);

  // A lifted drawing keeps the keyboard's focus as it moves, and a removal
  // hands it to a neighbour.
  useEffect(() => {
    if (lifted) handleRefs.current.get(lifted)?.focus();
    const next = refocus.current;
    if (next && !lifted) {
      const target = next === "arrange" ? arrangeButton.current : handleRefs.current.get(next);
      if (target) {
        refocus.current = null;
        target.focus();
      }
    }
  }, [lifted, orderKey]);

  const react = async (turnId: string, emoji: string | null) => {
    const result = await setGalleryReaction(turnId, emoji);
    setReacted((current) => ({
      ...current,
      [turnId]: { reactionCounts: result.reactionCounts, myReaction: result.myReaction },
    }));
  };

  const change = async (next: string[]) => {
    if (!onReorder || held) return;
    setBusy(true);
    setError(null);
    setDraft(next);
    try {
      await onReorder(next);
    } catch (changeError) {
      // The server's sentence is for a log; the player's comes from the
      // catalogue by code, or is the generic one (R-I18N-01).
      setError(refusalText(changeError, ui.profilePage.couldNotUpdateFavorites));
    } finally {
      setDraft(null);
      setBusy(false);
    }
  };

  const promptOf = (turnId: string) => byId.get(turnId)?.prompt ?? "";
  const announcePlace = (turnId: string, list: string[], say: typeof ui.profilePage.favoriteMoved) =>
    setAnnouncement(say({ prompt: promptOf(turnId), position: list.indexOf(turnId) + 1, total: list.length }));

  /** Put down what is lifted, writing the order it is in if that moved anything. */
  const drop = (turnId: string, list: string[]) => {
    // While a write is out the drawing stays lifted, to be dropped again.
    if (held) return;
    setLifted(null);
    announcePlace(turnId, list, ui.profilePage.favoriteDropped);
    if (list.join(",") === turnIds.join(",")) {
      setDraft(null);
      return;
    }
    void change(list);
  };

  const toggleLift = (turnId: string) => {
    if (held || suppressClick.current) return;
    if (lifted === turnId) {
      drop(turnId, order);
      return;
    }
    // Another drawing's handle is a place, as the drawing itself is.
    if (lifted) {
      drop(lifted, moveFavoriteTo(order, lifted, order.indexOf(turnId)));
      return;
    }
    setLifted(turnId);
    announcePlace(turnId, order, ui.profilePage.favoritePickedUp);
  };

  const onHandleKey = (event: ReactKeyboardEvent<HTMLButtonElement>, turnId: string) => {
    if (lifted !== turnId || held) return;
    const at = order.indexOf(turnId);
    const delta =
      event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1
        : event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
          : 0;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setLifted(null);
      setDraft(null);
      announcePlace(turnId, turnIds, ui.profilePage.favoriteDropped);
      return;
    }
    if (!delta) return;
    event.preventDefault();
    const next = moveFavoriteTo(order, turnId, at + delta);
    setDraft(next);
    announcePlace(turnId, next, ui.profilePage.favoriteMoved);
  };

  const remove = (turnId: string) => {
    if (held) return;
    setLifted(null);
    // The last one out ends the mode, rather than leaving it to come back
    // on its own the next time the shelf has something on it.
    if (order.length === 1) setArranging(false);
    setAnnouncement(ui.profilePage.favoriteRemoved({ prompt: promptOf(turnId) }));
    // The keyboard stays on the shelf: the next drawing's handle, or the one
    // before, or the heading's button once nothing is left.
    const at = order.indexOf(turnId);
    refocus.current = order[at + 1] ?? order[at - 1] ?? "arrange";
    void change(withoutFavorite(order, turnId));
  };

  // What a drag that ends later reads: the shelf and the hold as they are
  // then, not as they were at the press.
  const latest = useRef({ drop, order });
  useLayoutEffect(() => {
    latest.current = { drop, order };
  });

  /** The place nearest the dragged drawing's centre, among where they stood. */
  const placeFor = (current: Drag): number => {
    const own = current.slots[current.from];
    const x = own.left + own.width / 2 + current.dx;
    const y = own.top + own.height / 2 + current.dy;
    let best = current.from;
    let bestDistance = Number.POSITIVE_INFINITY;
    current.slots.forEach((slot, index) => {
      const distance = Math.hypot(slot.left + slot.width / 2 - x, slot.top + slot.height / 2 - y);
      if (distance < bestDistance) {
        best = index;
        bestDistance = distance;
      }
    });
    return best;
  };

  const updateDrag = (next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  };

  // The pointer is followed on the window, not captured: a capture would send
  // the click a tap ends in to the frame rather than the button under it. The
  // listeners go on in the press itself rather than in an effect after it, so
  // a quick drag cannot finish before anything is listening.
  const stopFollowing = useRef<(() => void) | null>(null);
  useEffect(() => () => stopFollowing.current?.(), []);

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>, turnId: string) => {
    if (!arranging || held || !event.isPrimary || event.button !== 0 || dragRef.current) return;
    // The remove button is a button of its own.
    if ((event.target as HTMLElement).closest(".profile-shelf-remove")) return;
    // Where the places are, not where a slide still running draws them.
    for (const item of itemRefs.current.values()) {
      item.style.transition = "none";
      item.style.translate = "";
    }
    const slots = order.map((id) => itemRefs.current.get(id)?.getBoundingClientRect() ?? new DOMRect());
    for (const item of itemRefs.current.values()) item.style.transition = "";
    const from = order.indexOf(turnId);
    const pointerId = event.pointerId;
    updateDrag({
      turnId,
      pointerId,
      from,
      to: from,
      moving: false,
      startX: event.clientX,
      startY: event.clientY,
      dx: 0,
      dy: 0,
      slots,
    });
    const move = (moved: PointerEvent) => {
      const current = dragRef.current;
      if (!current || moved.pointerId !== pointerId) return;
      const dx = moved.clientX - current.startX;
      const dy = moved.clientY - current.startY;
      if (!current.moving && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      moved.preventDefault();
      const next = { ...current, moving: true, dx, dy };
      next.to = placeFor(next);
      updateDrag(next);
    };
    const end = (ended: PointerEvent) => {
      const current = dragRef.current;
      if (!current || ended.pointerId !== pointerId) return;
      stop();
      updateDrag(null);
      if (!current.moving) return;
      // The click this pointer-up makes is the drop, not a tap on the drawing.
      suppressClick.current = true;
      window.setTimeout(() => {
        suppressClick.current = false;
      }, 0);
      latest.current.drop(current.turnId, moveFavoriteTo(latest.current.order, current.turnId, current.to));
    };
    const cancel = (cancelled: PointerEvent) => {
      if (cancelled.pointerId !== pointerId) return;
      stop();
      updateDrag(null);
    };
    function stop() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", cancel);
      stopFollowing.current = null;
    }
    stopFollowing.current?.();
    stopFollowing.current = stop;
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", cancel);
  };

  const pressDrawing = (turnId: string, index: number) => {
    if (suppressClick.current) return;
    if (!arranging) {
      setViewing({ favorites, index: favorites.findIndex((favorite) => favorite.turnId === turnId) });
      return;
    }
    // A tap on a place puts the lifted drawing there: the single-pointer way.
    if (lifted && lifted !== turnId) {
      drop(lifted, moveFavoriteTo(order, lifted, index));
    } else if (lifted === turnId) {
      drop(turnId, order);
    }
  };

  const finishArranging = () => {
    if (lifted) drop(lifted, order);
    setArranging(false);
  };

  const hint = !isOwner
    ? ui.profilePage.favoritesHintVisitor
    : arranging
      ? ui.profilePage.favoritesHintArranging
      : ui.profilePage.favoritesHintOwner;

  return (
    <>
      <div className="profile-shelf-head">
        <h2 className="profile-shelf-title">
          <span className="profile-shelf-star" aria-hidden="true"><StarIcon size={20} /></span>
          {ui.profilePage.favorites}
        </h2>
        {isOwner && favorites.length > 0 && (
          <span className="profile-shelf-count">
            {ui.profilePage.favoritesCount({ count: favorites.length, slots: FAVORITE_SLOTS })}
          </span>
        )}
        {canArrange && favorites.length > 0 && (
          arranging ? (
            <button
              ref={arrangeButton}
              type="button"
              className="btn btn-primary btn-compact profile-shelf-arrange"
              onClick={finishArranging}
            >
              <CheckIcon size={16} />
              {ui.profilePage.doneArranging}
            </button>
          ) : (
            <button
              ref={arrangeButton}
              type="button"
              className="btn btn-secondary btn-compact profile-shelf-arrange"
              disabled={disabled}
              onClick={() => setArranging(true)}
            >
              <GripIcon size={16} />
              {ui.profilePage.arrangeFavorites}
            </button>
          )
        )}
      </div>
      {favorites.length === 0 ? (
        // The profile's one empty-state recipe, as the history and the
        // statistics use it: three empty panels on a new profile wore two
        // looks (#1280).
        <EmptyState compact title={ui.profilePage.noFavoritesYet} />
      ) : (
        <>
          <p className="profile-shelf-hint">{hint}</p>
          {error && <p className="lobby-action-error" role="alert">{error}</p>}
          <ul
            className={`profile-shelf${arranging ? " is-arranging" : ""}${drag?.moving ? " is-dragging" : ""}`}
            data-testid="favorites"
          >
            {preview.map((turnId, index) => {
              const favorite = byId.get(turnId);
              if (!favorite) return null;
              const visible = promptShown(turnId);
              const dragging = drag?.moving && drag.turnId === turnId ? drag : null;
              // The dragged drawing is laid out in the place it would land and
              // drawn under the pointer: its own place, moved by the pointer.
              const style = dragging
                ? {
                    translate: cssOffset(
                      dragging.slots[dragging.from].left - dragging.slots[dragging.to].left + dragging.dx,
                      dragging.slots[dragging.from].top - dragging.slots[dragging.to].top + dragging.dy,
                    ),
                  }
                : undefined;
              return (
                <li
                  key={turnId}
                  ref={(element) => {
                    if (element) itemRefs.current.set(turnId, element);
                    else itemRefs.current.delete(turnId);
                  }}
                  className={`profile-shelf-item${lifted === turnId ? " is-lifted" : ""}${dragging ? " is-dragging" : ""}`}
                  style={style}
                  data-turn-id={turnId}
                >
                  <div
                    className="profile-shelf-frame"
                    onPointerDown={(event) => startDrag(event, turnId)}
                    // A long press would open the picture's own menu and cancel the drag.
                    onContextMenu={arranging ? (event) => event.preventDefault() : undefined}
                  >
                    <button
                      type="button"
                      className="profile-shelf-open"
                      onClick={() => pressDrawing(turnId, index)}
                      aria-label={
                        visible
                          ? ui.profilePage.openFavorite({ prompt: favorite.prompt, drawer: favorite.drawerDisplayName })
                          : ui.profilePage.aDrawingBy({ drawer: favorite.drawerDisplayName })
                      }
                    >
                      <FavoriteThumbnail userId={userId} favorite={favorite} labelled={visible} />
                    </button>
                    {arranging && (
                      <>
                        <button
                          type="button"
                          ref={(element) => {
                            if (element) handleRefs.current.set(turnId, element);
                            else handleRefs.current.delete(turnId);
                          }}
                          className="profile-shelf-handle"
                          aria-label={ui.profilePage.moveFavorite({
                            prompt: favorite.prompt,
                            position: index + 1,
                            total: preview.length,
                          })}
                          aria-pressed={lifted === turnId}
                          // Not disabled while a write is out: a disabled
                          // button drops the keyboard's focus.
                          aria-disabled={held}
                          onClick={() => toggleLift(turnId)}
                          onKeyDown={(event) => onHandleKey(event, turnId)}
                        >
                          <GripIcon size={16} />
                          <span aria-hidden="true">{index + 1}</span>
                        </button>
                        <button
                          type="button"
                          className="profile-shelf-remove"
                          aria-label={ui.profilePage.removeFavorite({ prompt: favorite.prompt })}
                          title={ui.profilePage.removeFavorite({ prompt: favorite.prompt })}
                          disabled={held}
                          onClick={() => remove(turnId)}
                        >
                          <XIcon size={16} />
                        </button>
                      </>
                    )}
                  </div>
                  <div className="profile-shelf-caption">
                    {visible ? (
                      <span className="profile-shelf-prompt">{favorite.prompt}</span>
                    ) : (
                      <HiddenPrompt prompt={favorite.prompt} onReveal={() => reveal(turnId)} />
                    )}
                    <span className="profile-shelf-byline">
                      <span className="profile-shelf-drawer">
                        {ui.galleryPage.byDrawerPrefix}{" "}
                        <strong
                          className="colored-player-name"
                          style={favorite.drawerNameColor ? { color: favorite.drawerNameColor } : undefined}
                        >
                          {favorite.drawerDisplayName}
                        </strong>
                      </span>
                      <ReactionTally reactions={favorite.reactions} counts={shown(favorite).reactionCounts} />
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
          <span className="visually-hidden" role="status" aria-live="polite">
            {announcement}
          </span>
        </>
      )}
      {viewing && (
        <DrawingViewer
          entries={favoritesAsRecapEntries(viewing.favorites).map((entry, at) =>
            promptShown(viewing.favorites[at].turnId)
              ? entry
              : {
                  ...entry,
                  // Every label the viewer reads names the prompt; a hidden
                  // one names the mask instead, and so does a saved image.
                  prompt: ui.promptDisplay.maskedPrompt({
                    shape: hiddenPromptShape(entry.prompt).counts.join(", "),
                  }),
                },
          )}
          initialIndex={viewing.index}
          onClose={() => setViewing(null)}
          // A drawing taken off this shelf while the viewer is open is still
          // in the Gallery, and read from there.
          loadEntry={(entry) =>
            fetchFavoriteDrawing(userId, viewing.favorites[entry.index].turnId).catch((failure: unknown) => {
              if (failure instanceof ApiError && failure.status === 404) {
                return fetchGalleryDrawing(viewing.favorites[entry.index].turnId);
              }
              throw failure;
            })
          }
          renderPrompt={(entry) => {
            const favorite = viewing.favorites[entry.index];
            if (!favorite || promptShown(favorite.turnId)) return favorite?.prompt ?? entry.prompt;
            return <HiddenPrompt prompt={favorite.prompt} onReveal={() => reveal(favorite.turnId)} large />;
          }}
          renderActions={(entry) => {
            // Somebody's favorite is a Gallery drawing, so any registered
            // viewer may make it one of theirs too (#1501); the owner sees
            // theirs filled in, and pressing it takes it off this shelf.
            const favorite = viewing.favorites[entry.index];
            return favorite && viewerIsRegistered ? <GalleryFavoriteControl turnId={favorite.turnId} /> : null;
          }}
          renderReactions={(entry) => {
            const favorite = viewing.favorites[entry.index];
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

/**
 * A prompt not yet seen: a blank tile per letter, words and punctuation kept
 * (`hiddenPromptShape`), as one button that shows it. Its name says how many
 * letters, which is what the tiles say to anyone looking.
 */
export function HiddenPrompt({
  prompt,
  onReveal,
  large = false,
}: {
  prompt: string;
  onReveal: () => void;
  large?: boolean;
}) {
  const { words, counts } = hiddenPromptShape(prompt);
  const label = ui.profilePage.showThePrompt({ shape: counts.join(", ") });
  return (
    <button
      type="button"
      className={`hidden-prompt${large ? " is-large" : ""}`}
      aria-label={label}
      title={label}
      onClick={onReveal}
    >
      {words.map((segments, wordIndex) => (
        <span key={wordIndex} className="hidden-prompt-word" aria-hidden="true">
          {segments.map((segment, segmentIndex) =>
            segment.kind === "glyph" ? (
              <span key={segmentIndex} className="hidden-prompt-glyph">{segment.text}</span>
            ) : (
              segment.chars.map((_, charIndex) => (
                <span key={`${segmentIndex}-${charIndex}`} className="hidden-prompt-tile" />
              ))
            ),
          )}
        </span>
      ))}
    </button>
  );
}

/** One shelf slot, drawn at the slot's size once the shelf is near the
    viewport (`DrawingThumbnail`). Fetched directly rather than through the
    gallery's cache because the shelf shows all six at once, and the gallery
    opens on one. */
function FavoriteThumbnail({
  userId,
  favorite,
  labelled,
}: {
  userId: string;
  favorite: ProfileFavorite;
  labelled: boolean;
}) {
  return (
    <DrawingThumbnail
      drawingKey={`${userId}:${favorite.turnId}`}
      load={() => fetchFavoriteDrawing(userId, favorite.turnId)}
      label={
        labelled
          ? ui.drawingRecapGallery.drawingLabel({ prompt: favorite.prompt, drawer: favorite.drawerDisplayName })
          : ui.profilePage.aDrawingBy({ drawer: favorite.drawerDisplayName })
      }
      className="profile-shelf-canvas"
      noteClassName="profile-note"
      failedText={ui.profilePage.couldNotLoadThisDrawing}
    />
  );
}
