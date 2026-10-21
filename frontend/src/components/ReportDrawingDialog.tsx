import { ReportDialog } from "./ReportDialog";
import { reportGalleryDrawing } from "../lib/moderation";
import { ui } from "../content/ui/index.ts";

/** Report a drawing met in the Gallery (R-GAL-08).

The in-room report dialog attaches the canvas only while the room still shows
it; a Gallery drawing is one the room has long since left behind, seen by
people who were never there. So there is no reason to choose - a drawing in
the Gallery can only be reported as a drawing - and nothing to cite: the
server holds the frame the Gallery shows, resolves who drew it, and copies the
stored drawing as the evidence. All that is asked here is whether the
reporter has anything to add. */
export function ReportDrawingDialog({
  turnId,
  submit,
  onClose,
}: {
  /** The Gallery's drawing, by turn. */
  turnId?: string;
  /** Another door's report instead - a Solo serve (#1434), which names no turn. */
  submit?: (details: string | null) => Promise<unknown>;
  onClose: () => void;
}) {
  return (
    <ReportDialog
      title={ui.reportDrawingDialog.reportThisDrawing}
      intro={ui.reportDrawingDialog.nothingHappensYet}
      testId="report-drawing-dialog"
      sendTestId="report-drawing-send"
      onSend={async (details) => {
        if (submit) await submit(details);
        else if (turnId) await reportGalleryDrawing(turnId, details);
        return ui.reportDrawingDialog.sentWithTheDrawingAttached;
      }}
      onClose={onClose}
    />
  );
}
