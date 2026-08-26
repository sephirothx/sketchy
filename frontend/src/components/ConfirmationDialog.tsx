import { useId, useRef } from "react";
import { ModalShell } from "./ui/ModalShell";

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
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  return (
    <ModalShell
      role="alertdialog"
      labelledBy={titleId}
      describedBy={descriptionId}
      cardClassName="confirmation-dialog"
      onDismiss={onCancel}
      initialFocusRef={cancelButtonRef}
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
    </ModalShell>
  );
}
