// Generates the clickable mockup explorer: every screen embedded in one
// self-contained page, with wired navigation between screens, a game-flow
// stepper, hotspot highlighting, and the light/dark theme toggle.
// Run from docs/ui-mockups:  node tools/build-explorer.mjs
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { themeStyles } from './ui.mjs';
import { SCREENS } from './screens.mjs';

const out = join(dirname(fileURLToPath(import.meta.url)), '..');

// Click wiring: on each screen, a control whose visible text or aria-label
// contains `match` (checked in order, case-insensitive) navigates to `to`.
const ROUTES = {
  Main: [
    ['Create a room', 'CreateRoom'], ['Quick start', 'WaitingRoom'],
    ['Join in progress', 'Guessing'], ['Join', 'WaitingRoom'], ['Spectate', 'WaitingRoom'],
    ['Prompt stats', 'PromptStats'], ['My prompt lists', 'MyPromptLists'], ['Profile', 'Profile'], ['Settings', 'Settings'], ['Marta', 'Profile'],
  ],
  Settings: [['Done', 'Main'], ['Back to lobby', 'Main'], ['Manage account', 'Profile']],
  CreateRoom: [['Back to lobby', 'Main'], ['Create room', 'WaitingRoom'], ['Marta', 'Profile']],
  AccountRecovery: [['Back to the lobby', 'Main'], ['Send a reset link', 'Main']],
  NotFound: [['Back to lobby', 'Main']],
  Crash: [['Back to lobby', 'Main']],
  WaitingRoom: [['Start game', 'PromptChoice'], ['Edit settings', 'CreateRoom'], ['Settings', 'Settings'], ['Leave', 'Main']],
  PromptChoice: [['lighthouse', 'Drawing'], ['roller coaster', 'Drawing'], ['windmill', 'Drawing'], ['Settings', 'Settings'], ['Leave', 'Main']],
  Drawing: [['Settings', 'Settings'], ['Leave', 'Main']],
  Guessing: [['Send', 'TurnResults'], ['Settings', 'Settings'], ['Leave', 'Main']],
  TurnResults: [['Settings', 'Settings'], ['Leave', 'Main']],
  GameOver: [['Highlights', 'Highlights'], ['Continue', 'WaitingRoom'], ['Stay here', 'GameOver'], ['Settings', 'Settings'], ['Leave', 'Main']],
  Highlights: [['Back to results', 'GameOver'], ['Close highlights', 'GameOver'], ['Settings', 'Settings'], ['Leave', 'Main']],
  PromptStats: [['Back to lobby', 'Main'], ['Marta', 'Profile']],
  MyPromptLists: [['Back to lobby', 'Main'], ['Marta', 'Profile']],
  Profile: [['Back to lobby', 'Main']],
  AdminOps: [['Back to lobby', 'Main'], ['Tuning', 'AdminOpsTuning'], ['Audit ledger', 'AdminOpsAudit']],
  AdminOpsTuning: [['Back to lobby', 'Main'], ['Overview', 'AdminOps'], ['Audit ledger', 'AdminOpsAudit']],
  AdminOpsAudit: [['Back to lobby', 'Main'], ['Overview', 'AdminOps'], ['Tuning', 'AdminOpsTuning']],
  Moderation: [['Back to operations', 'AdminOps'], ['Back to lobby', 'Main']],
  BugReportMenu: [['Report a bug', 'BugReportDialog']],
  BugReportDialog: [['Cancel', 'Main'], ['Send report', 'Main']],
  BugReports: [['Back to operations', 'AdminOps'], ['Back to lobby', 'Main']],
};

// The happy path a game actually follows, for the ◀ ▶ flow stepper.
const FLOW = ['Main', 'CreateRoom', 'WaitingRoom', 'PromptChoice', 'Drawing', 'Guessing', 'TurnResults', 'GameOver', 'Highlights'];

const groups = [...new Set(SCREENS.map((s) => s.group))];

const meta = Object.fromEntries(SCREENS.map((s) => [s.name, { title: s.title, w: s.w, h: s.h, group: s.group }]));

const html = `<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sketchy Explorer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600&family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700;6..12,800&display=swap">
<style>
  * { box-sizing: border-box; }
${themeStyles}
  html, body { height: 100%; }
  body { margin: 0; background: var(--paper); color: var(--ink); font-family: 'Nunito Sans', 'Segoe UI', system-ui, sans-serif; display: grid; grid-template-rows: auto 1fr; grid-template-columns: 232px 1fr; grid-template-areas: 'bar bar' 'rail stage'; }
  h1, h2, p, ul { margin: 0; }
  button { cursor: pointer; font-family: inherit; }

  .bar { grid-area: bar; display: flex; align-items: center; gap: 14px; padding: 10px 16px; border-bottom: 1.5px solid var(--line); background: var(--card); }
  .brand { font-family: 'Fredoka', 'Trebuchet MS', system-ui, sans-serif; font-weight: 600; font-size: 19px; color: var(--ink); }
  .brand em { font-style: normal; color: var(--primary); }
  .crumb { font-size: 13.5px; font-weight: 800; color: var(--muted); }
  .spacer { flex: 1; }
  .bar button { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 7px 13px; border-radius: 10px; border: 1.5px solid var(--lineStrong); background: var(--card); color: var(--ink); font-size: 13px; font-weight: 800; }
  .bar button[aria-pressed="true"] { background: var(--primarySoft); border-color: var(--primary); color: var(--primaryInk); }
  .bar button:disabled { opacity: 0.4; cursor: default; }
  .bar button:focus-visible, .rail button:focus-visible { outline: 3px solid var(--primary); outline-offset: 2px; }

  .rail { grid-area: rail; overflow-y: auto; padding: 14px 12px 24px; border-right: 1.5px solid var(--line); display: grid; gap: 16px; align-content: start; background: var(--paper); }
  .rail h2 { font-size: 11px; font-weight: 800; letter-spacing: 0.09em; text-transform: uppercase; color: var(--faint); padding: 0 6px; margin-bottom: 6px; }
  .rail button { display: block; width: 100%; text-align: left; padding: 9px 12px; border-radius: 10px; border: 1.5px solid transparent; background: transparent; color: var(--muted); font-size: 13.5px; font-weight: 700; }
  .rail button[aria-current="true"] { background: var(--primarySoft); border-color: var(--primary); color: var(--primaryInk); font-weight: 800; }

  .stage { grid-area: stage; overflow: auto; padding: 22px; }
  .frame-wrap { margin: 0 auto; position: relative; }
  .frame { transform-origin: top left; background: var(--paper); border: 1.5px solid var(--lineStrong); border-radius: 14px; overflow: hidden; box-shadow: 0 12px 34px rgba(20, 16, 10, 0.14); }
  .frame > .screen-root { font-family: 'Nunito Sans', 'Segoe UI', system-ui, sans-serif; color: var(--ink); }

  .hotspots .hot { outline: 3px dashed var(--warm) !important; outline-offset: 3px; }
  #toast { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%) translateY(8px); background: var(--ink); color: var(--paper); font-size: 13px; font-weight: 800; padding: 10px 16px; border-radius: 999px; opacity: 0; pointer-events: none; transition: opacity 0.18s, transform 0.18s; z-index: 10; }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .hint { text-align: center; font-size: 12px; font-weight: 700; color: var(--faint); padding: 12px 0 2px; }

  @media (max-width: 860px) {
    body { grid-template-columns: 1fr; grid-template-areas: 'bar' 'stage'; }
    .rail { display: none; }
  }
</style>
</head>
<body>
<header class="bar">
  <span class="brand">Sketchy <em>explorer</em></span>
  <span class="crumb" id="crumb"></span>
  <span class="spacer"></span>
  <button id="prev" title="Previous step in the game flow (←)">◀ Back</button>
  <button id="next" title="Next step in the game flow (→)">Play through ▶</button>
  <button id="hotspots-btn" aria-pressed="false" title="Outline the controls that navigate">Hotspots</button>
  <button id="theme-btn" aria-pressed="false" title="Toggle dark theme">Dark</button>
</header>

<nav class="rail" id="rail" aria-label="Screens"></nav>

<main class="stage">
  <div class="frame-wrap" id="frame-wrap">
    <div class="frame" id="frame"><div class="screen-root" id="screen-root"></div></div>
    <p class="hint">Click the interface to move between screens — Hotspots shows what's wired. ← → step through a whole game.</p>
  </div>
  <div id="toast" role="status"></div>
</main>

${SCREENS.map((s) => `<template id="tpl-${s.name}">${s.page}</template>`).join('\n')}

<script>
  const META = ${JSON.stringify(meta)};
  const ROUTES = ${JSON.stringify(ROUTES)};
  const FLOW = ${JSON.stringify(FLOW)};
  const GROUPS = ${JSON.stringify(groups.map((g) => [g, SCREENS.filter((s) => s.group === g).map((s) => s.name)]))};

  const rail = document.getElementById('rail');
  const root = document.getElementById('screen-root');
  const frame = document.getElementById('frame');
  const wrap = document.getElementById('frame-wrap');
  const crumb = document.getElementById('crumb');
  const toast = document.getElementById('toast');
  let current = null;
  let toastTimer = 0;

  for (const [group, names] of GROUPS) {
    const section = document.createElement('div');
    const h = document.createElement('h2');
    h.textContent = group;
    section.appendChild(h);
    for (const name of names) {
      const b = document.createElement('button');
      b.textContent = META[name].title;
      b.dataset.screen = name;
      b.addEventListener('click', () => go(name));
      section.appendChild(b);
    }
    rail.appendChild(section);
  }

  function showToast(text) {
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
  }

  function markHotspots() {
    for (const el of root.querySelectorAll('.hot')) el.classList.remove('hot');
    for (const [match] of ROUTES[current] ?? []) {
      const el = findTarget(match);
      if (el) el.classList.add('hot');
    }
  }

  function findTarget(match) {
    const m = match.toLowerCase();
    for (const el of root.querySelectorAll('button, a')) {
      const text = (el.textContent + ' ' + (el.getAttribute('aria-label') ?? '')).toLowerCase();
      if (text.includes(m)) return el;
    }
    return null;
  }

  function routeFor(el) {
    const label = ((el.textContent ?? '') + ' ' + (el.getAttribute('aria-label') ?? '')).toLowerCase();
    for (const [match, to] of ROUTES[current] ?? []) {
      if (label.includes(match.toLowerCase())) return to;
    }
    return null;
  }

  function layout() {
    if (!current) return;
    const { w, h } = META[current];
    const avail = document.querySelector('.stage').clientWidth - 44;
    const s = Math.min(1, avail / w);
    frame.style.width = w + 'px';
    frame.style.transform = 'scale(' + s + ')';
    wrap.style.width = Math.round(w * s) + 'px';
    wrap.style.height = Math.round(h * s) + 60 + 'px';
    frame.style.height = h + 'px';
  }

  function go(name, push = true) {
    if (!META[name]) name = 'Main';
    current = name;
    root.innerHTML = '';
    root.appendChild(document.getElementById('tpl-' + name).content.cloneNode(true));
    const tw = root.querySelector('[data-tab]');
    if (tw) tw.setAttribute('data-tab', 'general');
    crumb.textContent = META[name].title;
    for (const b of rail.querySelectorAll('button')) b.setAttribute('aria-current', String(b.dataset.screen === name));
    const i = FLOW.indexOf(name);
    document.getElementById('prev').disabled = i <= 0;
    document.getElementById('next').disabled = i === -1 || i >= FLOW.length - 1;
    if (push) history.replaceState(null, '', '#' + name);
    layout();
    markHotspots();
    document.querySelector('.stage').scrollTop = 0;
  }

  root.addEventListener('click', (e) => {
    const tabBtn = e.target.closest('[data-pref-tab]');
    if (tabBtn && root.contains(tabBtn)) {
      e.preventDefault();
      const tw = root.querySelector('[data-tab]');
      if (tw) tw.setAttribute('data-tab', tabBtn.dataset.prefTab);
      for (const b of root.querySelectorAll('[data-pref-tab]')) b.setAttribute('aria-current', String(b === tabBtn));
      return;
    }
    const el = e.target.closest('button, a, [role="switch"]');
    if (!el || !root.contains(el)) return;
    e.preventDefault();
    const to = routeFor(el);
    if (to) go(to);
    else showToast('Not wired in the explorer — use the sidebar');
  });

  document.getElementById('prev').addEventListener('click', () => {
    const i = FLOW.indexOf(current);
    if (i > 0) go(FLOW[i - 1]);
  });
  document.getElementById('next').addEventListener('click', () => {
    const i = FLOW.indexOf(current);
    if (i !== -1 && i < FLOW.length - 1) go(FLOW[i + 1]);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') document.getElementById('prev').click();
    if (e.key === 'ArrowRight') document.getElementById('next').click();
  });

  const themeBtn = document.getElementById('theme-btn');
  themeBtn.addEventListener('click', () => {
    const dark = document.documentElement.getAttribute('data-theme') !== 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    themeBtn.setAttribute('aria-pressed', String(dark));
  });

  const hotBtn = document.getElementById('hotspots-btn');
  hotBtn.addEventListener('click', () => {
    const on = document.body.classList.toggle('hotspots');
    hotBtn.setAttribute('aria-pressed', String(on));
  });

  addEventListener('resize', layout);
  addEventListener('hashchange', () => go(location.hash.slice(1), false));
  go((location.hash || '#Main').slice(1), false);
</script>
</body>
</html>
`;

writeFileSync(join(out, 'sketchy-explorer.html'), html);
console.log(`wrote sketchy-explorer.html (${(html.length / 1024).toFixed(0)} KB)`);
