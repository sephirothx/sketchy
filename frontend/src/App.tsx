import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { useRoomSessionReconnect } from "./hooks/useRoomSessionReconnect";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { CreateRoomPage } from "./pages/CreateRoomPage";
import { GameRoomPage } from "./pages/GameRoomPage";
import { VersionBadge } from "./components/VersionBadge";
import { SettingsModal } from "./components/SettingsModal";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();

  return (
    <ToastProvider>
      <ConnectionStatusBanner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LobbyBrowserPage />} />
          <Route path="/create" element={<CreateRoomPage />} />
          <Route path="/room/:code" element={<GameRoomPage />} />
        </Routes>
        <SettingsModal />
        <VersionBadge />
        <ConfettiCanvas />
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
