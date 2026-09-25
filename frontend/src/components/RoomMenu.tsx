import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { BottomSheet } from "./ui/BottomSheet";
import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";
import {
  DotsIcon,
  DownloadIcon,
  LeaveIcon,
  LinkIcon,
  MoonIcon,
  RoundsIcon,
  UsersIcon,
} from "./icons";
import { useCooldownSeconds } from "../hooks/useCooldownSeconds";
import { ui } from "../content/ui/index.ts";

export interface RoomMenuActions {
  code: string;
  isPlaying: boolean;
  isAfk: boolean;
  canProposeRestart: boolean;
  restartBusy: boolean;
  /** When the next restart vote may be called, as a `Date.now()` timestamp. */
  restartCooldownUntil: number;
  onCopyLink: () => void;
  /** Only where the players are not already on screen: a phone in play. */
  onOpenPlayers?: () => void;
  onToggleAfk: () => void;
  onSaveImage: () => void;
  onProposeRestart: () => void;
  onLeave: () => void;
}

/**
 * The Room menu's rows (#580): one list, drawn as a dropdown on a desktop and
 * as the ⋯ sheet on a phone, so the two can never disagree about what a room
 * offers or in which order.
 *
 * Routine first, leaving last and red, below a rule. The room code is here
 * rather than in the bar: it is what the invite link carries, and a player
 * who wants it is a player who wants to invite somebody. The one row that
 * differs by device is Players and scores, which a phone needs because its
 * players column is folded away and a desktop does not, because it is not.
 *
 * Player settings is not a row: they are about you, not the room, and the
 * identity chip beside this menu opens them at every width (R-UX-11). While
 * a phone's bar left the chip out this list carried a Settings row; once the
 * chip came back, two menus side by side offered the same screen.
 */
function RoomMenuRows({ actions, run, asMenu }: {
  actions: RoomMenuActions;
  run: (action: () => void) => () => void;
  /** Rows of a `role="menu"` rather than plain buttons in a sheet. */
  asMenu: boolean;
}) {
  const role = asMenu ? "menuitem" : undefined;
  const {
    code, isPlaying, isAfk, canProposeRestart, restartBusy, restartCooldownUntil,
  } = actions;
  const restartCooldownSeconds = useCooldownSeconds(restartCooldownUntil);
  return (
    <ul className="sheet-menu" role={asMenu ? "none" : undefined}>
      {isPlaying && actions.onOpenPlayers && (
        <li role={asMenu ? "none" : undefined}>
          <button type="button" role={role} className="sheet-menu-item" onClick={run(actions.onOpenPlayers)}>
            <UsersIcon size={19} />
            <span>{ui.roomMenuSheet.playersScores}</span>
          </button>
        </li>
      )}
      <li role={asMenu ? "none" : undefined}>
        <button
          type="button"
          role={role}
          className="sheet-menu-item room-menu-invite"
          data-room-code={code}
          onClick={run(actions.onCopyLink)}
        >
          <LinkIcon size={19} />
          <span>
            {ui.roomMenuSheet.copyInviteLink}
            <small className="room-menu-code">{code}</small>
          </span>
        </button>
      </li>
      <li role={asMenu ? "none" : undefined}>
        <button
          type="button"
          role={asMenu ? "menuitemcheckbox" : undefined}
          className={`sheet-menu-item${isAfk ? " is-active" : ""}`}
          aria-pressed={asMenu ? undefined : isAfk}
          aria-checked={asMenu ? isAfk : undefined}
          onClick={run(actions.onToggleAfk)}
        >
          <MoonIcon size={19} />
          <span>{isAfk ? ui.roomMenuSheet.iMBack : ui.roomMenuSheet.goAwayForABit}</span>
        </button>
      </li>
      {isPlaying && (
        <li role={asMenu ? "none" : undefined}>
          <button type="button" role={role} className="sheet-menu-item" onClick={run(actions.onSaveImage)}>
            <DownloadIcon size={19} />
            <span>{ui.roomMenuSheet.saveThisDrawing}</span>
          </button>
        </li>
      )}
      {isPlaying && canProposeRestart && (
        <li role={asMenu ? "none" : undefined}>
          <button
            type="button"
            role={role}
            className="sheet-menu-item"
            disabled={restartBusy || restartCooldownSeconds > 0}
            onClick={run(actions.onProposeRestart)}
          >
            <RoundsIcon size={19} />
            <span>
              {ui.roomMenuSheet.startTheGameOver}
              {restartCooldownSeconds > 0 && (
                <small>{ui.roomMenuSheet.startOverCooldown({ seconds: restartCooldownSeconds })}</small>
              )}
            </span>
          </button>
        </li>
      )}
      <li className="sheet-menu-sep" role={asMenu ? "none" : undefined}>
        <button
          type="button"
          role={role}
          className="sheet-menu-item is-danger room-menu-leave"
          onClick={run(actions.onLeave)}
        >
          <LeaveIcon size={19} />
          <span>{ui.roomMenuSheet.leaveRoom}</span>
        </button>
      </li>
    </ul>
  );
}

/** The Room menu on a phone: the rows as a bottom sheet over the room. */
export function RoomMenuSheet({ actions, onDismiss }: {
  actions: RoomMenuActions;
  onDismiss: () => void;
}) {
  const run = (action: () => void) => () => {
    onDismiss();
    action();
  };
  return (
    <BottomSheet title={ui.roomMenuSheet.room} onDismiss={onDismiss} testId="room-menu-sheet">
      <RoomMenuRows actions={actions} run={run} asMenu={false} />
    </BottomSheet>
  );
}

/**
 * The Room menu on a desktop: the same rows, dropped down from the bar.
 *
 * Built like the identity chip's menu - a real `role="menu"`, focus moved in
 * on open and back to the button on close, arrow keys between rows, Escape
 * and a click elsewhere to dismiss - because it is the same kind of control
 * sitting beside it.
 */
export function RoomMenuDropdown({ actions }: { actions: RoomMenuActions }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

  useEscapeLayer(open, () => setOpen(false));
  useFocusTrap(menuRef, { active: open });

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step !== undefined) {
      event.preventDefault();
      items[(index + step + items.length) % items.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  const run = (action: () => void) => () => {
    setOpen(false);
    action();
  };

  return (
    <div className="room-menu" ref={rootRef}>
      <button
        type="button"
        className="btn btn-secondary btn-compact game-header-menu-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        data-testid="open-room-menu"
        onClick={() => setOpen((current) => !current)}
      >
        <DotsIcon size={16} />
        <span>{ui.roomMenuSheet.room}</span>
      </button>
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          className="room-menu-dropdown"
          role="menu"
          aria-label={ui.activeGameRoom.roomMenu}
          tabIndex={-1}
          onKeyDown={handleKeyDown}
          data-testid="room-menu-sheet"
        >
          <RoomMenuRows actions={actions} run={run} asMenu />
        </div>
      )}
    </div>
  );
}
