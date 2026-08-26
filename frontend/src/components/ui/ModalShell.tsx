import { useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";

interface ModalShellProps {
  role?: "dialog" | "alertdialog";
  labelledBy?: string;
  ariaLabel?: string;
  describedBy?: string;
  /** Extra classes on the .modal-card element. */
  cardClassName?: string;
  /** Called on Escape and backdrop click. */
  onDismiss: () => void;
  /** Where focus lands when the dialog opens (defaults to first focusable). */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Set false to keep the dialog open on backdrop clicks. */
  dismissOnBackdrop?: boolean;
  children: ReactNode;
}

/**
 * The one modal frame: scrim + card + focus trap + Escape. Keeps the
 * `.modal-overlay` / `.modal-card` classes the stylesheets and e2e suite
 * already know. Focus restore on close is handled by useFocusTrap.
 */
export function ModalShell({
  role = "dialog",
  labelledBy,
  ariaLabel,
  describedBy,
  cardClassName,
  onDismiss,
  initialFocusRef,
  dismissOnBackdrop = true,
  children,
}: ModalShellProps) {
  const cardRef = useRef<HTMLDivElement | null>(null);

  useFocusTrap(cardRef, {
    onEscape: onDismiss,
    initialFocusRef,
  });

  const cardClasses = ["modal-card", cardClassName ?? ""].filter(Boolean).join(" ");
  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (dismissOnBackdrop && event.target === event.currentTarget) onDismiss();
      }}
    >
      <div
        ref={cardRef}
        className={cardClasses}
        role={role}
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );
}
