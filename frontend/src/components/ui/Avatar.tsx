import type { CSSProperties } from "react";

import { avatarFillClass, doodleFromUrl } from "../../lib/avatarDoodles";

interface AvatarProps {
  name: string;
  /** The account color; ignored for guests, who use the theme's guest fill. */
  nameColor?: string;
  /** The uploaded picture or the chosen doodle (#573). Never set for a guest:
      the grey initial is what marks a name as unclaimed (R-ACCT-05). */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  size?: number;
}

/**
 * What fills a disc that has something other than an initial: an uploaded
 * picture covers it, a doodle is drawn in the disc's own ink from the sprite
 * (R-AVA-06), so the name color still shows through. Shared by every disc
 * that is not the `Avatar` component itself - the header chip, the profile
 * header, the moderation queue - so a doodle never lands in an <img>, which
 * could not tint it.
 */
export function AvatarPicture({ url, size }: { url: string; size?: number }) {
  const doodle = doodleFromUrl(url);
  if (doodle) {
    return (
      <svg className="avatar-doodle" aria-hidden="true" focusable="false">
        <use href={url} />
      </svg>
    );
  }
  return <img src={url} alt="" width={size} height={size} />;
}

/**
 * Round avatar: the uploaded picture or doodle when the account has one,
 * otherwise the initial. Light theme fills with the account color and a white
 * initial; dark theme pastelizes the same color via color-mix (see
 * primitives.css) with a dark initial, so arbitrary account colors stay
 * legible on the slate ground. Guests use the fixed guest fill per theme.
 */
export function Avatar({
  name,
  nameColor,
  avatarUrl,
  isAnonymous = false,
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
  return (
    <span
      aria-hidden="true"
      className={`avatar ${variant}${avatarFillClass(picture)}`}
      style={style}
    >
      {picture ? <AvatarPicture url={picture} size={size} /> : initial}
    </span>
  );
}
