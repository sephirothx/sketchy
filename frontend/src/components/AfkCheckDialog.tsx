import { useId, useRef } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ui } from "../content/ui/index.ts";

/** The AFK check: the room asking whether anybody is still there (#677).

Only ever seen by somebody whose client has seen no pointer and no key for a
while — anybody at the controls has already answered without this appearing.
That is what lets it be a dialog at all rather than a corner toast: by the time
it shows, nothing is being interrupted.

Its one job is to be answerable by accident. Any input at all answers it,
handled in `useAfkCheck` at the window rather than here, so the player does not
have to find the button; the button exists for a pointer already resting on
the canvas, and for anybody driving the page by keyboard alone.

Deliberately not dismissible by Escape or a click outside the way other
dialogs are — both of those *are* input, so they answer it. There is no way to
close this without answering it, which is right: closing it and staying is
what answering it means. */
export function AfkCheckDialog({
  secondsLeft,
  onAnswer,
}: {
  secondsLeft: number;
  onAnswer: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(dialogRef, { active: true });

  return (
    <div className="modal-overlay afk-check-overlay">
      <div
        ref={dialogRef}
        className="modal-card afk-check-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">{ui.afkCheckDialog.stillThere}</h3>
        <p className="modal-body">
          {ui.afkCheckDialog.youHaveBeenQuietWhileAnswer}
        </p>
        <p className="afk-check-countdown" role="timer" aria-live="off">
          <span className="afk-check-seconds">{secondsLeft}</span>
          <span className="afk-check-unit">
            {ui.afkCheckDialog.secondsUnit({ count: secondsLeft })}
          </span>
        </p>
        {/* Announced once rather than on every tick: a countdown read out
        second by second is unusable with a screen reader, and the sentence
        that matters is this one. */}
        <p className="visually-hidden" role="status">
          {ui.afkCheckDialog.stillTherePressButtonMoveMouse}
        </p>
        <button
          type="button"
          className="afk-check-answer"
          onClick={onAnswer}
          autoFocus
        >
          {ui.afkCheckDialog.iMHere}
        </button>
      </div>
    </div>
  );
}
