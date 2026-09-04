import { useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { DOODLE_LABELS, DOODLES, doodleFromUrl, doodleUrl, type Doodle } from "../lib/avatarDoodles";
import { Avatar } from "./ui/Avatar";

/**
 * Picking a doodle (R-AVA-06): every drawing on the player's own disc, in
 * their own color, because that is how it will look beside their name.
 * Choosing one applies at once, like every other setting (R-SET-05).
 */
export function AvatarDoodleDialog({
  name,
  nameColor,
  currentUrl,
  onChoose,
  onClose,
}: {
  name: string;
  nameColor: string;
  currentUrl: string | null | undefined;
  /** Wear the doodle; a throw is shown here and the dialog stays. */
  onChoose: (doodle: Doodle) => Promise<void>;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const [busy, setBusy] = useState<Doodle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wearing = doodleFromUrl(currentUrl);

  useFocusTrap(dialogRef, { onEscape: onClose });

  async function choose(doodle: Doodle) {
    if (busy) return;
    setBusy(doodle);
    setError(null);
    try {
      await onChoose(doodle);
    } catch (failure) {
      setError(
        failure instanceof ApiError ? failure.message : "Could not pick that doodle. Please try again.",
      );
      setBusy(null);
    }
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card avatar-doodle-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">
          Pick a doodle
        </h3>
        <p className="modal-body">Drawn in your color, wherever your name appears.</p>
        <div className="avatar-doodle-grid" role="group" aria-label="Doodles">
          {DOODLES.map((doodle) => (
            <button
              key={doodle}
              type="button"
              className={`avatar-doodle-choice${doodle === wearing ? " is-selected" : ""}`}
              aria-label={DOODLE_LABELS[doodle]}
              aria-pressed={doodle === wearing}
              title={DOODLE_LABELS[doodle]}
              disabled={busy !== null}
              onClick={() => void choose(doodle)}
            >
              <Avatar name={name} nameColor={nameColor} avatarUrl={doodleUrl(doodle)} size={52} />
            </button>
          ))}
        </div>
        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}
        <button type="button" className="modal-dismiss" disabled={busy !== null} onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
