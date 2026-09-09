import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";

/** What a row in the lobby's online list offers about the person on it.

The room's seat menu is the model, down to its keyboard behaviour: one trigger,
arrow keys through the items, Escape closes and returns focus to where it came
from. Two lists of people should not be operated in two different ways.

Reporting is last and separated, because it is the item nobody is reaching for
and the one that would be worst to hit by accident. */
export function LobbyPlayerMenu({
  userId,
  displayName,
  isOpen,
  onOpenChange,
  onAddFriend,
  onReport,
  children,
}: {
  userId: string;
  displayName: string;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null when there is nothing to offer — an existing friend, a guest on
      either side, or your own row (R-FRIEND-03, R-FRIEND-11). */
  onAddFriend: (() => void) | null;
  /** Null for a viewer with no identity of their own to report from
      (R-MOD-06), or for a guest, who has no account to report. */
  onReport: (() => void) | null;
  /** The row's own content, which is what opens the menu. */
  children: React.ReactNode;
}) {
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEscapeLayer(isOpen, () => {
    onOpenChange(false);
    triggerRef.current?.focus();
  });
  useFocusTrap(menuRef, { active: isOpen });

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        onOpenChange(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onOpenChange]);

  function close() {
    onOpenChange(false);
    triggerRef.current?.focus();
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(currentIndex + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length]?.focus();
    }
  }

  return (
    <div className="online-player-menu-root" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="online-player-trigger"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={menuId}
        aria-label={`What to do about ${displayName}`}
        onClick={() => onOpenChange(!isOpen)}
      >
        {children}
      </button>

      {isOpen && (
        <div
          id={menuId}
          ref={menuRef}
          className="online-player-menu"
          role="menu"
          aria-label={`What to do about ${displayName}`}
          onKeyDown={handleMenuKeyDown}
          data-testid="online-player-menu"
        >
          {/* A real link, not a button that navigates: presence carries the
              account id for exactly this reason (R-ROOM-07, R-FRIEND-11), and
              a profile is somewhere people open in another tab. */}
          <Link
            to={`/profile/${userId}`}
            role="menuitem"
            className="online-player-menu-item"
            onClick={() => onOpenChange(false)}
          >
            Open player profile
          </Link>
          {onAddFriend && (
            <button
              type="button"
              role="menuitem"
              className="online-player-menu-item"
              onClick={() => {
                close();
                onAddFriend();
              }}
            >
              Add as friend
            </button>
          )}
          {onReport && (
            <button
              type="button"
              role="menuitem"
              className="online-player-menu-item is-report"
              onClick={() => {
                close();
                onReport();
              }}
            >
              Report
            </button>
          )}
        </div>
      )}
    </div>
  );
}
