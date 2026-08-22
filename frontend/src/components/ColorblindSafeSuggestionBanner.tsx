import type { ColorblindSafeSuggestion } from "../types";

export function ColorblindSafeSuggestionBanner({
  suggestion,
  busy,
  onAccept,
  onDismiss,
}: {
  suggestion: ColorblindSafeSuggestion;
  busy: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <aside
      className="colorblind-safe-suggestion"
      aria-label="Colorblind-safe color suggestion"
      data-testid="colorblind-safe-suggestion"
    >
      <div className="colorblind-safe-suggestion-copy">
        <strong>A player in this room plays with colorblind-safe colors.</strong>
        <span>
          {suggestion.canApply
            ? "Switch the room palette for future drawings?"
            : "The palette can be switched after this game."}
        </span>
      </div>
      <div className="colorblind-safe-suggestion-actions">
        <button
          type="button"
          className="primary"
          disabled={busy || !suggestion.canApply}
          onClick={onAccept}
        >
          Switch colors
        </button>
        <button type="button" disabled={busy} onClick={onDismiss}>
          Not now
        </button>
      </div>
    </aside>
  );
}
