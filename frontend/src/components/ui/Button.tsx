import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant =
  | "primary"
  | "warm"
  | "secondary"
  | "ghost"
  | "dangerGhost"
  | "icon";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  warm: "btn-warm",
  secondary: "btn-secondary",
  ghost: "btn-ghost",
  dangerGhost: "btn-danger-ghost",
  icon: "btn-icon",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Larger call-to-action sizing. */
  big?: boolean;
  /** 38px control sizing for dense chrome. */
  compact?: boolean;
  iconLeft?: ReactNode;
}

export function Button({
  variant = "secondary",
  big = false,
  compact = false,
  iconLeft,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    VARIANT_CLASS[variant],
    big ? "btn-big" : "",
    compact ? "btn-compact" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type} className={classes} {...rest}>
      {iconLeft}
      {children}
    </button>
  );
}
