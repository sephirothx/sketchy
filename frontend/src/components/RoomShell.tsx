import type { ReactNode } from "react";
import { recordRender } from "../lib/renderDiagnostics";
import { useBottomDock } from "../hooks/useBottomDock";
import "../styles/lazy/toolbar.css";

export type RoomShellMode = "waiting" | "playing" | "game-end";

interface RoomShellProps {
  mode: RoomShellMode;
  players: ReactNode;
  main: ReactNode;
  chat: ReactNode;
  /** The stage is paused (#823): nothing in it takes input, and `overlay` says why. */
  inert?: boolean;
  overlay?: ReactNode;
}

export function RoomShell({ mode, players, main, chat, inert = false, overlay = null }: RoomShellProps) {
  recordRender("roomShell");
  const dockRef = useBottomDock();
  return (
    <div
      className={`room-shell room-shell-${mode}${mode === "playing" ? " game-layout" : ""}`}
      data-room-view={mode}
    >
      <aside className="sidebar-left room-shell-players" data-testid="room-players-region" inert={inert}>
        <div className="sidebar-box room-shell-panel">{players}</div>
      </aside>

      <div className="room-shell-main" inert={inert}>
        <div key={mode} className="room-shell-main-transition">
          {main}
        </div>
      </div>

      <aside className="sidebar-right room-shell-chat" data-testid="room-chat-region" inert={inert}>
        <div className="sidebar-box room-shell-panel">{chat}</div>
      </aside>

      {/* Where the phone's drawing dock lands. The toolbar renders itself in
          here (see Toolbar), so the palette sits at the bottom of the screen
          under the thumb rather than in a strip between canvas and chat.
          Empty and inert on desktop, where the toolbar stays in the column. */}
      <div className="room-shell-dock" id="room-shell-dock" inert={inert} ref={dockRef} />

      {/* Outside the inert regions, so its own buttons still work. */}
      {overlay}
    </div>
  );
}
