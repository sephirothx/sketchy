import fire from "../assets/reactions/fire.svg";
import heart from "../assets/reactions/heart.svg";
import laugh from "../assets/reactions/laugh.svg";
import wow from "../assets/reactions/wow.svg";
import { reactionFor } from "../lib/reactions";

/**
 * Bundled artwork per code (Fluent Emoji, MIT - see assets/reactions/LICENSE.md).
 *
 * Drawn as an image rather than a Unicode emoji on purpose. Every platform's
 * emoji font puts its glyphs on a different baseline, so an emoji beside a
 * number lands somewhere different in every browser and no CSS nudge fixes
 * all of them at once. An image in a fixed square box lands in the same place
 * everywhere, which is why chat apps render reactions this way too.
 *
 * A code this build has no artwork for - one the server added later - falls
 * back to the text glyph, so old history from a newer server still renders.
 */
const ARTWORK: Record<string, string> = { heart, laugh, wow, fire };

interface ReactionGlyphProps {
  code: string;
  /** Rendered size in CSS pixels; the box is always square. */
  size: number;
  className?: string;
}

export function ReactionGlyph({ code, size, className }: ReactionGlyphProps) {
  const emoji = reactionFor(code);
  const src = ARTWORK[code];
  const classes = `reaction-emoji${className ? ` ${className}` : ""}`;
  if (!src) {
    return (
      <span className={classes} style={{ width: size, height: size, fontSize: size * 0.85 }} aria-hidden="true">
        {emoji.glyph}
      </span>
    );
  }
  return (
    <img
      className={classes}
      src={src}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
