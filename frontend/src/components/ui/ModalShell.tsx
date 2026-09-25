import { useId, useRef } from "react";
import type { ReactNode, Ref, RefObject } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { XIcon } from "../icons";
import { ui } from "../../content/ui/index.ts";

interface ModalHeaderProps {
  /** The heading's text; an icon may lead it. Rendered as an `h2`. */
  title: ReactNode;
  titleId: string;
  /** A quiet line above the title - what the dialog is about, not what it is. */
  eyebrow?: ReactNode;
  /** Draws the ✕ when given. */
  onClose?: () => void;
  /** The ✕'s accessible name; "Close" unless the dialog needs to say more. */
  closeLabel?: string;
  closeRef?: RefObject<HTMLButtonElement | null>;
  className?: string;
}

/**
 * Title on the left, ✕ on the right: the one header every dialog wears.
 *
 * Exported on its own for the two route overlays, Settings and Friends, which
 * keep their own sheet layout (a rail, a fixed height, their own layer) but
 * should not read as a different kind of window from every other dialog.
 */
export function ModalHeader({
  title,
  titleId,
  eyebrow,
  onClose,
  closeLabel,
  closeRef,
  className,
}: ModalHeaderProps) {
  const label = closeLabel ?? ui.dialog.close;
  return (
    <div className={["modal-head", className ?? ""].filter(Boolean).join(" ")}>
      <div className="modal-head-text">
        {eyebrow && <p className="section-label">{eyebrow}</p>}
        <h2 id={titleId} className="modal-title">{title}</h2>
      </div>
      {onClose && (
        <button
          ref={closeRef}
          type="button"
          className="btn btn-icon modal-close"
          onClick={onClose}
          aria-label={label}
          title={label}
          data-skip-initial-focus=""
        >
          <XIcon size={16} />
        </button>
      )}
    </div>
  );
}

/** Escape, taken and dropped. */
const swallow = () => {};

interface ModalShellProps {
  role?: "dialog" | "alertdialog";
  /** The heading. Also the dialog's accessible name, so `labelledBy` is only
      for a dialog that draws its own heading inside the body. */
  title?: ReactNode;
  eyebrow?: ReactNode;
  labelledBy?: string;
  ariaLabel?: string;
  describedBy?: string;
  /** Extra classes on the .modal-card element. */
  cardClassName?: string;
  /** Extra classes on the .modal-overlay element - its layer, for the few
      dialogs that open over something already high up. */
  overlayClassName?: string;
  overlayRef?: Ref<HTMLDivElement>;
  testId?: string;
  /**
   * How the dialog is set aside: the ✕, Escape and a click on the scrim.
   * Omitted for a blocking notice - one that is answered, never dismissed -
   * which then has no ✕, ignores the scrim and swallows Escape.
   * Focus is trapped either way (R-A11Y-04).
   */
  onDismiss?: () => void;
  /** Escape's own handler, when it should differ from `onDismiss`; `false`
      makes Escape do nothing. Escape never passes through to what is below. */
  onEscape?: (() => void) | false;
  /** Set false to keep the dialog open on backdrop clicks. */
  dismissOnBackdrop?: boolean;
  /** Set false to leave the ✕ out while `onDismiss` still serves Escape. */
  closeButton?: boolean;
  closeLabel?: string;
  /** Where focus lands when the dialog opens (defaults to first focusable). */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** The dialog's actions, pinned under the scrolling body: right-aligned
      with the primary last, stacked full width on a phone. */
  footer?: ReactNode;
  children: ReactNode;
}

/**
 * The one dialog: scrim, card, focus trap and Escape, with a header, a body
 * that scrolls on its own, and a footer for the actions.
 *
 * The anatomy is the point. Dialogs used to be hand-rolled one at a time, and
 * it showed - titles centred in some and left in others, a ✕ in five sizes,
 * four footer layouts, a blurred scrim behind some and a flat one behind the
 * rest, and cards with no height limit that ran off a landscape phone with the
 * submit button out of reach. Now the header and footer stay put and only the
 * body scrolls, however tall it grows.
 *
 * Keeps the `.modal-overlay` / `.modal-card` classes the stylesheets and e2e
 * suite already know. Focus restore on close is handled by useFocusTrap.
 */
export function ModalShell({
  role = "dialog",
  title,
  eyebrow,
  labelledBy,
  ariaLabel,
  describedBy,
  cardClassName,
  overlayClassName,
  overlayRef,
  testId,
  onDismiss,
  onEscape,
  dismissOnBackdrop = true,
  closeButton = true,
  closeLabel,
  initialFocusRef,
  footer,
  children,
}: ModalShellProps) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  // Escape is always claimed while a dialog is up. A blocking notice that
  // left it unhandled let the key through to whatever was open beneath it -
  // Settings closed behind a suspension notice.
  const escape = onEscape === false ? swallow : (onEscape ?? onDismiss ?? swallow);
  useFocusTrap(cardRef, {
    onEscape: escape,
    initialFocusRef,
  });

  const hasHeader = title !== undefined;
  const cardClasses = ["modal-card", cardClassName ?? ""].filter(Boolean).join(" ");
  const overlayClasses = ["modal-overlay", overlayClassName ?? ""].filter(Boolean).join(" ");
  return (
    <div
      ref={overlayRef}
      className={overlayClasses}
      onMouseDown={(event) => {
        if (onDismiss && dismissOnBackdrop && event.target === event.currentTarget) onDismiss();
      }}
    >
      <div
        ref={cardRef}
        className={cardClasses}
        role={role}
        aria-modal="true"
        aria-labelledby={hasHeader ? titleId : labelledBy}
        aria-label={hasHeader ? undefined : ariaLabel}
        aria-describedby={describedBy}
        tabIndex={-1}
        data-testid={testId}
      >
        {hasHeader && (
          <ModalHeader
            title={title}
            titleId={titleId}
            eyebrow={eyebrow}
            onClose={closeButton ? onDismiss : undefined}
            closeLabel={closeLabel}
          />
        )}
        <div className="modal-content">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}
