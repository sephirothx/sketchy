// The shared in-room shell: header, players sidebar, chat panel, canvas art.
// One story, six-plus artboards — rosters and scores must agree everywhere.
import { T, P, icon, avatar, pname, btn, chip, sectionLabel } from './ui.mjs';

export const ROOM = { name: 'Coffee break doodles', code: 'BQ7F2K' };

// The lighthouse drawing, unchanged from the shipped mockups' story.
export const lighthouseSVG = `<svg viewBox="0 0 800 600" style="display: block; width: 100%; height: 100%" xmlns="http://www.w3.org/2000/svg">
  <path d="M40 470 C 150 452, 250 462, 330 470 L 330 600 L 40 600 Z" fill="#7ac9e8" opacity="0.35"/>
  <path d="M470 468 C 570 458, 690 470, 770 462 L 770 600 L 470 600 Z" fill="#7ac9e8" opacity="0.35"/>
  <path d="M300 480 C 340 455, 380 448, 420 450 C 470 452, 510 462, 540 480 Z" fill="#c69c6d"/>
  <path d="M356 470 L 372 250 L 452 250 L 468 470 Z" fill="#ffffff" stroke="#000000" stroke-width="6" stroke-linejoin="round"/>
  <path d="M362 400 L 462 400 L 466 448 L 358 448 Z" fill="#ed1c24"/>
  <path d="M368 300 L 456 300 L 459 342 L 365 342 Z" fill="#ed1c24"/>
  <rect x="360" y="228" width="104" height="22" rx="4" fill="#4c4c4c" stroke="#000000" stroke-width="5"/>
  <rect x="378" y="180" width="68" height="50" fill="#fff200" stroke="#000000" stroke-width="6"/>
  <path d="M374 180 L 450 180 L 412 142 Z" fill="#22b14c" stroke="#000000" stroke-width="6" stroke-linejoin="round"/>
  <path d="M412 130 L 412 116" stroke="#000000" stroke-width="6" stroke-linecap="round"/>
  <path d="M446 196 L 610 150" stroke="#fff200" stroke-width="10" stroke-linecap="round" opacity="0.75"/>
  <path d="M446 212 L 620 214" stroke="#fff200" stroke-width="10" stroke-linecap="round" opacity="0.55"/>
  <path d="M378 202 L 214 158" stroke="#fff200" stroke-width="10" stroke-linecap="round" opacity="0.75"/>
  <path d="M40 500 C 90 490, 140 508, 190 498 C 240 488, 280 504, 320 496" fill="none" stroke="#2e5090" stroke-width="5" stroke-linecap="round"/>
  <path d="M480 508 C 530 498, 580 516, 630 506 C 680 496, 720 512, 764 504" fill="none" stroke="#2e5090" stroke-width="5" stroke-linecap="round"/>
  <path d="M60 552 C 120 542, 190 560, 250 550" fill="none" stroke="#2e5090" stroke-width="5" stroke-linecap="round"/>
  <path d="M540 556 C 600 546, 670 564, 740 554" fill="none" stroke="#2e5090" stroke-width="5" stroke-linecap="round"/>
  <path d="M120 96 C 140 76, 180 78, 192 96 C 220 92, 236 112, 220 126 L 128 126 C 108 122, 106 104, 120 96 Z" fill="#c1c1c1" opacity="0.6"/>
  <path d="M600 74 C 620 54, 660 56, 672 74 C 700 70, 716 90, 700 104 L 608 104 C 588 100, 586 82, 600 74 Z" fill="#c1c1c1" opacity="0.6"/>
</svg>`;

// Tracked-uppercase panel heading shared by the sidebars.
const panelHeading = (text, size = 15) =>
  `<h2 style="font-family: ${T.body}; font-weight: 800; font-size: ${size}px; letter-spacing: 0.2em; text-transform: uppercase; color: ${T.ink}">${text}</h2>`;

// Room header, one lean row: room identity left, live game status center,
// self controls right — the destructive Leave separated at the far edge.
export const roomHeader = ({ inGame = false, status = '' } = {}) => `
<header style="display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 16px; margin-bottom: 14px; min-height: 44px">
  <div style="display: flex; align-items: center; gap: 10px; min-width: 0">
    <span style="font-weight: 800; font-size: 16px; color: ${T.ink}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${ROOM.name}</span>
    <button type="button" title="Copy invite link" style="display: inline-flex; align-items: center; gap: 7px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 999px; padding: 6px 12px; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; color: ${T.muted}; letter-spacing: 0.08em">
      ${ROOM.code}<span style="display: inline-flex; color: ${T.faint}">${icon.copy(13)}</span>
    </button>
  </div>
  ${status ? `<div style="display: flex; align-items: center; gap: 10px; flex: none">${status}</div>` : '<span></span>'}
  <div style="display: flex; align-items: center; gap: 7px; flex: none; justify-self: end">
    ${inGame ? btn.iconOnly(icon.rounds(16), 'Vote to restart', 38) : ''}
    <button type="button" aria-pressed="false" style="display: inline-flex; align-items: center; gap: 6px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 999px; padding: 7px 13px; font-family: ${T.body}; font-size: 13px; font-weight: 800; color: ${T.muted}; min-height: 38px">${icon.moon(14)}AFK</button>
    ${inGame ? btn.iconOnly(icon.download(16), 'Save drawing as PNG', 38) : ''}
    ${btn.iconOnly(icon.gear(16), 'Settings', 38)}
    <span style="width: 1.5px; height: 22px; background: ${T.line}; margin: 0 3px"></span>
    ${btn.dangerGhost('Leave', { iconL: icon.leave(14), style: 'min-height: 38px; padding: 7px 10px; font-size: 13px' })}
  </div>
</header>`;

// The game status shown in the header's center slot.
export const headerStatus = ({ round = 'Round 2 of 3', turn = 'Turn 1 of 4', timer = '' }) =>
  `${chip(round, 'primary')}<span style="color: ${T.faint}; font-size: 12.5px; font-weight: 800">${turn}</span>${timer}`;

// Players sidebar.
export const playersPanel = ({ heading = 'Players', count = '5/8', spectators = 2, rows, footer = '', ready = null }) => `
<aside style="display: flex; flex-direction: column; gap: 12px">
  <div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px 12px; box-shadow: ${T.shadow}">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; padding: 0 4px">
      <div style="display: flex; align-items: baseline; gap: 8px">
        ${panelHeading(heading)}
        <span style="color: ${T.faint}; font-size: 13px; font-weight: 800; font-variant-numeric: tabular-nums">${count}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px">
        ${ready ? chip(ready, 'success') : ''}
        <span title="${spectators} spectating" style="display: inline-flex; align-items: center; gap: 4px; color: ${T.faint}; font-size: 12.5px; font-weight: 800">${icon.eye(14)}${spectators}</span>
      </div>
    </div>
    <ul style="list-style: none; margin: 0; padding: 0; display: grid; gap: 5px">
      ${rows.join('\n')}
    </ul>
    ${footer}
  </div>
</aside>`;

// One player row: name on top, live status underneath, score on the right.
// `guessed` is the guess time ("1:03") when the player has answered this turn.
export const playerRow = (p, { score = null, drawing = false, afk = false, guessed = null, host = false, you = false, rank = null, medal = null } = {}) => {
  const status = drawing
    ? `<span style="display: inline-flex; align-items: center; gap: 5px; color: ${T.primary}; font-size: 12.5px; font-weight: 800">${icon.pencil(12)}Drawing</span>`
    : guessed
      ? `<span style="display: inline-flex; align-items: center; gap: 5px; color: ${T.successInk}; font-size: 12.5px; font-weight: 800">${icon.check(12)}Got it · <span style="font-variant-numeric: tabular-nums">${guessed}</span></span>`
      : afk
        ? `<span style="display: inline-flex; align-items: center; gap: 5px; color: ${T.warning}; font-size: 12.5px; font-weight: 800">${icon.moon(12)}AFK</span>`
        : '';
  const medals = { 1: '#E3A008', 2: '#9AA1AC', 3: '#B0703C' };
  const lead = medal
    ? `<span aria-label="Rank ${medal}" style="display: inline-flex; align-items: center; justify-content: center; width: 20px; color: ${medals[medal]}; flex: none">${icon.medal(16)}</span>`
    : rank
      ? `<span style="display: inline-flex; justify-content: center; width: 20px; color: ${T.faint}; font-size: 12.5px; font-weight: 800; font-variant-numeric: tabular-nums; flex: none">${rank}</span>`
      : '';
  const surface = guessed
    ? `background: ${T.successSoft}; border: 1.5px solid transparent`
    : drawing
      ? `background: ${T.primarySoft}; border: 1.5px solid ${T.primaryEdgeSoft}`
      : 'border: 1.5px solid transparent';
  return `<li style="display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 12px; ${surface}${afk ? '; opacity: 0.6' : ''}">
    ${lead}
    ${avatar(p, 38)}
    <span style="display: flex; flex-direction: column; gap: 2px; min-width: 0">
      <span style="display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; white-space: nowrap; font-size: 15px">
        ${pname(p)}
        ${you ? `<span style="color: ${T.faint}; font-size: 12px; font-weight: 700">you</span>` : ''}
        ${host ? `<span title="Host" style="display: inline-flex; color: ${T.muted}; flex: none">${icon.crown(14)}</span>` : ''}
      </span>
      ${status}
    </span>
    ${score === null ? '' : `<span style="margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 800; font-size: 19px; color: ${T.ink}; flex: none">${score}</span>`}
  </li>`;
};

const sysLine = (text) =>
  `<div style="display: flex; align-items: baseline; gap: 7px; color: ${T.faint}; font-size: 13px"><span style="flex: none; width: 4px; height: 4px; border-radius: 50%; background: ${T.lineStrong}; align-self: center"></span><span style="overflow-wrap: anywhere">${text}</span></div>`;

// A correct-guess event: soft green card with a left accent, time, and points.
const guessedLine = (p, pts, time) =>
  `<div style="display: flex; align-items: center; gap: 8px; background: ${T.successSoft}; border-left: 3px solid ${T.success}; border-radius: 8px; padding: 8px 11px; margin: 2px 0; font-size: 13.5px">
    <span style="display: inline-flex; color: ${T.success}; flex: none">${icon.check(13)}</span>
    <span style="min-width: 0; overflow: hidden; white-space: nowrap">${pname(p)} <strong style="color: ${T.successInk}; font-weight: 800">got it</strong>${time ? ` <span style="color: ${T.faint}; font-weight: 700">· ${time}</span>` : ''}</span>
    ${pts ? `<strong style="margin-left: auto; color: ${T.successInk}; font-weight: 800; font-variant-numeric: tabular-nums; flex: none">+${pts}</strong>` : ''}
  </div>`;

const chatMsg = (p, text) =>
  `<div style="font-size: 14px; overflow-wrap: anywhere">${pname(p, '; font-size: 13.5px')}<span style="color: ${T.muted}"> ${text}</span></div>`;

// Post-guess chat is restricted to the drawer, spectators and players who
// already guessed (R-SPEC-04); the dashed rule marks it for those who see it.
const restrictedMsg = (p, text) =>
  `<div title="Visible only to the drawer, spectators, and players who already guessed" style="border-left: 3px dashed ${T.lineStrong}; padding-left: 9px; margin: 1px 0">${chatMsg(p, text)}</div>`;

// An attention notice above the guess box (near miss, hint prompts).
const notice = (text) =>
  `<div style="display: flex; align-items: flex-start; gap: 9px; background: ${T.warningSoft}; border: 1px solid ${T.warningEdge}; border-radius: 10px; padding: 10px 12px; color: ${T.warning}; font-size: 13px; font-weight: 800; line-height: 1.45">
    <span style="display: inline-flex; margin-top: 1px; flex: none">${icon.alertCircle(15)}</span>
    <span>${text}</span>
  </div>`;

export const chat = {
  sysLine, guessedLine, chatMsg, restrictedMsg, notice,
  panel: ({ heading = 'Chat', lines, inputHTML }) => `
<aside style="display: flex; flex-direction: column; gap: 12px">
  <div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px; box-shadow: ${T.shadow}; display: flex; flex-direction: column; height: 560px">
    <div style="margin-bottom: 12px; flex: none">
      ${panelHeading(heading, 14)}
    </div>
    <div style="flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px">
      ${lines.join('\n')}
    </div>
    ${inputHTML}
  </div>
</aside>`,
  // `hints` renders the shipped GUI's live per-word letter counts above the
  // field: grey while a word is being typed, green when its length matches
  // the masked prompt's word, red when it can no longer match.
  input: ({ placeholder = 'Type a message…', value = '', hints = null, accent = false, above = '' } = {}) => {
    const hintColor = { typing: T.faint, correct: T.success, wrong: T.danger };
    const hintRow = hints
      ? `<div aria-label="Letters typed per word" style="display: flex; align-items: center; gap: 8px; min-height: 15px; padding: 0 6px">${hints.map((h) => `<sup style="font-size: 12.5px; font-weight: 800; font-variant-numeric: tabular-nums; color: ${hintColor[h.state]}">${h.n}</sup>`).join('')}</div>`
      : '';
    return `
<form style="display: flex; flex-direction: column; gap: 7px; margin-top: 10px; flex: none; border-top: 1.5px solid ${T.line}; padding-top: 12px">
  ${above}
  ${hintRow}
  <div style="display: flex; align-items: center; gap: 7px">
    <div style="flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 10px 12px; border: 1.5px solid ${accent ? T.primary : T.lineStrong}; border-radius: ${T.radiusSm}; background: ${T.field}">
      <input type="text" ${value ? `value="${value}" ` : ''}placeholder="${placeholder}" style="flex: 1; min-width: 0; border: none; outline: none; padding: 0; font-family: ${T.body}; font-size: 14.5px; background: transparent; color: ${T.ink}">
    </div>
    <button type="submit" aria-label="Send" style="display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; background: ${T.primary}; color: #fff; border: 0; border-radius: ${T.radiusSm}; box-shadow: 0 2px 0 ${T.primaryEdge}; flex: none">${icon.chevR(17)}</button>
  </div>
</form>`;
  },
};

// Standard three-column room grid.
export const roomGrid = (left, center, right) => `
<div style="display: grid; grid-template-columns: 252px minmax(0, 1fr) 292px; gap: 16px; align-items: start">
  ${left}
  <div style="min-width: 0">${center}</div>
  ${right}
</div>`;

export const roomPage = (inner, { width = 1240, minHeight = 980 } = {}) =>
  `<div style="width: ${width}px; min-height: ${minHeight}px; margin: 0 auto; padding: 18px 20px 28px">${inner}</div>`;

export const canvasFrame = (inner, overlay = '') => `
<div style="position: relative; width: 100%; max-width: 820px; aspect-ratio: 4 / 3; background: #fff; border: 1.5px solid ${T.lineStrong}; border-radius: 12px; overflow: hidden; box-shadow: ${T.shadow}">
  ${inner}
  ${overlay}
</div>`;
