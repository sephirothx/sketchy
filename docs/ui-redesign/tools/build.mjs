// Generates every redesign artboard plus canvas.json.
// Run from docs/ui-redesign:  node tools/build.mjs
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dcWrap } from './ui.mjs';
import { SCREENS } from './screens.mjs';

const out = join(dirname(fileURLToPath(import.meta.url)), '..');

for (const s of SCREENS) {
  writeFileSync(join(out, `${s.name}.dc.html`), dcWrap(s.page, { width: s.w, height: s.h }));
}

const canvas = {
  artboards: SCREENS.map((s) => ({ file: `${s.name}.dc.html`, x: s.x, y: s.y, w: s.w, h: s.h, title: s.title })),
  annotations: [
    { id: 'note-getting-in', x: 0, y: -170, w: 460, text: 'GETTING IN — one identity system everywhere: warm paper surface, Fredoka display type, SVG icons (no emoji), avatar chips for every player, and a light/dark theme switched per artboard with the theme tweak above each frame. Lobby gains header nav to stats/lists, a segmented code input, capacity meters and one primary action per card. Create-room is grouped into four sections with a sticky summary bar; drawing time steps through the real preset list, and scoring/hint modes explain themselves.' },
    { id: 'note-in-the-room', x: 0, y: 1610, w: 460, text: 'IN THE ROOM — same story as the shipped canvas (room BQ7F2K, round 2, Marta draws lighthouse). Waiting room leads with the invite, settings collapse to a summary. NEW: the prompt-choice moment, with difficulty pulled from prompt stats. In-turn: ring timer with urgency color, letter-tile masked prompt, per-player status lines (Got it · time / Drawing / AFK), got-it event cards and dashed post-guess chat in the feed, near-miss attached to the guess box (Guessing is Yuki’s seat), 44px tool targets, destructive actions separated.' },
    { id: 'note-after-turn', x: 0, y: 2830, w: 460, text: 'AFTER THE TURN — the 5-second results overlay is one readable card: prompt reveal, your outcome line, deltas and movement, plus a “next turn” progress bar. Game over gets a real podium, one primary action, and an escapable auto-continue. Highlights become four superlative cards.' },
    { id: 'note-library', x: 0, y: 4010, w: 460, text: 'LIBRARY AND PROFILE — prompt stats get styled filters and difficulty meters; list editing gets capacity meters, visible duplicate reporting, a locked-language hint and a separated delete. Profile leads with four hero stats and placement-badged history.' },
    { id: 'note-operators', x: 0, y: 5450, w: 460, text: 'OPERATOR PAGES — same layout logic, fixed broken native controls, evidence blocks labeled with their server-side guarantee, and the suspend action fused with its duration so the two cannot be triggered separately.' },
  ],
  launch: { view: 'canvas' },
};

writeFileSync(join(out, 'canvas.json'), JSON.stringify(canvas, null, 2) + '\n');
console.log(`wrote ${SCREENS.length} artboards + canvas.json to ${out}`);
