import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import "./App.css";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { useRoomSessionReconnect } from "./hooks/useRoomSessionReconnect";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import { SettingsModal } from "./components/SettingsModal";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";

const CreateRoomPage = lazy(async () => {
  const module = await import("./pages/CreateRoomPage");
  return { default: module.CreateRoomPage };
});

const GameRoomPage = lazy(async () => {
  const module = await import("./pages/GameRoomPage");
  return { default: module.GameRoomPage };
});

function RouteLoadingFallback() {
  return (
    <main className="route-loading" role="status" aria-live="polite">
      Loading page…
    </main>
  );
}

function AppRoutes() {
  const location = useLocation();

  return (
    <Suspense key={location.pathname} fallback={<RouteLoadingFallback />}>
      <Routes>
        <Route path="/" element={<LobbyBrowserPage />} />
        <Route path="/create" element={<CreateRoomPage />} />
        <Route path="/room/:code" element={<GameRoomPage />} />
      </Routes>
    </Suspense>
  );
}

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();

  return (
    <ToastProvider>
      <ConnectionStatusBanner />
      <BrowserRouter>
        <AppRoutes />
        <SettingsModal />
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
