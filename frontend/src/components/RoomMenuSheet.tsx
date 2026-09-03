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
  ChevronDownIcon,
  CopyIcon,
  DownloadIcon,
  GearIcon,
  LeaveIcon,
  LinkIcon,
  MoonIcon,
  RoundsIcon,
  UsersIcon,
} from "./icons";

export interface RoomMenuActions {
  code: string;
  isPlaying: boolean;
  isAfk: boolean;
  canProposeRestart: boolean;
  restartBusy: boolean;
  restartCooldownSeconds: number;
  onShareInvite: () => void;
  onCopyCode: () => void;
  onOpenPlayers: () => void;
  onToggleAfk: () => void;
  onSaveImage: () => void;
  onOpenSettings: () => void;
  onProposeRestart: () => void;
  onLeave: () => void;
}

interface RoomMenuItemsProps extends RoomMenuActions {
  /** The phone sheet carries what the phone bar has no room for. */
  phone: boolean;
  /** Inside a role="menu" the rows are menu items; in a sheet they are buttons. */
  inMenu: boolean;
  /** Closes the menu before an action runs. */
  dismiss: () => void;
}

/**
 * The room's actions, as one list used by both the desktop dropdown and the
 * phone sheet — the same rows in the same order, so a player who learns the
 * menu on one device knows it on the other.
 *
 * The invite comes first because it is what a waiting room is for. Routine
 * actions follow. Leaving is last, separated, and styled as the destructive
 * thing it is (it still routes through the confirmation dialog).
 */
export function RoomMenuItems({
  phone,
  inMenu,
  dismiss,
  code,
  isPlaying,
  isAfk,
  canProposeRestart,
  restartBusy,
  restartCooldownSeconds,
  onShareInvite,
  onCopyCode,
  onOpenPlayers,
  onToggleAfk,
  onSaveImage,
  onOpenSettings,
  onProposeRestart,
  onLeave,
}: RoomMenuItemsProps) {
  const run = (action: () => void) => () => {
    dismiss();
    action();
  };

  return (
    <>
      <div className="room-menu-invite">
        <div className="room-menu-invite-code">
          <span className="room-menu-invite-label">Invite</span>
          <span className="room-menu-code" aria-label={`Room code ${code}`}>{code}</span>
        </div>
        <button type="button" role={inMenu ? "menuitem" : undefined} className="btn btn-primary btn-compact" onClick={run(onShareInvite)}>
          <LinkIcon size={14} />
          Share the link
        </button>
        <button type="button" role={inMenu ? "menuitem" : undefined} className="btn btn-secondary btn-compact" onClick={run(onCopyCode)}>
          <CopyIcon size={13} />
          Copy code
        </button>
      </div>
      <ul className="sheet-menu" role="presentation">
        {phone && isPlaying && (
          <li>
            <button type="button" role={inMenu ? "menuitem" : undefined} className="sheet-menu-item" onClick={run(onOpenPlayers)}>
              <UsersIcon size={19} />
              <span>Players and scores</span>
            </button>
          </li>
        )}
        <li>
          <button
            type="button"
            role={inMenu ? "menuitemcheckbox" : undefined}
            className={`sheet-menu-item game-header-afk-button${isAfk ? " is-active" : ""}`}
            aria-checked={inMenu ? isAfk : undefined}
            aria-pressed={inMenu ? undefined : isAfk}
            onClick={run(onToggleAfk)}
          >
            <MoonIcon size={19} />
            <span>{isAfk ? "I’m back" : "Go AFK"}</span>
            {!isAfk && <small>skipped until you’re back</small>}
          </button>
        </li>
        {isPlaying && (
          <li>
            <button type="button" role={inMenu ? "menuitem" : undefined} className="sheet-menu-item" onClick={run(onSaveImage)}>
              <DownloadIcon size={19} />
              <span>Save this drawing</span>
            </button>
          </li>
        )}
        {isPlaying && canProposeRestart && (
          <li>
            <button
              type="button"
              role={inMenu ? "menuitem" : undefined}
              className="sheet-menu-item game-header-restart-button"
              disabled={restartBusy || restartCooldownSeconds > 0}
              aria-label={restartCooldownSeconds > 0
                ? `Restart vote available in ${restartCooldownSeconds} seconds`
                : undefined}
              onClick={run(onProposeRestart)}
            >
              <RoundsIcon size={19} />
              <span>
                Vote to restart the game
                {restartCooldownSeconds > 0 && (
                  <small> · in {restartCooldownSeconds}s</small>
                )}
              </span>
            </button>
          </li>
        )}
        {phone && (
          <li>
            <button
              type="button"
              role={inMenu ? "menuitem" : undefined}
              className="sheet-menu-item header-settings-button"
              onClick={run(onOpenSettings)}
            >
              <GearIcon size={19} />
              <span>Player settings</span>
            </button>
          </li>
        )}
        <li className="sheet-menu-sep">
          <button
            type="button"
            role={inMenu ? "menuitem" : undefined}
            className="sheet-menu-item is-danger game-header-leave-button"
            onClick={run(onLeave)}
          >
            <LeaveIcon size={19} />
            <span>Leave the room</span>
          </button>
        </li>
      </ul>
    </>
  );
}

/** The room menu on a phone: a sheet under the thumb, the game still visible above it. */
export function RoomMenuSheet({ onDismiss, ...actions }: RoomMenuActions & { onDismiss: () => void }) {
  return (
    <BottomSheet title="Room" onDismiss={onDismiss} testId="room-menu-sheet">
      <RoomMenuItems phone inMenu={false} dismiss={onDismiss} {...actions} />
    </BottomSheet>
  );
}

/**
 * The room menu on a desktop: the bar's one action for a room, opening a
 * dropdown under itself. Focus returns to the button before an action runs,
 * so a dialog the action opens (the leave confirmation) restores focus to
 * something that still exists when it closes.
 */
export function RoomMenuDropdown(actions: RoomMenuActions) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

  useEscapeLayer(open, () => setOpen(false));
  useFocusTrap(menuRef, { active: open });

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(currentIndex + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  const dismiss = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div className="room-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`btn btn-secondary btn-compact room-menu-button${open ? " is-open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        Room
        <ChevronDownIcon size={14} />
      </button>
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          className="room-menu-dropdown"
          role="menu"
          aria-label="Room"
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          <RoomMenuItems phone={false} inMenu dismiss={dismiss} {...actions} />
        </div>
      )}
    </div>
  );
}
