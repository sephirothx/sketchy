import type { ReactNode } from "react";

/**
 * One preference: what it is and why on the left, the control on the right.
 * `stacked` gives a wide control - a palette, theme cards - the whole width.
 *
 * Its own module so the parts of Settings that live in files of their own -
 * the device and export lists (#864) - draw the same row as the rest.
 */
export function SettingsRow({
  label,
  hint,
  children,
  stacked = false,
  tone,
}: {
  label: string;
  hint?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
  tone?: "danger";
}) {
  const classes = ["settings-row"];
  if (stacked) classes.push("is-stacked");
  if (tone) classes.push(`is-${tone}`);
  return (
    <div className={classes.join(" ")}>
      <span className="settings-row-label">
        <b>{label}</b>
        {hint && <small>{hint}</small>}
      </span>
      <span className="settings-row-control">{children}</span>
    </div>
  );
}
