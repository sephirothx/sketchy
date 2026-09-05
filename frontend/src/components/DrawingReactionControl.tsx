import { useEffect, useRef, useState } from "react";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  compactTally,
  myReaction,
  offeredReactions,
  tallyReactions,
  totalReactions,
  type ReactionEligibility,
} from "../lib/reactions";
import { useToast } from "../lib/toast";
import type { DrawingReaction } from "../types";
import { HeartIcon } from "./icons";
import { ReactionGlyph } from "./ReactionGlyph";

interface DrawingReactionControlProps {
  /** Every reaction on this drawing, by reactor seat. */
  reactions: DrawingReaction[];
  /** The seat that is me in these reactions - a room token live, a seat id in history. */
  myReactorId: string | null;
  eligibility: ReactionEligibility;
  /** `null` takes my reaction back. Rejections are shown beside the picker. */
  onReact?: (emoji: string | null) => Promise<unknown>;
  /** Guests: how to become able to react. */
  onRequestAccount?: () => void;
  /**
   * "canvas" pins the control to a corner of the drawing frame it is rendered
   * inside; "panel" lets it sit in a card's flow.
   */
  placement: "canvas" | "panel";
  /**
   * A reaction somebody else just left on this drawing: the control floats its
   * glyph. Sequence-numbered so the same glyph twice still floats twice.
   */
  incoming?: { seq: number; emoji: string | null; playerId: string } | null;
}

interface Floater {
  id: number;
  code: string;
  /** Horizontal jitter so two in a row do not stack into one; leftwards only. */
  drift: number;
  /** How far it rises, measured from the frame so it never leaves it. */
  rise: number;
}

function TallyChip({ code, count }: { code: string; count: number }) {
  return (
    <span className="reaction-chip" data-emoji={code}>
      <ReactionGlyph code={code} size={14} />
      <span className="reaction-count">{count}</span>
    </span>
  );
}

const FLOAT_MS = 1800;
const MAX_FLOATERS = 8;
const FLOAT_GLYPH_PX = 34;
const MAX_RISE_PX = 220;
const PANEL_RISE_PX = 110;

/**
 * One small button in the corner of a drawing carrying its reaction tally;
 * pressing it opens the picker. Everyone sees the tally. The picker is only
 * offered where pressing it can work (the house rule - a control that always
 * failed would be the usual experience of it): guests get one line on how to
 * become able to, spectators and the drawer get the tally alone.
 *
 * Reactions are literal emoji. The rest of the UI draws SVG icons, and that
 * rule stands; a reaction is player content, which is the sanctioned exception.
 */
export function DrawingReactionControl({
  reactions,
  myReactorId,
  eligibility,
  onReact,
  onRequestAccount,
  placement,
  incoming,
}: DrawingReactionControlProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [floaters, setFloaters] = useState<Floater[]>([]);
  const { notify } = useToast();
  const floaterSeq = useRef(0);
  const timersRef = useRef(new Map<number, number>());
  const prefersReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const rootRef = useRef<HTMLDivElement | null>(null);

  const tally = tallyReactions(reactions);
  const chips = compactTally(tally);
  const total = totalReactions(tally);
  const mine = myReaction(reactions, myReactorId);
  const canPick = eligibility === "ok" && Boolean(onReact);
  const canOpen = canPick || (eligibility === "guest" && Boolean(onRequestAccount));

  useEscapeLayer(open, () => setOpen(false));

  // Close on a click anywhere else; the picker is small and owns no scrim.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer);
      timers.clear();
    };
  }, []);

  function float(code: string) {
    if (prefersReducedMotion) return;
    const id = ++floaterSeq.current;
    // Rise inside the frame: from just above the pill to a little under its
    // top edge. Measured each time, because the canvas scales with the window.
    const frame = rootRef.current?.closest(".canvas-stack");
    const rise = frame
      ? Math.max(
          FLOAT_GLYPH_PX,
          Math.min(MAX_RISE_PX, frame.getBoundingClientRect().height - FLOAT_GLYPH_PX * 2.2),
        )
      : PANEL_RISE_PX;
    // Only leftwards: the pill sits against the frame's right edge.
    const drift = -((id * 37) % 48);
    setFloaters((current) => [
      ...current.slice(-(MAX_FLOATERS - 1)),
      { id, code, drift, rise },
    ]);
    const timer = window.setTimeout(() => {
      timersRef.current.delete(id);
      setFloaters((current) => current.filter((floater) => floater.id !== id));
    }, FLOAT_MS);
    timersRef.current.set(id, timer);
  }

  // Everyone in the room - guessers, the drawer, spectators - sees a reaction
  // float as it lands; my own floats when I press, below, so the REST path,
  // which has no broadcast, looks the same.
  const lastSeenSeq = useRef(incoming?.seq ?? 0);
  useEffect(() => {
    if (!incoming || incoming.seq === lastSeenSeq.current) return;
    lastSeenSeq.current = incoming.seq;
    if (incoming.emoji && incoming.playerId !== myReactorId) float(incoming.emoji);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incoming?.seq]);

  async function pick(code: string) {
    if (!onReact || busy) return;
    const next = code === mine ? null : code;
    setBusy(true);
    try {
      await onReact(next);
      if (next) float(next);
      setOpen(false);
    } catch (failure) {
      // The strip holds emoji and nothing else, so a refusal is said elsewhere.
      notify(
        failure instanceof Error ? failure.message : "That reaction could not be sent.",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  const summary =
    total === 0
      ? "No reactions yet"
      : `${total} ${total === 1 ? "reaction" : "reactions"}: ${chips
          .map((chip) => `${chip.label} ${chip.count}`)
          .join(", ")}`;

  return (
    <div
      ref={rootRef}
      className={`reaction-control reaction-control-${placement}${open ? " is-open" : ""}${
        canOpen ? "" : " is-passive"
      }`}
      data-testid="reaction-control"
    >
      <div className="reaction-floaters" aria-hidden="true">
        {floaters.map((floater) => (
          <span
            key={floater.id}
            className="reaction-floater"
            style={{
              ["--drift" as string]: `${floater.drift}px`,
              ["--rise" as string]: `${floater.rise}px`,
            }}
          >
            <ReactionGlyph code={floater.code} size={FLOAT_GLYPH_PX} />
          </span>
        ))}
      </div>
      {canOpen ? (
        <button
          type="button"
          className={`reaction-toggle${mine ? " has-mine" : ""}`}
          aria-label={canPick ? `React to this drawing. ${summary}` : summary}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          data-testid="reaction-toggle"
        >
          {chips.length === 0 ? (
            <span className="reaction-toggle-empty">
              <HeartIcon size={15} />
            </span>
          ) : (
            chips.map((chip) => <TallyChip key={chip.code} code={chip.code} count={chip.count} />)
          )}
        </button>
      ) : chips.length > 0 ? (
        // The drawer and spectators get the tally and no control: a see-through
        // pill that only appears once there is something to count.
        <div
          className="reaction-toggle reaction-tally"
          role="status"
          aria-label={summary}
          data-testid="reaction-tally"
        >
          {chips.map((chip) => <TallyChip key={chip.code} code={chip.code} count={chip.count} />)}
        </div>
      ) : null}
      {open && canPick && (
        // A strip of emoji and nothing else: the names live in the labels, and
        // a refusal goes to a toast.
        <div className="reaction-picker" role="dialog" aria-label="React to this drawing">
          {offeredReactions().map((emoji) => (
            <button
              key={emoji.code}
              type="button"
              className={`reaction-option${mine === emoji.code ? " is-mine" : ""}`}
              aria-pressed={mine === emoji.code}
              aria-label={mine === emoji.code ? `${emoji.label}, your reaction. Press to remove it` : emoji.label}
              title={emoji.label}
              disabled={busy}
              onClick={() => void pick(emoji.code)}
              data-testid={`reaction-option-${emoji.code}`}
            >
              <ReactionGlyph code={emoji.code} size={24} />
            </button>
          ))}
        </div>
      )}
      {open && !canPick && eligibility === "guest" && (
        <div className="reaction-picker reaction-picker-guest" role="dialog" aria-label="Reactions">
          <p className="reaction-picker-hint">Create an account to react.</p>
          <button
            type="button"
            className="reaction-claim"
            onClick={() => {
              setOpen(false);
              onRequestAccount?.();
            }}
          >
            Create account
          </button>
        </div>
      )}
    </div>
  );
}
