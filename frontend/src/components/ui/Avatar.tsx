import type { CSSProperties } from "react";

interface AvatarProps {
  name: string;
  /** The account color; ignored for guests, who use the theme's guest fill. */
  nameColor?: string;
  isAnonymous?: boolean;
  size?: number;
}

/**
 * Round initial avatar. Light theme fills with the account color and a white
 * initial; dark theme pastelizes the same color via color-mix (see
 * primitives.css) with a dark initial, so arbitrary account colors stay
 * legible on the slate ground. Guests use the fixed guest fill per theme.
 */
export function Avatar({ name, nameColor, isAnonymous = false, size = 28 }: AvatarProps) {
  const initial = name.trim().charAt(0) || "?";
  const style: CSSProperties & { "--player-color"?: string } = {
    width: size,
    height: size,
    fontSize: Math.round(size * 0.48),
  };
  if (!isAnonymous && nameColor) style["--player-color"] = nameColor;
  const variant = isAnonymous || !nameColor ? "avatar-guest" : "avatar-player";
  return (
    <span aria-hidden="true" className={`avatar ${variant}`} style={style}>
      {initial}
    </span>
  );
}
