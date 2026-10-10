import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { useMediaQuery } from "../hooks/useMediaQuery";
import { useAuthStore } from "../store/authStore";
import { useInboxStore } from "../store/inboxStore";
import { BellIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

// The panel and its styles load on the first press: the bell is on every
// page, the list is opened now and then.
const InboxPanel = lazy(() => import("./InboxPanel"));

/** The bell in the header, and the inbox behind it (#1436, R-INBOX-01).

On every page, between the language flag and the account chip, and in a
game's header too - where the count is all that moves: nothing opens over a
turn (R-INBOX-02). `compact` there, at the size of the Room menu's own
buttons: a phone's game bar gives way one thing at a time (game-room.css), and
a full-size bell took the wordmark with it on a narrow phone. The count is
what this tab last read of the server's, so
reading an entry in another tab moves it here as well. Opening the inbox reads
nothing: an entry is read when it is acted on or marked. */
export function InboxBell({ compact = false }: { compact?: boolean }) {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const owner = useInboxStore((state) => state.owner);
  const unread = useInboxStore((state) => state.unreadCount);
  const narrow = useMediaQuery("(max-width: 640px)");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // A panel, not a modal, on a wide screen: a press elsewhere or Escape
  // closes it, and focus goes back to the bell.
  useEffect(() => {
    if (!open || narrow) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Element;
      // A confirmation the panel opened sits at the document's root.
      if (target.closest?.(".modal-overlay")) return;
      if (wrapRef.current && !wrapRef.current.contains(target)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || document.querySelector(".modal-overlay")) return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, narrow]);

  if (!userId) return null;
  const count = owner === userId ? unread : 0;
  const label = count > 0 ? ui.inbox.openInboxUnread({ count }) : ui.inbox.inbox;

  return (
    <div className="inbox-bell" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`btn btn-icon${compact ? " btn-compact" : ""} inbox-bell-button`}
        aria-label={label}
        title={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        data-testid="inbox-bell"
        onClick={() => setOpen((value) => !value)}
      >
        <BellIcon size={18} />
        {count > 0 && (
          <span className="inbox-badge" aria-hidden="true" data-testid="inbox-count">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && (
        <Suspense fallback={null}>
          <InboxPanel
            asSheet={narrow}
            onClose={() => {
              setOpen(false);
              buttonRef.current?.focus();
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
