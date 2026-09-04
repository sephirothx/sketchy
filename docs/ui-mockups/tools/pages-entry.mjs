// Entry screens: lobby, room creation, account recovery.
import { T, P, icon, flag, avatar, pname, btn, chip, card, sectionLabel, segmented, selectBox, switchCtl, input, wordmark, squiggle } from './ui.mjs';
import { NOT_FOUND_PATHS, NOT_FOUND_VIEWBOX } from './notFoundArt.mjs';
import { CRASH_PATHS, CRASH_VIEWBOX } from './crashArt.mjs';

const menuItem = (svg, label, danger = false) => `
<button type="button" style="display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: transparent; border: 0; border-radius: 9px; padding: 10px 12px; font-family: ${T.body}; font-size: 14px; font-weight: 700; color: ${danger ? T.danger : T.ink}; min-height: 40px">
  <span style="display: inline-flex; color: ${danger ? T.danger : T.faint}">${svg}</span>${label}
</button>`;

// The lobby header carries only the account button; every navigation option
// lives in its menu, drawn open here so the design documents its contents.
const appHeader = `
<header style="display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 26px">
  ${wordmark(34)}
  <div style="position: relative">
    <button type="button" aria-expanded="true" style="display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: 5px 14px 5px 5px; min-height: 44px; font-family: ${T.body}; box-shadow: ${T.shadow}">
      ${avatar(P.marta, 30)}
      <span style="font-weight: 800; font-size: 14px; color: ${T.ink}">Marta</span>
      <span style="display: inline-flex; color: ${T.faint}">${icon.chevD(14)}</span>
    </button>
    <div role="menu" style="position: absolute; right: 0; top: calc(100% + 8px); z-index: 20; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 12px; box-shadow: ${T.shadowRaised}; padding: 6px; width: 216px; display: grid; gap: 1px">
      ${menuItem(icon.user(16), 'Profile')}
      ${menuItem(icon.zap(16), 'Prompt stats')}
      ${menuItem(icon.bulb(16), 'My prompt lists')}
      ${menuItem(icon.gear(16), 'Settings')}
      <div style="border-top: 1.5px solid ${T.line}; margin: 4px 6px"></div>
      ${menuItem(icon.leave(16), 'Sign out', true)}
    </div>
  </div>
</header>`;

const backBar = (label = 'Back to lobby') => `
<div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px">
  ${btn.ghost(label, { iconL: icon.back(15), style: 'padding-left: 0' })}
  <button type="button" style="display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: 5px 14px 5px 5px; min-height: 44px; font-family: ${T.body}; box-shadow: ${T.shadow}">
    ${avatar(P.marta, 30)}
    <span style="font-weight: 800; font-size: 14px; color: ${T.ink}">Marta</span>
  </button>
</div>`;

// ---------------------------------------------------------------- Main lobby
const codeCells = ['B', 'Q', '7', 'F', '', '']
  .map((c, i) => `<span style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 48px; border: 1.5px solid ${c ? T.lineStrong : T.line}; border-radius: 10px; background: ${T.field}; font-family: ${T.display}; font-weight: 600; font-size: 20px; color: ${T.ink}${i === 4 ? `; border-color: ${T.primary}; box-shadow: 0 0 0 3px ${T.primarySoft}` : ''}">${c}</span>`)
  .join('');

const roomCard = ({ name, status, statusKind, lang, meta, fillFrac, tags, actions }) => `
<article style="display: flex; align-items: center; gap: 18px; justify-content: space-between; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}">
  <div style="min-width: 0; display: grid; gap: 8px">
    <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 9px">
      <h3 style="font-family: ${T.display}; font-weight: 600; font-size: 17px; color: ${T.ink}">${name}</h3>
      ${chip(status, statusKind)}
    </div>
    <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 5px 16px; color: ${T.muted}; font-size: 13px; font-weight: 700">
      <span title="Prompt language: ${lang.label}" style="display: inline-flex; align-items: center; gap: 7px">${flag[lang.code]}${lang.label}</span>
      <span style="display: inline-flex; align-items: center; gap: 6px">${icon.users(14)}${meta.players}
        <span aria-hidden="true" style="display: inline-block; width: 44px; height: 5px; border-radius: 999px; background: ${T.line}; overflow: hidden"><span style="display: block; width: ${Math.round(fillFrac * 100)}%; height: 100%; background: ${fillFrac >= 1 ? T.warm : T.primary}"></span></span>
      </span>
      <span style="display: inline-flex; align-items: center; gap: 6px">${icon.rounds(14)}${meta.rounds}</span>
      <span style="display: inline-flex; align-items: center; gap: 6px">${icon.clock(14)}${meta.time}</span>
      ${meta.spectators ? `<span style="display: inline-flex; align-items: center; gap: 6px">${icon.eye(14)}${meta.spectators}</span>` : ''}
    </div>
    ${tags.length ? `<div style="display: flex; flex-wrap: wrap; gap: 6px">${tags.map((t) => chip(t)).join('')}</div>` : ''}
  </div>
  <div style="display: flex; flex-direction: column; gap: 8px; flex: none; min-width: 132px">
    ${actions}
  </div>
</article>`;

export const MainPage = `
<div style="width: 960px; min-height: 1240px; margin: 0 auto; padding: 26px 24px 48px">
  ${appHeader}

  <div style="display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; margin-bottom: 18px">
    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 24px; box-shadow: ${T.shadow}; display: flex; flex-direction: column; gap: 12px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 22px; color: ${T.ink}">Start a game</h2>
      <p style="color: ${T.muted}; font-size: 14px; line-height: 1.5">Pick the basics, invite your friends, draw. Settings can change any time before the first round.</p>
      <div style="display: flex; align-items: center; gap: 12px; margin-top: auto">
        ${btn.primary('Create a room', { big: true, iconL: icon.plus(16) })}
        ${btn.ghost('Quick start with defaults')}
      </div>
    </section>

    <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 24px; box-shadow: ${T.shadow}; display: flex; flex-direction: column; gap: 12px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 22px; color: ${T.ink}">Join with a code</h2>
      <div style="display: flex; gap: 6px" aria-label="Room code">${codeCells}</div>
      <div style="display: flex; align-items: center; gap: 10px; margin-top: auto">
        ${btn.primary('Join')}
        ${btn.secondary('Spectate instead', { iconL: icon.eye(14) })}
      </div>
    </section>
  </div>

  <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 22px 24px; box-shadow: ${T.shadow}">
    <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 14px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 22px; color: ${T.ink}">Public rooms</h2>
      <span style="font-size: 13px; color: ${T.faint}; font-weight: 700">Showing 4 of 4</span>
    </div>

    <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px">
      <div style="flex: 1 1 240px; display: flex; align-items: center; gap: 9px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 10px 13px; min-height: 44px">
        <span style="display: inline-flex; color: ${T.faint}">${icon.search(15)}</span>
        <input type="search" placeholder="Search rooms by name or code" style="flex: 1; min-width: 0; border: 0; outline: none; background: transparent; font-family: ${T.body}; font-size: 14px; color: ${T.ink}">
      </div>
      ${selectBox('All languages')}
      <button type="button" aria-pressed="false" style="background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 999px; padding: 9px 15px; font-family: ${T.body}; font-size: 13px; font-weight: 800; color: ${T.muted}; min-height: 42px">Hide full</button>
      <button type="button" aria-pressed="false" style="background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 999px; padding: 9px 15px; font-family: ${T.body}; font-size: 13px; font-weight: 800; color: ${T.muted}; min-height: 42px">Hide in progress</button>
    </div>

    <div style="display: grid; gap: 12px">
      ${roomCard({
        name: 'Coffee break doodles', status: 'Waiting', statusKind: 'success', fillFrac: 5 / 8,
        lang: { code: 'en', label: 'English' },
        meta: { players: '5/8', rounds: '3 rounds', time: '90s', spectators: '2' },
        tags: ['Timed hints', 'Spectators see prompt'],
        actions: btn.primary('Join') + btn.secondary('Spectate', { iconL: icon.eye(14) }),
      })}
      ${roomCard({
        name: 'Slow and steady', status: 'Waiting', statusKind: 'success', fillFrac: 2 / 6,
        lang: { code: 'it', label: 'Italian' },
        meta: { players: '2/6', rounds: '4 rounds', time: '180s' },
        tags: ['No scoring', '42 custom prompts'],
        actions: btn.primary('Join') + btn.secondary('Spectate', { iconL: icon.eye(14) }),
      })}
      ${roomCard({
        name: 'After-work sketch club', status: 'Round 2 of 3', statusKind: 'warning', fillFrac: 5 / 10,
        lang: { code: 'de', label: 'German' },
        meta: { players: '5/10', rounds: '3 rounds', time: '120s', spectators: '1' },
        tags: ['Hidden prompt', 'Colorblind-safe'],
        actions: btn.warm('Join in progress') + btn.secondary('Spectate', { iconL: icon.eye(14) }),
      })}
      ${roomCard({
        name: 'Chaos hour', status: 'In progress', statusKind: 'warning', fillFrac: 1,
        lang: { code: 'en', label: 'English' },
        meta: { players: '8/8 · full', rounds: '5 rounds', time: '60s' },
        tags: ['Pressure', 'Wheel of Fortune', 'Brush only'],
        actions: btn.secondary('Spectate', { iconL: icon.eye(14) }),
      })}
    </div>
  </section>
</div>`;

// ------------------------------------------------------------- Create a room
// A numeric setting as a small card: icon + label up top, − value + in
// display type in the middle, the allowed range as a quiet caption.
const stepBtn = (glyph, label) =>
  `<button type="button" aria-label="${label}" style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border-radius: 50%; border: 1.5px solid ${T.lineStrong}; background: ${T.card}; color: ${T.ink}; font-family: ${T.body}; font-size: 19px; font-weight: 700; box-shadow: ${T.shadow}; flex: none">${glyph}</button>`;

const settingCard = (svg, label, value, unit, hint) => `
<div style="display: flex; flex-direction: column; align-items: center; gap: 11px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 15px 12px 12px; text-align: center">
  <span style="display: inline-flex; align-items: center; gap: 7px; color: ${T.muted}; font-size: 12px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase">${svg}${label}</span>
  <div style="display: flex; align-items: center; gap: 10px">
    ${stepBtn('−', `Decrease ${label}`)}
    <span style="min-width: 68px; text-align: center; font-family: ${T.display}; font-weight: 600; font-size: 30px; color: ${T.ink}; font-variant-numeric: tabular-nums; line-height: 1">${value}<span style="font-size: 16px; color: ${T.faint}">${unit}</span></span>
    ${stepBtn('+', `Increase ${label}`)}
  </div>
  <span style="color: ${T.faint}; font-size: 11.5px; font-weight: 700; line-height: 1.45">${hint}</span>
</div>`;

const listChip = (name, count, on) => {
  const pill = count === '' ? '' : on
    ? `<span style="background: ${T.card}; border-radius: 999px; padding: 1px 8px; font-size: 11.5px; color: ${T.primary}">${count}</span>`
    : `<span style="background: ${T.well}; border-radius: 999px; padding: 1px 8px; font-size: 11.5px; color: ${T.faint}">${count}</span>`;
  return on
    ? `<button type="button" aria-pressed="true" style="display: inline-flex; align-items: center; gap: 7px; background: ${T.primarySoft}; border: 1.5px solid ${T.primary}; border-radius: 999px; padding: 9px 15px; font-family: ${T.body}; font-size: 13.5px; font-weight: 800; color: ${T.primaryInk}; min-height: 42px">${icon.check(12)}${name}${pill}</button>`
    : `<button type="button" aria-pressed="false" style="display: inline-flex; align-items: center; gap: 7px; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 999px; padding: 9px 15px; font-family: ${T.body}; font-size: 13.5px; font-weight: 800; color: ${T.muted}; min-height: 42px">${icon.plus(12)}${name}${pill}</button>`;
};

const optionCard = (title, desc, on, extra = '') => `
<button type="button" aria-pressed="${on}" style="display: flex; flex-direction: column; gap: 4px; text-align: left; background: ${on ? T.primarySoft : T.card}; border: 1.5px solid ${on ? T.primary : T.line}; border-radius: ${T.radiusSm}; padding: 12px 14px; font-family: ${T.body}; min-height: 44px">
  <span style="display: flex; align-items: center; gap: 7px; font-size: 14px; font-weight: 800; color: ${on ? T.primaryInk : T.ink}">${on ? `<span style="display: inline-flex; color: ${T.primary}">${icon.check(13)}</span>` : ''}${title}${extra}</span>
  <span style="font-size: 12.5px; color: ${T.muted}; line-height: 1.45; font-weight: 600">${desc}</span>
</button>`;

// A form section card. `collapsed` renders it as a closed disclosure whose
// header row summarizes the current values, so the long tail of settings
// stays out of the way until the host asks for it.
const formSection = (title, hint, inner, { collapsed = false } = {}) => {
  const header = `
    <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.ink}">${title}</h2>
    ${hint ? `<span style="font-size: 12.5px; color: ${T.faint}; font-weight: 700">${hint}</span>` : ''}`;
  if (!collapsed) {
    return `
<section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 20px 22px; box-shadow: ${T.shadow}">
  <div style="display: flex; align-items: baseline; gap: 10px; margin-bottom: 16px">${header}</div>
  ${inner}
</section>`;
  }
  return `
<details style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadow}">
  <summary class="plain" style="display: flex; align-items: baseline; gap: 10px; padding: 20px 22px; cursor: pointer; list-style: none">
    ${header}
    <span style="margin-left: auto; align-self: center; display: inline-flex; color: ${T.faint}">${icon.chevR(16)}</span>
  </summary>
  <div style="padding: 0 22px 20px">${inner}</div>
</details>`;
};

export const CreateRoomPage = `
<div style="width: 780px; min-height: 1100px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <div style="display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 18px">
    <div>
      ${sectionLabel('Room setup')}
      <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 30px; color: ${T.ink}; margin-top: 4px">Create a room</h1>
    </div>
    <div style="display: flex; align-items: center; gap: 8px">
      ${selectBox('Start from a preset…')}
      ${btn.ghost('Save as preset')}
    </div>
  </div>

  <div style="display: grid; gap: 14px">
    ${formSection('Basics', '', `
      <div style="display: grid; gap: 16px">
        <div style="display: flex; align-items: flex-start; gap: 20px">
          <label style="flex: 1; display: grid; gap: 6px; font-size: 14.5px; font-weight: 800; color: ${T.ink}">Room name
            <span style="display: flex; align-items: center; gap: 8px">
              ${input({ placeholder: 'Leave blank for a random name!' })}
              <button type="button" title="Roll a random name" aria-label="Roll a random name" style="display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; flex: none; background: ${T.card}; color: ${T.muted}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; box-shadow: ${T.shadow}">${icon.dice(19)}</button>
            </span>
          </label>
          <div style="display: grid; gap: 6px; justify-items: start">
            <span style="font-size: 14.5px; font-weight: 800; color: ${T.ink}">Visibility</span>
            ${segmented([`${icon.globe(14)}Public`, `${icon.lock(14)}Private`], 0)}
            <span style="font-size: 11.5px; font-weight: 700; color: ${T.faint}">Listed in the lobby — anyone can wander in.</span>
          </div>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px">
          ${settingCard(icon.users(14), 'Players', 8, '', "2–16 · spectators aren't counted")}
          ${settingCard(icon.rounds(14), 'Rounds', 3, '', '1–10 · everyone draws once per round')}
          ${settingCard(icon.clock(14), 'Drawing time', 90, 's', 'Snaps to presets · 30s to 300s')}
        </div>
        <div style="display: flex; align-items: center; gap: 10px; border: 1.5px dashed ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 11px 14px; color: ${T.muted}">
          <span style="display: inline-flex; color: ${T.warm}">${icon.clock(17)}</span>
          <span style="font-size: 13.5px; font-weight: 700">This setup runs <strong style="color: ${T.ink}">about 45 minutes</strong> with a full room of 8 — closer to <strong style="color: ${T.ink}">20</strong> if 4 join.</span>
        </div>
      </div>`)}

    ${formSection('Prompts', 'English · Standard English · 432 prompts', `
      <div style="display: grid; gap: 14px">
        <div style="display: flex; flex-wrap: wrap; gap: 8px">
          ${listChip('Standard English', 432, true)}
          ${listChip('Extended English', 1284, false)}
          ${listChip('Studio in-jokes', 64, false)}
        </div>
        <div style="display: flex; align-items: center; gap: 8px">
          ${input({ placeholder: 'Add an unlisted list by code', style: 'max-width: 260px' })}
          ${btn.secondary('Add')}
        </div>
        <details style="border-top: 1.5px solid ${T.line}; padding-top: 14px">
          <summary style="font-size: 14px; font-weight: 800; color: ${T.muted}">Custom prompts for this game <span style="color: ${T.faint}; font-weight: 700">· 3 added</span></summary>
          <div style="display: grid; gap: 8px; margin-top: 12px">
            <textarea style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; font-family: ${T.body}; font-size: 14px; padding: 10px 12px; height: 110px; resize: none; width: 100%; color: ${T.ink}">roller coaster
lighthouse
bow and arrow</textarea>
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px">
              <span style="font-size: 13px; font-weight: 800; color: ${T.successInk}">3 usable prompts</span>
              <div style="display: flex; align-items: center; gap: 10px">
                ${switchCtl('Only use these', false)}
                ${btn.ghost('Save as a reusable list')}
              </div>
            </div>
          </div>
        </details>
      </div>`, { collapsed: true })}

    ${formSection('Drawing', 'Brush, Fill, Shapes · All colors', `
      <div style="display: grid; gap: 16px">
        <div style="display: grid; gap: 8px">
          <span style="font-size: 14.5px; font-weight: 800; color: ${T.ink}">Allowed tools</span>
          <div style="display: flex; flex-wrap: wrap; gap: 8px">
            ${listChip('Brush', '', true)}
            ${listChip('Fill', '', true)}
            ${listChip('Shapes', '', true)}
          </div>
        </div>
        <div style="display: grid; gap: 8px">
          <span style="font-size: 14.5px; font-weight: 800; color: ${T.ink}">Colors</span>
          ${segmented(['All colors', 'Palette only', 'Colorblind-safe', 'Black and white'], 0)}
        </div>
      </div>`, { collapsed: true })}

    ${formSection('Scoring and hints', 'Default scoring · Timed hints', `
      <div style="display: grid; gap: 16px">
        <div style="display: grid; gap: 8px">
          <span style="font-size: 14.5px; font-weight: 800; color: ${T.ink}">Scoring</span>
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px">
            ${optionCard('Default', 'Faster guesses earn more, 100–300 points.', true)}
            ${optionCard('Pressure', 'Points decay — and decay doubles once someone guesses.', false)}
            ${optionCard('No scoring', 'Just draw and guess. No standings.', false)}
          </div>
        </div>
        <div style="display: grid; gap: 8px">
          <span style="font-size: 14.5px; font-weight: 800; color: ${T.ink}">Hints</span>
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px">
            ${optionCard('Timed hints', 'Letters reveal to everyone at fixed times.', true)}
            ${optionCard('No hints', 'Blanks only, all turn long.', false)}
            ${optionCard('Buy letters', 'Each guesser can spend points to reveal a letter slot.', false)}
            ${optionCard('Wheel of Fortune', 'Pick a letter, pay its price — vowels cost extra.', false)}
          </div>
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 8px 24px; border-top: 1.5px solid ${T.line}; padding-top: 14px">
          ${switchCtl('Spectators can see the prompt', true)}
          ${switchCtl('Hide blanks', false, '(turns hints off)')}
        </div>
      </div>`, { collapsed: true })}
  </div>

  <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadowRaised}; padding: 14px 18px; margin-top: 16px">
    <div style="display: grid; gap: 3px">
      <span style="font-size: 13px; color: ${T.muted}; font-weight: 700">Public · 8 players · 3 rounds · 90s · Default scoring · Timed hints</span>
      ${switchCtl('Keep this room for future games', false)}
    </div>
    ${btn.primary('Create room', { big: true })}
  </div>
</div>`;

// --------------------------------------------------------- Account recovery
// A split auth layout: a friendly art panel beside the form.
export const AccountRecoveryPage = `
<div style="width: 880px; min-height: 560px; display: flex; align-items: center; justify-content: center; padding: 40px 24px">
  <div style="display: grid; grid-template-columns: 1fr 1.15fr; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 18px; box-shadow: ${T.shadowRaised}; overflow: hidden; width: 100%">
    <section style="background: ${T.primarySoft}; padding: 34px 28px; display: flex; flex-direction: column; justify-content: flex-end; gap: 10px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 26px; line-height: 1.25; color: ${T.primaryInk}">Even the best guessers forget sometimes.</h2>
      ${squiggle(110, T.primary)}
      <p style="font-size: 13.5px; color: ${T.muted}; font-weight: 600; line-height: 1.5">We'll send a secure, time-limited link to the confirmed email on your account.</p>
    </section>
    <section style="padding: 30px 32px; display: grid; gap: 13px; align-content: start">
      ${wordmark(22)}
      <div style="margin-top: 8px">
        ${sectionLabel('Account help')}
        <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 23px; color: ${T.ink}; margin-top: 4px">Reset your password</h1>
      </div>
      <p style="font-size: 13.5px; color: ${T.muted}; font-weight: 600; line-height: 1.5">Enter your username or email. If it matches an account, a reset link is on its way.</p>
      <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">Username or email
        ${input({ placeholder: 'marta@example.com' })}
      </label>
      ${btn.primary('Send a reset link', { big: true, style: 'width: 100%' })}
      ${btn.ghost('Back to the lobby', { iconL: icon.back(14), style: 'justify-self: center' })}
    </section>
  </div>
</div>`;

// --------------------------------------------------------------- Not found
// The page a URL with nothing behind it gets (#527), and the page the staff
// routes show an account that is not staff. The canvas sheet is white in both
// themes, exactly like `.canvas-stack` in the room, so the doodle is drawn on
// the same paper the game draws on. The tool strip is decoration - spans in
// the build, hidden from assistive technology - and it is here because an
// empty canvas with no tools under it looks like a broken screenshot.
// The header keeps the wordmark alone, with no back control: the card's
// button is the one way out, and two of them side by side is the same
// offer made twice.
const notFoundTool = (svg) => `
<span style="display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; color: ${T.faint}">${svg}</span>`;

export const NotFoundPage = `
<div style="width: 720px; min-height: 700px; padding: 22px 26px 34px">
  <header style="display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px">
    ${wordmark(34)}
    <div style="display: flex; align-items: center; gap: 10px">
      ${btn.iconOnly(icon.gear(18), 'Player settings')}
      <button type="button" style="display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: 5px 14px 5px 5px; min-height: 44px; font-family: ${T.body}; box-shadow: ${T.shadow}">
        ${avatar(P.marta, 30)}
        <span style="font-weight: 800; font-size: 14px; color: ${T.ink}">Marta</span>
      </button>
    </div>
  </header>
  <main style="max-width: 460px; margin: 12px auto 0; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadow}; padding: 26px 24px; text-align: center">
    <div style="aspect-ratio: 4 / 3; background: #fff; border: 1.5px solid ${T.lineStrong}; border-radius: 12px; box-shadow: ${T.shadow}; overflow: hidden; margin-bottom: 16px; padding: 3.5%">
      <svg viewBox="${NOT_FOUND_VIEWBOX}" width="100%" height="100%" aria-hidden="true" style="display: block">
        ${NOT_FOUND_PATHS.map(({ fill, d }) => `<path d="${d}" fill="${fill}"/>`).join('')}
      </svg>
    </div>
    <div style="display: flex; justify-content: center; gap: 7px; margin-bottom: 18px">
      ${notFoundTool(icon.brush(18))}${notFoundTool(icon.fill(18))}${notFoundTool(icon.rect(18))}${notFoundTool(icon.undo(18))}
    </div>
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 25px; color: ${T.ink}; margin-bottom: 8px">Nobody drew this page</h1>
    <p style="font-size: 14.5px; color: ${T.muted}; font-weight: 600; margin-bottom: 20px">That link doesn&rsquo;t lead anywhere on Sketchy.</p>
    ${btn.primary('Back to lobby')}
  </main>
</div>`;

// ------------------------------------------------------------------- Crash
// What a screen shows when its own code throws (#474, R-UX-06): the not-found
// card again, because it is the same object - a canvas nobody meant to draw on
// - with a bug on the sheet. Two ways out first, and under them a bug report
// that is already written: the player adds what they were doing, if anything,
// and sends it. The header is the wordmark alone: the boundary around the app
// sits outside the router, so there is no account button to draw.
const crashRow = (label, value) => `
<div style="display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 10px; padding: 7px 2px; border-bottom: 1px solid ${T.line}">
  <dt style="color: ${T.faint}; font-size: 12.5px; font-weight: 700">${label}</dt>
  <dd style="margin: 0; font-size: 12.5px; font-weight: 700; text-align: right; overflow-wrap: anywhere">${value}</dd>
</div>`;

export const CrashPage = `
<div style="width: 720px; min-height: 1040px; padding: 22px 26px 34px">
  <header style="display: flex; align-items: flex-end; margin-bottom: 18px">
    ${wordmark(34)}
  </header>
  <main style="max-width: 460px; margin: 12px auto 0; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadow}; padding: 26px 24px; text-align: center">
    <div style="aspect-ratio: 4 / 3; background: #fff; border: 1.5px solid ${T.lineStrong}; border-radius: 12px; box-shadow: ${T.shadow}; overflow: hidden; margin-bottom: 16px; padding: 3.5%">
      <svg viewBox="${CRASH_VIEWBOX}" width="100%" height="100%" aria-hidden="true" style="display: block">
        ${CRASH_PATHS.map(({ fill, d }) => `<path d="${d}" fill="${fill}"/>`).join('')}
      </svg>
    </div>
    <div style="display: flex; justify-content: center; gap: 7px; margin-bottom: 18px">
      ${notFoundTool(icon.brush(18))}${notFoundTool(icon.fill(18))}${notFoundTool(icon.rect(18))}${notFoundTool(icon.undo(18))}
    </div>
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 25px; color: ${T.ink}; margin-bottom: 8px">A bug crawled onto the page</h1>
    <p style="font-size: 14.5px; color: ${T.muted}; font-weight: 600; margin-bottom: 20px">This screen hit an error and had to stop. Your account and settings are safe.</p>
    <div style="display: flex; gap: 10px; justify-content: center; margin-bottom: 22px">
      ${btn.primary('Reload', { style: 'flex: 1 1 150px' })}
      ${btn.secondary('Back to lobby', { style: 'flex: 1 1 150px' })}
    </div>
    <form style="display: flex; flex-direction: column; gap: 6px; text-align: left; border-top: 1.5px solid ${T.line}; padding-top: 18px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 17.5px; color: ${T.ink}; margin: 0 0 4px">Help us squash it</h2>
      <p style="font-size: 12px; color: ${T.muted}; margin: 0 0 8px">A report is ready to send: the error, and what this tab knows about itself. It reaches the people who run Sketchy &mdash; never other players.</p>
      <label style="font-size: 13px; font-weight: 600; color: ${T.ink}">What were you doing? <span style="color: ${T.faint}; margin-left: 4px">Optional</span></label>
      <textarea rows="3" placeholder="The last thing you clicked or typed, if you remember." style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 16px; color: ${T.ink}; min-height: 84px; resize: vertical"></textarea>
      <details open style="background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; margin-top: 6px; padding: 12px 14px">
        <summary style="cursor: pointer; font-size: 13px; font-weight: 800; color: ${T.ink}">What we send with this</summary>
        <dl style="display: grid; margin: 0">
          ${crashRow('Summary', 'Crash on /room/BQ7F2K: TypeError: Cannot read properties of null (reading &lsquo;players&rsquo;)')}
          ${crashRow('Build', 'a299f80 &middot; 2026-09-05')}
          ${crashRow('Page', '/room/BQ7F2K')}
          ${crashRow('Room', 'BQ7F2K &middot; round 2 of 3')}
          ${crashRow('Screen', '1440 &times; 900 &middot; 2&times;')}
          ${crashRow('Connection', 'connected &middot; 0 reconnects this visit')}
        </dl>
        <p style="color: ${T.faint}; font-size: 12px; font-weight: 800; margin: 10px 0 6px">Recent client errors, newest first</p>
        <ul style="background: ${T.well}; border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; display: grid; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; gap: 3px; line-height: 1.5; list-style: none; margin: 0; padding: 10px 12px; color: ${T.muted}">
          <li style="display: flex; gap: 10px"><span style="color: ${T.faint}">14:02:11</span>[room] TypeError: Cannot read properties of null (reading &lsquo;players&rsquo;)<br>in at PlayerList &lt; at RoomShell &lt; at ActiveGameRoom</li>
          <li style="display: flex; gap: 10px"><span style="color: ${T.faint}">14:01:58</span>[socket] disconnect: transport close</li>
        </ul>
        <p style="font-size: 12px; color: ${T.muted}; margin: 8px 0 0">The crash, the last 20 errors your browser recorded, and where in the page it happened. No page addresses beyond the path, nothing you typed into chat, and never the prompt in play.</p>
      </details>
      <label style="display: flex; align-items: flex-start; gap: 10px; margin-top: 8px; cursor: pointer">
        <input type="checkbox" style="flex: none; margin-top: 2px">
        <span style="font-size: 13px; font-weight: 700; color: ${T.ink}; line-height: 1.45">Send my description only<span style="display: block; color: ${T.faint}; font-size: 12px; font-weight: 600; margin-top: 2px">Drops the details above. We will still read it, but the crash is much harder to find.</span></span>
      </label>
      ${btn.primary('Send report', { style: 'margin-top: 10px; width: 100%' })}
    </form>
  </main>
</div>`;

// ------------------------------------------------------------------ Settings
// A full settings page: category rail on the left, two-column preference
// groups on the right. Everything shown is the R-SET-01 synced set.
const bareSwitch = (on) => `
<span role="switch" aria-checked="${on}" style="display: inline-flex; align-items: center; width: 42px; height: 24px; border-radius: 999px; padding: 3px; background: ${on ? T.primary : T.lineStrong}; flex: none; cursor: pointer">
  <span style="width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(20, 16, 10, 0.25); transform: translateX(${on ? '18px' : '0'})"></span>
</span>`;

const prefCategory = (tab, svg, title, sub, current = false) => `
<button type="button" role="tab" data-pref-tab="${tab}" aria-current="${current}" style="display: flex; align-items: center; gap: 11px; width: 100%; text-align: left; background: transparent; border: 1.5px solid transparent; border-radius: ${T.radiusSm}; padding: 11px 12px; font-family: ${T.body}">
  <span style="display: inline-flex; color: ${T.faint}">${svg}</span>
  <span style="display: grid; gap: 1px; min-width: 0">
    <strong style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">${title}</strong>
    <small style="font-size: 11.5px; color: ${T.faint}; font-weight: 700">${sub}</small>
  </span>
  <span style="margin-left: auto; display: inline-flex; color: ${T.faint}">${icon.chevR(14)}</span>
</button>`;

const prefGroup = (title, desc, rows) => `
<section style="display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 20px; padding: 20px 0; border-bottom: 1.5px solid ${T.line}">
  <div>
    <h3 style="font-family: ${T.display}; font-weight: 600; font-size: 16px; color: ${T.ink}">${title}</h3>
    <p style="font-size: 12.5px; color: ${T.faint}; font-weight: 700; margin-top: 4px; line-height: 1.45">${desc}</p>
  </div>
  <div style="display: grid; gap: 4px">${rows}</div>
</section>`;

const prefRow = (label, hint, control) => `
<div style="display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 52px; padding: 6px 0">
  <div style="display: grid; gap: 2px">
    <strong style="font-size: 14px; font-weight: 800; color: ${T.ink}">${label}</strong>
    ${hint ? `<p style="font-size: 12.5px; color: ${T.faint}; font-weight: 700">${hint}</p>` : ''}
  </div>
  ${control}
</div>`;

const themeCard = (name, sub, selected, sky, ground) => `
<button type="button" aria-pressed="${selected}" style="display: grid; gap: 7px; justify-items: center; background: ${selected ? T.primarySoft : T.card}; border: 1.5px solid ${selected ? T.primary : T.line}; border-radius: ${T.radiusSm}; padding: 10px 14px 9px; font-family: ${T.body}; min-width: 92px">
  <span aria-hidden="true" style="width: 62px; height: 38px; border-radius: 7px; overflow: hidden; display: grid; grid-template-rows: 1fr 1fr; border: 1px solid ${T.lineStrong}">${sky}${ground}</span>
  <strong style="font-size: 12.5px; font-weight: 800; color: ${selected ? T.primaryInk : T.ink}">${name}${sub ? `<small style="display: block; font-weight: 700; color: ${T.faint}">${sub}</small>` : ''}</strong>
</button>`;

const colorDot = (c, selected = false) =>
  `<button type="button" aria-label="${c}" style="width: 26px; height: 26px; border-radius: 50%; border: 0; padding: 0; background: ${c}${selected ? `; box-shadow: 0 0 0 2.5px ${T.card}, 0 0 0 5px ${T.primary}` : ''}"></button>`;

const keyChip = (key) =>
  `<button type="button" title="Change shortcut" style="display: inline-flex; align-items: center; justify-content: center; min-width: 34px; height: 30px; padding: 0 9px; border-radius: 8px; border: 1.5px solid ${T.lineStrong}; border-bottom-width: 3px; background: ${T.card}; color: ${T.ink}; font-family: ${T.body}; font-size: 12.5px; font-weight: 800">${key}</button>`;

const keyChipAlt = (key) =>
  `<button type="button" title="Change secondary shortcut" style="display: inline-flex; align-items: center; justify-content: center; min-width: 34px; height: 30px; padding: 0 9px; border-radius: 8px; border: 1.5px solid ${T.line}; border-bottom-width: 3px; background: ${T.well}; color: ${T.muted}; font-family: ${T.body}; font-size: 12.5px; font-weight: 800">${key}</button>`;

// Each action shows its main key and, where one exists, the secondary key.
const shortcutRow = (svg, label, key, alt = '') => `
<div style="display: flex; align-items: center; gap: 9px; min-height: 40px">
  <span style="display: inline-flex; color: ${T.faint}">${svg}</span>
  <span style="font-size: 13px; font-weight: 700; color: ${T.muted}">${label}</span>
  <span style="margin-left: auto; display: inline-flex; gap: 5px">${keyChip(key)}${alt ? keyChipAlt(alt) : ''}</span>
</div>`;

const brushPreset = (color, sizeLabel, dot) => `
<button type="button" style="display: inline-flex; align-items: center; gap: 8px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: 999px; padding: 8px 14px; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; color: ${T.muted}; min-height: 40px">
  <span style="width: ${dot}px; height: ${dot}px; border-radius: 50%; background: ${color}; border: 1px solid rgba(0, 0, 0, 0.15); flex: none"></span>${sizeLabel}
</button>`;

const volumeSlider = `
<span style="display: inline-flex; align-items: center; gap: 10px; width: 200px">
  <span aria-label="Volume, 70%" role="slider" aria-valuenow="70" style="position: relative; flex: 1; height: 8px; border-radius: 999px; background: ${T.track}; cursor: pointer">
    <span style="position: absolute; inset: 0 30% 0 0; border-radius: 999px; background: ${T.primary}"></span>
    <span style="position: absolute; left: 70%; top: 50%; transform: translate(-50%, -50%); width: 20px; height: 20px; border-radius: 50%; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; box-shadow: ${T.shadow}"></span>
  </span>
  <span style="font-size: 12.5px; font-weight: 800; color: ${T.muted}; font-variant-numeric: tabular-nums; width: 34px; text-align: right">70%</span>
</span>`;

export const SettingsPage = `
<div style="width: 1080px; min-height: 900px; margin: 0 auto; padding: 24px 24px 40px">
  <header style="display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; margin-bottom: 18px">
    <div>
      ${sectionLabel('Personal preferences')}
      <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 27px; color: ${T.ink}; margin-top: 4px">Settings</h1>
    </div>
    ${chip(`${icon.check(11)} Synced to your account`, 'success')}
  </header>

  <div style="display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 16px; align-items: start">
    <aside style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 12px; box-shadow: ${T.shadow}; display: grid; gap: 4px; position: sticky; top: 0">
      <div style="display: flex; align-items: center; gap: 10px; padding: 8px 10px 12px">
        ${avatar(P.marta, 34)}
        <span style="display: grid; gap: 0"><strong style="font-size: 14px; font-weight: 800; color: ${T.ink}">Marta</strong><small style="font-size: 11.5px; color: ${T.faint}; font-weight: 700">Signed in</small></span>
      </div>
      <div style="border-top: 1.5px solid ${T.line}; margin: 0 6px 4px"></div>
      ${prefCategory('general', icon.gear(16), 'General', 'Account, appearance & sound', true)}
      ${prefCategory('game', icon.brush(16), 'Game', 'Drawing & celebrations')}
      ${prefCategory('shortcuts', icon.keyboard(16), 'Shortcuts', 'Drawing tool key bindings')}
      <div style="border-top: 1.5px solid ${T.line}; margin: 6px 6px 2px"></div>
      ${btn.ghost('Back to lobby', { iconL: icon.back(14), style: 'justify-content: flex-start' })}
    </aside>

    <section data-tab="{{tab}}" style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 6px 24px 18px; box-shadow: ${T.shadow}">
      <div data-pref-panel="general">
      ${prefGroup('You', 'How you appear to other players.', `
        ${prefRow('Username', 'Your account login and in-game name.', `<span style="display: inline-flex; align-items: center; gap: 10px">${avatar(P.marta, 26)}<strong style="font-size: 14px; font-weight: 800; color: ${T.ink}">Marta</strong>${btn.secondary('Manage account', { style: 'min-height: 38px; padding: 7px 13px; font-size: 13px' })}</span>`)}
        ${prefRow('Name color', 'How your name reads in every room. Guests stay grey.', `<span style="display: inline-flex; align-items: center; gap: 14px">${pname(P.marta, '; font-size: 15px')}<span style="display: inline-flex; gap: 8px">${colorDot('#0F766E', true)}${colorDot('#C2410C')}${colorDot('#7E22CE')}${colorDot('#0369A1')}</span></span>`)}`)}

      ${prefGroup('Appearance', 'Theme and accessible color behavior.', `
        ${prefRow('Theme', 'Follow your device, or lock an appearance.', `<span style="display: inline-flex; gap: 8px">
          ${themeCard('Light', '', false, '<i style="background: #FAF6EF"></i>', '<i style="background: #FFFFFF"></i>')}
          ${themeCard('Dark', '', false, '<i style="background: #0F172A"></i>', '<i style="background: #1E293B"></i>')}
          ${themeCard('System', 'Current: Light', true, '<i style="background: linear-gradient(100deg, #FAF6EF 50%, #0F172A 50%)"></i>', '<i style="background: linear-gradient(100deg, #FFFFFF 50%, #1E293B 50%)"></i>')}
        </span>`)}
        ${prefRow('Colorblind-safe colors', 'Hosts of rooms you join get a quiet suggestion to switch the palette. Never shown with your name.', bareSwitch(false))}`)}

      ${prefGroup('Audio', 'Feedback for guesses, rounds, and timers.', `
        ${prefRow('Sound', '', bareSwitch(true))}
        ${prefRow('Volume', '', volumeSlider)}`)}
      </div>

      <div data-pref-panel="game">
      ${prefGroup('Drawing', 'Your drawing experience only — rooms set the rules.', `
        ${prefRow('Brush cursor', 'A precise crosshair, or the full brush outline.', segmented(['Crosshair', 'Outline'], 1, { w: 92 }))}
        ${prefRow('Brush presets', '3 of 20 saved.', `<span style="display: inline-flex; flex-wrap: wrap; gap: 7px; justify-content: flex-end">${brushPreset('#000000', 'Ink · 4px', 8)}${brushPreset('#ED1C24', 'Marker · 12px', 13)}${brushPreset('#7AC9E8', 'Sky wash · 24px', 17)}</span>`)}`)}

      ${prefGroup('Celebrations', 'Keep the energy without covering the canvas.', `
        ${prefRow('Confetti', 'On correct guesses and podiums.', bareSwitch(true))}
        ${prefRow('Clear the guess box after each guess', 'Off keeps your last guess for quick edits.', bareSwitch(true))}`)}
      </div>

      <div data-pref-panel="shortcuts">
      ${prefGroup('Keyboard shortcuts', 'Select a key to rebind it. Each action can carry a main and a secondary key.', `
        <div style="display: grid; grid-template-columns: 1fr; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 8px 16px">
          ${shortcutRow(icon.brush(15), 'Brush', 'P', '1')}
          ${shortcutRow(icon.fill(15), 'Fill', 'F', '2')}
          ${shortcutRow(icon.eraser(15), 'Eraser', 'E', '3')}
          ${shortcutRow(icon.rect(15), 'Rectangle', 'R', '4')}
          ${shortcutRow(icon.triangle(15), 'Triangle', 'T', '5')}
          ${shortcutRow(icon.circle(15), 'Ellipse', 'C', '6')}
          ${shortcutRow(icon.chevD(15), 'Decrease brush size', '[')}
          ${shortcutRow(icon.chevU(15), 'Increase brush size', ']')}
          ${shortcutRow(icon.undo(15), 'Undo stroke', 'Z')}
        </div>
        <div style="display: flex; justify-content: flex-end; margin-top: 8px">${btn.ghost('Reset to defaults', { style: 'min-height: 34px; padding: 4px 8px; font-size: 12.5px' })}</div>`)}
      </div>

      <footer style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 16px">
        <span style="font-size: 12.5px; font-weight: 700; color: ${T.faint}">Changes apply immediately, on every device you're signed in on.</span>
        ${btn.primary('Done')}
      </footer>
    </section>
  </div>
</div>`;
