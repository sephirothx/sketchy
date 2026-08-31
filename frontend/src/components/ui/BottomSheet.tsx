import { useRef, useState } from "react";
import type { ReactNode, RefObject, TouchEvent } from "react";
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
  /** Replaces the ✕ in the header — the grab handle still dismisses. */
  headerAction?: ReactNode;
  children: ReactNode;
}

/** How far down the handle must travel before the sheet takes it as a dismiss. */
const SWIPE_DISMISS_PX = 56;

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
  headerAction,
  children,
}: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const grabRef = useRef<HTMLButtonElement | null>(null);
  const dragOriginRef = useRef<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);

  // Escape and the scrim both dismiss, but neither is discoverable by touch or
  // announced, so the sheet always carries one real control: the ✕, or the
  // grab handle when the header slot is spent on something else.
  useFocusTrap(sheetRef, {
    onEscape: onDismiss,
    initialFocusRef: initialFocusRef ?? (headerAction ? grabRef : closeRef),
  });

  // The handle is the thing a thumb reaches for, so it both takes a tap and
  // follows a downward drag. Anything that reads as a vertical scroll rather
  // than a pull is let go of.
  const onGrabTouchStart = (event: TouchEvent<HTMLButtonElement>) => {
    dragOriginRef.current = event.touches[0]?.clientY ?? null;
  };
  const onGrabTouchMove = (event: TouchEvent<HTMLButtonElement>) => {
    const origin = dragOriginRef.current;
    const touch = event.touches[0];
    if (origin == null || !touch) return;
    setDragOffset(Math.max(0, touch.clientY - origin));
  };
  const onGrabTouchEnd = () => {
    const travelled = dragOffset;
    dragOriginRef.current = null;
    setDragOffset(0);
    if (travelled >= SWIPE_DISMISS_PX) onDismiss();
  };

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
        style={{
          ...(height ? { height } : null),
          ...(dragOffset > 0
            ? { transform: `translateY(${dragOffset}px)`, transition: "none" }
            : null),
        }}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        tabIndex={-1}
        data-testid={testId}
      >
        {/* The handle always takes a tap and a drag. It only carries the
            accessible name when the ✕ is not there to carry it, so the two
            never announce themselves as the same control twice. */}
        <button
          ref={grabRef}
          type="button"
          className="bottom-sheet-grab"
          aria-label={headerAction ? closeLabel : undefined}
          aria-hidden={headerAction ? undefined : true}
          tabIndex={headerAction ? undefined : -1}
          onClick={onDismiss}
          onTouchStart={onGrabTouchStart}
          onTouchMove={onGrabTouchMove}
          onTouchEnd={onGrabTouchEnd}
          onTouchCancel={onGrabTouchEnd}
        >
          <span className="bottom-sheet-grab-bar" aria-hidden="true" />
        </button>
        <div className="bottom-sheet-head">
          {header ?? (title ? <h2 className="bottom-sheet-title">{title}</h2> : <span />)}
          {headerAction ?? (
            <button
              ref={closeRef}
              type="button"
              className="bottom-sheet-close"
              onClick={onDismiss}
              aria-label={closeLabel}
            >
              <XIcon size={16} />
            </button>
          )}
        </div>
        <div className="bottom-sheet-body">{children}</div>
        {footer && <div className="bottom-sheet-foot">{footer}</div>}
      </div>
    </div>
  );
}
