import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { AccountMenu } from "./AccountMenu";
import { BackIcon, CopyIcon, GearIcon, Wordmark } from "./icons";

export interface HeaderRoom {
  name: string;
  code: string;
  /** Pressing the chip copies the invite link. */
  onCopyLink: () => void;
}

interface AppHeaderProps {
  /** A sub-page's name, shown as a crumb beside the wordmark. */
  page?: string;
  /** The room this screen is inside, shown as the room chip. */
  room?: HeaderRoom;
  /** What is going on: the room's phase. Empty outside a room. */
  center?: ReactNode;
  /** The one action this place has: the lobby's Create room, a room's menu. */
  action?: ReactNode;
  /** Force the phone layout. Rooms switch layouts at 900px, pages at 720px. */
  phone?: boolean;
}

/**
 * One bar, three slots, on every screen.
 *
 *   1 · where you are — the wordmark, which is always the way back to the
 *       lobby, then the place: a page name, or the room chip.
 *   2 · what is going on — the room's phase while you are in one; empty
 *       everywhere else.
 *   3 · you — at most three controls, and the last two never move: the
 *       place's one action, then Player settings, then the identity chip.
 *
 * The way back is in slot 1 too. The wordmark is a link to the lobby on
 * every screen but a room, where a click must not silently give up the seat.
 * A sub-page also gets a back arrow, on both devices: it goes back in
 * history when the previous entry was one of ours, and to the lobby when
 * the page was arrived at from outside.
 *
 * The phone keeps the same three slots with one control each: the arrow or
 * the mark; the page name or the phase; one menu on the right — the
 * identity chip outside a room, the room menu inside one. Player settings
 * lives inside whichever menu that is.
 *
 * The gear keeps its `.header-settings-button` class and "Player settings"
 * name — Settings restores focus to it on close, and the e2e suite asserts
 * both. It opens `/settings/account` over this page (R-SET-06). The room chip
 * keeps `.room-copy-button` and `data-room-code` for the same reason.
 */
export function AppHeader({ page, room, center, action, phone }: AppHeaderProps = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const openSettings = useOpenSettings();
  const compact = phone ?? isNarrow;
  const mode = room ? "room" : page ? "page" : "lobby";
  // React Router keys the first entry of a session "default"; anything else
  // was navigated to from inside the app, so back is where you came from.
  const goBack = () => {
    if (location.key !== "default") navigate(-1);
    else navigate("/");
  };
  const mark = (
    <h1 className="lobby-wordmark">
      {room ? (
        <Wordmark size={compact ? 22 : 28} />
      ) : (
        <Link to="/" className="lobby-wordmark-link" aria-label="Sketchy · back to the lobby">
          <Wordmark size={compact ? 22 : 28} decorative />
        </Link>
      )}
    </h1>
  );

  return (
    <header
      className={`lobby-header app-header app-header-${mode}${compact ? " is-compact" : ""}${room ? " game-header" : ""}${room && compact ? " game-header-mobile" : ""}`}
    >
      <div className="lobby-header-lead">
        {mode === "page" && (
          <button
            type="button"
            className="btn btn-icon header-back-button"
            onClick={goBack}
            aria-label="Back"
            title="Back"
          >
            <BackIcon size={18} />
          </button>
        )}
        {!(mode === "page" && compact) && mark}
        {mode === "page" && !compact && (
          <>
            <span className="header-divider" aria-hidden="true" />
            <span className="header-crumb">{page}</span>
          </>
        )}
        {room && !compact && (
          <button
            type="button"
            className="room-chip room-copy-button"
            data-room-code={room.code}
            onClick={room.onCopyLink}
            title="Copy the invite link"
          >
            <span className="room-chip-name">{room.name}</span>
            <span className="header-divider" aria-hidden="true" />
            <span className="room-chip-code">{room.code}</span>
            <CopyIcon size={13} />
          </button>
        )}
      </div>

      <div className="app-header-center">
        {mode === "page" && compact ? (
          <span className="app-header-title">{page}</span>
        ) : (
          center
        )}
      </div>

      <div className="lobby-header-actions">
        {action}
        {!compact && (
          <button
            type="button"
            className="btn btn-icon header-settings-button"
            onClick={() => openSettings()}
            title="Player settings"
            aria-label="Player settings"
          >
            <GearIcon size={18} />
          </button>
        )}
        {!(room && compact) && <AccountMenu compact={Boolean(room) || (compact && mode === "page")} />}
      </div>
    </header>
  );
}
