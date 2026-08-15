import type { ReactNode } from "react";
import { recordRender } from "../lib/renderDiagnostics";

export type RoomShellMode = "waiting" | "playing" | "game-end";

interface RoomShellProps {
  mode: RoomShellMode;
  players: ReactNode;
  main: ReactNode;
  chat: ReactNode;
}

export function RoomShell({ mode, players, main, chat }: RoomShellProps) {
  recordRender("roomShell");
  return (
    <div
      className={`room-shell room-shell-${mode}${mode === "playing" ? " game-layout" : ""}`}
      data-room-view={mode}
    >
      <aside className="sidebar-left room-shell-players" data-testid="room-players-region">
        <div className="sidebar-box room-shell-panel">{players}</div>
      </aside>

      <div className="room-shell-main">
        <div key={mode} className="room-shell-main-transition">
          {main}
        </div>
      </div>

      <aside className="sidebar-right room-shell-chat" data-testid="room-chat-region">
        <div className="sidebar-box room-shell-panel">{chat}</div>
      </aside>
    </div>
  );
}
