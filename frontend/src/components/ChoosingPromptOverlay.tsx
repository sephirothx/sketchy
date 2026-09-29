import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
interface ChoosingPromptOverlayProps {
  drawerNickname: string;
  drawerNameColor?: string;
  /** A guest drawer wears the guest style here as everywhere (#1279): the
      bare name showed upright in #888, 3.54:1, on every turn. */
  drawerIsAnonymous?: boolean;
}

export function ChoosingPromptOverlay({
  drawerNickname,
  drawerNameColor,
  drawerIsAnonymous,
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
        <p className="section-label choosing-prompt-kicker">{ui.choosingPromptOverlay.nextTurn}</p>
        <p className="choosing-prompt-message">
          {fill(ui.choosingPromptOverlay.isChoosingPrompt, {
            drawer: (
              <strong
                className={playerNameClass(drawerIsAnonymous)}
                style={playerNameStyle(drawerNameColor, drawerIsAnonymous)}
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
