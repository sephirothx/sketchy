import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
interface ChoosingPromptOverlayProps {
  drawerNickname: string;
  drawerNameColor?: string;
}

export function ChoosingPromptOverlay({
  drawerNickname,
  drawerNameColor,
}: ChoosingPromptOverlayProps) {
  return (
    <div
      className="choosing-prompt-overlay"
      data-testid="choosing-prompt-status"
      role="status"
      aria-live="polite"
    >
      <div className="choosing-prompt-card">
        <div className="choosing-prompt-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <p className="choosing-prompt-kicker">{ui.choosingPromptOverlay.nextTurn}</p>
        <p className="choosing-prompt-message">
          {fill(ui.choosingPromptOverlay.isChoosingPrompt, {
            drawer: (
              <strong
                className="colored-player-name"
                style={{ color: drawerNameColor }}
              >
                {drawerNickname}
              </strong>
            ),
          })}
        </p>
        <p className="choosing-prompt-hint">
          {ui.choosingPromptOverlay.drawingWillBeginAsSoonAs}
        </p>
      </div>
    </div>
  );
}
