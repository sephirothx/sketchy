import { useRef, useState } from "react";
import type { ReactNode, RefObject, TouchEvent } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { useBackCloses } from "../../hooks/useRoomHistory";
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
  /** Accessible name for the close control, from the caller's catalogue
      group - required, so no sheet falls back to an English "Close". */
  closeLabel: string;
  /** Beside the ✕ in the header, never instead of it (#1280): above 900px
      the grab handle is hidden, and Join by code's Paste left a desktop
      sheet with no way out but Escape and the scrim. */
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
  closeLabel,
  headerAction,
  children,
}: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const grabRef = useRef<HTMLButtonElement | null>(null);
  const dragOriginRef = useRef<number | null>(null);
  // The distance travelled lives in a ref as well as in state. State drives the
  // transform; the ref is what `touchend` reads, because a `touchmove` that
  // lands in the same task as the lift has not re-rendered yet, and the
  // handler would then decide the gesture on the previous frame's distance —
  // losing exactly the swipes that end on the threshold.
  const dragOffsetRef = useRef(0);
  const [dragOffset, setDragOffset] = useState(0);

  // Escape and the scrim both dismiss, but neither is discoverable by touch or
  // announced, so the sheet always carries one real control: the ✕, beside
  // any header action the sheet has (#1280).
  useFocusTrap(sheetRef, {
    onEscape: onDismiss,
    initialFocusRef: initialFocusRef ?? closeRef,
  });
  // In a room, Back closes the sheet as Escape does - on a phone it is the
  // gesture people reach for first (R-UX-15).
  useBackCloses(true, onDismiss);

  // The handle is the thing a thumb reaches for, so it both takes a tap and
  // follows a downward drag. Anything that reads as a vertical scroll rather
  // than a pull is let go of.
  const onGrabTouchStart = (event: TouchEvent<HTMLButtonElement>) => {
    dragOriginRef.current = event.touches[0]?.clientY ?? null;
    dragOffsetRef.current = 0;
  };
  const onGrabTouchMove = (event: TouchEvent<HTMLButtonElement>) => {
    const origin = dragOriginRef.current;
    const touch = event.touches[0];
    if (origin == null || !touch) return;
    const travelled = Math.max(0, touch.clientY - origin);
    dragOffsetRef.current = travelled;
    setDragOffset(travelled);
  };
  const onGrabTouchEnd = () => {
    const travelled = dragOffsetRef.current;
    dragOriginRef.current = null;
    dragOffsetRef.current = 0;
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
        {/* The handle takes a tap and a drag; the ✕ is the control a
            keyboard and a screen reader reach, so the two never announce
            themselves as the same control twice. */}
        <button
          ref={grabRef}
          type="button"
          className="bottom-sheet-grab"
          aria-hidden
          tabIndex={-1}
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
          <span className="bottom-sheet-head-actions">
            {headerAction}
            <button
              ref={closeRef}
              type="button"
              className="bottom-sheet-close"
              onClick={onDismiss}
              aria-label={closeLabel}
            >
              <XIcon size={16} />
            </button>
          </span>
        </div>
        <div className="bottom-sheet-body">{children}</div>
        {footer && <div className="bottom-sheet-foot">{footer}</div>}
      </div>
    </div>
  );
}
