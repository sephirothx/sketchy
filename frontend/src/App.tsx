import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { isSettingsPath, type SettingsLocationState } from "./hooks/useSettingsRoute";
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
import { BugReportsPage } from "./pages/BugReportsPage";
import { ModerationPage } from "./pages/ModerationPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SettingsOverlay } from "./components/SettingsOverlay";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";
import { FriendInviteNotice } from "./components/FriendInviteNotice";
import { EmailRecoveryReminder } from "./components/EmailRecoveryReminder";
import { SuspensionNotice } from "./components/SuspensionNotice";
import { RoleChangeNotice } from "./components/RoleChangeNotice";
import { WarningNotice } from "./components/WarningNotice";
import { XIcon } from "./components/icons";
import { useAuthStore } from "./store/authStore";
import { useFriendsStore } from "./store/friendsStore";
import { socket } from "./lib/socket";
import {
  parsePausedNotice,
  parseShutdownNotice,
  shutdownSecondsRemaining,
} from "./lib/shutdownNotice";
import { onServerFull } from "./lib/socket";
import type { ServerShutdownNotice } from "./types";

/* The router keeps the window scroll across navigations, so submitting a form
   at the bottom of one page would open the next one part-way down. Settings is
   the exception: it opens *over* the page, which stays where it was. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (isSettingsPath(pathname)) return;
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/**
 * The page table, with Settings over the top of it (R-SET-06).
 *
 * Settings is a route so it can be linked and bookmarked, and an overlay so
 * opening it never unmounts a live room. The two are reconciled by rendering
 * `<Routes>` against the location Settings was opened *from*; somebody who
 * arrives on the URL itself gets the lobby behind it.
 */
function AppRoutes() {
  const location = useLocation();
  const onSettings = isSettingsPath(location.pathname);
  // Always a value, never undefined: `useRoutes` wraps its result in an extra
  // location context *only* when it is handed one, so letting this flip
  // between a value and nothing would change the element tree and remount
  // every page behind the overlay - the live room included.
  const behind = onSettings
    ? ((location.state as SettingsLocationState | null)?.settingsBackground ?? "/")
    : location;

  return (
    <>
      <Routes location={behind}>
        <Route path="/" element={<LobbyBrowserPage />} />
        <Route path="/create" element={<CreateRoomPage />} />
        <Route path="/room/:code" element={<GameRoomPage />} />
        <Route path="/prompt-lists" element={<PromptStatsPage />} />
        <Route path="/prompt-lists/:slug" element={<PromptStatsPage />} />
        <Route path="/my-prompt-lists" element={<MyPromptListsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/profile/:userId" element={<ProfilePage />} />
        {/* Declared so backend/app/client_routes.py has something to mirror
            and an unknown URL still answers 404. They never render: the table
            is drawing the page underneath, and the overlay below draws
            Settings itself. */}
        <Route path="/settings" element={null} />
        <Route path="/settings/:section" element={null} />
        <Route path="/forgot-password" element={<AccountRecoveryPage mode="forgot" />} />
        <Route path="/reset-password" element={<AccountRecoveryPage mode="reset" />} />
        <Route path="/verify-email" element={<AccountRecoveryPage mode="verify" />} />
        <Route path="/admin/operations" element={<AdminOperationsPage />} />
        <Route path="/moderation" element={<ModerationPage />} />
        <Route path="/admin/bug-reports" element={<BugReportsPage />} />
        {/* Last, and the only route not mirrored in
            backend/app/client_routes.py: it is what draws the page a URL
            with nothing behind it gets, and the server answers 404 for
            exactly the URLs that land here. */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      {onSettings && <SettingsOverlay />}
    </>
  );
}

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();
  const fetchMe = useAuthStore((state) => state.fetchMe);
  // App-wide rather than per page: the lobby lists friends, the waiting room
  // offers them an invitation, and the in-room menu needs to know who is one
  // already. Re-read on the account, since registering or signing in replaces
  // whose friends these are - and a guest simply has none.
  const refreshFriends = useFriendsStore((state) => state.refresh);
  const myAccountId = useAuthStore((state) => state.user?.id ?? null);
  useEffect(() => {
    void refreshFriends();
  }, [refreshFriends, myAccountId]);
  const [shutdownNotice, setShutdownNotice] = useState<ServerShutdownNotice | null>(null);
  const [serverFull, setServerFull] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [restarted, setRestarted] = useState(false);
  // Whether a drain was on screen when the connection dropped, so the "we are
  // back" line can be shown once - after the notice itself has been cleared.
  const sawShutdownRef = useRef(false);

  useEffect(() => {
    const onServerShutdown = (payload: unknown) => {
      const notice = parseShutdownNotice(payload);
      if (!notice) return;
      setShutdownNotice(notice);
      setSecondsLeft(shutdownSecondsRemaining(notice));
      setRestarted(false);
    };
    // Both notices describe the connection that carried them, and are dropped
    // when it ends rather than when the next one opens. A server that is
    // paused or draining says so at the handshake, and socket.io delivers
    // those buffered events *before* `connect` - so clearing there would erase
    // what the new server had just said. It also fixes the other direction: a
    // pause lifted while this client was away sends no notice on reconnect,
    // so a cached `true` would otherwise claim for ever that rooms are paused.
    const onDisconnect = () => {
      setShutdownNotice((current) => {
        if (current) sawShutdownRef.current = true;
        return null;
      });
      setPaused(false);
    };
    // A player whose game vanished mid-round is owed the reason, so a drain
    // that ended in a restart is reported once the server is back - unless it
    // is back and *still* draining, which the handshake will have said just
    // above and which is not a "we are back" story.
    const onConnect = () => {
      if (!sawShutdownRef.current) return;
      sawShutdownRef.current = false;
      setShutdownNotice((current) => {
        if (!current) setRestarted(true);
        return current;
      });
    };
    // A pause is not a version skew and not a drain: the server is still
    // here, so the banner clears when it is lifted rather than on a reload.
    const onServerPaused = (payload: unknown) => {
      const notice = parsePausedNotice(payload);
      if (notice) setPaused(notice.paused);
    };
    socket.on("server_shutdown", onServerShutdown);
    socket.on("server_paused", onServerPaused);
    socket.on("disconnect", onDisconnect);
    socket.on("connect", onConnect);
    return () => {
      socket.off("server_shutdown", onServerShutdown);
      socket.off("server_paused", onServerPaused);
      socket.off("disconnect", onDisconnect);
      socket.off("connect", onConnect);
    };
  }, []);

  // Being turned away closes the socket immediately, so this is the only
  // chance to say why: without it the player sees a silent, permanent
  // disconnection and no reason for it.
  useEffect(() => onServerFull(setServerFull), []);

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
      {serverFull && (
        <div className="server-shutdown-banner" role="status" aria-live="polite">
          {serverFull}
        </div>
      )}
      {paused && !shutdownNotice && (
        <div className="server-shutdown-banner" role="status" aria-live="polite">
          New rooms are paused for maintenance. Games already running carry on
          as normal.
        </div>
      )}
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
          <button type="button" aria-label="Dismiss" onClick={() => setRestarted(false)}><XIcon size={14} /></button>
        </div>
      )}
      <ConnectionStatusBanner />
      <EmailRecoveryReminder />
      <SuspensionNotice />
      <WarningNotice />
      <RoleChangeNotice />
      <BrowserRouter>
        <ScrollToTop />
        {/* Inside the router: answering an invitation navigates. */}
        <FriendInviteNotice />
        <AppRoutes />
        <ConfettiCanvas />
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
