// The single manifest of every redesign screen: page markup, frame size,
// canvas position, display title, and grouping. Both the canvas build and
// the explorer build read this, so they cannot drift apart.
import { MainPage, CreateRoomPage, AccountRecoveryPage, SettingsPage } from './pages-entry.mjs';
import { WaitingRoomPage, PromptChoicePage, DrawingPage, GuessingPage, TurnResultsPage, GameOverPage, HighlightsPage } from './pages-room.mjs';
import { PromptStatsPage, MyPromptListsPage, ProfilePage, AdminOpsPage, AdminOpsTuningPage, AdminOpsAuditPage, ModerationPage } from './pages-library.mjs';
import { BugReportMenuPage, BugReportDialogPage, BugReportsQueuePage } from './pages-support.mjs';

export const SCREENS = [
  // Row 1 — getting in
  { name: 'Main', page: MainPage, w: 960, h: 1240, x: 0, y: 0, title: 'Lobby', group: 'Getting in' },
  { name: 'CreateRoom', page: CreateRoomPage, w: 780, h: 1100, x: 1050, y: 0, title: 'Create a room', group: 'Getting in' },
  { name: 'AccountRecovery', page: AccountRecoveryPage, w: 880, h: 560, x: 1920, y: 0, title: 'Reset password', group: 'Getting in' },
  { name: 'Settings', page: SettingsPage, w: 1080, h: 900, x: 2900, y: 0, title: 'Settings (new)', group: 'Getting in', extraProps: { tab: { editor: 'enum', options: ['general', 'game', 'shortcuts'], default: 'general' } } },
  // Row 2 — in the room
  { name: 'WaitingRoom', page: WaitingRoomPage, w: 1240, h: 1000, x: 0, y: 1780, title: 'Waiting room', group: 'In the room' },
  { name: 'PromptChoice', page: PromptChoicePage, w: 1240, h: 1000, x: 1330, y: 1780, title: 'Prompt choice (new)', group: 'In the room' },
  { name: 'Drawing', page: DrawingPage, w: 1240, h: 1080, x: 2660, y: 1780, title: 'Drawing — drawer', group: 'In the room' },
  { name: 'Guessing', page: GuessingPage, w: 1240, h: 1000, x: 3990, y: 1780, title: 'Guessing — guesser', group: 'In the room' },
  // Row 3 — after the turn
  { name: 'TurnResults', page: TurnResultsPage, w: 1240, h: 1000, x: 0, y: 3000, title: 'Turn results', group: 'After the turn' },
  { name: 'GameOver', page: GameOverPage, w: 1240, h: 960, x: 1330, y: 3000, title: 'Game over', group: 'After the turn' },
  { name: 'Highlights', page: HighlightsPage, w: 1240, h: 960, x: 2660, y: 3000, title: 'Highlights', group: 'After the turn' },
  // Row 4 — library and profile
  { name: 'PromptStats', page: PromptStatsPage, w: 920, h: 980, x: 0, y: 4180, title: 'Prompt stats', group: 'Library and profile' },
  { name: 'MyPromptLists', page: MyPromptListsPage, w: 1020, h: 1080, x: 1010, y: 4180, title: 'My prompt lists', group: 'Library and profile' },
  { name: 'Profile', page: ProfilePage, w: 920, h: 1220, x: 2120, y: 4180, title: 'Profile', group: 'Library and profile' },
  // Row 5 — operator pages
  { name: 'AdminOps', page: AdminOpsPage, w: 1100, h: 940, x: 0, y: 5620, title: 'Server operations — overview', group: 'Operator pages' },
  { name: 'AdminOpsTuning', page: AdminOpsTuningPage, w: 1100, h: 1000, x: 1190, y: 5620, title: 'Server operations — tuning', group: 'Operator pages' },
  { name: 'AdminOpsAudit', page: AdminOpsAuditPage, w: 1100, h: 620, x: 2380, y: 5620, title: 'Server operations — audit ledger', group: 'Operator pages' },
  { name: 'Moderation', page: ModerationPage, w: 1160, h: 1040, x: 3570, y: 5620, title: 'Moderation', group: 'Operator pages' },
  // Row 6 — reporting a bug
  { name: 'BugReportMenu', page: BugReportMenuPage, w: 820, h: 600, x: 0, y: 7060, title: 'Report a bug — entry point', group: 'Reporting a bug' },
  { name: 'BugReportDialog', page: BugReportDialogPage, w: 760, h: 1330, x: 910, y: 7060, title: 'Report a bug — dialog', group: 'Reporting a bug' },
  { name: 'BugReports', page: BugReportsQueuePage, w: 1160, h: 1200, x: 1760, y: 7060, title: 'Bug reports (admin)', group: 'Reporting a bug' },
];
