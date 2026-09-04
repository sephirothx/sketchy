import type { CSSProperties } from "react";

interface AvatarProps {
  name: string;
  /** The account color; ignored for guests, who use the theme's guest fill. */
  nameColor?: string;
  /** The uploaded picture (#573). Never set for a guest: the grey initial is
      what marks a name as unclaimed (R-ACCT-05). */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  size?: number;
}

/**
 * Round avatar: the uploaded picture when the account has one, otherwise the
 * initial. Light theme fills with the account color and a white initial; dark
 * theme pastelizes the same color via color-mix (see primitives.css) with a
 * dark initial, so arbitrary account colors stay legible on the slate ground.
 * Guests use the fixed guest fill per theme.
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
      className={`avatar ${variant}${picture ? " has-picture" : ""}`}
      style={style}
    >
      {picture ? <img src={picture} alt="" width={size} height={size} /> : initial}
    </span>
  );
}
