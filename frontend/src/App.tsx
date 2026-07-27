import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { GameRoomPage } from "./pages/GameRoomPage";
import { VersionBadge } from "./components/VersionBadge";
import { SettingsModal } from "./components/SettingsModal";
import { ConfettiCanvas } from "./components/ConfettiCanvas";

function App() {
  useGameSocketListeners();

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LobbyBrowserPage />} />
        <Route path="/room/:code" element={<GameRoomPage />} />
      </Routes>
      <SettingsModal />
      <VersionBadge />
      <ConfettiCanvas />
    </BrowserRouter>
  );
}

export default App;
