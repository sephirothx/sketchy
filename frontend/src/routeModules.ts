/** Every page and overlay that is fetched when it is first needed (#475).

The lobby is the one page drawn from the entry chunk: it is where nearly
every visit starts, and where somebody arriving from nowhere lands. Everything
else - the room, account and community pages, and above all the staff
consoles no player ever opens - is a chunk of its own, so a first visit
downloads the lobby and not the whole app.

The room is the exception to "when first needed": it is what the lobby is for,
so it is fetched as soon as the lobby has painted (`prefetchPlayRoutes`), and
straight away when the address already is a room (`prefetchRouteFor`) - an
invite link should not wait for the lobby it is not showing. */
import { lazy } from "react";

const load = {
  createRoom: () => import("./pages/CreateRoomPage"),
  gameRoom: () => import("./pages/GameRoomPage"),
  rules: () => import("./pages/RulesPage"),
  promptStats: () => import("./pages/PromptStatsPage"),
  communityCatalogue: () => import("./pages/CommunityCataloguePage"),
  gallery: () => import("./pages/GalleryPage"),
  galleryDrawing: () => import("./pages/GalleryDrawingPage"),
  myPromptLists: () => import("./pages/MyPromptListsPage"),
  profile: () => import("./pages/ProfilePage"),
  accountRecovery: () => import("./pages/AccountRecoveryPage"),
  adminOperations: () => import("./pages/AdminOperationsPage"),
  moderation: () => import("./pages/ModerationPage"),
  bugReports: () => import("./pages/BugReportsPage"),
  notFound: () => import("./pages/NotFoundPage"),
  settingsOverlay: () => import("./components/SettingsOverlay"),
  friendsOverlay: () => import("./components/FriendsOverlay"),
};

export const CreateRoomPage = lazy(() => load.createRoom().then((m) => ({ default: m.CreateRoomPage })));
export const GameRoomPage = lazy(() => load.gameRoom().then((m) => ({ default: m.GameRoomPage })));
export const RulesPage = lazy(() => load.rules().then((m) => ({ default: m.RulesPage })));
export const PromptStatsPage = lazy(() => load.promptStats().then((m) => ({ default: m.PromptStatsPage })));
export const CommunityCataloguePage = lazy(() =>
  load.communityCatalogue().then((m) => ({ default: m.CommunityCataloguePage })),
);
export const GalleryPage = lazy(() => load.gallery().then((m) => ({ default: m.GalleryPage })));
export const GalleryDrawingPage = lazy(() =>
  load.galleryDrawing().then((m) => ({ default: m.GalleryDrawingPage })),
);
export const MyPromptListsPage = lazy(() => load.myPromptLists().then((m) => ({ default: m.MyPromptListsPage })));
export const ProfilePage = lazy(() => load.profile().then((m) => ({ default: m.ProfilePage })));
export const AccountRecoveryPage = lazy(() =>
  load.accountRecovery().then((m) => ({ default: m.AccountRecoveryPage })),
);
export const AdminOperationsPage = lazy(() =>
  load.adminOperations().then((m) => ({ default: m.AdminOperationsPage })),
);
export const ModerationPage = lazy(() => load.moderation().then((m) => ({ default: m.ModerationPage })));
export const BugReportsPage = lazy(() => load.bugReports().then((m) => ({ default: m.BugReportsPage })));
export const NotFoundPage = lazy(() => load.notFound().then((m) => ({ default: m.NotFoundPage })));
export const SettingsOverlay = lazy(() => load.settingsOverlay().then((m) => ({ default: m.SettingsOverlay })));
export const FriendsOverlay = lazy(() => load.friendsOverlay().then((m) => ({ default: m.FriendsOverlay })));

/** Start fetching the page `pathname` will draw, before anything renders.

Called from `main.tsx` while the first paint waits on the account, so the
page's chunk arrives alongside that answer rather than after it. A failed
fetch is ignored here: the page asks again when it renders, and that is where
a failure is shown. */
export function prefetchRouteFor(pathname: string): void {
  const first = pathname.split("/")[1] ?? "";
  const loader = ({
    create: load.createRoom,
    room: load.gameRoom,
    rules: load.rules,
    "prompt-lists": load.promptStats,
    "community-lists": load.communityCatalogue,
    gallery: pathname.split("/").length > 2 ? load.galleryDrawing : load.gallery,
    "my-prompt-lists": load.myPromptLists,
    profile: load.profile,
    settings: load.settingsOverlay,
    friends: load.friendsOverlay,
    "forgot-password": load.accountRecovery,
    "reset-password": load.accountRecovery,
    "verify-email": load.accountRecovery,
    admin: pathname.startsWith("/admin/bug-reports") ? load.bugReports : load.adminOperations,
    moderation: load.moderation,
  } as Record<string, (() => Promise<unknown>) | undefined>)[first];
  void loader?.().catch(() => undefined);
}

/** Fetch what the lobby's buttons lead to once the lobby is on screen, so
    Quick play and Create do not wait on a download - and the offline
    banner's scratch pad, which cannot be fetched once it is needed. */
export function prefetchPlayRoutes(): void {
  const idle = (callback: () => void) =>
    typeof window.requestIdleCallback === "function"
      ? window.requestIdleCallback(callback, { timeout: 3000 })
      : window.setTimeout(callback, 1000);
  idle(() => {
    void load.gameRoom().catch(() => undefined);
    void load.createRoom().catch(() => undefined);
    void import("./components/ScratchPad").catch(() => undefined);
  });
}
