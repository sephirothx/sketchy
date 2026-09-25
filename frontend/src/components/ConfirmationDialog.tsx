import { useId, useRef } from "react";
import { ModalShell } from "./ui/ModalShell";
import { AlertCircleIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

interface ConfirmationDialogProps {
  title: string;
  description: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}

/** A yes-or-no before something that cannot be taken back.

No ✕: a confirmation has exactly two answers, both in the footer, and a third
control that means the same as Cancel would only sit between them in the tab
order. Escape and the scrim still cancel. */
export function ConfirmationDialog({
  title,
  description,
  confirmLabel,
  onCancel,
  onConfirm,
}: ConfirmationDialogProps) {
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const descriptionId = useId();

  return (
    <ModalShell
      role="alertdialog"
      title={
        <>
          <span className="modal-title-icon is-danger" aria-hidden="true">
            <AlertCircleIcon size={20} />
          </span>
          {title}
        </>
      }
      describedBy={descriptionId}
      cardClassName="confirmation-dialog"
      onDismiss={onCancel}
      closeButton={false}
      initialFocusRef={cancelButtonRef}
      footer={
        <>
          <button ref={cancelButtonRef} type="button" className="btn btn-secondary" onClick={onCancel}>
            {ui.confirmationDialog.cancel}
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <p id={descriptionId} className="modal-body">{description}</p>
    </ModalShell>
  );
}
