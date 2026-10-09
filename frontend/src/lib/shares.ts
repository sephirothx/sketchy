/**
 * Sharing a drawing to the Gallery (#1430): which control a viewer is offered
 * beside a drawing, and how the share is credited. Pure, so the node suite can
 * hold every case without a DOM.
 *
 * A drawing is in the Gallery while somebody shares it (R-SHARE-01). Its
 * drawer may share it from any game and take it back out for everybody
 * (R-SHARE-04); anyone else who sat in a public game may share it, and take
 * back their own share, until its drawer takes it out (R-SHARE-02).
 */

/** What the control beside a drawing offers this viewer. */
export type ShareOffer =
  /** Nothing: a spectator, a seat with no account, a private game that is
      not theirs, a drawing not kept or blank. */
  | "hidden"
  /** Share to Gallery. */
  | "share"
  /** The viewer shared it and is not its drawer: take the share back. */
  | "unshare"
  /** The viewer drew it and it is in the Gallery: take it out for everybody. */
  | "takeOut"
  /** Its drawer took it out: said, not offered. */
  | "withdrawn";

export interface ShareSituation {
  /** The viewer drew this drawing. */
  isDrawer: boolean;
  /** The viewer may share at all: seated, not a spectator, with an account. */
  canAct: boolean;
  isPublicGame: boolean;
  /** Kept, and something was drawn: a blank canvas is nothing to show. */
  shareable: boolean;
  /** The sharers, first first: seat tokens in a room, seat ids in history. */
  shares: readonly string[];
  /** The viewer's own token or seat id, to find their share among them. */
  mine: string | null;
  withdrawn: boolean;
}

export function shareOffer(situation: ShareSituation): ShareOffer {
  if (!situation.canAct) return "hidden";
  const inGallery = situation.shares.length > 0;
  if (situation.isDrawer) {
    if (inGallery) return "takeOut";
    return situation.shareable ? "share" : "hidden";
  }
  if (!situation.isPublicGame) return "hidden";
  if (situation.withdrawn) return situation.shareable ? "withdrawn" : "hidden";
  if (situation.mine !== null && situation.shares.includes(situation.mine)) return "unshare";
  return situation.shareable ? "share" : "hidden";
}

/**
 * Which token is the viewer's against a drawing's sharers, in a room: the
 * one of their own that shares it, else the seat's current token. A player
 * who left and came back holds a new token, and a share made before that
 * still names the old one.
 */
export function mineAmong(
  shares: readonly string[],
  own: readonly string[],
  current: string | null,
): string | null {
  return shares.find((token) => own.includes(token)) ?? current;
}

/** Who to credit for a drawing's place in the Gallery: its first sharer. */
export type ShareCredit =
  | { kind: "none" }
  | { kind: "you" }
  | { kind: "drawer" }
  | { kind: "player"; name: string; nameColor?: string | null; isAnonymous?: boolean }
  /** In the Gallery, by somebody the viewer cannot name (a seat that left). */
  | { kind: "someone" };

export function shareCredit(
  shares: readonly string[],
  context: {
    mine: string | null;
    drawer: string | null;
    nameOf: (id: string) => { name: string; nameColor?: string | null; isAnonymous?: boolean } | null;
  },
): ShareCredit {
  const first = shares[0];
  if (first === undefined) return { kind: "none" };
  if (context.mine !== null && first === context.mine) return { kind: "you" };
  if (context.drawer !== null && first === context.drawer) return { kind: "drawer" };
  const named = context.nameOf(first);
  return named ? { kind: "player", ...named } : { kind: "someone" };
}
