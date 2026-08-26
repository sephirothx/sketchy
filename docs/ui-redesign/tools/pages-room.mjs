// In-room artboards: one game, one story — waiting, choosing, drawing,
// guessing, turn results, game over, highlights.
import { T, P, icon, avatar, pname, btn, chip, card, sectionLabel, segmented } from './ui.mjs';
import { ROOM, roomHeader, headerStatus, roomGrid, roomPage, playersPanel, playerRow, chat, canvasFrame, lighthouseSVG } from './shell.mjs';

// ------------------------------------------------------------- Waiting room
const waitingPlayers = playersPanel({
  heading: 'Players', count: '5/8', spectators: 2, ready: '4 ready',
  rows: [
    playerRow(P.marta, { host: true, you: true }),
    playerRow(P.bruno, {}),
    playerRow(P.yuki, {}),
    playerRow(P.ines, { afk: true }),
    playerRow(P.sparrow, {}),
  ],
});

const waitingChat = chat.panel({
  heading: 'Chat while you wait',
  lines: [
    chat.sysLine('Bruno joined the room'),
    chat.chatMsg(P.marta, 'ready when you are'),
    chat.chatMsg(P.bruno, 'one sec, grabbing a coffee'),
    chat.sysLine('Yuki joined the room'),
    chat.chatMsg(P.yuki, 'hi all'),
    chat.sysLine('Sparrow-14 joined the room'),
    chat.sysLine('Ines was marked AFK by vote'),
  ],
  inputHTML: chat.input({}),
});

const settingChip = (label, value) =>
  `<span style="display: inline-flex; align-items: center; gap: 6px; background: ${T.well}; border: 1px solid ${T.line}; border-radius: 999px; padding: 6px 12px; font-size: 12.5px; font-weight: 700; color: ${T.muted}">${label}<strong style="color: ${T.ink}; font-weight: 800">${value}</strong></span>`;

export const WaitingRoomPage = roomPage(roomHeader() + roomGrid(
  waitingPlayers,
  `
  <div style="display: grid; gap: 14px">
    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 24px; box-shadow: ${T.shadow}; text-align: center">
      ${sectionLabel('Public room · waiting for players')}
      <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 28px; color: ${T.ink}; margin-top: 5px">${ROOM.name}</h1>
      <p style="color: ${T.muted}; font-size: 14px; margin-top: 6px">Send friends the code or the link — they can join mid-lobby.</p>
      <div style="display: flex; align-items: center; justify-content: center; gap: 5px; margin: 18px 0 14px" aria-label="Room code ${ROOM.code}">
        ${ROOM.code.split('').map((c) => `<span style="display: inline-flex; align-items: center; justify-content: center; width: 46px; height: 56px; border: 1.5px solid ${T.lineStrong}; border-radius: 12px; background: ${T.well}; font-family: ${T.display}; font-weight: 600; font-size: 26px; color: ${T.ink}">${c}</span>`).join('')}
      </div>
      <div style="display: flex; align-items: center; justify-content: center; gap: 10px">
        ${btn.primary('Copy invite link', { iconL: icon.link(15) })}
        ${btn.ghost('Copy code', { iconL: icon.copy(14) })}
      </div>
    </section>

    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 20px 22px; box-shadow: ${T.shadow}">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px">
        <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.ink}">Room settings</h2>
        ${btn.secondary('Edit settings', { iconL: icon.gear(15) })}
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 7px">
        ${settingChip('Players', '8 max')}
        ${settingChip('Rounds', '3')}
        ${settingChip('Drawing time', '90s')}
        ${settingChip('Scoring', 'Default')}
        ${settingChip('Hints', 'Timed')}
        ${settingChip('Prompts', 'Standard English · 432')}
        ${settingChip('Colors', 'All')}
        ${settingChip('Spectators', 'See the prompt')}
      </div>
      <p style="color: ${T.faint}; font-size: 12.5px; margin-top: 10px">Only you can edit settings while the room waits. Everyone sees changes instantly.</p>
    </section>

    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 20px 22px; box-shadow: ${T.shadow}; display: flex; align-items: center; justify-content: space-between; gap: 16px">
      <div>
        <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.ink}">Ready when you are</h2>
        <p style="color: ${T.muted}; font-size: 13.5px; margin-top: 4px">4 players are ready. Ines is AFK and will sit out until she's back.</p>
      </div>
      ${btn.warm('Start game', { big: true })}
    </section>
  </div>`,
  waitingChat,
), { minHeight: 1000 });

// ------------------------------------------------------ Prompt choice (new)
const promptOption = (word) => `
<button type="button" style="display: flex; align-items: center; justify-content: center; background: ${T.well}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radius}; padding: 20px 18px; min-width: 150px; font-family: ${T.body}; box-shadow: 0 3px 0 ${T.lineStrong}">
  <span style="font-family: ${T.display}; font-weight: 600; font-size: 20px; color: ${T.ink}">${word}</span>
</button>`;

const inGamePlayersChoosing = playersPanel({
  heading: 'Players', count: '5/8', spectators: 2,
  rows: [
    playerRow(P.bruno, { score: 820 }),
    playerRow(P.yuki, { score: 705 }),
    playerRow(P.marta, { score: 640, you: true, host: true, drawing: true }),
    playerRow(P.ines, { score: 310, afk: true }),
    playerRow(P.sparrow, { score: 180 }),
  ],
});

export const PromptChoicePage = roomPage(roomHeader({ inGame: true, status: headerStatus({ round: 'Round 2 of 3', turn: 'Turn 1 of 4', timer: icon.timerRing(11, 11 / 15, T.success, 40) }) }) + roomGrid(
  inGamePlayersChoosing,
  `
  <main style="display: flex; flex-direction: column; gap: 12px; align-items: center">
    ${canvasFrame(
      `<div style="position: absolute; inset: 0; background: repeating-linear-gradient(45deg, ${T.card} 0 14px, ${T.paper} 14px 28px)"></div>`,
      `<div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: ${T.scrim}">
        <div style="background: ${T.card}; border-radius: 16px; box-shadow: ${T.shadowRaised}; padding: 28px 32px; text-align: center; max-width: 92%">
          ${sectionLabel('Your turn')}
          <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 26px; color: ${T.ink}; margin: 6px 0 4px">Pick something to draw</h2>
          <p style="color: ${T.muted}; font-size: 13.5px; margin-bottom: 18px">Auto-picks when time runs out.</p>
          <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap">
            ${promptOption('lighthouse')}
            ${promptOption('roller coaster')}
            ${promptOption('windmill')}
          </div>
        </div>
      </div>`
    )}
  </main>`,
  chat.panel({
    heading: 'Chat',
    lines: [
      chat.sysLine('Round 2 begins'),
      chat.sysLine('Marta is choosing a prompt…'),
      chat.chatMsg(P.bruno, 'no pressure marta'),
      chat.chatMsg(P.yuki, 'draw fast, guess faster'),
    ],
    inputHTML: chat.input({}),
  }),
), { minHeight: 1000 });

// ------------------------------------------------------------------ Drawing
const toolBtn = (svg, label, key, active = false) => `
<button type="button" aria-label="${label} (${key})" title="${label} (${key})" aria-pressed="${active}" style="position: relative; width: 44px; height: 44px; border-radius: ${T.radiusSm}; display: flex; align-items: center; justify-content: center; border: 1.5px solid ${active ? T.primary : T.line}; background: ${active ? T.primarySoft : T.card}; color: ${active ? T.primaryInk : T.muted}${active ? `; box-shadow: 0 0 0 3px ${T.primarySoft}` : ''}">
  ${svg}
  <span aria-hidden="true" style="position: absolute; bottom: 2px; right: 5px; font-size: 9px; font-weight: 800; color: ${active ? T.primary : T.faint}">${key}</span>
</button>`;

const paletteColors = ['#ffffff', '#000000', '#c1c1c1', '#4c4c4c', '#ed1c24', '#7f0000', '#ff7f27', '#a0522d', '#fff200', '#c9a227', '#b5e61d', '#2d5b1e', '#22b14c', '#1c6b5a', '#7ac9e8', '#2e5090', '#3f48cc', '#1b1b6e', '#a349a4', '#5c2d91', '#ec6ea8', '#7b3f61', '#ffae85', '#a9714b', '#c69c6d', '#5b3a1e'];

const swatch = (c, active = false) =>
  `<button type="button" aria-label="${c}" style="width: 26px; height: 26px; border-radius: 6px; padding: 0; background-color: ${c}; border: 1px solid rgba(0, 0, 0, 0.15)${active ? `; box-shadow: 0 0 0 2.5px ${T.primary}; transform: scale(1.12)` : ''}"></button>`;

const toolbar = `
<div style="width: fit-content; max-width: 100%; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 16px; padding: 10px 14px; box-shadow: ${T.shadowRaised}">
  <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: center">
    <div style="display: flex; align-items: center; gap: 4px">
      ${toolBtn(icon.brush(19), 'Brush', 'P', true)}
      ${toolBtn(icon.fill(19), 'Fill', 'F')}
      ${toolBtn(icon.eraser(19), 'Eraser', 'E')}
      ${toolBtn(icon.rect(19), 'Rectangle', 'R')}
      ${toolBtn(icon.triangle(19), 'Triangle', 'T')}
      ${toolBtn(icon.circle(19), 'Ellipse', 'C')}
    </div>
    <span style="width: 1.5px; height: 32px; background: ${T.line}"></span>
    <button type="button" title="Brush size" style="height: 44px; padding: 0 13px; border-radius: ${T.radiusSm}; border: 1.5px solid ${T.line}; background: ${T.card}; display: flex; align-items: center; gap: 8px; font-family: ${T.body}">
      <span style="border-radius: 50%; display: inline-block; width: 9px; height: 9px; background: #000"></span>
      <span style="font-size: 12.5px; font-weight: 800; color: ${T.muted}; font-variant-numeric: tabular-nums">8px</span>
      <span style="display: inline-flex; color: ${T.faint}">${icon.chevD(13)}</span>
    </button>
    <span style="width: 1.5px; height: 32px; background: ${T.line}"></span>
    <div style="display: grid; grid-template-rows: repeat(2, 1fr); grid-auto-flow: column; gap: 3px">
      ${paletteColors.map((c, i) => swatch(c, i === 1)).join('')}
      <label aria-label="Custom color" style="grid-row: span 2; width: 26px; height: 55px; border-radius: 6px; background: conic-gradient(red, yellow, lime, cyan, blue, magenta, red); display: block"></label>
    </div>
    <span style="width: 1.5px; height: 32px; background: ${T.line}"></span>
    <div style="display: flex; gap: 6px">
      ${btn.secondary('Undo', { iconL: icon.undo(15), style: 'min-height: 44px; padding: 8px 13px; font-size: 13px' })}
      ${btn.dangerGhost('Clear', { iconL: icon.trash(15), style: 'min-height: 44px; padding: 8px 10px; font-size: 13px' })}
    </div>
  </div>
</div>`;

const inGamePlayersDrawing = playersPanel({
  heading: 'Players', count: '5/8', spectators: 2,
  rows: [
    playerRow(P.bruno, { score: 820, guessed: '1:03' }),
    playerRow(P.yuki, { score: 705 }),
    playerRow(P.marta, { score: 640, you: true, host: true, drawing: true }),
    playerRow(P.ines, { score: 310, afk: true }),
    playerRow(P.sparrow, { score: 180, guessed: '1:06' }),
  ],
});

export const DrawingPage = roomPage(roomHeader({ inGame: true, status: headerStatus({ round: 'Round 2 of 3', turn: 'Turn 1 of 4', timer: icon.timerRing(21, 21 / 90, T.warm, 40) }) }) + roomGrid(
  inGamePlayersDrawing,
  `
  <main style="display: flex; flex-direction: column; gap: 10px; align-items: center">
    <span style="font-family: ${T.display}; font-weight: 600; font-size: 27px; color: ${T.ink}; line-height: 1.2">lighthouse</span>
    ${canvasFrame(lighthouseSVG)}
    ${toolbar}
  </main>`,
  chat.panel({
    heading: 'Guesses',
    lines: [
      chat.sysLine('Marta is drawing: 10 letters'),
      chat.chatMsg(P.bruno, 'tower?'),
      chat.chatMsg(P.yuki, 'rocket'),
      chat.chatMsg(P.bruno, 'a candle'),
      chat.chatMsg(P.sparrow, 'chimney'),
      chat.guessedLine(P.bruno, 161, '1:03'),
      chat.guessedLine(P.sparrow, 153, '1:06'),
      chat.restrictedMsg(P.bruno, 'the light gave it away'),
      chat.chatMsg(P.yuki, 'watchtower'),
    ],
    inputHTML: `<p style="color: ${T.faint}; font-size: 12.5px; margin-top: 10px; flex: none">You're drawing — watch the guesses come in.</p>`,
  }),
), { minHeight: 1080 });

// ----------------------------------------------------------------- Guessing
// Viewed from Yuki's seat, moments after her near miss.
const tile = (ch, revealed) => revealed
  ? `<span style="display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 34px; border-radius: 7px; background: ${T.primarySoft}; border: 1.5px solid ${T.primary}; font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.primaryInk}">${ch}</span>`
  : `<span style="display: inline-flex; width: 26px; height: 34px; border-radius: 7px; background: ${T.card}; border: 1.5px solid ${T.lineStrong}"></span>`;

// One group per word, each with its letter count as a superscript numeral
// (a multi-word prompt like "bow and arrow" renders three groups: ³ ³ ⁵).
const maskedWords = (words) => words.map((word) => `
  <span style="display: inline-flex; align-items: flex-start; gap: 4px">
    <span style="display: inline-flex; gap: 4px">${word.map((c) => tile(c, c !== '')).join('')}</span>
    <span aria-label="${word.length} letters" style="font-size: 12px; font-weight: 800; color: ${T.faint}; font-variant-numeric: tabular-nums; line-height: 1; margin-top: -1px">${word.length}</span>
  </span>`).join('<span style="width: 14px"></span>');

const maskedTiles = maskedWords([['l', '', '', 'h', '', '', '', 'u', '', '']]);

const guessingPlayers = playersPanel({
  heading: 'Players', count: '5/8', spectators: 2,
  rows: [
    playerRow(P.bruno, { score: 820, guessed: '1:03' }),
    playerRow(P.yuki, { score: 705, you: true }),
    playerRow(P.marta, { score: 640, host: true, drawing: true }),
    playerRow(P.ines, { score: 310, afk: true }),
    playerRow(P.sparrow, { score: 180, guessed: '1:06' }),
  ],
});

export const GuessingPage = roomPage(roomHeader({ inGame: true, status: headerStatus({ round: 'Round 2 of 3', turn: 'Turn 1 of 4', timer: icon.timerRing(15, 15 / 90, T.warm, 40) }) }) + roomGrid(
  guessingPlayers,
  `
  <main style="display: flex; flex-direction: column; gap: 12px; align-items: center">
    <div style="display: flex; flex-direction: column; align-items: center; gap: 8px">
      <div style="display: flex; align-items: flex-start" aria-label="Masked prompt, 10 letters">
        ${maskedTiles}
      </div>
      ${chip(`${icon.bulb(12)} Next free letter in 9s`, 'warm')}
    </div>
    ${canvasFrame(lighthouseSVG)}
  </main>`,
  chat.panel({
    heading: 'Guess and chat',
    lines: [
      chat.sysLine('Marta is drawing: 10 letters'),
      chat.chatMsg(P.bruno, 'tower?'),
      chat.chatMsg(P.yuki, 'rocket'),
      chat.chatMsg(P.sparrow, 'chimney'),
      chat.guessedLine(P.bruno, 161, '1:03'),
      chat.guessedLine(P.sparrow, 153, '1:06'),
      chat.chatMsg(P.yuki, 'watchtower'),
    ],
    inputHTML: chat.input({
      placeholder: 'Type your guess…', value: 'lighthou', accent: true,
      hints: [{ n: 8, state: 'typing' }],
      above: chat.notice('“light house” is very close!'),
    }),
  }),
), { minHeight: 1000 });

// ------------------------------------------------------------- Turn results
const resultRow = (p, { rank, delta, total, movement = null, drawer = false, you = false }) => `
<li style="display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 10px${you ? `; background: ${T.primarySoft}` : ''}">
  <span style="width: 22px; color: ${T.faint}; font-weight: 800; font-size: 13px; font-variant-numeric: tabular-nums">#${rank}</span>
  ${avatar(p, 28)}
  <span style="display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; white-space: nowrap; font-size: 14.5px">
    ${pname(p)}
    ${you ? `<span style="color: ${T.faint}; font-size: 11px; font-weight: 800">you</span>` : ''}
    ${drawer ? `<span title="Drew this turn" style="display: inline-flex; align-items: center; gap: 4px; color: ${T.warmInk}; font-size: 11.5px; font-weight: 800">${icon.pencil(12)}drew</span>` : ''}
  </span>
  ${movement === 'up' ? `<span style="color: ${T.success}; font-size: 12px; font-weight: 800">▲1</span>` : movement === 'down' ? `<span style="color: ${T.danger}; font-size: 12px; font-weight: 800">▼1</span>` : ''}
  <span style="margin-left: auto; min-width: 48px; text-align: right; font-weight: 800; font-size: 13.5px; color: ${T.success}">${delta}</span>
  <span style="min-width: 44px; text-align: right; font-weight: 800; font-variant-numeric: tabular-nums; color: ${T.ink}">${total}</span>
</li>`;

const turnResultsPlayers = playersPanel({
  heading: 'Players', count: '5/8', spectators: 2,
  rows: [
    playerRow(P.bruno, { score: 981 }),
    playerRow(P.yuki, { score: 846 }),
    playerRow(P.marta, { score: 760, you: true, host: true }),
    playerRow(P.sparrow, { score: 333 }),
    playerRow(P.ines, { score: 310, afk: true }),
  ],
});

export const TurnResultsPage = roomPage(roomHeader({ inGame: true, status: headerStatus({ round: 'Round 2 of 3', turn: 'Turn 1 of 4' }) }) + roomGrid(
  turnResultsPlayers,
  `
  <main style="display: flex; flex-direction: column; gap: 12px; align-items: center">
    ${canvasFrame(lighthouseSVG,
      `<div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: ${T.scrim}">
        <div style="background: ${T.card}; border-radius: 16px; box-shadow: ${T.shadowRaised}; padding: 22px 26px; width: min(430px, 92%)">
          <p style="text-align: center; color: ${T.faint}; font-size: 12px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase">The prompt was</p>
          <p style="text-align: center; font-family: ${T.display}; font-weight: 600; font-size: 30px; color: ${T.ink}; margin: 3px 0 10px">lighthouse</p>
          <p style="display: flex; align-items: center; justify-content: center; gap: 7px; background: ${T.warmSoft}; border-radius: 10px; color: ${T.warmInk}; padding: 9px 12px; font-size: 14px; font-weight: 800; margin-bottom: 12px">${icon.pencil(14)}All 3 guessed your drawing · +120 for you</p>
          <ul style="list-style: none; margin: 0; padding: 0; display: grid; gap: 1px">
            ${resultRow(P.bruno, { rank: 1, delta: '+161', total: 981 })}
            ${resultRow(P.yuki, { rank: 2, delta: '+141', total: 846 })}
            ${resultRow(P.marta, { rank: 3, delta: '+120', total: 760, drawer: true, you: true })}
            ${resultRow(P.sparrow, { rank: 4, delta: '+153', total: 333, movement: 'up' })}
            ${resultRow(P.ines, { rank: 5, delta: '—', total: 310, movement: 'down' }).replace(`color: ${T.success}">—`, `color: ${T.faint}">—`)}
          </ul>
          <div style="margin-top: 14px">
            <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 800; color: ${T.faint}; margin-bottom: 5px"><span>Next turn: Bruno draws</span><span>3s</span></div>
            <div style="height: 6px; border-radius: 999px; background: ${T.line}; overflow: hidden"><span style="display: block; width: 40%; height: 100%; background: ${T.primary}"></span></div>
          </div>
        </div>
      </div>`
    )}
  </main>`,
  chat.panel({
    heading: 'Guess and chat',
    lines: [
      chat.chatMsg(P.yuki, 'watchtower'),
      chat.guessedLine(P.bruno, 161, '1:03'),
      chat.guessedLine(P.sparrow, 153, '1:06'),
      chat.guessedLine(P.yuki, 141, '1:12'),
      chat.sysLine('The prompt was “lighthouse”'),
    ],
    inputHTML: chat.input({}),
  }),
), { minHeight: 1000 });

// ---------------------------------------------------------------- Game over
const finalPlayers = playersPanel({
  heading: 'Final standings', count: '5/8', spectators: 2,
  rows: [
    playerRow(P.bruno, { score: 1420, medal: 1 }),
    playerRow(P.yuki, { score: 1180, medal: 2 }),
    playerRow(P.marta, { score: 980, medal: 3, you: true, host: true }),
    playerRow(P.sparrow, { score: 520, rank: 4 }),
    playerRow(P.ines, { score: 310, rank: 5, afk: true }),
  ],
});

const podiumCol = (p, place, score, h, color) => `
<div style="display: flex; flex-direction: column; align-items: center; gap: 8px; width: 108px">
  ${avatar(p, place === 1 ? 52 : 42)}
  ${pname(p, '; font-size: 14px')}
  <div style="width: 100%; height: ${h}px; border-radius: 10px 10px 0 0; background: ${color}; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; padding-top: 8px; gap: 1px">
    <span style="font-family: ${T.display}; font-weight: 600; font-size: 19px; color: #fff">${place}</span>
    <span style="font-size: 12px; font-weight: 800; color: rgba(255, 255, 255, 0.9); font-variant-numeric: tabular-nums">${score}</span>
  </div>
</div>`;

const confettiDots = `<svg width="360" height="44" viewBox="0 0 360 44" fill="none" aria-hidden="true" style="display: block; margin: 0 auto">
  <circle cx="24" cy="26" r="4" style="fill: ${T.warm}"/><rect x="70" y="10" width="8" height="8" rx="2" style="fill: ${T.primary}" transform="rotate(18 74 14)"/>
  <circle cx="126" cy="14" r="3.5" style="fill: ${T.success}"/><rect x="168" y="22" width="9" height="9" rx="2" style="fill: ${T.warm}" transform="rotate(-14 172 26)"/>
  <circle cx="228" cy="10" r="4" style="fill: ${T.primary}"/><rect x="272" y="16" width="8" height="8" rx="2" style="fill: ${T.success}" transform="rotate(24 276 20)"/>
  <circle cx="330" cy="24" r="3.5" style="fill: ${T.warm}"/>
</svg>`;

export const GameOverPage = roomPage(roomHeader() + roomGrid(
  finalPlayers,
  `
  <main style="display: flex; align-items: center; justify-content: center; min-height: 560px">
    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 18px; box-shadow: ${T.shadowRaised}; max-width: 560px; width: 100%; padding: 26px 30px; text-align: center">
      ${confettiDots}
      ${sectionLabel('Game over')}
      <h1 style="display: flex; align-items: center; justify-content: center; gap: 10px; font-family: ${T.display}; font-weight: 600; font-size: 30px; color: ${T.ink}; margin: 6px 0 2px"><span style="display: inline-flex; color: #E3A008">${icon.crown(26)}</span>Bruno takes the crown!</h1>
      <p style="color: ${T.muted}; font-size: 14px; font-weight: 700; margin-bottom: 18px">You finished <strong style="color: ${T.ink}">3rd</strong> with 980 points.</p>
      <div style="display: flex; align-items: flex-end; justify-content: center; gap: 10px; margin-bottom: 16px">
        ${podiumCol(P.yuki, 2, 1180, 74, '#9AA1AC')}
        ${podiumCol(P.bruno, 1, 1420, 104, '#E3A008')}
        ${podiumCol(P.marta, 3, 980, 56, '#B0703C')}
      </div>
      <ul style="list-style: none; margin: 0 0 18px; padding: 0; border-top: 1.5px solid ${T.line}">
        <li style="display: flex; align-items: center; gap: 10px; padding: 9px 6px; border-bottom: 1.5px solid ${T.line}; font-size: 14px">
          <span style="width: 22px; color: ${T.faint}; font-weight: 800">#4</span>${avatar(P.sparrow, 26)}${pname(P.sparrow)}
          <span style="margin-left: auto; font-weight: 800; font-variant-numeric: tabular-nums">520</span>
        </li>
        <li style="display: flex; align-items: center; gap: 10px; padding: 9px 6px; font-size: 14px; opacity: 0.65">
          <span style="width: 22px; color: ${T.faint}; font-weight: 800">#5</span>${avatar(P.ines, 26)}${pname(P.ines)}
          <span style="margin-left: auto; font-weight: 800; font-variant-numeric: tabular-nums">310</span>
        </li>
      </ul>
      <div style="display: flex; align-items: center; justify-content: center; gap: 10px; flex-wrap: wrap">
        ${btn.secondary('Highlights', { iconL: icon.trophy(15) })}
        ${btn.secondary('Drawings', { iconL: icon.brush(15) })}
        <button type="button" aria-label="Continue to the waiting room, 7 seconds left" style="display: inline-flex; align-items: center; gap: 11px; background: ${T.primary}; color: #fff; border: 0; border-radius: 999px; padding: 11px 26px 11px 13px; font-family: ${T.display}; font-weight: 600; font-size: 18px; min-height: 52px; box-shadow: 0 4px 0 ${T.primaryEdge}">
          ${icon.timerRing(7, 0.85, '#fff', 28, 'rgba(255, 255, 255, 0.35)')}
          Continue
        </button>
      </div>
      <p style="color: ${T.faint}; font-size: 12.5px; font-weight: 700; margin-top: 12px"><a href="#">Stay here</a></p>
    </section>
  </main>`,
  chat.panel({
    heading: 'Game chat',
    lines: [
      chat.sysLine('The prompt was “bow and arrow”'),
      chat.chatMsg(P.yuki, 'gg everyone'),
      chat.chatMsg(P.bruno, 'that lighthouse was unfair'),
      chat.chatMsg(P.marta, 'rematch?'),
    ],
    inputHTML: chat.input({}),
  }),
), { minHeight: 960 });

// --------------------------------------------------------------- Highlights
const highlightCard = (svg, label, who, stat, sub) => `
<div style="background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 18px; display: flex; flex-direction: column; gap: 10px">
  <span style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border-radius: 12px; background: ${T.warmSoft}; color: ${T.warmInk}">${svg}</span>
  ${sectionLabel(label)}
  <div style="display: flex; align-items: center; gap: 8px; font-size: 15.5px">${who}</div>
  <div style="display: flex; align-items: baseline; gap: 8px">
    <span style="font-family: ${T.display}; font-weight: 600; font-size: 24px; color: ${T.ink}">${stat}</span>
    <span style="font-size: 12.5px; color: ${T.faint}; font-weight: 700">${sub}</span>
  </div>
</div>`;

export const HighlightsPage = roomPage(roomHeader() + roomGrid(
  finalPlayers,
  `
  <main style="display: flex; align-items: center; justify-content: center; min-height: 560px">
    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 18px; box-shadow: ${T.shadowRaised}; max-width: 620px; width: 100%; padding: 26px 30px">
      <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 18px">
        <div>
          ${sectionLabel('Last game')}
          <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 26px; color: ${T.ink}; margin-top: 4px">Highlights</h1>
        </div>
        <button type="button" aria-label="Close highlights" style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; background: transparent; border: 0; border-radius: ${T.radiusSm}; color: ${T.muted}">${icon.x(17)}</button>
      </header>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px">
        ${highlightCard(icon.alert(19), 'Hardest prompt', `<em style="font-weight: 700; color: ${T.ink}">roller coaster</em>`, '1 of 3', 'guessed it')}
        ${highlightCard(icon.zap(19), 'Fastest guess', `${avatar(P.bruno, 26)}${pname(P.bruno)}<span style="color: ${T.faint}; font-size: 13px">on banana</span>`, '4.2s', 'from first stroke')}
        ${highlightCard(icon.brush(19), 'Best drawer', `${avatar(P.marta, 26)}${pname(P.marta)}`, '92%', 'of guessers got it')}
        ${highlightCard(icon.clock(19), 'Quickest on average', `${avatar(P.yuki, 26)}${pname(P.yuki)}`, '12.7s', 'per correct guess')}
      </div>
      <div style="display: flex; justify-content: center; margin-top: 20px">
        ${btn.secondary('Back to results', { iconL: icon.back(15) })}
      </div>
    </section>
  </main>`,
  chat.panel({
    heading: 'Game chat',
    lines: [
      chat.sysLine('The prompt was “bow and arrow”'),
      chat.chatMsg(P.yuki, 'gg everyone'),
      chat.chatMsg(P.bruno, 'that lighthouse was unfair'),
      chat.chatMsg(P.marta, 'rematch?'),
    ],
    inputHTML: chat.input({}),
  }),
), { minHeight: 960 });
