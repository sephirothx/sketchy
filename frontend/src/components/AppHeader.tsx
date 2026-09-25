import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { AccountMenu } from "./AccountMenu";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { needsIdentity, useAuthStore } from "../store/authStore";
import {
  BackIcon,
  BarChartIcon,
  ChevronRightIcon,
  GearIcon,
  HomeIcon,
  ImageIcon,
  InfoIcon,
  StarIcon,
  Wordmark,
} from "./icons";
import { ui } from "../content/ui/index.ts";
import { InterfaceLanguageButton } from "./InterfaceLanguageButton";
import { linksToGallery } from "../lib/lobbyControls.ts";
import { siteLinkCurrent, siteNavMode } from "../lib/siteNav.ts";
import type { SiteNavMode } from "../lib/siteNav.ts";
import { useLocaleRerender } from "../hooks/useLocaleRerender";

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
 * The bar spans the shell (`--shell-width`) on every page, whatever width the
 * page's own content keeps (`.lobby-header` in settings-shared.css), so the
 * wordmark and the chip sit in the same place on every page.
 *
 * You is the identity chip, and nothing beside it: Player settings are the
 * first row of the chip's menu on every width, where the gear used to sit one
 * control to its left (variant C). Before there is anybody to show - a first
 * visit, before a name - the gear takes the chip's place. Both carry
 * `.header-settings-button`.
 *
 * Between the two, the site's pages: the lobby, the Gallery (only with a
 * session - R-GAL-02), the Community catalogue, Prompt stats and Rules, the
 * one you are on marked. They were reachable only from the chip's menu. The
 * nav takes only the room the rest of the bar leaves, and shows as much of
 * itself as fits there (`SiteNav`); the chip's menu keeps every entry, since
 * on a narrow phone it is the only way there - and a visitor with no name yet,
 * who has no chip, reaches those pages there once they have chosen one.
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
        {/* Not a heading: the page's own <h1> is its name, and a wordmark
            heading on every page made two of them. The link keeps the
            wordmark's name, "Sketchy". */}
        <div className="lobby-wordmark">
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
        </div>
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
      <SiteNav />
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

/**
 * The site's pages, in the bar (R-UX-11): named if the names fit, as icons
 * with a tooltip if only the icons do, and not at all if neither does - at
 * any width, a phone's included. The room is whatever the bar leaves once the
 * wordmark, a crumb, the flag and the chip have theirs: the nav takes
 * `flex: 1 1 0`, so it only ever gets free space and never takes any from
 * them, and its own content never changes the room it is measured against.
 *
 * What each mode needs is read off two rulers - invisible, unfocusable copies
 * of the row with and without its names - so the nav never has to be drawn in
 * a mode to learn whether that mode fits, and the decision is one pure
 * function (`siteNavMode`) with a little slack before growing, so a bar on
 * the line does not flicker. A ResizeObserver watches the room and both
 * rulers, which also catches new words (a language, or the Gallery link
 * arriving with a session) and a web font that changes the names' width,
 * whenever it loads; `document.fonts` is asked too, for a font that loads
 * before the observer's first report. The nav clips its overflow, so the
 * frame before a decision lands never paints names over the flag.
 *
 * Two names have header-only keys (`communityLink`, `promptStatsLink`): at the
 * page titles' length Spanish, French, Italian, Portuguese and Dutch did not
 * fit beside a crumb, the flag and a long name at 1200px, so those languages
 * name the pages more briefly here.
 */
function SiteNav() {
  const { pathname } = useLocation();
  const hasSession = useAuthStore((state) => linksToGallery(state.user));
  useLocaleRerender();
  const boxRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLSpanElement>(null);
  const iconsRef = useRef<HTMLSpanElement>(null);
  const [mode, setMode] = useState<SiteNavMode>("labels");

  useLayoutEffect(() => {
    const box = boxRef.current;
    const labels = labelsRef.current;
    const icons = iconsRef.current;
    if (!box || !labels || !icons) return;
    const check = () => {
      const style = getComputedStyle(box);
      const room = box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      // The rulers carry the row's leading gap (the header's own), as the
      // list does.
      const lead = parseFloat(style.getPropertyValue("--header-gap")) || 0;
      setMode((current) =>
        siteNavMode({
          room,
          labels: labels.getBoundingClientRect().width + lead,
          icons: icons.getBoundingClientRect().width + lead,
          current,
        }),
      );
    };
    check();
    let live = true;
    void document.fonts?.ready.then(() => {
      if (live) check();
    });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    observer?.observe(box);
    observer?.observe(labels);
    observer?.observe(icons);
    return () => {
      live = false;
      observer?.disconnect();
    };
  }, []);

  const pages: { to: string; label: string; icon: ReactNode }[] = [
    { to: "/", label: ui.lobbyBrowserPage.lobby, icon: <HomeIcon size={16} /> },
    ...(hasSession ? [{ to: "/gallery", label: ui.galleryPage.gallery, icon: <ImageIcon size={16} /> }] : []),
    { to: "/community-lists", label: ui.appHeader.communityLink, icon: <StarIcon size={16} /> },
    { to: "/prompt-lists", label: ui.appHeader.promptStatsLink, icon: <BarChartIcon size={16} /> },
    { to: "/rules", label: ui.accountMenu.rules, icon: <InfoIcon size={16} /> },
  ];
  return (
    <div ref={boxRef} className={`site-nav is-${mode}`}>
      {/* `hidden` takes it out of the tab order and the accessibility tree,
          not only out of sight. */}
      <nav aria-label={ui.appHeader.siteNav} hidden={mode === "hidden"}>
        <ul>
          {pages.map((page) => (
            <li key={page.to}>
              <Link
                to={page.to}
                className="site-nav-link"
                aria-current={siteLinkCurrent(page.to, pathname)}
                title={mode === "icons" ? page.label : undefined}
              >
                {page.icon}
                <span className="site-nav-label">{page.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <span className="site-nav-rulers" aria-hidden="true">
        <span ref={labelsRef} className="site-nav-ruler">
          {pages.map((page) => (
            <span key={page.to} className="site-nav-link">
              {page.icon}
              <span className="site-nav-label">{page.label}</span>
            </span>
          ))}
        </span>
        <span ref={iconsRef} className="site-nav-ruler is-icons">
          {pages.map((page) => (
            <span key={page.to} className="site-nav-link">
              {page.icon}
            </span>
          ))}
        </span>
      </span>
    </div>
  );
}
