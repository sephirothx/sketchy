import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { GameRoomPage } from "./pages/GameRoomPage";

function App() {
  useGameSocketListeners();

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LobbyBrowserPage />} />
        <Route path="/room/:code" element={<GameRoomPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
