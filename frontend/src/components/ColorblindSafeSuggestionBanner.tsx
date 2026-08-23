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
      aria-label="Colorblind-safe color suggestion"
      data-testid="colorblind-safe-suggestion"
    >
      <div className="colorblind-safe-suggestion-copy">
        <strong>A player in this room plays with colorblind-safe colors.</strong>
        <span>Switch the room palette for future drawings?</span>
      </div>
      <div className="colorblind-safe-suggestion-actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
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
