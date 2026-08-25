// Entry screens: lobby, room creation, account recovery.
import { T, P, icon, flag, avatar, btn, chip, card, sectionLabel, segmented, selectBox, switchCtl, input, wordmark, squiggle } from './ui.mjs';

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
  .map((c, i) => `<span style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 48px; border: 1.5px solid ${c ? T.lineStrong : T.line}; border-radius: 10px; background: ${T.card}; font-family: ${T.display}; font-weight: 600; font-size: 20px; color: ${T.ink}${i === 4 ? `; border-color: ${T.primary}; box-shadow: 0 0 0 3px ${T.primarySoft}` : ''}">${c}</span>`)
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

const formSection = (title, hint, inner) => `
<section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 20px 22px; box-shadow: ${T.shadow}">
  <div style="display: flex; align-items: baseline; gap: 10px; margin-bottom: 16px">
    <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.ink}">${title}</h2>
    ${hint ? `<span style="font-size: 12.5px; color: ${T.faint}; font-weight: 700">${hint}</span>` : ''}
  </div>
  ${inner}
</section>`;

export const CreateRoomPage = `
<div style="width: 780px; min-height: 1720px; margin: 0 auto; padding: 26px 24px 48px">
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

    ${formSection('Prompts', 'English · resolved from your lists', `
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
            <textarea style="border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; font-family: ${T.body}; font-size: 14px; padding: 10px 12px; height: 110px; resize: none; width: 100%; color: ${T.ink}">roller coaster
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
      </div>`)}

    ${formSection('Drawing', '', `
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
      </div>`)}

    ${formSection('Scoring and hints', '', `
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
      </div>`)}
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
export const AccountRecoveryPage = `
<div style="width: 560px; min-height: 500px; display: flex; justify-content: center; padding: 56px 16px">
  <div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadowRaised}; max-width: 420px; padding: 30px; width: 100%; display: grid; gap: 14px">
    ${wordmark(24)}
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 22px; color: ${T.ink}; margin-top: 6px">Reset your password</h1>
    <p style="font-size: 14px; color: ${T.muted}; line-height: 1.55">Enter your username or your confirmed email address. If the account can be recovered, a link is on its way.</p>
    <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">Username or email
      ${input({})}
    </label>
    ${btn.primary('Send a reset link', { big: true, style: 'width: 100%' })}
    ${btn.ghost('Back to the lobby', { iconL: icon.back(14), style: 'justify-self: center' })}
  </div>
</div>`;

// ------------------------------------------------------------------ Settings
// The settings modal, drawn over a dimmed lobby. Everything here follows a
// registered account across devices (R-SET-01); guests keep it in this
// browser only.
const settingsRow = (label, control, hint = '') => `
<div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 44px">
  <div style="display: grid; gap: 2px">
    <span style="font-size: 14px; font-weight: 800; color: ${T.ink}">${label}</span>
    ${hint ? `<span style="font-size: 12px; font-weight: 700; color: ${T.faint}">${hint}</span>` : ''}
  </div>
  ${control}
</div>`;

const bareSwitch = (on) => `
<span role="switch" aria-checked="${on}" style="display: inline-flex; align-items: center; width: 42px; height: 24px; border-radius: 999px; padding: 3px; background: ${on ? T.primary : T.lineStrong}; flex: none; cursor: pointer">
  <span style="width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(20, 16, 10, 0.25); transform: translateX(${on ? '18px' : '0'})"></span>
</span>`;

const volumeSlider = `
<span style="display: inline-flex; align-items: center; gap: 10px; width: 190px">
  <span aria-label="Volume, 70%" role="slider" aria-valuenow="70" style="position: relative; flex: 1; height: 8px; border-radius: 999px; background: ${T.track}; cursor: pointer">
    <span style="position: absolute; inset: 0 30% 0 0; border-radius: 999px; background: ${T.primary}"></span>
    <span style="position: absolute; left: 70%; top: 50%; transform: translate(-50%, -50%); width: 20px; height: 20px; border-radius: 50%; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; box-shadow: ${T.shadow}"></span>
  </span>
  <span style="font-size: 12.5px; font-weight: 800; color: ${T.muted}; font-variant-numeric: tabular-nums; width: 34px; text-align: right">70%</span>
</span>`;

const keyChip = (key) =>
  `<button type="button" title="Change shortcut" style="display: inline-flex; align-items: center; justify-content: center; min-width: 34px; height: 30px; padding: 0 9px; border-radius: 8px; border: 1.5px solid ${T.lineStrong}; border-bottom-width: 3px; background: ${T.card}; color: ${T.ink}; font-family: ${T.body}; font-size: 12.5px; font-weight: 800">${key}</button>`;

const shortcutRow = (svg, label, key) => `
<div style="display: flex; align-items: center; gap: 9px; min-height: 38px">
  <span style="display: inline-flex; color: ${T.faint}">${svg}</span>
  <span style="font-size: 13px; font-weight: 700; color: ${T.muted}">${label}</span>
  <span style="margin-left: auto">${keyChip(key)}</span>
</div>`;

const brushPreset = (color, sizeLabel, dot) => `
<button type="button" style="display: inline-flex; align-items: center; gap: 8px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: 999px; padding: 8px 14px; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; color: ${T.muted}; min-height: 40px">
  <span style="width: ${dot}px; height: ${dot}px; border-radius: 50%; background: ${color}; border: 1px solid rgba(0, 0, 0, 0.15); flex: none"></span>${sizeLabel}
</button>`;

const settingsDivider = `<div style="border-top: 1.5px solid ${T.line}; margin: 6px 0 2px"></div>`;

export const SettingsPage = `
<div style="width: 960px; min-height: 1060px; position: relative; overflow: hidden">
  <div aria-hidden="true" style="position: absolute; inset: 0; padding: 26px 24px; opacity: 0.4; filter: blur(2px)">
    <div style="display: flex; justify-content: space-between; margin-bottom: 26px">${wordmark(34)}<span style="width: 260px; height: 44px; border-radius: 999px; background: ${T.card}; border: 1.5px solid ${T.line}"></span></div>
    <div style="display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; margin-bottom: 18px">
      <div style="height: 170px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}"></div>
      <div style="height: 170px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}"></div>
    </div>
    <div style="height: 620px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}"></div>
  </div>

  <div style="position: absolute; inset: 0; background: ${T.scrim}; display: flex; align-items: flex-start; justify-content: center; padding: 44px 20px">
    <section role="dialog" aria-label="Settings" style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 18px; box-shadow: ${T.shadowRaised}; width: min(660px, 100%); padding: 24px 28px 26px; display: grid; gap: 14px">
      <header style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
        <div>
          ${sectionLabel('Your preferences')}
          <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 24px; color: ${T.ink}; margin-top: 3px">Settings</h1>
        </div>
        <button type="button" aria-label="Close settings" style="display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; background: transparent; border: 0; border-radius: ${T.radiusSm}; color: ${T.muted}">${icon.x(17)}</button>
      </header>

      ${settingsRow('Theme', segmented(['Light', 'Dark', 'System'], 2, { w: 74 }))}
      ${settingsRow('Colorblind-safe colors', bareSwitch(false), 'Hosts of rooms you join get a quiet suggestion to switch the palette. Never shown with your name.')}

      ${settingsDivider}
      ${settingsRow('Sound', bareSwitch(true))}
      ${settingsRow('Volume', volumeSlider)}
      ${settingsRow('Confetti', bareSwitch(true), 'Celebrations on correct guesses and podiums.')}

      ${settingsDivider}
      ${settingsRow('Brush outline cursor', bareSwitch(true), 'Show the brush size under your pointer while drawing.')}
      <div style="display: grid; gap: 8px">
        <span style="font-size: 14px; font-weight: 800; color: ${T.ink}">Brush presets <span style="font-weight: 700; color: ${T.faint}">· 3 of 20</span></span>
        <div style="display: flex; flex-wrap: wrap; gap: 7px">
          ${brushPreset('#000000', 'Ink · 4px', 8)}
          ${brushPreset('#ED1C24', 'Marker · 12px', 13)}
          ${brushPreset('#7AC9E8', 'Sky wash · 24px', 17)}
          <button type="button" style="display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 1.5px dashed ${T.lineStrong}; border-radius: 999px; padding: 8px 14px; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; color: ${T.muted}; min-height: 40px">${icon.plus(12)}Save current brush</button>
        </div>
      </div>
      <div style="display: grid; gap: 6px">
        <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 10px">
          <span style="font-size: 14px; font-weight: 800; color: ${T.ink}">Keyboard shortcuts</span>
          ${btn.ghost('Reset to defaults', { style: 'min-height: 34px; padding: 4px 8px; font-size: 12.5px' })}
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0 28px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 8px 16px">
          ${shortcutRow(icon.pencil(15), 'Brush', 'P')}
          ${shortcutRow(icon.rect(15), 'Rectangle', 'R')}
          ${shortcutRow(icon.fill(15), 'Fill', 'F')}
          ${shortcutRow(icon.triangle(15), 'Triangle', 'T')}
          ${shortcutRow(icon.eraser(15), 'Eraser', 'E')}
          ${shortcutRow(icon.circle(15), 'Ellipse', 'C')}
        </div>
      </div>

      ${settingsDivider}
      ${settingsRow('Clear the guess box after each guess', bareSwitch(true), 'Off keeps your last guess in the box for quick edits.')}

      <footer style="display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1.5px solid ${T.line}; padding-top: 16px; margin-top: 2px">
        <span style="display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 700; color: ${T.faint}">${avatar(P.marta, 24)}Signed in as Marta — settings follow you across devices.</span>
        ${btn.primary('Done')}
      </footer>
    </section>
  </div>
</div>`;
