interface ChoosingWordOverlayProps {
  drawerNickname: string;
  drawerNameColor?: string;
}

export function ChoosingWordOverlay({
  drawerNickname,
  drawerNameColor,
}: ChoosingWordOverlayProps) {
  return (
    <div
      className="choosing-word-overlay"
      data-testid="choosing-word-status"
      role="status"
      aria-live="polite"
    >
      <div className="choosing-word-card">
        <div className="choosing-word-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <p className="choosing-word-kicker">Next turn</p>
        <p className="choosing-word-message">
          <strong
            className="colored-player-name"
            style={{ color: drawerNameColor }}
          >
            {drawerNickname}
          </strong>{" "}
          is choosing a word…
        </p>
        <p className="choosing-word-hint">
          Drawing will begin as soon as they choose.
        </p>
      </div>
    </div>
  );
}
