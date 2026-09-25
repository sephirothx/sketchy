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
import { siteLinkCurrent } from "../lib/siteNav.ts";
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
 * Between the two, on a desktop (901px and up), the site's pages: the lobby,
 * the Gallery (only with a session - R-GAL-02), the Community catalogue,
 * Prompt stats and Rules, the one you are on marked. They were reachable only
 * from the chip's menu, and the lobby's own row of links sat below the fold on
 * every other page. Icons with a tooltip up to 1199px, where the labels would
 * crowd the chip; labels from 1200px. A phone has no room in its bar, so it
 * keeps the menu and the lobby's row (`LobbyLinks`) instead.
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
 * The site's pages, in the bar. Hidden below 901px by CSS (lobby-page.css),
 * which keeps the first paint right without waiting for a media query here.
 * The labels are always in the markup; from 901 to 1199px they are hidden
 * visually and the link keeps its name, with the same words as a tooltip.
 *
 * From 1200px the labels show if they fit. In English they fit with room to
 * spare, but the labels are as long as a language makes them - Spanish's
 * Prompt stats is "Estadísticas de palabras" - and beside a crumb, the flag
 * and a long name they pushed the flag onto a second row at 1200px. So the
 * nav takes only the width the bar has left (`flex-basis: 0`, which also means
 * its own content never changes that width, so the check cannot flip back and
 * forth), and when the labelled row is wider than that it falls back to icons
 * (`is-crowded`). The labelled width is remembered from the last time the
 * labels were shown, and measured again whenever the words change or a web
 * font finishes loading.
 */
function SiteNav() {
  const { pathname } = useLocation();
  const hasSession = useAuthStore((state) => linksToGallery(state.user));
  const wide = useMediaQuery("(min-width: 1200px)");
  const locale = useLocaleRerender();
  const navRef = useRef<HTMLElement>(null);
  const labelledWidth = useRef(0);
  // Crowded for these words: new words, or a link more or fewer, show the
  // labels once more, so the next pass measures them rather than a width
  // remembered for others.
  const words = `${locale}|${hasSession}`;
  const [crowdedFor, setCrowdedFor] = useState<string | null>(null);
  const crowded = crowdedFor === words;
  const labelled = wide && !crowded;

  useLayoutEffect(() => {
    const nav = navRef.current;
    const list = nav?.firstElementChild;
    if (!wide || !nav || !(list instanceof HTMLElement)) return;
    const check = () => {
      if (!nav.classList.contains("is-crowded")) labelledWidth.current = list.scrollWidth;
      setCrowdedFor(labelledWidth.current > list.clientWidth ? words : null);
    };
    check();
    // A web font that arrives after this pass changes the labels' width
    // without resizing the nav, so nothing above would notice. Once it has
    // loaded: measure again, and if the row was already icons, show the
    // labels for one pass so that pass measures them in the real font. Only
    // while fonts are still loading - `ready` also resolves at once when they
    // are not, and un-crowding on that would loop.
    let live = true;
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    if (fonts && fonts.status === "loading") {
      void fonts.ready.then(() => {
        if (!live) return;
        if (nav.classList.contains("is-crowded")) setCrowdedFor(null);
        else check();
      });
    }
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    observer?.observe(nav);
    return () => {
      live = false;
      observer?.disconnect();
    };
  }, [wide, words, crowded]);

  const pages: { to: string; label: string; icon: ReactNode }[] = [
    { to: "/", label: ui.lobbyBrowserPage.lobby, icon: <HomeIcon size={16} /> },
    ...(hasSession ? [{ to: "/gallery", label: ui.galleryPage.gallery, icon: <ImageIcon size={16} /> }] : []),
    { to: "/community-lists", label: ui.communityCataloguePage.communityCatalogue, icon: <StarIcon size={16} /> },
    { to: "/prompt-lists", label: ui.accountMenu.promptStats, icon: <BarChartIcon size={16} /> },
    { to: "/rules", label: ui.accountMenu.rules, icon: <InfoIcon size={16} /> },
  ];
  return (
    <nav ref={navRef} className={`site-nav${crowded ? " is-crowded" : ""}`} aria-label={ui.appHeader.siteNav}>
      <ul>
        {pages.map((page) => (
          <li key={page.to}>
            <Link
              to={page.to}
              className="site-nav-link"
              aria-current={siteLinkCurrent(page.to, pathname)}
              title={labelled ? undefined : page.label}
            >
              {page.icon}
              <span className="site-nav-label">{page.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
