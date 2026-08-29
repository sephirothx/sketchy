import { BottomSheet } from "./ui/BottomSheet";
import {
  DownloadIcon,
  GearIcon,
  LeaveIcon,
  LinkIcon,
  MoonIcon,
  RoundsIcon,
  UsersIcon,
} from "./icons";

interface RoomMenuSheetProps {
  isPlaying: boolean;
  isAfk: boolean;
  canProposeRestart: boolean;
  restartBusy: boolean;
  restartCooldownSeconds: number;
  onDismiss: () => void;
  onCopyLink: () => void;
  onOpenPlayers: () => void;
  onToggleAfk: () => void;
  onSaveImage: () => void;
  onOpenSettings: () => void;
  onProposeRestart: () => void;
  onLeave: () => void;
}

/**
 * The room's secondary actions, on a phone.
 *
 * The header used to line all of these up as icon buttons — eight targets in a
 * 44px strip on a 390px screen, with a red **Leave** one thumb-width from
 * **Settings**. Here they are rows with labels, ordered routine-first, and
 * leaving is separated and styled as the destructive thing it is (it still
 * routes through the existing confirmation dialog).
 */
export function RoomMenuSheet({
  isPlaying,
  isAfk,
  canProposeRestart,
  restartBusy,
  restartCooldownSeconds,
  onDismiss,
  onCopyLink,
  onOpenPlayers,
  onToggleAfk,
  onSaveImage,
  onOpenSettings,
  onProposeRestart,
  onLeave,
}: RoomMenuSheetProps) {
  const run = (action: () => void) => () => {
    onDismiss();
    action();
  };

  return (
    <BottomSheet title="Room" onDismiss={onDismiss} testId="room-menu-sheet">
      <ul className="sheet-menu">
        {isPlaying && (
          <li>
            <button type="button" className="sheet-menu-item" onClick={run(onOpenPlayers)}>
              <UsersIcon size={19} />
              <span>Players and scores</span>
            </button>
          </li>
        )}
        <li>
          <button type="button" className="sheet-menu-item" onClick={run(onCopyLink)}>
            <LinkIcon size={19} />
            <span>Copy the invite link</span>
          </button>
        </li>
        <li>
          <button
            type="button"
            className={`sheet-menu-item${isAfk ? " is-active" : ""}`}
            aria-pressed={isAfk}
            onClick={run(onToggleAfk)}
          >
            <MoonIcon size={19} />
            <span>{isAfk ? "I’m back" : "Go away for a bit"}</span>
          </button>
        </li>
        {isPlaying && (
          <li>
            <button type="button" className="sheet-menu-item" onClick={run(onSaveImage)}>
              <DownloadIcon size={19} />
              <span>Save this drawing</span>
            </button>
          </li>
        )}
        {isPlaying && canProposeRestart && (
          <li>
            <button
              type="button"
              className="sheet-menu-item"
              disabled={restartBusy || restartCooldownSeconds > 0}
              onClick={run(onProposeRestart)}
            >
              <RoundsIcon size={19} />
              <span>
                Start the game over
                {restartCooldownSeconds > 0 && (
                  <small> · in {restartCooldownSeconds}s</small>
                )}
              </span>
            </button>
          </li>
        )}
        <li>
          <button type="button" className="sheet-menu-item" onClick={run(onOpenSettings)}>
            <GearIcon size={19} />
            <span>Settings</span>
          </button>
        </li>
        <li className="sheet-menu-sep">
          <button type="button" className="sheet-menu-item is-danger" onClick={run(onLeave)}>
            <LeaveIcon size={19} />
            <span>Leave the room</span>
          </button>
        </li>
      </ul>
    </BottomSheet>
  );
}
