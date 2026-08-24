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
import { AccountRecoveryPage } from "./pages/AccountRecoveryPage";
import { AdminOperationsPage } from "./pages/AdminOperationsPage";
import { ModerationPage } from "./pages/ModerationPage";
import { SettingsModal } from "./components/SettingsModal";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";
import { EmailRecoveryReminder } from "./components/EmailRecoveryReminder";
import { useAuthStore } from "./store/authStore";
import { socket } from "./lib/socket";
import { parseShutdownNotice, shutdownSecondsRemaining } from "./lib/shutdownNotice";
import type { ServerShutdownNotice } from "./types";

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();
  const fetchMe = useAuthStore((state) => state.fetchMe);
  const [shutdownNotice, setShutdownNotice] = useState<ServerShutdownNotice | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [restarted, setRestarted] = useState(false);

  useEffect(() => {
    const onServerShutdown = (payload: unknown) => {
      const notice = parseShutdownNotice(payload);
      if (!notice) return;
      setShutdownNotice(notice);
      setSecondsLeft(shutdownSecondsRemaining(notice));
      setRestarted(false);
    };
    // Connecting while a shutdown notice is up can only be a reconnection, and
    // the process that sent it is gone: the drain it described is over however
    // it ended. The notice is replaced rather than dropped, because a player
    // whose game vanished mid-round is owed the reason.
    const onConnect = () => {
      setShutdownNotice((current) => {
        if (current) setRestarted(true);
        return null;
      });
    };
    socket.on("server_shutdown", onServerShutdown);
    socket.on("connect", onConnect);
    return () => {
      socket.off("server_shutdown", onServerShutdown);
      socket.off("connect", onConnect);
    };
  }, []);

  useEffect(() => {
    if (!shutdownNotice) return;
    const tick = () => setSecondsLeft(shutdownSecondsRemaining(shutdownNotice));
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [shutdownNotice]);

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
          Server update in progress. No new rooms or games can start;{" "}
          {secondsLeft > 0
            ? `a current game has ${secondsLeft} second${secondsLeft === 1 ? "" : "s"} to finish.`
            : "any game still running is ending now."}
        </div>
      )}
      {restarted && (
        <div className="server-shutdown-banner is-restarted" role="status" aria-live="polite">
          <span>The server was updated and is back. Any game in progress ended.</span>
          <button type="button" aria-label="Dismiss" onClick={() => setRestarted(false)}>×</button>
        </div>
      )}
      <ConnectionStatusBanner />
      <EmailRecoveryReminder />
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
          <Route path="/forgot-password" element={<AccountRecoveryPage mode="forgot" />} />
          <Route path="/reset-password" element={<AccountRecoveryPage mode="reset" />} />
          <Route path="/verify-email" element={<AccountRecoveryPage mode="verify" />} />
          <Route path="/admin/operations" element={<AdminOperationsPage />} />
          <Route path="/moderation" element={<ModerationPage />} />
        </Routes>
        <SettingsModal />
        <ConfettiCanvas />
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
