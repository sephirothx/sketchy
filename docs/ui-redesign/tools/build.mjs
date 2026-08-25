// Generates every redesign artboard plus canvas.json.
// Run from docs/ui-redesign:  node tools/build.mjs
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dcWrap } from './ui.mjs';
import { MainPage, CreateRoomPage, AccountRecoveryPage } from './pages-entry.mjs';
import { WaitingRoomPage, PromptChoicePage, DrawingPage, GuessingPage, TurnResultsPage, GameOverPage, HighlightsPage } from './pages-room.mjs';
import { PromptStatsPage, MyPromptListsPage, ProfilePage, AdminOpsPage, ModerationPage } from './pages-library.mjs';

const out = join(dirname(fileURLToPath(import.meta.url)), '..');

const boards = [
  // Row 1 — getting in
  ['Main', MainPage, 960, 1240, 0, 0],
  ['CreateRoom', CreateRoomPage, 780, 1720, 1050, 0],
  ['AccountRecovery', AccountRecoveryPage, 560, 500, 1920, 0],
  // Row 2 — in the room
  ['WaitingRoom', WaitingRoomPage, 1240, 1000, 0, 1780],
  ['PromptChoice', PromptChoicePage, 1240, 1000, 1330, 1780],
  ['Drawing', DrawingPage, 1240, 1080, 2660, 1780],
  ['Guessing', GuessingPage, 1240, 1000, 3990, 1780],
  // Row 3 — after the turn
  ['TurnResults', TurnResultsPage, 1240, 1000, 0, 3000],
  ['GameOver', GameOverPage, 1240, 960, 1330, 3000],
  ['Highlights', HighlightsPage, 1240, 960, 2660, 3000],
  // Row 4 — library and profile
  ['PromptStats', PromptStatsPage, 920, 980, 0, 4180],
  ['MyPromptLists', MyPromptListsPage, 1020, 1080, 1010, 4180],
  ['Profile', ProfilePage, 920, 1220, 2120, 4180],
  // Row 5 — operator pages
  ['AdminOps', AdminOpsPage, 1100, 840, 0, 5620],
  ['Moderation', ModerationPage, 1100, 880, 1190, 5620],
];

const titles = {
  Main: 'Lobby', CreateRoom: 'Create a room', AccountRecovery: 'Reset password',
  WaitingRoom: 'Waiting room', PromptChoice: 'Prompt choice (new)', Drawing: 'Drawing — drawer',
  Guessing: 'Guessing — guesser', TurnResults: 'Turn results', GameOver: 'Game over',
  Highlights: 'Highlights', PromptStats: 'Prompt stats', MyPromptLists: 'My prompt lists',
  Profile: 'Profile', AdminOps: 'Server operations', Moderation: 'Moderation',
};

for (const [name, body, w, h] of boards) {
  writeFileSync(join(out, `${name}.dc.html`), dcWrap(body, { width: w, height: h }));
}

const canvas = {
  artboards: boards.map(([name, , w, h, x, y]) => ({ file: `${name}.dc.html`, x, y, w, h, title: titles[name] })),
  annotations: [
    { id: 'note-getting-in', x: 0, y: -170, w: 460, text: 'GETTING IN — one identity system everywhere: warm paper surface, Fredoka display type, SVG icons (no emoji), avatar chips for every player. Lobby gains header nav to stats/lists, a segmented code input, capacity meters and one primary action per card. Create-room is grouped into four sections with a sticky summary bar; drawing time is the real preset list, and scoring/hint modes explain themselves.' },
    { id: 'note-in-the-room', x: 0, y: 1610, w: 460, text: 'IN THE ROOM — same story as the shipped canvas (room BQ7F2K, round 2, Marta draws lighthouse). Waiting room leads with the invite, settings collapse to a summary. NEW: the prompt-choice moment, with difficulty pulled from prompt stats. In-turn: ring timer with urgency color, letter-tile masked prompt, guessed-state badges on players, near-miss attached to the guess box (Guessing is Bruno’s seat), 44px tool targets, destructive actions separated.' },
    { id: 'note-after-turn', x: 0, y: 2830, w: 460, text: 'AFTER THE TURN — the 5-second results overlay is one readable card: prompt reveal, your outcome line, deltas and movement, plus a “next turn” progress bar. Game over gets a real podium, one primary action, and an escapable auto-continue. Highlights become four superlative cards.' },
    { id: 'note-library', x: 0, y: 4010, w: 460, text: 'LIBRARY AND PROFILE — prompt stats get styled filters and difficulty meters; list editing gets capacity meters, visible duplicate reporting, a locked-language hint and a separated delete. Profile leads with four hero stats and placement-badged history.' },
    { id: 'note-operators', x: 0, y: 5450, w: 460, text: 'OPERATOR PAGES — same layout logic, fixed broken native controls, evidence blocks labeled with their server-side guarantee, and the suspend action fused with its duration so the two cannot be triggered separately.' },
  ],
  launch: { view: 'canvas' },
};

writeFileSync(join(out, 'canvas.json'), JSON.stringify(canvas, null, 2) + '\n');
console.log(`wrote ${boards.length} artboards + canvas.json to ${out}`);
