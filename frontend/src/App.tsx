import { Suspense, useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import {
  isFriendsPath,
  isOverlayPath,
  isSettingsPath,
  overlayBackgroundOf,
} from "./lib/overlayRoutes";
import "./App.css";
import { useEmailStateSync } from "./hooks/useEmailStateSync";
import { useGameSocketListeners } from "./hooks/useGameSocketListeners";
import { useRoomSessionReconnect } from "./hooks/useRoomSessionReconnect";
import { useServerNotices } from "./hooks/useServerNotices";
import { useSignedOutElsewhere } from "./hooks/useSignedOutElsewhere";
import { LobbyBrowserPage } from "./pages/LobbyBrowserPage";
import {
  AccountRecoveryPage,
  AdminOperationsPage,
  BugReportsPage,
  CommunityCataloguePage,
  CreateRoomPage,
  FriendsOverlay,
  GalleryDrawingPage,
  GalleryPage,
  GameRoomPage,
  ModerationPage,
  MyPromptListsPage,
  NotFoundPage,
  ProfilePage,
  PromptStatsPage,
  RulesPage,
  SettingsOverlay,
} from "./routeModules";
import { ConfettiCanvas } from "./components/ConfettiCanvas";
import { ToastProvider } from "./components/ToastProvider";
import { AppBanners } from "./components/AppBanners";
import { SettingsSyncNotices } from "./components/SettingsSyncNotices";
import { FriendInviteNotice } from "./components/FriendInviteNotice";
import { SuspensionNotice } from "./components/SuspensionNotice";
import { RoleChangeNotice } from "./components/RoleChangeNotice";
import { ReportsReviewedNotice } from "./components/ReportsReviewedNotice";
import { WarningNotice } from "./components/WarningNotice";
import { CrashProbe } from "./lib/crashTestSeam";
import { useAuthStore } from "./store/authStore";
import { useFriendsStore } from "./store/friendsStore";
import { friendListOwner } from "./lib/friends";
import { useSettingsStore } from "./store/settingsStore";
import { socket } from "./lib/socket";

/* The router keeps the window scroll across navigations, so submitting a form
   at the bottom of one page would open the next one part-way down. The overlay
   routes are the exception: they open *over* the page, which stays where it
   was - scrolling it to the top would move something the reader is not even
   looking at, and leave it there once the overlay closes. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (isOverlayPath(pathname)) return;
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/**
 * The page table, with the overlay routes over the top of it (R-SET-06,
 * R-FRIEND-10).
 *
 * Settings and Friends are routes so they can be linked and bookmarked, and
 * overlays so opening one never unmounts a live room. The two are reconciled
 * by rendering `<Routes>` against the location the overlay was opened *from*;
 * somebody who arrives on the URL itself gets the lobby behind it.
 */
function AppRoutes() {
  const location = useLocation();
  const onOverlay = isOverlayPath(location.pathname);
  // Always a value, never undefined: `useRoutes` wraps its result in an extra
  // location context *only* when it is handed one, so letting this flip
  // between a value and nothing would change the element tree and remount
  // every page behind the overlay - the live room included.
  const behind = onOverlay
    ? (overlayBackgroundOf(location.state) ?? "/")
    : location;

  // The pages draw nothing while their chunk arrives: navigations are
  // transitions, so a page already on screen stays there until the next one
  // is ready, and only a first visit to a page's address waits on a blank.
  // The overlays load themselves (`LazyOverlay`), so a failed fetch over a
  // live room is a retry notice, not the crash page.
  return (
    <>
      <Suspense fallback={null}>
      <Routes location={behind}>
        <Route path="/" element={<LobbyBrowserPage />} />
        <Route path="/create" element={<CreateRoomPage />} />
        <Route path="/room/:code" element={<GameRoomPage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/prompt-lists" element={<PromptStatsPage />} />
        <Route path="/prompt-lists/:slug" element={<PromptStatsPage />} />
        <Route path="/community-lists" element={<CommunityCataloguePage />} />
        <Route path="/community-lists/:listId" element={<CommunityCataloguePage />} />
        <Route path="/gallery" element={<GalleryPage />} />
        <Route path="/gallery/:turnId" element={<GalleryDrawingPage />} />
        <Route path="/my-prompt-lists" element={<MyPromptListsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/profile/:userId" element={<ProfilePage />} />
        {/* Declared so backend/app/client_routes.py has something to mirror
            and an unknown URL still answers 404. They never render: the table
            is drawing the page underneath, and the overlays below draw
            themselves. */}
        <Route path="/settings" element={null} />
        <Route path="/settings/:section" element={null} />
        <Route path="/friends" element={null} />
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
      </Suspense>
      {isSettingsPath(location.pathname) && <SettingsOverlay />}
      {isFriendsPath(location.pathname) && <FriendsOverlay />}
    </>
  );
}

function App() {
  useGameSocketListeners();
  useRoomSessionReconnect();
  // Every screen reads the catalogue through a live binding React cannot see
  // change, so the root subscribes to the locale: switching it re-renders the
  // whole tree rather than only the settings panel it was switched in.
  useSettingsStore((state) => state.locale);
  const fetchMe = useAuthStore((state) => state.fetchMe);
  // App-wide rather than per page: the lobby lists friends, the waiting room
  // offers them an invitation, and the in-room menu needs to know who is one
  // already. Re-read on the account, since registering or signing in replaces
  // whose friends these are - and a guest simply has none.
  const refreshFriends = useFriendsStore((state) => state.refresh);
  const myAccountId = useAuthStore((state) => friendListOwner(state.user));
  useEffect(() => {
    // The account is handed over rather than looked up: the store clears its
    // baseline when the owner changes, so signing in never announces the new
    // account's waiting requests as if they had just arrived.
    void refreshFriends(myAccountId);
  }, [refreshFriends, myAccountId]);
  useEmailStateSync();
  useServerNotices();
  useSignedOutElsewhere();

  // Who this visitor is, asked once on arrival (naming yourself is what
  // creates an account; this only reads one, and a registered account's
  // settings with it). The socket connects afterwards either way: the handshake reads the session
  // cookie once, and connecting first would bind it to no account. A failed
  // lookup still connects, so play degrades rather than stopping.
  useEffect(() => {
    let cancelled = false;
    // main.tsx asked before the first paint, so this is usually answered
    // already and asking again would read the account twice. Still in the
    // air past the paint's bound, `fetchMe` hands back that same request.
    const lookup = useAuthStore.getState().hasResolved ? Promise.resolve() : fetchMe();
    void lookup.finally(() => {
      if (!cancelled) socket.connect();
    });
    return () => {
      cancelled = true;
    };
  }, [fetchMe]);

  return (
    <ToastProvider>
      {/* Nothing in a production build; the E2E suite's way to crash the app. */}
      <CrashProbe scope="app" />
      <AppBanners />
      <SettingsSyncNotices />
      <SuspensionNotice />
      <WarningNotice />
      <ReportsReviewedNotice />
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
