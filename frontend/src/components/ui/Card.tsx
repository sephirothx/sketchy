import type { HTMLAttributes } from "react";

/** The redesign's card surface: --card ground, 1.5px --line, --radius. */
export function Card({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  const classes = ["surface-card", className ?? ""].filter(Boolean).join(" ");
  return (
    <section className={classes} {...rest}>
      {children}
    </section>
  );
}

/** Tracked-uppercase eyebrow label above headings. */
export function SectionLabel({ className, children, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  const classes = ["section-label", className ?? ""].filter(Boolean).join(" ");
  return (
    <p className={classes} {...rest}>
      {children}
    </p>
  );
}
