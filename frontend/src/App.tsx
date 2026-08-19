import { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { useRoomSessionReconnect } from "./hooks/useRoomSessionReconnect";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { CreateRoomPage } from "./pages/CreateRoomPage";
import { GameRoomPage } from "./pages/GameRoomPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SettingsModal } from "./components/SettingsModal";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";
import { useAuthStore } from "./store/authStore";
import { socket } from "./lib/socket";

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();
  const fetchMe = useAuthStore((state) => state.fetchMe);

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
      <ConnectionStatusBanner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LobbyBrowserPage />} />
          <Route path="/create" element={<CreateRoomPage />} />
          <Route path="/room/:code" element={<GameRoomPage />} />
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
