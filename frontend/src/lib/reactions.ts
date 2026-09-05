/**
 * The reaction set and the rules around it (#520), free of runtime imports so
 * `frontend/tests` can load it under bare `node --test`.
 *
 * Codes are the wire and storage identity; glyphs are how this build draws
 * them. A code is never removed here once shipped - the stored-drawing rule,
 * applied to an emoji - so history from any age keeps rendering. Retiring a
 * code means adding it to `RETIRED_REACTION_CODES`: it stays in the table and
 * keeps its glyph, it just stops being offered.
 *
 * These are literal emoji on purpose. The redesign replaced every UI glyph
 * with an SVG icon; emoji remain where they are player content, and a
 * reaction is exactly that.
 */

export const REACTION_SET_VERSION = 1;

export interface ReactionEmoji {
  code: string;
  glyph: string;
  /** How a screen reader says it. */
  label: string;
}

/** Every code this build knows, in the order a picker shows them. */
export const REACTION_GLYPHS: readonly ReactionEmoji[] = [
  { code: "heart", glyph: "\u2764\uFE0F", label: "Love it" },
  { code: "laugh", glyph: "\uD83D\uDE02", label: "Funny" },
  { code: "wow", glyph: "\uD83D\uDE2E", label: "Wow" },
  { code: "fire", glyph: "\uD83D\uDD25", label: "Fire" },
];

export const RETIRED_REACTION_CODES: ReadonlySet<string> = new Set();

/** A code the server added after this build shipped still needs a face. */
const UNKNOWN_REACTION: ReactionEmoji = { code: "", glyph: "\u2B50", label: "Reaction" };

export function offeredReactions(): ReactionEmoji[] {
  return REACTION_GLYPHS.filter((emoji) => !RETIRED_REACTION_CODES.has(emoji.code));
}

export function reactionFor(code: string): ReactionEmoji {
  return REACTION_GLYPHS.find((emoji) => emoji.code === code) ?? { ...UNKNOWN_REACTION, code };
}

export function glyphFor(code: string): string {
  return reactionFor(code).glyph;
}

export function tallyReactions(reactions: readonly { emoji: string }[]): Record<string, number> {
  const tally: Record<string, number> = {};
  for (const reaction of reactions) {
    tally[reaction.emoji] = (tally[reaction.emoji] ?? 0) + 1;
  }
  return tally;
}

/**
 * The tally as a row of chips: known codes in picker order, then anything this
 * build has never heard of, zeros dropped.
 */
export function compactTally(
  tally: Record<string, number>,
): Array<{ code: string; count: number; glyph: string; label: string }> {
  const known = REACTION_GLYPHS.map((emoji) => emoji.code);
  const codes = [
    ...known.filter((code) => (tally[code] ?? 0) > 0),
    ...Object.keys(tally).filter((code) => !known.includes(code) && tally[code] > 0),
  ];
  return codes.map((code) => {
    const emoji = reactionFor(code);
    return { code, count: tally[code], glyph: emoji.glyph, label: emoji.label };
  });
}

export function totalReactions(tally: Record<string, number>): number {
  return Object.values(tally).reduce((sum, count) => sum + count, 0);
}

/** Apply one broadcast to a turn's reaction list: replace, add, or remove that seat's entry. */
export function applyReactionEvent<T extends { playerId: string; emoji: string }>(
  reactions: readonly T[],
  event: { playerId: string; emoji: string | null },
): T[] {
  const others = reactions.filter((reaction) => reaction.playerId !== event.playerId);
  if (event.emoji === null) return others;
  return [...others, { playerId: event.playerId, emoji: event.emoji } as T];
}

export function myReaction(
  reactions: readonly { playerId: string; emoji: string }[],
  reactorId: string | null | undefined,
): string | null {
  if (!reactorId) return null;
  return reactions.find((reaction) => reaction.playerId === reactorId)?.emoji ?? null;
}

/**
 * Why the picker is, or is not, offered. Mirrors the server's authorization
 * step so the control is only drawn where pressing it can work: guests are
 * told how to become able to, everyone else who cannot sees the tally alone.
 */
export type ReactionEligibility = "ok" | "guest" | "spectator" | "drawer" | "closed";

export function reactionEligibility(input: {
  isRegistered: boolean;
  isSpectator?: boolean;
  isDrawer?: boolean;
  open?: boolean;
}): ReactionEligibility {
  if (input.open === false) return "closed";
  if (input.isSpectator) return "spectator";
  if (input.isDrawer) return "drawer";
  if (!input.isRegistered) return "guest";
  return "ok";
}
