interface ChoosingWordOverlayProps {
  drawerNickname: string;
  drawerNameColor?: string;
}

export function ChoosingPromptOverlay({
  drawerNickname,
  drawerNameColor,
}: ChoosingWordOverlayProps) {
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
        <p className="choosing-prompt-kicker">Next turn</p>
        <p className="choosing-prompt-message">
          <strong
            className="colored-player-name"
            style={{ color: drawerNameColor }}
          >
            {drawerNickname}
          </strong>{" "}
          is choosing a prompt…
        </p>
        <p className="choosing-prompt-hint">
          Drawing will begin as soon as they choose.
        </p>
      </div>
    </div>
  );
}
