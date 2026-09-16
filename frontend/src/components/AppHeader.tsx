import { useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { AccountMenu } from "./AccountMenu";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { needsIdentity, useAuthStore } from "../store/authStore";
import { BackIcon, ChevronRightIcon, GearIcon, Wordmark } from "./icons";
import { ui } from "../content/ui/index.ts";
import { InterfaceLanguageButton } from "./InterfaceLanguageButton";

/**
 * The shared page chrome outside a room (#580): where you are on the left, you
 * on the right.
 *
 * Where you are is the wordmark, which always goes back to the lobby, then the
 * page's name as a crumb. The crumb is what this bar lacked: every sub-page
 * drew the same back button, wordmark, gear and chip, so the bar never said
 * which page it was. It is accessory - a phone drops it, and the page's own
 * heading says the same thing further down.
 *
 * On a desktop there is no back button: the wordmark is the way home, and a
 * page under another (a Gallery drawing) makes its crumb the link to its
 * parent. On a phone the arrow comes back, beside the wordmark rather than in
 * place of it - the invite page is the one screen a first-time visitor may
 * arrive on from a link, and it has to say whose site it is.
 *
 * You is the identity chip, and nothing beside it: Player settings are the
 * first row of the chip's menu on every width, where the gear used to sit one
 * control to its left (variant C). Before there is anybody to show - a first
 * visit, before a name - the gear takes the chip's place. Both carry
 * `.header-settings-button`.
 *
 * A page's own actions are not the chrome's and do not live here: the lobby's
 * *Create room* and *Join by code* sit beside its room list (#594), and a phone
 * has them in the lobby's thumb dock.
 *
 * `languageSwitch` shows the language you read in, as a flag, at every width:
 * it is the one control a visitor who cannot read the page needs before any
 * other, and a phone is where Settings is furthest away.
 */
export function AppHeader({
  title,
  titleTo,
  backLabel,
  backTo = "/",
  languageSwitch = false,
}: {
  /** The page's name, shown after the wordmark on a wide screen. */
  title?: string;
  /** Where the crumb goes, for a page that sits under another. */
  titleTo?: string;
  /** Names the phone's back arrow. */
  backLabel?: string;
  /** Where the back arrow goes: the lobby unless a page sits under another. */
  backTo?: string;
  languageSwitch?: boolean;
} = {}) {
  const navigate = useNavigate();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const showBack = Boolean(backLabel) && isNarrow;
  const openSettings = useOpenSettings();
  // The chip is only drawn once there is somebody to show. Until then - a
  // first visit, before a name - the gear stands in its place, so the theme
  // and the language are never out of reach of somebody who has not decided
  // to play yet.
  const nameless = useAuthStore((state) => state.hasResolved && needsIdentity(state.user) && !state.user?.displayName);

  return (
    <header className={`lobby-header${showBack ? " has-back" : ""}`}>
      <div className="lobby-header-lead">
        {showBack && (
          <button
            type="button"
            className="btn btn-ghost header-back-button"
            onClick={() => navigate(backTo)}
            aria-label={backLabel}
            title={backLabel}
          >
            <BackIcon size={15} />
          </button>
        )}
        <h1 className="lobby-wordmark">
          <a
            href="/"
            className="header-home-link"
            title={ui.appHeader.sketchyHome}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
              event.preventDefault();
              navigate("/");
            }}
          >
            <Wordmark size={34} />
          </a>
        </h1>
        {title && !isNarrow && (
          <p className="header-crumb">
            <ChevronRightIcon size={14} />
            {titleTo ? (
              <a
                href={titleTo}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                  event.preventDefault();
                  navigate(titleTo);
                }}
              >
                {title}
              </a>
            ) : (
              <span>{title}</span>
            )}
          </p>
        )}
      </div>
      <div className="lobby-header-actions">
        {languageSwitch && <InterfaceLanguageButton />}
        {nameless && (
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
