import { useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { AccountMenu } from "./AccountMenu";
import { BackIcon, GearIcon, Wordmark } from "./icons";
import { ui } from "../content/ui/index.ts";
import { InterfaceLanguageButton } from "./InterfaceLanguageButton";

/**
 * The shared page chrome outside a room: the wordmark on the left, preceded by
 * a back control on sub-pages, and the settings gear and identity chip on the
 * right.
 *
 * The wordmark is on every page, sub-pages included. It used to be replaced by
 * the back button there, so the one screen a first-time visitor might arrive on
 * from a link was the one that never said whose site it was. On a phone the
 * back control is the arrow alone — the label is what would not fit beside it.
 *
 * The gear keeps its `.header-settings-button` class and "Player settings"
 * name — Settings restores focus to it on close, and the e2e suite asserts
 * both. It opens `/settings/account` over this page (R-SET-06).
 *
 * On a phone the gear moves into the identity menu instead: three controls
 * beside a wordmark is what used to push this header onto two rows, and
 * settings is the one of them nobody opens mid-session.
 *
 * A page's own actions are not the chrome's and do not live here: the lobby's
 * *Create room* and *Join by code* sit beside its room list (#594), and a phone
 * has them in the lobby's thumb dock.
 *
 * `languageSwitch` is the exception, shown at every width: the language you
 * read in, as a flag. It is the one control a visitor who cannot read the
 * page needs before any other, and a phone is where Settings is furthest away.
 */
export function AppHeader({
  backLabel,
  backTo = "/",
  languageSwitch = false,
}: {
  backLabel?: string;
  /** Where the back control goes: the lobby unless a page sits under another. */
  backTo?: string;
  languageSwitch?: boolean;
} = {}) {
  const navigate = useNavigate();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const openSettings = useOpenSettings();

  return (
    <header className={`lobby-header${backLabel ? " has-back" : ""}`}>
      <div className="lobby-header-lead">
        {backLabel && (
          <button
            type="button"
            className="btn btn-ghost header-back-button"
            onClick={() => navigate(backTo)}
            aria-label={backLabel}
            title={backLabel}
          >
            <BackIcon size={15} />
            <span className="header-back-label">{backLabel}</span>
          </button>
        )}
        <h1 className="lobby-wordmark">
          <Wordmark size={34} />
        </h1>
      </div>
      <div className="lobby-header-actions">
        {languageSwitch && <InterfaceLanguageButton />}
        {!isNarrow && (
          <button
            type="button"
            className="btn btn-icon header-settings-button"
            onClick={() => openSettings()}
            title={ui.appHeader.playerSettings}
            aria-label={ui.appHeader.playerSettings}
          >
            <GearIcon size={18} />
          </button>
        )}
        <AccountMenu />
      </div>
    </header>
  );
}
