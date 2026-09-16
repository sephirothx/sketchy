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
 * Where you are is the wordmark, which always goes back to the lobby. The
 * page's name is the page's own heading, a few pixels below, and is not said
 * again here: a crumb repeating it on every sub-page put the same words twice
 * on one screen. A page that sits under another (a Gallery drawing) gets a
 * crumb anyway, because there it does something the heading cannot - it is
 * the link back to its parent.
 *
 * On a desktop there is no back button: the wordmark is the way home and the
 * crumb the way up. On a phone the arrow comes back, beside the wordmark
 * rather than in place of it - the invite page is the one screen a
 * first-time visitor may arrive on from a link, and it has to say whose site
 * it is.
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
  parent,
  backLabel,
  backTo = "/",
  languageSwitch = false,
}: {
  /** The page this one sits under, as a crumb linking back to it on a wide
      screen. Only for nested pages: a page's own name is its heading. */
  parent?: { label: string; to: string };
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
        {parent && !isNarrow && (
          <p className="header-crumb">
            <ChevronRightIcon size={14} />
            <a
              href={parent.to}
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                event.preventDefault();
                navigate(parent.to);
              }}
            >
              {parent.label}
            </a>
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
