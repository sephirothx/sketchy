import { ui } from "../../content/ui";

/**
 * The small heart after a supporter's name (#1474). The one place it is drawn.
 * Not clickable, and it sorts and counts nothing (R-SUP-10). The server has
 * already combined it with the owner's choice to show it, so whoever renders
 * this never sees a heart its owner hid. The label says what a heart alone does
 * not: on most sites a heart is free.
 */
export function SupporterMark({ size = 13 }: { size?: number }) {
  return (
    <span className="supporter-mark" role="img" aria-label={ui.supporterMark.label} title={ui.supporterMark.label}>
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20.5s-7.5-4.6-9.2-9.4C1.6 7.6 4 4.5 7.2 4.5c2 0 3.6 1.1 4.8 2.8 1.2-1.7 2.8-2.8 4.8-2.8 3.2 0 5.6 3.1 4.4 6.6-1.7 4.8-9.2 9.4-9.2 9.4Z" />
      </svg>
    </span>
  );
}
