import { useState } from "react";

import { ReportDialog } from "./ReportDialog";
import { reportPlayerInRoom, type ReportReason } from "../lib/moderation";
import { socketRequestErrorMessage } from "../lib/socket";
import { ui } from "../content/ui/index.ts";
import { refusalText } from "../lib/refusals.ts";
import "../styles/lazy/player-list.css";

/** What went with the report, in one sentence.

Each part is stated from the acknowledgement rather than from what was asked
for: the turn can end between opening the dialog and sending, and a reporter
who ticked the box should hear that the drawing did not make it. */
function sentSummary(sent: {
  messages: number;
  drawing: boolean;
  drawingRequested: boolean;
}): string {
  const messages =
    sent.messages > 0
      ? ui.reportPlayerDialog.recentMessages({ count: sent.messages })
      : null;
  if (sent.drawing) {
    return messages
      ? ui.reportPlayerDialog.sentWithTheirDrawingAnd({ messages })
      : ui.reportPlayerDialog.sentWithTheirDrawingAttached;
  }
  const base = messages
    ? ui.reportPlayerDialog.sentWithMessagesAttached({ messages })
    : ui.reportPlayerDialog.sentTheyHadSaidNothing;
  return sent.drawingRequested
    ? ui.reportPlayerDialog.baseTheTurnHadEnded({ base })
    : base;
}

/** An acknowledgement that said no, carried to the dialog's failure text. */
class Refused {
  readonly ack: unknown;
  constructor(ack: unknown) {
    this.ack = ack;
  }
}

const REASONS: { value: ReportReason; label: string }[] = [
  { value: "harassment", get label() { return ui.reportPlayerDialog.harassmentOrAbuse; } },
  { value: "offensive_drawing", get label() { return ui.reportPlayerDialog.offensiveDrawing; } },
  { value: "inappropriate_name", get label() { return ui.reportPlayerDialog.inappropriateName; } },
  { value: "cheating", get label() { return ui.reportPlayerDialog.cheating; } },
  { value: "spam", get label() { return ui.reportPlayerDialog.spam; } },
  { value: "inappropriate_avatar", get label() { return ui.reportPlayerDialog.inappropriatePicture; } },
];

/** Report somebody in this room.

The reported player is named by their seat; their account is never mentioned
here because the room never tells anyone what it is. Their recent messages are
attached by the server rather than picked here - a reporter should not have to
assemble evidence, and evidence they assembled would have to be checked. The
drawing is the same: when the reported player is the one drawing, the dialog
offers to include it, and the server copies the canvas as it is right now. */
export function ReportPlayerDialog({
  targetPlayerId,
  nickname,
  drawingOffered = false,
  onClose,
}: {
  targetPlayerId: string;
  nickname: string;
  /** Whether this seat is drawing right now, so the canvas can be attached. */
  drawingOffered?: boolean;
  onClose: () => void;
}) {
  const [reason, setReason] = useState<ReportReason>(
    drawingOffered ? "offensive_drawing" : "harassment",
  );
  // On by default when offered: a complaint about the player drawing is
  // almost always about the drawing, and a reporter in a hurry should not
  // have to find the box.
  const [includeDrawing, setIncludeDrawing] = useState(drawingOffered);

  async function send(details: string): Promise<string> {
    // The reporter's choice, sent as made, and read back from here rather
    // than from the live props afterwards. If the turn has ended since the
    // box was ticked the server declines it and says so; deciding that here
    // would only hide the answer - and the offer itself can vanish before the
    // confirmation renders, when the reporter should still hear why the
    // drawing did not come with it.
    const drawingRequested = includeDrawing;
    const result = await reportPlayerInRoom({
      targetPlayerId,
      reason,
      details,
      includeDrawing: drawingRequested,
    });
    if (!result.ok) throw new Refused(result);
    return sentSummary({
      messages: result.evidenceCount ?? 0,
      drawing: result.drawingAttached ?? false,
      drawingRequested,
    });
  }

  return (
    <ReportDialog
      title={ui.reportPlayerDialog.reportNickname({ nickname })}
      intro={ui.reportPlayerDialog.nothingHappensYet({ name: nickname })}
      reason={{
        label: ui.reportPlayerDialog.whatHappened,
        choices: REASONS,
        value: reason,
        onChange: setReason,
      }}
      detailsPlaceholder={ui.reportPlayerDialog.whatTheySaidDrewWhen}
      attachedHint={ui.reportPlayerDialog.theirRecentMessagesThisRoomAre}
      trailing={
        drawingOffered && (
          <label className="report-include-drawing">
            <input
              type="checkbox"
              checked={includeDrawing}
              onChange={(change) => setIncludeDrawing(change.target.checked)}
            />
            <span>
              {ui.reportPlayerDialog.includeTheirDrawing}
              <span>{ui.reportPlayerDialog.canvasAsRightNowSoModerator}</span>
            </span>
          </label>
        )
      }
      onSend={send}
      // A refusal is the server's answer; anything else is the socket - a
      // dropped connection or no answer in time - and says which.
      failureText={(problem) =>
        problem instanceof Refused
          ? refusalText(problem.ack, ui.reportDialog.couldNotSend)
          : socketRequestErrorMessage(problem, ui.reportPlayerDialog.sendThatReport)
      }
      onClose={onClose}
    />
  );
}
