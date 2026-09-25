import { useState } from "react";

import { ReportDialog } from "./ReportDialog";
import type { LobbyChatLine } from "../lib/lobbyChat";
import { submitPlayerReport, type ReportReason } from "../lib/moderation";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { ui } from "../content/ui/index.ts";

/** The reasons a line of chat can be reported for. A line is words, so the
reasons about a drawing, a picture, or play are left out rather than offered
and never true. */
const REASONS: { value: ReportReason; label: string }[] = [
  { value: "harassment", get label() { return ui.reportLobbyLineDialog.harassmentOrAbuse; } },
  { value: "spam", get label() { return ui.reportLobbyLineDialog.spam; } },
  { value: "inappropriate_name", get label() { return ui.reportLobbyLineDialog.inappropriateName; } },
];

/** Report a line of the lobby's chat.

The room's dialog names a seat and lets the server pick the evidence. The
lobby has no seat - a line carries its author's account id for exactly this
reason (R-ROOM-07) - so this one goes over REST, names the account, and cites
the one line it was opened from; the server adds what the lobby said around
it, as it does for a room. The line is shown here so the reporter sees what
they are citing. */
export function ReportLobbyLineDialog({
  line,
  retainedMessageId,
  onClose,
}: {
  line: LobbyChatLine;
  /** Held apart from the line so a caller cannot open this without one. */
  retainedMessageId: string;
  onClose: () => void;
}) {
  const [reason, setReason] = useState<ReportReason>("harassment");

  return (
    <ReportDialog
      title={ui.reportLobbyLineDialog.reportDisplayName({ displayName: line.displayName })}
      intro={ui.reportLobbyLineDialog.nothingHappensYet({ name: line.displayName })}
      testId="report-lobby-line-dialog"
      quoted={
        <blockquote className="report-quoted-line" data-testid="report-quoted-line">
          <strong
            className={playerNameClass(line.isAnonymous)}
            style={playerNameStyle(line.nameColor ?? undefined, line.isAnonymous)}
          >
            {line.displayName}:{" "}
          </strong>
          {line.text}
        </blockquote>
      }
      reason={{
        label: ui.reportLobbyLineDialog.whatWrongWith,
        choices: REASONS,
        value: reason,
        onChange: setReason,
      }}
      attachedHint={ui.reportLobbyLineDialog.thisLineAttachedWithWhatLobby}
      onSend={async (details) => {
        await submitPlayerReport({
          reportedUserId: line.userId,
          reason,
          details,
          messageIds: [retainedMessageId],
        });
        return ui.reportLobbyLineDialog.sentWithLineWhatWasSaid;
      }}
      onClose={onClose}
    />
  );
}
