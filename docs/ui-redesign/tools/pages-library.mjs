// Library, profile and operator artboards.
import { T, P, icon, avatar, pname, btn, chip, sectionLabel, segmented, selectBox, input } from './ui.mjs';

const backBar = (label = 'Back to lobby') => `
<div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px">
  ${btn.ghost(label, { iconL: icon.back(15), style: 'padding-left: 0' })}
  <button type="button" style="display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: 5px 14px 5px 5px; min-height: 44px; font-family: ${T.body}; box-shadow: ${T.shadow}">
    ${avatar(P.marta, 30)}
    <span style="font-weight: 800; font-size: 14px; color: ${T.ink}">Marta</span>
  </button>
</div>`;

// ------------------------------------------------------------- Prompt stats
const diffMeter = (pct, label, color) => `
<span style="display: inline-flex; align-items: center; gap: 9px; justify-content: flex-end">
  <span style="font-size: 13px; font-weight: 700; color: ${T.muted}; white-space: nowrap">${label}</span>
  <span aria-hidden="true" style="display: inline-block; width: 64px; height: 7px; border-radius: 999px; background: ${T.line}; overflow: hidden"><span style="display: block; width: ${pct}%; height: 100%; background: ${color}"></span></span>
</span>`;

const statRow = (prompt, meter, guessed, picked, drawn, dim = false) => `
<tr${dim ? ` style="opacity: 0.55"` : ''}>
  <th scope="row" style="border-bottom: 1.5px solid ${T.line}; padding: 11px 12px; text-align: left; color: ${T.ink}; font-weight: 800; font-size: 14px">${prompt}</th>
  <td style="border-bottom: 1.5px solid ${T.line}; padding: 11px 12px; text-align: right">${meter}</td>
  <td style="border-bottom: 1.5px solid ${T.line}; padding: 11px 12px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; color: ${T.muted}">${guessed}</td>
  <td style="border-bottom: 1.5px solid ${T.line}; padding: 11px 12px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; color: ${T.muted}">${picked}</td>
  <td style="border-bottom: 1.5px solid ${T.line}; padding: 11px 12px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; color: ${T.muted}">${drawn}</td>
</tr>`;

const th = (label) => `<th scope="col" style="border-bottom: 1.5px solid ${T.lineStrong}; padding: 9px 12px; text-align: right; color: ${T.faint}; font-size: 11.5px; letter-spacing: 0.06em; text-transform: uppercase">${label}</th>`;

export const PromptStatsPage = `
<div style="width: 920px; min-height: 980px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <header style="margin-bottom: 16px">
    ${sectionLabel('Server-wide')}
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 28px; color: ${T.ink}; margin-top: 4px">Prompt stats</h1>
    <p style="color: ${T.muted}; font-size: 14px; margin-top: 6px">Every prompt in the list, and how it has actually played across finished games on this server.</p>
  </header>

  <div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px 16px; box-shadow: ${T.shadow}; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px">
    ${selectBox('Standard English · 432')}
    ${selectBox('Hardest first')}
    ${selectBox('All time')}
    ${selectBox('All scoring')}
    ${selectBox('All hints')}
    <div style="flex: 1 1 180px; display: flex; align-items: center; gap: 9px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 9px 13px; min-height: 42px">
      <span style="display: inline-flex; color: ${T.faint}">${icon.search(15)}</span>
      <input type="search" placeholder="Find a prompt" style="flex: 1; min-width: 0; border: 0; outline: none; background: transparent; font-family: ${T.body}; font-size: 14px; color: ${T.ink}">
    </div>
  </div>

  <p style="color: ${T.muted}; font-size: 13.5px; margin-bottom: 12px">389 ranked · <span style="color: ${T.faint}">43 unranked — fewer than 12 guessers have faced them yet</span></p>

  <div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; box-shadow: ${T.shadow}; overflow: hidden">
    <table style="border-collapse: collapse; width: 100%">
      <thead>
        <tr>
          <th scope="col" style="border-bottom: 1.5px solid ${T.lineStrong}; padding: 9px 12px; text-align: left; color: ${T.faint}; font-size: 11.5px; letter-spacing: 0.06em; text-transform: uppercase">Prompt</th>
          ${th('How it goes')}${th('Guessed')}${th('Picked')}${th('Drawn')}
        </tr>
      </thead>
      <tbody>
        ${statRow('bow and arrow', diffMeter(11, 'Rarely guessed', T.danger), '11%', '24%', '38')}
        ${statRow('roller coaster', diffMeter(22, 'Often missed', T.warm), '22%', '41%', '67')}
        ${statRow('windmill', diffMeter(48, 'Even odds', '#C9A227'), '48%', '57%', '91')}
        ${statRow('lighthouse', diffMeter(71, 'Usually guessed', T.success), '71%', '66%', '124')}
        ${statRow('banana', diffMeter(94, 'Almost a gimme', T.success), '94%', '78%', '203')}
        ${statRow('sextant', `<span style="font-size: 13px; font-weight: 700; color: ${T.faint}">Not played enough</span>`, '—', '—', '3', true)}
        ${statRow('funicular', `<span style="font-size: 13px; font-weight: 700; color: ${T.faint}">Not played enough</span>`, '—', '—', '1', true)}
      </tbody>
    </table>
  </div>
</div>`;

// --------------------------------------------------------- My prompt lists
const listNav = (name, meta, active, badge = '') => `
<button type="button" style="display: flex; flex-direction: column; gap: 4px; text-align: left; background: ${active ? T.primarySoft : T.card}; border: 1.5px solid ${active ? T.primary : T.line}; border-radius: ${T.radiusSm}; padding: 12px 15px; font-family: ${T.body}; min-height: 44px">
  <span style="display: flex; align-items: center; gap: 8px; font-size: 14.5px; font-weight: 800; color: ${active ? T.primaryInk : T.ink}">${name}${badge}</span>
  <span style="font-size: 12px; color: ${T.muted}; font-weight: 700">${meta}</span>
</button>`;

const promptChip = (text, review = false) => review
  ? `<li style="display: flex; align-items: center; gap: 4px; background: ${T.warningSoft}; border: 1px solid ${T.warningEdge}; border-radius: 999px; padding: 4px 4px 4px 13px; font-size: 13.5px; max-width: 100%">
      <span style="overflow-wrap: anywhere; color: ${T.ink}">${text}</span>
      ${chip('under review', 'warning')}
      <button type="button" aria-label="Remove ${text}" style="display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; background: none; border: 0; border-radius: 999px; color: ${T.faint}">${icon.x(13)}</button>
    </li>`
  : `<li style="display: flex; align-items: center; gap: 4px; background: ${T.well}; border: 1px solid ${T.line}; border-radius: 999px; padding: 4px 4px 4px 13px; font-size: 13.5px; max-width: 100%">
      <span style="overflow-wrap: anywhere; color: ${T.ink}">${text}</span>
      <button type="button" aria-label="Remove ${text}" style="display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; background: none; border: 0; border-radius: 999px; color: ${T.faint}">${icon.x(13)}</button>
    </li>`;

export const MyPromptListsPage = `
<div style="width: 1020px; min-height: 1080px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 22px 24px; box-shadow: ${T.shadow}">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 22px">
      <div>
        ${sectionLabel('Your library')}
        <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 28px; color: ${T.ink}; margin-top: 4px">Reusable prompt lists</h1>
      </div>
      ${btn.primary('New list', { iconL: icon.plus(15) })}
    </div>

    <div style="display: grid; gap: 24px; grid-template-columns: 250px minmax(0, 1fr)">
      <aside style="display: grid; gap: 8px; align-content: start">
        ${listNav('Studio in-jokes', '64 prompts · private', true, chip('1 under review', 'warning'))}
        ${listNav('Kitchen things', '120 prompts · unlisted', false)}
        ${listNav('Hard mode', '38 prompts · private', false)}
        <p style="color: ${T.faint}; font-size: 12px; font-weight: 700; padding: 4px 6px">3 of 25 lists used</p>
      </aside>

      <form style="display: grid; gap: 16px">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
          <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">Name
            ${input({ value: 'Studio in-jokes' })}
          </label>
          <label style="display: grid; gap: 6px; font-size: 13.5px; font-weight: 800; color: ${T.ink}">Description
            ${input({ value: 'Things only this team would draw' })}
          </label>
        </div>

        <div style="display: flex; align-items: flex-end; gap: 24px; flex-wrap: wrap">
          <div style="display: grid; gap: 6px">
            <span style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">Language</span>
            <span style="display: inline-flex; align-items: center; gap: 8px; color: ${T.muted}; font-size: 14px; font-weight: 700; min-height: 42px">English ${chip('locked after creation')}</span>
          </div>
          <div style="display: grid; gap: 6px">
            <span style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">Visibility</span>
            ${segmented(['Private', 'Unlisted'], 0, { w: 92 })}
          </div>
          <p style="color: ${T.faint}; font-size: 12.5px; font-weight: 700; max-width: 300px; padding-bottom: 10px">Unlisted lists get a share code — anyone holding it can use the list in a room.</p>
        </div>

        <div style="border-top: 1.5px solid ${T.line}; display: grid; gap: 10px; padding-top: 16px">
          <span style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">Add prompts</span>
          <textarea placeholder="One prompt per line, or separated by commas" style="border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; font-family: ${T.body}; font-size: 14px; padding: 10px 12px; height: 100px; resize: vertical; width: 100%; color: ${T.ink}"></textarea>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
            <span style="display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: ${T.muted}">
              <span aria-hidden="true" style="display: inline-block; width: 90px; height: 7px; border-radius: 999px; background: ${T.line}; overflow: hidden"><span style="display: block; width: 13%; height: 100%; background: ${T.primary}"></span></span>
              64 of 500 prompts
              <span style="color: ${T.warning}">· 2 duplicates skipped last paste</span>
            </span>
            ${btn.secondary('Add to list')}
          </div>
        </div>

        <div style="border-top: 1.5px solid ${T.line}; display: grid; gap: 12px; padding-top: 16px">
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
            <h3 style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">In this list</h3>
            <div style="flex: 1 1 200px; display: flex; align-items: center; gap: 8px; background: ${T.well}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; padding: 8px 12px">
              <span style="display: inline-flex; color: ${T.faint}">${icon.search(14)}</span>
              <input type="search" placeholder="Search prompts" style="flex: 1; min-width: 0; border: 0; outline: none; background: transparent; font-family: ${T.body}; font-size: 13.5px; color: ${T.ink}">
            </div>
            <button type="button" aria-pressed="false" style="background: ${T.card}; border: 1.5px solid ${T.warningEdge}; border-radius: 999px; padding: 8px 14px; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; color: ${T.warning}">Needs review · 1</button>
          </div>
          <ul style="display: flex; flex-wrap: wrap; gap: 7px; list-style: none; margin: 0; max-height: 300px; overflow: auto; padding: 0">
            ${promptChip('the good stapler')}
            ${promptChip('friday deploy')}
            ${promptChip('the office plant')}
            ${promptChip('the incident', true)}
            ${promptChip('standup bingo')}
            ${promptChip('the whiteboard nobody erases')}
            ${promptChip('coffee machine queue')}
            ${promptChip('rubber duck')}
          </ul>
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; border-top: 1.5px solid ${T.line}; padding-top: 16px">
          ${btn.dangerGhost('Delete list…', { iconL: icon.trash(14) })}
          ${btn.primary('Save list')}
        </div>
      </form>
    </div>
  </section>
</div>`;

// ------------------------------------------------------------------ Profile
const heroStat = (value, label) => `
<div style="display: flex; flex-direction: column; gap: 3px; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}">
  <span style="font-family: ${T.display}; font-weight: 600; font-size: 27px; color: ${T.ink}; font-variant-numeric: tabular-nums">${value}</span>
  <span style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: ${T.faint}; font-weight: 800">${label}</span>
</div>`;

const smallStat = (value, label) => `
<span style="display: inline-flex; align-items: baseline; gap: 7px; font-size: 13px; color: ${T.muted}; font-weight: 700"><strong style="color: ${T.ink}; font-weight: 800; font-variant-numeric: tabular-nums; font-size: 15px">${value}</strong>${label}</span>`;

const placeBadge = (place) => {
  const styles = {
    1: ['rgba(227, 160, 8, 0.16)', T.gold],
    2: ['rgba(122, 134, 154, 0.16)', T.silver],
    3: ['rgba(176, 112, 60, 0.16)', T.bronze],
  };
  const s = styles[place] ?? [T.well, T.muted];
  return `<span style="display: inline-flex; align-items: center; justify-content: center; min-width: 40px; height: 40px; border-radius: 12px; background: ${s[0]}; color: ${s[1]}; font-weight: 800; font-size: 14px">${place ? '#' + place : '—'}</span>`;
};

const historyHead = (name, meta, place, pts, open) => `
<button type="button" style="display: flex; align-items: center; gap: 14px; width: 100%; background: transparent; border: none; padding: 14px 16px; text-align: left; color: inherit; font-family: ${T.body}">
  ${placeBadge(place)}
  <span style="display: flex; flex-direction: column; gap: 2px; flex: 1 1 auto; min-width: 0">
    <span style="font-weight: 800; font-size: 15px; color: ${T.ink}">${name}</span>
    <span style="font-size: 12.5px; color: ${T.muted}; font-weight: 700">${meta}</span>
  </span>
  <span style="font-size: 13.5px; color: ${T.muted}; font-weight: 800; font-variant-numeric: tabular-nums">${pts}</span>
  <span aria-hidden="true" style="display: inline-flex; color: ${T.faint}">${open ? icon.chevD(16) : icon.chevR(16)}</span>
</button>`;

const turnCell = (v, opts = '') => `<td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid ${T.line}; white-space: nowrap; font-size: 13px; color: ${T.muted}; font-weight: 600${opts}">${v}</td>`;

export const ProfilePage = `
<div style="width: 920px; min-height: 1220px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <header style="display: flex; align-items: center; gap: 18px; margin-bottom: 20px">
    ${avatar(P.marta, 64)}
    <div>
      <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 28px">${pname(P.marta)}</h1>
      <p style="font-size: 13.5px; color: ${T.muted}; font-weight: 700; margin-top: 4px">Registered player · joined 12 Mar 2026</p>
    </div>
  </header>

  <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 10px">
    ${heroStat('48', 'Games played')}
    ${heroStat('14', 'Games won')}
    ${heroStat('29%', 'Win rate')}
    ${heroStat('874', 'Average score')}
  </div>
  <div style="display: flex; flex-wrap: wrap; gap: 8px 28px; padding: 6px 4px 0; margin-bottom: 22px">
    ${smallStat('193', 'turns played')}
    ${smallStat('121', 'prompts guessed')}
    ${smallStat('52', 'drawings made')}
    ${smallStat('41,952', 'total score')}
  </div>

  <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 20px 22px; box-shadow: ${T.shadow}">
    <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px">
      <h2 style="font-family: ${T.display}; font-weight: 600; font-size: 20px; color: ${T.ink}">Game history</h2>
      <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 800; color: ${T.muted}">
        <input type="checkbox">
        Include games that fell apart
      </label>
    </div>

    <ul style="list-style: none; margin: 0 0 14px; padding: 0; display: grid; gap: 10px">
      <li style="border: 1.5px solid ${T.line}; border-radius: ${T.radius}; background: ${T.card}; overflow: hidden">
        ${historyHead('Coffee break doodles', '24 Aug 2026, 18:42 · 3 rounds · 5 players', 3, '980 pts', true)}
        <div style="border-top: 1.5px solid ${T.line}; padding: 14px 16px; background: ${T.well}">
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px">
            ${chip('Default scoring v3')}${chip('Timed hints')}${chip('90s draws')}${chip('Curated prompts')}
          </div>
          <ol style="list-style: none; margin: 0 0 16px; padding: 0; display: grid; gap: 3px; font-size: 13.5px">
            ${[[1, P.bruno, 1420], [2, P.yuki, 1180], [3, P.marta, 980], [4, P.sparrow, 520], [5, P.ines, 310]].map(([r, p, s]) => `
            <li style="display: flex; align-items: center; gap: 9px${p === P.marta ? `; background: ${T.primarySoft}; border-radius: 8px; padding: 3px 6px; margin: 0 -6px` : ''}">
              <span style="color: ${T.faint}; font-weight: 800; font-variant-numeric: tabular-nums; min-width: 2em">#${r}</span>
              ${avatar(p, 22)}${pname(p)}
              <span style="margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 800; color: ${T.muted}">${s}</span>
            </li>`).join('')}
          </ol>
          <div style="width: 100%; overflow-x: auto; background: ${T.card}; border: 1px solid ${T.line}; border-radius: ${T.radiusSm}">
            <table style="width: 100%; border-collapse: collapse">
              <thead>
                <tr>
                  ${['Round', 'Prompt', 'Drawn by', 'Drawing', 'Guesser outcomes'].map((h) => `<th scope="col" style="padding: 8px 12px; text-align: left; border-bottom: 1.5px solid ${T.line}; white-space: nowrap; color: ${T.faint}; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em">${h}</th>`).join('')}
                </tr>
              </thead>
              <tbody>
                <tr>
                  ${turnCell('2')}${turnCell(`<strong style="color: ${T.ink}; font-weight: 800">lighthouse</strong>`)}${turnCell(pname(P.marta))}
                  ${turnCell(`<button type="button" style="display: inline-flex; align-items: center; gap: 6px; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 8px; color: ${T.primary}; font-family: inherit; font-size: 12.5px; font-weight: 800; padding: 5px 11px">${icon.eye(13)}View</button>`)}
                  ${turnCell(`${pname(P.bruno)} <span style="color: ${T.success}">✓161</span> · ${pname(P.sparrow)} <span style="color: ${T.success}">✓153</span> · ${pname(P.yuki)} <span style="color: ${T.success}">✓141</span> · ${pname(P.ines)} <span style="color: ${T.faint}">away</span>`)}
                </tr>
                <tr>
                  ${turnCell('2')}${turnCell(`<strong style="color: ${T.ink}; font-weight: 800">roller coaster</strong>`)}${turnCell(pname(P.bruno))}
                  ${turnCell(`<button type="button" style="display: inline-flex; align-items: center; gap: 6px; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: 8px; color: ${T.primary}; font-family: inherit; font-size: 12.5px; font-weight: 800; padding: 5px 11px">${icon.eye(13)}View</button>`)}
                  ${turnCell(`${pname(P.yuki)} <span style="color: ${T.success}">✓148</span> · ${pname(P.marta)} <span style="color: ${T.faint}">3 wrong</span> · ${pname(P.sparrow)} <span style="color: ${T.faint}">no attempt</span>`)}
                </tr>
                <tr>
                  ${turnCell('3')}${turnCell(`<strong style="color: ${T.ink}; font-weight: 800">bow and arrow</strong>`)}${turnCell(pname(P.yuki))}
                  ${turnCell(`<span style="color: ${T.faint}">not kept</span>`)}
                  ${turnCell(`${pname(P.marta)} <span style="color: ${T.success}">✓174</span> · ${pname(P.bruno)} <span style="color: ${T.faint}">2 wrong</span>`)}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </li>

      <li style="border: 1.5px solid ${T.line}; border-radius: ${T.radius}; background: ${T.card}; overflow: hidden">
        ${historyHead('Slow and steady', '23 Aug 2026, 21:07 · 4 rounds · 6 players', 1, '1640 pts', false)}
      </li>
      <li style="border: 1.5px solid ${T.line}; border-radius: ${T.radius}; background: ${T.card}; overflow: hidden">
        ${historyHead('Chaos hour', `21 Aug 2026, 19:30 · 5 rounds · 8 players · <span style="color: ${T.warning}">cut short</span>`, null, '610 pts', false)}
      </li>
    </ul>

    ${btn.secondary('Load 20 more')}
  </section>
</div>`;

// ----------------------------------------------------------------- AdminOps
const adminTabs = (tabs, active) => `
<nav style="border-bottom: 1.5px solid ${T.line}; display: flex; gap: 4px; margin-bottom: 22px">
  ${tabs.map((t, i) => i === active
    ? `<button type="button" style="background: none; border: 0; border-bottom: 2.5px solid ${T.primary}; color: ${T.ink}; font-family: ${T.body}; font-size: 14px; font-weight: 800; padding: 10px 14px">${t}</button>`
    : `<button type="button" style="background: none; border: 0; border-bottom: 2.5px solid transparent; color: ${T.muted}; font-family: ${T.body}; font-size: 14px; font-weight: 700; padding: 10px 14px">${t}</button>`
  ).join('')}
</nav>`;

const liveStat = (label, value, sub, alert = false) => `
<div style="background: ${T.card}; border: 1.5px solid ${alert ? T.warm : T.line}; border-radius: ${T.radius}; display: flex; flex-direction: column; gap: 3px; padding: 14px 16px; box-shadow: ${T.shadow}">
  <span style="font-size: 11.5px; letter-spacing: 0.06em; color: ${T.faint}; font-weight: 800; text-transform: uppercase">${label}</span>
  <span style="font-family: ${T.display}; font-weight: 600; font-size: 30px; font-variant-numeric: tabular-nums; color: ${alert ? T.warmInk : T.ink}">${value}</span>
  <span style="font-size: 12px; color: ${T.faint}; font-weight: 700">${sub}</span>
</div>`;

const trendCard = (label, value, points, alert = false) => `
<div style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 14px 16px; box-shadow: ${T.shadow}">
  <h2 style="font-size: 12.5px; margin-bottom: 6px; color: ${T.muted}; font-weight: 800">${label}</h2>
  <div style="display: flex; align-items: baseline; gap: 6px">
    <span style="font-size: 21px; font-variant-numeric: tabular-nums; font-weight: 800; color: ${T.ink}">${value}</span>
    <span style="font-size: 12px; color: ${T.faint}; font-weight: 700">today</span>
  </div>
  <svg viewBox="0 0 160 36" role="img" aria-label="${label} over the retained window" style="display: block; height: auto; margin-top: 8px; max-width: 100%; width: 100%">
    <polyline points="${points}" fill="none" style="stroke: ${alert ? T.warm : T.primary}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.8"/>
  </svg>
</div>`;

export const AdminOpsPage = `
<div style="width: 1100px; min-height: 840px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <header>
    ${sectionLabel('Administrators only')}
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 26px; color: ${T.ink}; margin: 4px 0 14px">Server operations</h1>
    ${adminTabs(['Overview', 'Activity', 'Audit ledger'], 0)}
  </header>

  <section style="display: grid; gap: 12px; grid-template-columns: repeat(4, 1fr); margin-bottom: 20px">
    ${liveStat('Rooms', '17', 'peak 41 · resets on restart')}
    ${liveStat('Players', '94', 'peak 233')}
    ${liveStat('Games running', '11', 'peak 26')}
    ${liveStat('Abandoned', '28%', '142 of 507 this window', true)}
  </section>

  <section style="display: grid; gap: 12px; grid-template-columns: repeat(5, 1fr); margin-bottom: 20px">
    ${trendCard('Rooms opened', '38', '0,28 20,24 40,30 60,18 80,20 100,12 120,16 140,8 160,10')}
    ${trendCard('Games finished', '21', '0,30 20,26 40,22 60,24 80,16 100,18 120,12 140,14 160,11')}
    ${trendCard('Games abandoned', '9', '0,20 20,26 40,18 60,28 80,22 100,26 120,20 140,24 160,19', true)}
    ${trendCard('Disconnects', '147', '0,24 20,14 40,20 60,10 80,18 100,8 120,14 140,6 160,12')}
    ${trendCard('Timer overruns', '0', '0,34 20,34 40,30 60,34 80,34 100,32 120,34 140,34 160,34')}
  </section>

  <section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 16px 18px; box-shadow: ${T.shadow}; display: flex; align-items: center; gap: 14px">
    ${chip('Recorder healthy', 'success')}
    <p style="font-size: 13.5px; color: ${T.muted}; font-weight: 700">184,291 observations stored · 12 waiting to be written · nothing dropped</p>
  </section>
</div>`;

// --------------------------------------------------------------- Moderation
const reportCard = (reason, reasonKind, when, body, evidence, actions) => `
<li style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: 18px 20px; box-shadow: ${T.shadow}">
  <div style="display: flex; align-items: center; gap: 10px; justify-content: space-between; margin-bottom: 8px">
    ${chip(reason, reasonKind)}
    <span style="font-size: 12.5px; font-variant-numeric: tabular-nums; color: ${T.faint}; font-weight: 700">${when}</span>
  </div>
  <p style="font-size: 14.5px; color: ${T.ink}; font-weight: 600">${body}</p>
  ${evidence}
  ${actions}
</li>`;

const evidenceBlock = (lines) => `
<div style="background: ${T.well}; border: 1px solid ${T.line}; border-radius: ${T.radiusSm}; margin-top: 12px; padding: 12px 14px">
  ${sectionLabel('Pinned messages — as the reporter received them')}
  <ul style="list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 5px; font-size: 13.5px">
    ${lines.map((l) => `<li style="color: ${T.muted}"><strong style="color: ${T.ink}; font-weight: 800">Nightjar-88:</strong> ${l}</li>`).join('')}
  </ul>
</div>`;

const actionBar = `
<div style="display: flex; align-items: center; gap: 8px; margin-top: 14px; flex-wrap: wrap">
  <input aria-label="Resolution note" placeholder="Why, in one line (required to decide)" style="flex: 1 1 260px; background: ${T.card}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 13.5px; color: ${T.ink}; min-height: 42px">
  ${btn.ghost('Dismiss')}
  ${btn.secondary('Resolve')}
  <span style="display: inline-flex; align-items: center; gap: 6px">
    <button type="button" style="display: inline-flex; align-items: center; gap: 7px; background: ${T.card}; border: 1.5px solid ${T.danger}; border-radius: ${T.radiusSm} 0 0 ${T.radiusSm}; color: ${T.danger}; font-family: ${T.body}; font-size: 13.5px; font-weight: 800; padding: 10px 14px; min-height: 42px">Suspend</button><button type="button" style="display: inline-flex; align-items: center; gap: 5px; background: ${T.dangerSoft}; border: 1.5px solid ${T.danger}; border-left: 0; border-radius: 0 ${T.radiusSm} ${T.radiusSm} 0; color: ${T.danger}; font-family: ${T.body}; font-size: 12.5px; font-weight: 800; padding: 10px 10px; min-height: 42px">7 days ${icon.chevD(12)}</button>
  </span>
</div>`;

export const ModerationPage = `
<div style="width: 1100px; min-height: 880px; margin: 0 auto; padding: 26px 24px 48px">
  ${backBar()}
  <header>
    ${sectionLabel('Moderators and administrators')}
    <h1 style="font-family: ${T.display}; font-weight: 600; font-size: 26px; color: ${T.ink}; margin: 4px 0 14px">Moderation</h1>
    ${adminTabs(['Player reports', 'Prompt content', 'Suspensions'], 0)}
  </header>

  <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px">
    ${selectBox('Waiting for review · 2')}
    ${btn.ghost('Refresh', { iconL: icon.rounds(14) })}
  </div>

  <ul style="display: grid; gap: 12px; list-style: none; margin: 0; padding: 0">
    ${reportCard('Harassment', 'danger', '25 Aug 2026, 09:41',
      'Kept naming other players in chat after being asked to stop.',
      evidenceBlock(['nobody wants you in this room', 'leave already', `stop drawing, you are ruining it <em style="color: ${T.faint}"> — author no longer in the room</em>`]),
      actionBar)}
    ${reportCard('Offensive drawing', 'warning', '24 Aug 2026, 22:18',
      'Drew something unrelated to the prompt, twice in a row.',
      '', actionBar)}
    ${reportCard('Spam', 'neutral', '24 Aug 2026, 15:02',
      'Pasted the same link into four different rooms.',
      `<p style="display: flex; align-items: center; gap: 8px; font-size: 13px; margin-top: 10px; color: ${T.muted}; font-weight: 700">${chip('Resolved', 'success')} Suspended 7 days — third report this week.</p>`, '')}
  </ul>
</div>`;
