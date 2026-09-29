/** When a drawing thumbnail asks the queue for its picture again (#1282).

A card whose job the queue dropped while it was still in view must not ask
again at once: its request takes the place of another waiting card, whose
drop makes it ask at once in turn - a churn for as long as more cards are in
view than the queue holds (#1282 review). It asks again when it leaves the
view and comes back, or when its retry timer fires while it is still
waiting: never at once, and never not at all. */
export interface ThumbnailAsk {
  /** Dropped while in view, and not yet asked again. */
  dropped: boolean;
}

export function newThumbnailAsk(): ThumbnailAsk {
  return { dropped: false };
}

/** The queue dropped this card's job. */
export function droppedFromQueue(ask: ThumbnailAsk): void {
  ask.dropped = true;
}

/** What an observer record means for the card: whether it is now in view for
    the purpose of asking, or `null` to leave it as it is. */
export function visibilityFromRecord(ask: ThumbnailAsk, isIntersecting: boolean): boolean | null {
  if (!isIntersecting) {
    ask.dropped = false;
    return false;
  }
  return ask.dropped ? null : true;
}

/** The retry timer fired: whether the card should look again - only if it is
    still waiting, since leaving and coming back already asked. */
export function retryIsDue(ask: ThumbnailAsk): boolean {
  const due = ask.dropped;
  ask.dropped = false;
  return due;
}
