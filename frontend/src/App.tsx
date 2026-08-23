import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { useRoomSessionReconnect } from "./hooks/useRoomSessionReconnect";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { CreateRoomPage } from "./pages/CreateRoomPage";
import { GameRoomPage } from "./pages/GameRoomPage";
import { PromptStatsPage } from "./pages/PromptStatsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { MyPromptListsPage } from "./pages/MyPromptListsPage";
import { SettingsModal } from "./components/SettingsModal";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";
import { useAuthStore } from "./store/authStore";
import { socket } from "./lib/socket";
import { parseShutdownNotice } from "./lib/shutdownNotice";
import type { ServerShutdownNotice } from "./types";

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();
  const fetchMe = useAuthStore((state) => state.fetchMe);
  const [shutdownNotice, setShutdownNotice] = useState<ServerShutdownNotice | null>(null);

  useEffect(() => {
    const onServerShutdown = (payload: unknown) => {
      const notice = parseShutdownNotice(payload);
      if (notice) setShutdownNotice(notice);
    };
    socket.on("server_shutdown", onServerShutdown);
    return () => { socket.off("server_shutdown", onServerShutdown); };
  }, []);

  // The only call that provisions a guest, so it runs once on arrival and
  // gives every visitor a durable identity before they create or join a room.
  // The socket connects afterwards either way: the handshake reads the session
  // cookie once, and connecting first would bind it to no account. A failed
  // lookup still connects, so play degrades rather than stopping.
  useEffect(() => {
    let cancelled = false;
    void fetchMe().finally(() => {
      if (!cancelled) socket.connect();
    });
    return () => {
      cancelled = true;
    };
  }, [fetchMe]);

  return (
    <ToastProvider>
      {shutdownNotice && (
        <div className="server-shutdown-banner" role="status" aria-live="polite">
          Server update in progress. No new rooms or games can start; a current game has up to {shutdownNotice.drainSeconds} seconds to finish.
        </div>
      )}
      <ConnectionStatusBanner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LobbyBrowserPage />} />
          <Route path="/create" element={<CreateRoomPage />} />
          <Route path="/room/:code" element={<GameRoomPage />} />
          <Route path="/prompt-lists" element={<PromptStatsPage />} />
          <Route path="/prompt-lists/:slug" element={<PromptStatsPage />} />
          <Route path="/my-prompt-lists" element={<MyPromptListsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/profile/:userId" element={<ProfilePage />} />
        </Routes>
        <SettingsModal />
        <ConfettiCanvas />
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
