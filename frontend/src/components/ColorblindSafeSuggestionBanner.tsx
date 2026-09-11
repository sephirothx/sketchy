import { ui } from "../content/ui/index.ts";
export function ColorblindSafeSuggestionBanner({
  busy,
  onAccept,
  onDismiss,
}: {
  busy: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <aside
      className="colorblind-safe-suggestion"
      aria-label={ui.colorblindSafeSuggestionBanner.colorblindSafeColorSuggestion}
      data-testid="colorblind-safe-suggestion"
    >
      <div className="colorblind-safe-suggestion-copy">
        <strong>{ui.colorblindSafeSuggestionBanner.playerThisRoomPlaysWithColorblind}</strong>
        <span>{ui.colorblindSafeSuggestionBanner.switchRoomPaletteFutureDrawings}</span>
      </div>
      <div className="colorblind-safe-suggestion-actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={onAccept}
        >
          {ui.colorblindSafeSuggestionBanner.switchColors}
        </button>
        <button type="button" disabled={busy} onClick={onDismiss}>
          {ui.colorblindSafeSuggestionBanner.notNow}
        </button>
      </div>
    </aside>
  );
}
