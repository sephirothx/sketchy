import { useRef } from "react";

import { ModalShell } from "./ui/ModalShell";
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
dialogs are — both of those *are* input, so they answer it. So no `onDismiss`:
ModalShell then draws no ✕ and leaves Escape and the scrim to the window. There is no way to
close this without answering it, which is right: closing it and staying is
what answering it means. */
export function AfkCheckDialog({
  secondsLeft,
  onAnswer,
}: {
  secondsLeft: number;
  onAnswer: () => void;
}) {
  const answerRef = useRef<HTMLButtonElement>(null);

  return (
    <ModalShell
      role="alertdialog"
      title={ui.afkCheckDialog.stillThere}
      overlayClassName="afk-check-overlay"
      cardClassName="afk-check-dialog"
      initialFocusRef={answerRef}
      footer={
        <button
          ref={answerRef}
          type="button"
          className="btn btn-primary afk-check-answer"
          onClick={onAnswer}
        >
          {ui.afkCheckDialog.iMHere}
        </button>
      }
    >
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
    </ModalShell>
  );
}
