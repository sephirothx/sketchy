import { useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { XIcon } from "../icons";

interface BottomSheetProps {
  /** Heading text; also the accessible name. */
  title?: string;
  /** Replaces `title` when the header needs more than a string. */
  header?: ReactNode;
  ariaLabel?: string;
  onDismiss: () => void;
  /** Sheet height as a fraction of the visible viewport. Defaults to content. */
  height?: string;
  /** Extra classes on the sheet element. */
  className?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Sheet actions, pinned below the scrolling body. */
  footer?: ReactNode;
  testId?: string;
  /** Accessible name for the close control; defaults to "Close". */
  closeLabel?: string;
  children: ReactNode;
}

/**
 * A sheet that rises from the bottom edge, leaving what is above it visible.
 *
 * The point on a phone is that the thing you were looking at — the drawing —
 * stays on screen while the sheet reports on it, and that the sheet's controls
 * land under the thumb rather than in the top-right corner. Above the mobile
 * breakpoint the stylesheet centres the same markup as an ordinary dialog, so
 * one component serves both.
 */
export function BottomSheet({
  title,
  header,
  ariaLabel,
  onDismiss,
  height,
  className,
  initialFocusRef,
  footer,
  testId,
  closeLabel = "Close",
  children,
}: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  // Escape and the scrim both dismiss, but neither is discoverable by touch or
  // announced, so the sheet carries a real control and opens focused on it.
  useFocusTrap(sheetRef, { onEscape: onDismiss, initialFocusRef: initialFocusRef ?? closeRef });

  const classes = ["bottom-sheet", className ?? ""].filter(Boolean).join(" ");

  return (
    <div
      className="bottom-sheet-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onDismiss();
      }}
    >
      <div
        ref={sheetRef}
        className={classes}
        style={height ? { height } : undefined}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        tabIndex={-1}
        data-testid={testId}
      >
        {/* Decorative: the sheet is dismissed by Escape, the scrim, or a
            control inside it, so the handle is a visual affordance only. */}
        <span className="bottom-sheet-grab" aria-hidden="true" />
        <div className="bottom-sheet-head">
          {header ?? (title ? <h2 className="bottom-sheet-title">{title}</h2> : <span />)}
          <button
            ref={closeRef}
            type="button"
            className="bottom-sheet-close"
            onClick={onDismiss}
            aria-label={closeLabel}
          >
            <XIcon size={16} />
          </button>
        </div>
        <div className="bottom-sheet-body">{children}</div>
        {footer && <div className="bottom-sheet-foot">{footer}</div>}
      </div>
    </div>
  );
}
