import type { HTMLAttributes } from "react";

export type ChipKind =
  | "neutral"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "warm";

interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  kind?: ChipKind;
}

export function Chip({ kind = "neutral", className, children, ...rest }: ChipProps) {
  const classes = ["chip", `chip-${kind}`, className ?? ""].filter(Boolean).join(" ");
  return (
    <span className={classes} {...rest}>
      {children}
    </span>
  );
}
