// The single manifest of every redesign screen: page markup, frame size,
// canvas position, display title, and grouping. Both the canvas build and
// the explorer build read this, so they cannot drift apart.
import { MainPage, CreateRoomPage, AccountRecoveryPage, SettingsPage } from './pages-entry.mjs';
import { WaitingRoomPage, PromptChoicePage, DrawingPage, GuessingPage, TurnResultsPage, GameOverPage, HighlightsPage } from './pages-room.mjs';
import { PromptStatsPage, MyPromptListsPage, ProfilePage, AdminOpsPage, ModerationPage } from './pages-library.mjs';

export const SCREENS = [
  // Row 1 — getting in
  { name: 'Main', page: MainPage, w: 960, h: 1240, x: 0, y: 0, title: 'Lobby', group: 'Getting in' },
  { name: 'CreateRoom', page: CreateRoomPage, w: 780, h: 1100, x: 1050, y: 0, title: 'Create a room', group: 'Getting in' },
  { name: 'AccountRecovery', page: AccountRecoveryPage, w: 560, h: 500, x: 1920, y: 0, title: 'Reset password', group: 'Getting in' },
  { name: 'Settings', page: SettingsPage, w: 960, h: 1060, x: 1920, y: 600, title: 'Settings (new)', group: 'Getting in' },
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
  { name: 'AdminOps', page: AdminOpsPage, w: 1100, h: 840, x: 0, y: 5620, title: 'Server operations', group: 'Operator pages' },
  { name: 'Moderation', page: ModerationPage, w: 1100, h: 880, x: 1190, y: 5620, title: 'Moderation', group: 'Operator pages' },
];
