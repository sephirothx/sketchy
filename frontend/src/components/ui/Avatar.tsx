import type { CSSProperties } from "react";

import { CrownMarkIcon, FriendMarkIcon } from "../icons";

interface AvatarProps {
  name: string;
  /** The account color; ignored for guests, who use the theme's guest fill. */
  nameColor?: string;
  /** The uploaded picture (#573). Never set for a guest: the grey initial is
      what marks a name as unclaimed (R-ACCT-05). */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  /** The room's host: a gold crown on the disc's top-right edge (#574). */
  isHost?: boolean;
  /** The viewer's own disc: a ring in the primary colour (#574). */
  isSelf?: boolean;
  /** An accepted friend of the viewer: a mark on the disc's bottom-right. */
  isFriend?: boolean;
  size?: number;
}

/**
 * Round avatar: the uploaded picture when the account has one, otherwise the
 * initial. Light theme fills with the account color and a white initial; dark
 * theme pastelizes the same color via color-mix (see primitives.css) with a
 * dark initial, so arbitrary account colors stay legible on the slate ground.
 * Guests use the fixed guest fill per theme.
 *
 * The disc also carries the facts every roster used to spell out beside the
 * name (#574): the host's crown perches on its top-right edge, the viewer's
 * own disc wears a ring, and a friend of the viewer's carries a mark on the
 * one free corner — so "host", "you" and "friend" read at a glance without
 * spending name-line width and look the same on every surface.
 *
 * All three are per-*viewer* rather than per-player, which is the point: the
 * ring and the mark both say something about the relationship between whoever
 * is reading and whoever is drawn, and neither is a fact about the game.
 *
 * Every mark is decorative here; the roster that draws the name says "Host",
 * "you" and "Friend" for screen readers, where they read in the right order.
 */
export function Avatar({
  name,
  nameColor,
  avatarUrl,
  isAnonymous = false,
  isHost = false,
  isSelf = false,
  isFriend = false,
  size = 28,
}: AvatarProps) {
  const initial = name.trim().charAt(0) || "?";
  const style: CSSProperties & { "--player-color"?: string } = {
    width: size,
    height: size,
    fontSize: Math.round(size * 0.48),
  };
  if (!isAnonymous && nameColor) style["--player-color"] = nameColor;
  const variant = isAnonymous || !nameColor ? "avatar-guest" : "avatar-player";
  const picture = !isAnonymous && avatarUrl ? avatarUrl : null;
  const disc = (
    <span
      aria-hidden="true"
      className={`avatar ${variant}${picture ? " has-picture" : ""}${isSelf ? " is-self" : ""}`}
      style={style}
    >
      {picture ? <img src={picture} alt="" width={size} height={size} /> : initial}
    </span>
  );
  if (!isHost && !isFriend) return disc;
  // Both marks scale with the disc but never below a size they survive.
  const crown = Math.max(12, Math.round(size * 0.52));
  const mark = Math.max(12, Math.round(size * 0.46));
  return (
    <span className="avatar-frame" aria-hidden="true">
      {disc}
      {isHost && (
        <span className="avatar-crown">
          <CrownMarkIcon size={crown} strokeWidth={2} />
        </span>
      )}
      {/* The bottom-right corner, because the ring already owns the whole
          edge and the crown owns the top. The two can appear together: a
          friend who is also hosting wears both, on opposite corners. */}
      {isFriend && (
        <span className="avatar-friend">
          <FriendMarkIcon size={mark} />
        </span>
      )}
    </span>
  );
}
