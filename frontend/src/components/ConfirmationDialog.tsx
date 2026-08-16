import { useId, useRef } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";

interface ConfirmationDialogProps {
  title: string;
  description: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmationDialog({
  title,
  description,
  confirmLabel,
  onCancel,
  onConfirm,
}: ConfirmationDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useFocusTrap(dialogRef, {
    onEscape: onCancel,
    initialFocusRef: cancelButtonRef,
  });

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <div className="confirmation-dialog-icon" aria-hidden="true">!</div>
        <h2 id={titleId} className="modal-title">{title}</h2>
        <p id={descriptionId} className="modal-body">{description}</p>
        <div className="confirmation-dialog-actions">
          <button ref={cancelButtonRef} type="button" className="confirmation-cancel-button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="confirmation-danger-button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
