/**
 * Builds the six game-room artboards from one story definition.
 *
 * The room shell (header, players sidebar, chat panel) is identical markup in
 * all six views, and the scores/roster are one dataset — generating them is what
 * keeps a rank in the sidebar from disagreeing with the same rank in an overlay.
 * Values are lifted from frontend/src/styles/*.css; see README.md.
 */
import { writeFileSync } from "node:fs";

// ---------------------------------------------------------------- the story
const P = {
  marta: { name: "Marta", color: "#0f766e", host: true, you: true },
  bruno: { name: "Bruno", color: "#c2410c" },
  yuki: { name: "Yuki", color: "#7e22ce" },
  ines: { name: "Ines", color: "#0369a1", afk: true },
  sparrow: { name: "Sparrow-14", guest: true },
};
const ROSTER = [P.marta, P.bruno, P.yuki, P.ines, P.sparrow];
const MAX_PLAYERS = 8;
const SPECTATORS = 2;

// Round 2, turn 1: Marta draws "lighthouse" on a 90s timer, default scoring.
const PRE = [[P.bruno, 820], [P.yuki, 705], [P.marta, 640], [P.ines, 310], [P.sparrow, 180]];
const POST = [[P.bruno, 981, 161], [P.yuki, 846, 141], [P.marta, 760, 120], [P.sparrow, 333, 153], [P.ines, 310, 0]];
const FINAL = [[P.bruno, 1420], [P.yuki, 1180], [P.marta, 980], [P.sparrow, 520], [P.ines, 310]];

// --------------------------------------------------------------- primitives
const nameSpan = (p) =>
  p.guest
    ? `<span style="color: #6b7280; font-style: italic; font-weight: 600">${p.name}</span>`
    : `<span style="color: ${p.color}; font-weight: 700">${p.name}</span>`;

const PANEL = "background: #fff; border: 1px solid #dfe1e6; border-radius: 10px; padding: 12px; box-sizing: border-box; min-width: 0; width: 100%";
const HDR_BTN = "border-radius: 6px; padding: 8px 14px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; gap: 6px; font-family: inherit; font-size: 16px";
const GEAR = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>';
const CROWN = '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M2.2 12.5h11.6l-.7-7.2-3.1 2.4L8 4.2 6 7.7 2.9 5.3l-.7 7.2Zm-.4 1.3c-.5 0-.8-.5-.7-1l.8-8.2c.1-.7 1-.9 1.5-.4L5.7 6l1.6-2.8c.3-.6 1.1-.6 1.4 0L10.3 6l2.3-1.8c.5-.5 1.4-.3 1.5.4l.8 8.2c.1.5-.2 1-.7 1H1.8Z"/></svg>';

// The header's .header-action-icon spans are display:none above 480px, so a
// desktop artboard shows the label only. The Save icon is a plain <svg> and stays.
function header({ restart = false, save = false }) {
  return `    <header style="display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 12px">
      <div style="display: flex; align-items: center; gap: 8px; min-width: 0">
        <button type="button" style="background: #ffffff; color: #1e293b; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 8px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05); font-family: inherit">
          <span>Code: BQ7F2K</span>
        </button>
      </div>
      <div style="display: flex; align-items: center; gap: 8px; margin-left: auto; flex-wrap: nowrap">
${restart ? `        <button type="button" style="${HDR_BTN}; background: #fffbeb; border: 1px solid #fbbf24; color: #92400e"><span>Restart</span></button>\n` : ""}        <button type="button" aria-label="Signed in as Marta" style="display: inline-flex; align-items: center; border: 1px solid #cbd5e1; background: transparent; color: inherit; border-radius: 999px; padding: 4px; gap: 0; min-height: 36px; font: inherit">
          <span aria-hidden="true" style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; background: #0f766e; color: #fff; font-weight: 700; font-size: 14px; flex: none">M</span>
        </button>
        <button type="button" style="${HDR_BTN}; background: #f8fafc; border: 1px solid #cbd5e1; color: #334155"><span>AFK</span></button>
        <button type="button" style="${HDR_BTN}; background: #fef2f2; border: 1px solid #fca5a5; color: #b91c1c"><span>Leave</span></button>
${save ? `        <button type="button" aria-label="Save image" style="display: flex; align-items: center; gap: 6px; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px 12px; font-size: 13px; font-weight: 600; color: #475569; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06); flex: 0 0 auto; font-family: inherit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>Save</span>
        </button>\n` : ""}        <button type="button" style="display: inline-flex; align-items: center; gap: 6px; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 7px 13px; font-size: 14px; font-weight: 600; color: #334155; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); font-family: inherit">
          ${GEAR}
          <span>Settings</span>
        </button>
      </div>
    </header>`;
}

// PlayerList.tsx: rows are 1.25rem / 1fr, plus a 5ch score column when scores show.
// One role icon per row, in this order: drawing, AFK, host.
function playerRow(p, { score = null, drawer = false, placement = null }) {
  const cols = score === null ? "1.25rem minmax(0, 1fr)" : "1.25rem minmax(0, 1fr) 5ch";
  const dim = p.afk ? "; opacity: .72" : "";
  let role = `<span aria-hidden="true" style="grid-column: 1; grid-row: 1; height: 1.25rem; width: 1.25rem"></span>`;
  if (placement !== null) {
    const medal = ["🥇", "🥈", "🥉"][placement - 1];
    role = medal
      ? `<span aria-hidden="true" style="align-items: center; display: inline-flex; grid-column: 1; grid-row: 1; height: 1.25rem; justify-content: center; width: 1.25rem">${medal}</span>`
      : `<span aria-hidden="true" style="align-items: center; color: #64748b; display: inline-flex; font-size: 13px; font-weight: 700; grid-column: 1; grid-row: 1; height: 1.25rem; justify-content: center; width: 1.25rem">#${placement}</span>`;
  } else if (drawer) {
    role = `<span role="img" aria-label="Drawing" title="Drawing" style="align-items: center; color: #7c3aed; display: inline-flex; grid-column: 1; grid-row: 1; height: 1.25rem; justify-content: center; width: 1.25rem">✏️</span>`;
  } else if (p.afk) {
    role = `<span role="img" aria-label="AFK" title="AFK" style="align-items: center; color: #d97706; display: inline-flex; font-size: 9px; font-weight: 800; letter-spacing: 0.02em; grid-column: 1; grid-row: 1; height: 1.25rem; justify-content: center; width: 1.25rem">zzz</span>`;
  } else if (p.host) {
    role = `<span role="img" aria-label="Host" title="Host" style="align-items: center; color: #7c3aed; display: inline-flex; grid-column: 1; grid-row: 1; height: 1.25rem; justify-content: center; width: 1.25rem">${CROWN}</span>`;
  }
  const you = p.you ? `\n                  <span style="color: #94a3b8; flex: 0 0 auto; font-size: 11px; font-weight: 600">you</span>` : "";
  const scoreCell = score === null ? "" : `\n                <span style="font-variant-numeric: tabular-nums; font-weight: 700; grid-column: 3; grid-row: 1; justify-self: end; text-align: right; width: 100%">${score}</span>`;
  return `              <li style="align-items: center; border-radius: 6px; column-gap: 8px; display: grid; grid-template-columns: ${cols}; padding: 6px 4px; row-gap: 4px${dim}">
                ${role}
                <span style="align-items: center; display: inline-flex; gap: 6px; grid-column: 2; grid-row: 1; min-width: 0; overflow: hidden; white-space: nowrap">
                  ${nameSpan(p)}${you}
                </span>${scoreCell}
              </li>`;
}

function playersPanel(mode) {
  let rows, kicker = "", ready = "";
  if (mode === "waiting") {
    rows = ROSTER.map((p) => playerRow(p, {})).join("\n");
    const eligible = ROSTER.filter((p) => !p.afk).length;
    ready = `\n                <span style="background: #dcfce7; border-radius: 999px; color: #15803d; font-size: 13px; font-weight: 700; padding: 6px 9px">${eligible} ready</span>`;
  } else if (mode === "playing") {
    rows = PRE.map(([p, s]) => playerRow(p, { score: s, drawer: p === P.marta })).join("\n");
  } else if (mode === "turn-results") {
    rows = POST.map(([p, s]) => playerRow(p, { score: s, drawer: p === P.marta })).join("\n");
  } else {
    kicker = `\n                <p style="color: #64748b; font-size: 11px; font-weight: 800; letter-spacing: .07em; margin: 0 0 3px; text-transform: uppercase">Final standings</p>`;
    rows = FINAL.map(([p, s], i) => playerRow(p, { score: s, placement: i + 1 })).join("\n");
  }
  return `      <aside style="display: flex; flex-direction: column; gap: 12px">
        <div style="${PANEL}">
          <section>
            <div style="align-items: center; display: flex; gap: 8px; justify-content: space-between; margin-bottom: 14px; min-height: 42px">
              <div>${kicker}
                <div style="align-items: baseline; display: flex; gap: 8px">
                  <h2 style="color: #1e293b; font-size: 16px; margin: 0">Players</h2>
                  <span style="color: #64748b; font-size: 13px; font-variant-numeric: tabular-nums; font-weight: 700">${ROSTER.length}/${MAX_PLAYERS}</span>
                </div>
              </div>
              <div style="align-items: center; display: flex; flex: 0 0 auto; gap: 6px">${ready}
                <div style="align-items: center; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 999px; color: #64748b; display: inline-flex; font-size: 12px; font-weight: 800; gap: 3px; padding: 4px 7px">
                  <span aria-hidden="true" style="filter: grayscale(1); font-size: 13px; opacity: .72">👀</span><span>${SPECTATORS}</span>
                </div>
              </div>
            </div>
            <ul style="list-style: none; margin: 0; padding: 0">
${rows}
            </ul>
          </section>
        </div>
      </aside>`;
}

const sys = (t) => `                <div style="color: #6b6f76; font-style: italic; overflow-wrap: anywhere">${t}</div>`;
const said = (p, t) => `                <div style="overflow-wrap: anywhere"><strong style="${p.guest ? "color: #6b7280; font-style: italic; font-weight: 600" : `color: ${p.color}; font-weight: 700`}">${p.name}: </strong>${t}</div>`;
const close = (t) => `                <div style="color: #f08c00; font-style: italic; overflow-wrap: anywhere">${t}</div>`;
const correct = (p, t) => `                <div style="color: #2f9e44; font-weight: 600; overflow-wrap: anywhere"><strong style="${p.guest ? "color: #6b7280; font-style: italic; font-weight: 600" : `color: ${p.color}; font-weight: 700`}">${p.name}: </strong>${t}</div>`;

// .room-chat-panel.guess-chat is height: clamp(360px, calc(100vh - 130px), 520px)
// in every mode — it beats the .guess-chat base of 480px.
function chatPanel({ heading, messages, input = true, placeholder = "Type a message...", value = "", hint = "", drawerNote = false }) {
  const form = input
    ? `            <form style="position: relative; display: flex; flex-direction: column; gap: 4px; margin-top: 8px">
              <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 3px; min-height: 1.1rem; padding: 0 10px; font-size: 1rem">${hint}</div>
              <div style="display: flex; align-items: center; gap: 6px">
                <div style="flex: 1; display: flex; align-items: center; min-width: 0; padding: 8px 10px; border: 1px solid #c7cad1; border-radius: 6px; background: white">
                  <input type="search" ${value ? `value="${value}" ` : ""}placeholder="${placeholder}" style="flex: 1; min-width: 0; border: none; outline: none; padding: 0; font: inherit; background: transparent; color: inherit">
                </div>
                <button type="submit" style="background: #4c6ef5; color: white; border: none; border-radius: 6px; padding: 8px 14px; font-family: inherit; font-size: 16px">Send</button>
              </div>
            </form>`
    : "";
  const note = drawerNote
    ? `\n            <p style="color: #64748b; font-size: 13px; margin: 10px 0 0">You’re drawing—watch the guesses come in.</p>`
    : "";
  return `      <aside style="display: flex; flex-direction: column; gap: 12px">
        <div style="${PANEL}">
          <section style="display: flex; flex-direction: column; height: 520px">
            <div style="align-items: center; display: flex; gap: 8px; justify-content: space-between; margin-bottom: 14px; min-height: 42px; flex: 0 0 auto">
              <div>
                <p style="color: #64748b; font-size: 11px; font-weight: 800; letter-spacing: .07em; margin: 0 0 3px; text-transform: uppercase">Room chat</p>
                <h2 style="color: #1e293b; font-size: 16px; margin: 0">${heading}</h2>
              </div>
            </div>
            <div style="flex: 1; position: relative; min-height: 0; display: flex; flex-direction: column">
              <div style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; font-size: 14px">
${messages.join("\n")}
              </div>
            </div>
${form}${note}
          </section>
        </div>
      </aside>`;
}

function page(main, { restart, save, players, chat, height }) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #f2f3f7;
      color: #1c1d21;
      font-family: system-ui, "Segoe UI", Roboto, sans-serif;
    }
    h1, h2, h3, h4, p, ul, ol, fieldset, legend { margin: 0; }
    a { color: #4c6ef5; text-decoration: none; }
    a:hover { color: #3b5bdb; }
    summary { cursor: pointer; }
  </style>
</helmet>
<div style="width: 1200px; min-height: ${height}px; margin: 0 auto; padding: 16px">

${header({ restart, save })}

    <div style="display: grid; grid-template-columns: 220px minmax(0, 1fr) 280px; gap: 16px; align-items: start">

${players}

      <div style="min-width: 0">
${main}
      </div>

${chat}

    </div>
</div>
</x-dc>
<script data-dc-script data-props='{"$preview": {"width": 1200, "height": ${height}}}'>
class Component extends DCLogic {
  renderVals() {
    return {};
  }
}
</script>
</body>
</html>
`;
}

export { P, ROSTER, PRE, POST, FINAL, nameSpan, header, playersPanel, chatPanel, page, sys, said, close, correct, PANEL };
