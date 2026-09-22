import { ReactionGlyph } from "./ReactionGlyph";
import { compactTally, resolveTally } from "../lib/reactions";
import "../styles/lazy/reactions.css";

/**
 * The per-emoji counts of one drawing, read-only: the profile's turn table
 * and the pinned-drawings shelf, where the viewer may not have been in the
 * game and so has no picker. Nothing when there is nothing to count.
 */
export function ReactionTally({
  reactions,
  counts,
}: {
  reactions: readonly { emoji: string }[];
  /** The server's counts, when it sent them: they include the seatless reactions. */
  counts?: Record<string, number> | null;
}) {
  const chips = compactTally(resolveTally(reactions, counts));
  if (chips.length === 0) return null;
  return (
    <span
      className="profile-turn-reactions"
      aria-label={chips.map((chip) => `${chip.label} ${chip.count}`).join(", ")}
    >
      {chips.map((chip) => (
        <span key={chip.code} className="reaction-chip">
          <ReactionGlyph code={chip.code} size={14} />
          <span className="reaction-count">{chip.count}</span>
        </span>
      ))}
    </span>
  );
}
