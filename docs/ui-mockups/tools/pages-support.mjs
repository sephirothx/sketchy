// Support artboards: the bug-report entry point, the report dialog, and the
// administrator's triage queue. Every player can file one; only an
// administrator reads them, which is why the queue lives beside server
// operations rather than in the moderation queue.
import { T, P, icon, avatar, btn, chip, sectionLabel } from './ui.mjs';
import { lighthouseSVG } from './shell.mjs';
import { appHeader } from './header.mjs';

// The ten triage buckets, taken from the requirement sections rather than
// invented, so a report lands where the code and its tests already live.
export const BUG_AREAS = [
  'Drawing and canvas',
  'Guessing and chat',
  'Rounds, scoring and results',
  'Rooms and lobby',
  'Prompt lists',
  'Account and settings',
  'Connection and sync',
  'Performance',
  'Accessibility',
  'Something else',
];

// ------------------------------------------------------------ shared pieces

const menuItem = (svg, label, { danger = false, fresh = false } = {}) => `
<button type="button" style="display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: ${fresh ? T.primarySoft : 'transparent'}; border: 0; border-radius: 9px; padding: 10px 12px; font-family: ${T.body}; font-size: 14px; font-weight: 700; color: ${danger ? T.danger : fresh ? T.primaryInk : T.ink}; min-height: 40px">
  <span style="display: inline-flex; color: ${danger ? T.danger : fresh ? T.primary : T.faint}">${svg}</span>${label}
</button>`;

const accountMenu = (person, entries, { label }) => `
<div style="display: grid; gap: 10px; justify-items: end">
  <p style="font-size: 12px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: ${T.faint}; justify-self: start">${label}</p>
  <button type="button" aria-expanded="true" style="display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: 5px 14px 5px 5px; min-height: 44px; font-family: ${T.body}; box-shadow: ${T.shadow}">
    ${avatar(person, 30)}
    <span style="font-weight: 800; font-size: 14px; color: ${T.ink}${person.guest ? '; font-style: italic' : ''}">${person.name}</span>
    <span style="display: inline-flex; color: ${T.faint}">${icon.chevD(14)}</span>
  </button>
  <div role="menu" style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 12px; box-shadow: ${T.shadowRaised}; padding: 6px; width: 236px; display: grid; gap: 1px">
    ${entries}
  </div>
</div>`;

const divider = `<div style="border-top: 1.5px solid ${T.line}; margin: 4px 6px"></div>`;

// A screenshot of the game, drawn rather than embedded: a header strip, the
// canvas with the turn's lighthouse, and the player rail beside it.
const shot = (w, h) => `
<span style="display: block; position: relative; width: ${w}px; height: ${h}px; border-radius: 7px; overflow: hidden; border: 1.5px solid ${T.lineStrong}; background: ${T.paper}; flex: none">
  <span style="position: absolute; inset: 0 0 auto 0; height: ${Math.round(h * 0.13)}px; background: ${T.card}; border-bottom: 1px solid ${T.line}"></span>
  <span style="position: absolute; left: 4%; top: ${Math.round(h * 0.13) + 4}px; bottom: 4px; width: 66%; border-radius: 4px; overflow: hidden; background: #fff; border: 1px solid ${T.line}">${lighthouseSVG}</span>
  <span style="position: absolute; right: 4%; top: ${Math.round(h * 0.13) + 4}px; bottom: 4px; width: 24%; border-radius: 4px; background: ${T.card}; border: 1px solid ${T.line}"></span>
</span>`;

// --------------------------------------------------- 1. Entry point in place

export const BugReportMenuPage = `
<div style="width: 820px; min-height: 560px; margin: 0 auto; padding: 28px 24px 40px">
  <div style="margin-bottom: 22px">
    ${sectionLabel('Entry point')}
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 24px; color: ${T.ink}; margin-top: 4px">Report a bug lives in the account menu</h1>
    <p style="font-size: 14px; color: ${T.muted}; font-weight: 600; line-height: 1.5; margin-top: 6px; max-width: 560px">Reachable from every screen, and offered to guests too — most first-run bugs happen before anyone has made an account. It sits under the personal entries and above the sign-in block, separated from them so it never reads as an account action.</p>
  </div>
  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: start">
    ${accountMenu(P.marta, `
      ${menuItem(icon.gear(16), 'Settings')}
      ${menuItem(icon.user(16), 'My profile')}
      ${menuItem(icon.zap(16), 'Prompt stats')}
      ${menuItem(icon.bulb(16), 'My prompt lists')}
      ${divider}
      ${menuItem(icon.bug(16), 'Report a bug', { fresh: true })}
      ${divider}
      ${menuItem(icon.leave(16), 'Sign out', { danger: true })}
    `, { label: 'Registered player' })}
    ${accountMenu(P.sparrow, `
      ${menuItem(icon.gear(16), 'Settings')}
      ${menuItem(icon.user(16), 'My profile')}
      ${menuItem(icon.zap(16), 'Prompt stats')}
      ${divider}
      ${menuItem(icon.bug(16), 'Report a bug', { fresh: true })}
      ${divider}
      ${menuItem(icon.plus(16), 'Create account')}
      ${menuItem(icon.lock(16), 'Log in')}
    `, { label: 'Guest' })}
  </div>
</div>`;

// ------------------------------------------------------------ 2. The dialog

const field = (label, inner, hint = '') => `
<label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">${label}
  ${inner}
  ${hint ? `<span style="font-size: 12px; color: ${T.faint}; font-weight: 700">${hint}</span>` : ''}
</label>`;

const select = (value) =>
  `<span style="display: inline-flex; align-items: center; justify-content: space-between; gap: 10px; background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 9px 12px; font-size: 14px; font-weight: 700; color: ${T.ink}; min-height: 42px">${value}<span style="color: ${T.faint}; display: inline-flex">${icon.chevD(14)}</span></span>`;

const diagRow = (label, value) => `
<div style="display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid ${T.line}; font-size: 12.5px">
  <span style="color: ${T.faint}; font-weight: 700; flex: none">${label}</span>
  <span style="color: ${T.ink}; font-weight: 700; text-align: right; font-variant-numeric: tabular-nums">${value}</span>
</div>`;

const mono = (extra = '') =>
  `font-family: ui-monospace, SFMono-Regular, Menlo, monospace${extra}`;

const consoleLine = (time, text) => `
<div style="display: flex; gap: 10px; padding: 3px 0"><span style="color: ${T.faint}; flex: none">${time}</span><span style="color: ${T.muted}; word-break: break-word">${text}</span></div>`;

const consoleBlock = `
<div style="background: ${T.well}; border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 10px 12px; ${mono()}; font-size: 11.5px; line-height: 1.5">
  ${consoleLine('09:41:02', 'TypeError: cannot read properties of null (reading &#39;ctx&#39;)')}
  ${consoleLine('09:40:58', 'socket connect_error: websocket error')}
  ${consoleLine('09:40:51', 'canvas replay budget exceeded, falling back to snapshot')}
</div>`;

export const BugReportDialogPage = `
<div style="position: relative; width: 760px; min-height: 1300px; margin: 0 auto; background: ${T.paper}">
  <div style="position: absolute; inset: 0; background: ${T.scrim}"></div>
  <div style="position: relative; padding: 30px 26px 36px; display: flex; justify-content: center">
    <div role="dialog" aria-modal="true" aria-label="Report a bug" style="width: 100%; max-width: 620px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadowRaised}; padding: 22px 24px 20px; display: grid; gap: 14px">

      <div style="display: flex; align-items: flex-start; gap: 12px">
        <span style="display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 11px; background: ${T.warmSoft}; color: ${T.warmInk}; flex: none">${icon.bug(20)}</span>
        <div>
          <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 21px; color: ${T.ink}">Report a bug</h2>
          <p style="font-size: 13px; color: ${T.muted}; font-weight: 600; line-height: 1.5; margin-top: 3px">Something broken, not something someone said. This reaches the people who run Sketchy — never other players.</p>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px">
        ${field('Where', select('Drawing and canvas'))}
        ${field('How bad', select('Major — hard to play around'))}
      </div>

      ${field('One line summary', `<input type="text" value="Timer kept counting after everyone had guessed" style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 14.5px; color: ${T.ink}; min-height: 42px; width: 100%">`)}

      <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">What happened
        <textarea style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; font-family: ${T.body}; font-size: 13.5px; line-height: 1.5; padding: 10px 12px; height: 96px; resize: vertical; width: 100%; color: ${T.ink}">Round 2, everyone had guessed the lighthouse but the ring timer kept running to zero before the results card appeared. Happened twice in the same room.</textarea>
        <span style="display: flex; justify-content: space-between; gap: 10px; font-size: 12px; color: ${T.faint}; font-weight: 700"><span>What you did, what you expected, what happened instead.</span><span style="font-variant-numeric: tabular-nums">211 / 4000</span></span>
      </label>

      <div style="display: grid; gap: 8px; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 12px 14px">
        <div style="display: flex; align-items: center; gap: 8px">
          <span style="display: inline-flex; color: ${T.faint}">${icon.image(15)}</span>
          <strong style="font-size: 13px; font-weight: 800; color: ${T.ink}">Screenshot</strong>
          <span style="margin-left: auto">${chip('Optional', 'neutral')}</span>
        </div>
        <div style="display: flex; align-items: flex-start; gap: 12px">
          ${shot(148, 92)}
          <div style="display: grid; gap: 6px; min-width: 0">
            <span style="font-size: 12.5px; font-weight: 800; color: ${T.ink}; ${mono()}">1440 × 900 · WebP · 184 KB</span>
            <span style="font-size: 12px; color: ${T.muted}; font-weight: 600; line-height: 1.45">This dialog hides itself while the shot is taken, so you get the page behind it. Look at it before you send — you chose what to share.</span>
            <div style="display: flex; gap: 6px">
              ${btn.ghost('Replace', { style: 'min-height: 34px; padding: 6px 10px; font-size: 13px' })}
              ${btn.dangerGhost('Remove', { style: 'min-height: 34px; padding: 6px 10px; font-size: 13px' })}
            </div>
          </div>
        </div>
        <p style="font-size: 11.5px; color: ${T.faint}; font-weight: 700; line-height: 1.5; border-top: 1px solid ${T.line}; padding-top: 8px">Empty state: <strong style="color: ${T.muted}">Attach a screenshot</strong> opens your browser's picker, so choose this tab. Hidden on browsers without it — phones mostly — where the description stands alone.</p>
      </div>

      <details open style="background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 12px 14px">
        <summary class="plain" style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 800; color: ${T.ink}">
          <span style="display: inline-flex; color: ${T.faint}">${icon.chevU(14)}</span>What we send with this
          <span style="margin-left: auto">${chip('6 details', 'neutral')}</span>
        </summary>
        <div style="margin-top: 10px; display: grid; gap: 10px">
          <div>
            ${diagRow('Build', 'a299f80 · 27 Aug 2026')}
            ${diagRow('Page', '/room/BQ7F2K')}
            ${diagRow('Room', 'BQ7F2K · round 2, turn 1')}
            ${diagRow('Screen', '1440 × 900 · 2×')}
            ${diagRow('Browser', 'Chrome 141 · macOS 15')}
            ${diagRow('Connection', 'reconnected once, 12s ago')}
          </div>
          <div>
            <p style="font-size: 12px; font-weight: 800; color: ${T.faint}; margin-bottom: 6px">Recent client errors</p>
            ${consoleBlock}
            <p style="font-size: 11.5px; color: ${T.faint}; font-weight: 700; margin-top: 7px; line-height: 1.5">The last 20 errors your browser recorded, trimmed to 500 characters each. No page addresses beyond the path, and nothing you typed into chat.</p>
          </div>
        </div>
      </details>

      <label style="display: flex; align-items: flex-start; gap: 10px; cursor: pointer">
        <span aria-hidden="true" style="display: inline-flex; width: 20px; height: 20px; border-radius: 6px; border: 1.5px solid ${T.lineStrong}; background: ${T.field}; flex: none; margin-top: 1px"></span>
        <span style="font-size: 13px; font-weight: 700; color: ${T.ink}; line-height: 1.45">Send my description only<span style="display: block; font-weight: 600; color: ${T.faint}; font-size: 12px; margin-top: 2px">Drops the details above and the screenshot. We will still read it, but the bug is much harder to reproduce.</span></span>
      </label>

      <div style="display: flex; align-items: center; justify-content: flex-end; gap: 10px; border-top: 1.5px solid ${T.line}; padding-top: 14px">
        ${btn.ghost('Cancel')}
        ${btn.primary('Send report', { iconL: icon.send(15) })}
      </div>
    </div>
  </div>
</div>`;

// ------------------------------------------------------- 3. The triage queue

const filterPill = (label, on = false) => on
  ? `<button type="button" aria-pressed="true" style="background: ${T.primarySoft}; border: 1.5px solid ${T.primary}; border-radius: 999px; padding: 6px 12px; font-family: ${T.body}; font-size: 12px; font-weight: 800; color: ${T.primaryInk}">${label}</button>`
  : `<button type="button" aria-pressed="false" style="background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 999px; padding: 6px 12px; font-family: ${T.body}; font-size: 12px; font-weight: 800; color: ${T.muted}">${label}</button>`;

// Severity is the dot: red blocks play, amber is major, grey is minor. The
// same three colors the queue is sorted by, so triage reads at a glance.
const queueItem = (summary, meta, age, { current = false, dot = T.warning, shotted = false } = {}) => `
<button type="button" style="display: flex; align-items: flex-start; gap: 10px; width: 100%; text-align: left; background: ${current ? T.primarySoft : 'transparent'}; border: 1.5px solid ${current ? T.primary : 'transparent'}; border-radius: ${T.radiusSm}; padding: 11px 12px; font-family: ${T.body}">
  <span style="width: 9px; height: 9px; border-radius: 50%; background: ${dot}; flex: none; margin-top: 5px"></span>
  <span style="display: grid; gap: 2px; min-width: 0">
    <strong style="font-size: 13.5px; font-weight: 800; color: ${current ? T.primaryInk : T.ink}">${summary}</strong>
    <span style="display: flex; align-items: center; gap: 5px; font-size: 12px; color: ${T.muted}; font-weight: 600; line-height: 1.4">${shotted ? `<span style="display: inline-flex; color: ${T.faint}" title="Has a screenshot">${icon.image(12)}</span>` : ''}${meta}</span>
  </span>
  <time style="margin-left: auto; font-size: 11.5px; color: ${T.faint}; font-weight: 700; flex: none">${age}</time>
</button>`;

// One fact in the diagnostics strip. Rules are drawn on the cell rather than
// as a background behind the grid: the column count changes with the width, so
// the last row is usually short, and a painted background would turn that
// leftover into a grey notch.
const diagCell = (label, value, { wide = false, isMono = false } = {}) => `
<div style="display: grid; gap: 3px; padding: 9px 12px; border-bottom: 1px solid ${T.line}; border-right: 1px solid ${T.line}${wide ? `; grid-column: 1 / -1; border-bottom: 0; border-right: 0` : ''}">
  <span style="color: ${T.faint}; font-size: 11px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase">${label}</span>
  <span style="color: ${T.ink}; font-size: 13px; font-weight: 700; overflow-wrap: anywhere${isMono ? '; ' + mono('; font-size: 12px; line-height: 1.5') : ''}">${value}</span>
</div>`;

const moreContext = (label) => `
<div style="border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 10px 12px; display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 800; color: ${T.muted}">
  <span style="display: inline-flex; color: ${T.faint}">${icon.chevR(12)}</span>${label}
</div>`;

// What the Copy for triage button puts on the clipboard, shown verbatim so the
// format can be judged: stable headings, one fact per line, no prose glue.
// Markdown because it pastes readably into an issue and parses cleanly for a
// model asked to reproduce the bug.
const TRIAGE_TEXT = [
  '# Sketchy bug report 7c41a9de',
  'status: pending',
  'filed: 2026-08-27T09:41:12Z',
  'reporter: guest account, 3 days old',
  'area: drawing_and_canvas',
  'severity: blocks_play',
  '',
  '## Summary',
  'Timer kept counting after everyone had guessed',
  '',
  '## Details',
  'Round 2, everyone had guessed the lighthouse but the ring timer kept',
  'running to zero before the results card appeared. Happened twice in the',
  'same room.',
  '',
  '## Environment',
  'build: a299f80 (2026-08-27)',
  'route: /room/BQ7F2K',
  'room: BQ7F2K round 2 turn 1',
  'game_id: 4f2b9c81-... turn_id: b7d0a35e-...',
  'viewport: 1440x900 @2x',
  'user_agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/141',
  'connection: reconnected 12s before filing',
  '',
  '## Client errors (3, newest first)',
  '1. 09:41:02 error TypeError: cannot read properties of null (&#39;ctx&#39;)',
  '2. 09:40:58 socket connect_error: websocket error',
  '3. 09:40:51 console canvas replay budget exceeded, using snapshot',
  '',
  '## Screenshot',
  'attached: 1440x900 webp 184 KB',
  'url: /api/admin/bug-reports/7c41a9de/screenshot',
].map((line) => `<div>${line || '&nbsp;'}</div>`).join('');

export const BugReportsQueuePage = `
<div style="width: 1160px; min-height: 1175px; margin: 0 auto; padding: 24px 24px 40px">
  ${appHeader({ page: 'Bug reports', gap: 16 })}
  <div style="display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; align-items: start">

    <aside style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px; box-shadow: ${T.shadow}; display: grid; gap: 10px; align-content: start">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
        <div>
          ${sectionLabel('Administrators only')}
          <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 18px; color: ${T.ink}; margin-top: 3px">Bug reports</h2>
        </div>
        ${chip('4 open', 'warning')}
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 6px">
        ${filterPill('Open', true)}
        ${filterPill('Resolved')}
        ${filterPill('Dismissed')}
      </div>
      <div style="display: grid; gap: 4px">
        ${queueItem('Timer kept counting after everyone had guessed', 'Drawing · blocks play · Sparrow-14', '6m', { current: true, dot: T.danger, shotted: true })}
        ${queueItem('Prompt list picker forgets the language filter', 'Prompt lists · major · Bruno', '2h', { shotted: true })}
        ${queueItem('Reconnect leaves two seats for one player', 'Connection · blocks play · Yuki', '5h', { dot: T.danger })}
        ${queueItem('Confetti keeps animating behind the results card', 'Performance · minor · Ines', '1d', { dot: T.faint })}
      </div>
      <p style="font-size: 11.5px; color: ${T.faint}; font-weight: 700; line-height: 1.5; padding: 0 2px">Sorted newest first. A player may file several — unrelated bugs are not one complaint repeated.</p>
    </aside>

    <main style="display: grid; gap: 12px">
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px">
        <div>
          ${sectionLabel('Bug report · #7c41a9')}
          <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 24px; color: ${T.ink}; margin-top: 4px">Timer kept counting after everyone had guessed</h1>
          <p style="font-size: 13px; color: ${T.muted}; font-weight: 700; margin-top: 4px">From <span style="color: ${P.sparrow.text}; font-style: italic">Sparrow-14</span> (guest) · today 09:41 · build a299f80</p>
        </div>
        <div style="display: grid; gap: 8px; justify-items: end; flex: none">
          <div style="display: flex; gap: 6px">
            ${chip('Drawing and canvas', 'primary')}
            ${chip('Blocks play', 'danger')}
          </div>
          ${btn.secondary('Copy for triage', { iconL: icon.copy(15) })}
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1.6fr 1fr; gap: 12px; align-items: start">
        <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}; display: grid; gap: 12px">
          <div>
            <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 16px; color: ${T.ink}; margin-bottom: 8px">What happened</h2>
            <p style="font-size: 13.5px; color: ${T.muted}; font-weight: 600; line-height: 1.6">Round 2, everyone had guessed the lighthouse but the ring timer kept running to zero before the results card appeared. Happened twice in the same room.</p>
          </div>
          <div>
            <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 16px; color: ${T.ink}; margin-bottom: 8px">Client errors at the time</h2>
            ${consoleBlock}
            <p style="font-size: 12px; color: ${T.faint}; font-weight: 700; margin-top: 9px; line-height: 1.5">Collected by the reporter's browser and sent with the report. Evidence supplied by a player, not a fact the server checked.</p>
          </div>
        </section>

        <aside style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px">
            <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 16px; color: ${T.ink}">Screenshot</h2>
            <span style="margin-left: auto">${chip('184 KB', 'neutral')}</span>
          </div>
          ${shot(268, 166)}
          <div style="display: flex; align-items: center; gap: 8px; margin-top: 10px">
            ${btn.ghost('Open full size', { iconL: icon.eye(14), style: 'min-height: 34px; padding: 6px 8px; font-size: 13px' })}
          </div>
          <p style="font-size: 11.5px; color: ${T.faint}; font-weight: 700; margin-top: 6px; line-height: 1.5">Erased when this report is decided — the row stays, the pixels do not.</p>
        </aside>
      </div>

      <!-- Diagnostics across the width, not down a column: nine short facts in
           a narrow aside became a very tall list, and the user agent wrapped
           into a paragraph. Below the report itself, because what the player
           wrote and photographed is the case; the machine detail is what you
           turn to once you know what you are looking for. -->
      <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}">
        <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 16px; color: ${T.ink}; margin-bottom: 10px">Diagnostics</h2>
        <div style="display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; overflow: hidden">
          ${diagCell('Build', 'a299f80', { isMono: true })}
          ${diagCell('Page', '/room/BQ7F2K', { isMono: true })}
          ${diagCell('Room', 'BQ7F2K · round 2 of 3')}
          ${diagCell('Screen', '1440 × 900 · 2×')}
          ${diagCell('Connection', 'connected · 1 reconnect this visit')}
          ${diagCell('Seat', 'Guessing')}
          ${diagCell('Account', 'Guest')}
          ${diagCell('Clock skew', '0.9s')}
          ${diagCell('Browser', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.280 Safari/537.36', { wide: true, isMono: true })}
        </div>
        <!-- Full width, because these are long flat lists: opening one in a
             sidebar was the same problem again. -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px">
          ${moreContext('Everything the server saw')}
          ${moreContext('Everything the client reported')}
        </div>
      </section>

      <details style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px 18px; box-shadow: ${T.shadow}">
        <summary class="plain" style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 800; color: ${T.ink}">
          <span style="display: inline-flex; color: ${T.faint}">${icon.chevD(14)}</span>What “Copy for triage” puts on the clipboard
          <span style="margin-left: auto">${chip('Markdown · 1.1 KB', 'neutral')}</span>
        </summary>
        <div style="margin-top: 10px; background: ${T.well}; border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 12px 14px; ${mono()}; font-size: 11.5px; line-height: 1.55; color: ${T.muted}; white-space: pre-wrap">${TRIAGE_TEXT}</div>
        <p style="font-size: 12px; color: ${T.faint}; font-weight: 700; margin-top: 9px; line-height: 1.5">Stable headings, one fact per line, ids unabbreviated. Pastes readably into an issue and parses cleanly for a model asked to reproduce it.</p>
      </details>

      <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">Resolution note
        <textarea placeholder="What you found, in one line — required to decide" style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; font-family: ${T.body}; font-size: 13.5px; padding: 10px 12px; height: 72px; resize: vertical; width: 100%; color: ${T.ink}"></textarea>
        <span style="font-size: 12px; color: ${T.faint}; font-weight: 700">Kept in the append-only audit ledger. Deciding is one-way — a report gets one resolution, and its screenshot is erased.</span>
      </label>

      <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px">
        ${btn.ghost('Back to operations', { iconL: icon.back(14) })}
        <div style="display: flex; align-items: center; gap: 8px">
          ${btn.ghost('Dismiss')}
          ${btn.success('Resolve', { iconL: icon.check(15) })}
        </div>
      </div>
    </main>
  </div>
</div>`;
