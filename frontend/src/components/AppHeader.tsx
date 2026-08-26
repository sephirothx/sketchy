import { useNavigate } from "react-router-dom";
import { useSettingsStore } from "../store/settingsStore";
import { AccountMenu } from "./AccountMenu";
import { BackIcon, GearIcon, Wordmark } from "./icons";

/**
 * The shared page chrome outside a room: the wordmark (or a back button on
 * sub-pages) on the left, the settings gear and identity chip on the right.
 *
 * The gear keeps its `.header-settings-button` class and "Player settings"
 * name — the settings modal restores focus to it on close, and the e2e suite
 * asserts both.
 */
export function AppHeader({ backLabel }: { backLabel?: string } = {}) {
  const navigate = useNavigate();
  const openSettings = useSettingsStore((s) => s.openSettings);

  return (
    <header className="lobby-header">
      {backLabel ? (
        <button type="button" className="btn btn-ghost header-back-button" onClick={() => navigate("/")}>
          <BackIcon size={15} />
          {backLabel}
        </button>
      ) : (
        <h1 className="lobby-wordmark">
          <Wordmark size={34} />
        </h1>
      )}
      <div className="lobby-header-actions">
        <button
          type="button"
          className="btn btn-icon header-settings-button"
          onClick={openSettings}
          title="Player settings"
          aria-label="Player settings"
        >
          <GearIcon size={18} />
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}
