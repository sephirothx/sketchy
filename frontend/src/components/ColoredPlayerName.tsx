import type { CSSProperties } from "react";

export const GUEST_NAME_COLOR = "#888888";

export function ColoredPlayerName({
  nickname,
  nameColor,
  isAnonymous = false,
  as: Tag = "span",
}: {
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
  as?: "span" | "strong";
}) {
  const style: CSSProperties | undefined = isAnonymous
    ? { color: GUEST_NAME_COLOR }
    : nameColor
      ? { color: nameColor }
      : undefined;
  return (
    <Tag
      className={isAnonymous ? "colored-player-name is-anonymous" : "colored-player-name"}
      style={style}
    >
      {nickname}
    </Tag>
  );
}
