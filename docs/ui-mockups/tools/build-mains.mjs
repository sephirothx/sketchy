/** The six room views: each supplies only its middle column. */
import { writeFileSync } from "node:fs";
import { P, PRE, POST, FINAL, nameSpan, playersPanel, chatPanel, page, sys, said, close, correct } from "./build-rooms.mjs";

const LIGHTHOUSE_SVG = `            <svg viewBox="0 0 800 600" style="display: block; width: 100%; height: 100%" xmlns="http://www.w3.org/2000/svg">
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

const canvasStack = (inner) =>
  `          <div style="position: relative; width: 100%; max-width: 800px; aspect-ratio: 4 / 3; background: white; border: 1px solid #c7cad1; border-radius: 8px; overflow: hidden">
${inner}
          </div>`;

const roundInfo = (timer) =>
  `          <div style="display: flex; justify-content: space-between; width: 100%; font-weight: 600">
            <span>Round 2/3</span>${timer === null ? "" : `\n            <div style="font-variant-numeric: tabular-nums${timer <= 10 ? "; color: #e03131" : ""}">${timer}s</div>`}
          </div>`;

// ---------------------------------------------------------------- 1. waiting
const waitingMain = `        <main style="margin: 0; padding: 0 0 32px; width: 100%">

          <section style="display: flex; justify-content: space-between; gap: 20px; align-items: center; margin-bottom: 16px; min-height: 72px">
            <div>
              <p style="color: #64748b; font-size: 12px; font-weight: 700; letter-spacing: .07em; margin: 0 0 5px; text-transform: uppercase">Public room</p>
              <h1 style="color: #1e293b; margin: 0; font-size: 28px; font-weight: 700">Coffee break doodles</h1>
              <p style="color: #64748b; margin: 6px 0 0">Get everyone ready before the first round.</p>
            </div>
          </section>

          <section style="background: #fff; border: 1px solid #dfe1e6; border-radius: 12px; padding: 20px">
            <div style="margin-bottom: 14px">
              <p style="color: #64748b; font-size: 12px; font-weight: 700; letter-spacing: .07em; margin: 0 0 5px; text-transform: uppercase">Host settings</p>
              <h2 style="color: #1e293b; margin: 0; font-size: 19px; font-weight: 700">Edit room settings</h2>
            </div>

            <div style="display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr))">

              <div style="grid-column: 1 / -1; align-items: end; display: flex; gap: 12px; min-width: 0">
                <label style="flex: 0 1 280px; max-width: 280px; min-width: 0; width: 100%; display: flex; flex-direction: column; font-size: 15px; font-weight: 700; gap: 5px">
                  Room name
                  <input type="search" value="Coffee break doodles" style="border: 1px solid #c7cad1; border-radius: 6px; font: inherit; font-weight: 400; padding: 9px 10px; width: 100%">
                </label>
                <div style="flex: 0 0 auto">
                  <div style="background: #e8edf5; border-radius: 999px; display: inline-grid; gap: 2px; grid-auto-flow: column; grid-auto-columns: 88px; padding: 3px; position: relative; width: fit-content">
                    <span aria-hidden="true" style="background: #fff; border-radius: 999px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12); height: calc(100% - 6px); left: 3px; pointer-events: none; position: absolute; top: 3px; width: 88px; z-index: 0"></span>
                    <button type="button" style="background: transparent; border: 0; border-radius: 999px; color: #1e293b; font: inherit; font-size: 13px; font-weight: 700; padding: 8px 14px; position: relative; text-align: center; z-index: 1">Public</button>
                    <button type="button" style="background: transparent; border: 0; border-radius: 999px; color: #475569; font: inherit; font-size: 13px; font-weight: 700; padding: 8px 14px; position: relative; text-align: center; z-index: 1">Private</button>
                  </div>
                </div>
              </div>

${["Max players|8", "Rounds|3", "Drawing time (seconds)|90"].map((s) => {
  const [label, val] = s.split("|");
  return `              <label style="grid-column: 1 / -1; align-items: center; display: flex; flex-direction: row; font-size: 15px; font-weight: 700; gap: 12px; justify-content: flex-start; width: fit-content">
                <span style="box-sizing: border-box; flex: 0 0 12.5rem; width: 12.5rem">${label}</span>
                <div style="align-items: center; background: #fff; border-radius: 999px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.1); display: grid; flex: 0 0 auto; grid-template-columns: 44px minmax(48px, 1fr) 44px; height: 44px; width: 140px">
                  <button type="button" aria-label="Decrease ${label}" style="align-items: center; background: transparent; border: 0; color: #0f172a; display: inline-flex; font-size: 22px; font-weight: 500; height: 100%; justify-content: center; line-height: 1; padding: 0; font-family: inherit">−</button>
                  <input type="text" value="${val}" aria-label="${label}" style="background: transparent; border: 0; color: #0f172a; font: inherit; font-size: 16px; font-weight: 600; height: 100%; min-width: 0; padding: 0; text-align: center; width: 100%">
                  <button type="button" aria-label="Increase ${label}" style="align-items: center; background: transparent; border: 0; color: #0f172a; display: inline-flex; font-size: 22px; font-weight: 500; height: 100%; justify-content: center; line-height: 1; padding: 0; font-family: inherit">+</button>
                </div>
              </label>`;
}).join("\n")}

              <fieldset style="grid-column: 1 / -1; border: 0; padding: 0; min-width: 0; margin-top: 6px">
                <legend style="font-size: 15px; font-weight: 700; margin-bottom: 5px; padding: 0">Prompt lists</legend>
                <div style="align-items: center; color: #64748b; display: flex; font-size: 13px; gap: 8px; margin: 2px 0 7px">
                  <label style="font-weight: 650">Prompt language</label>
                  <output style="color: #334155; font-weight: 750">English</output>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px">
                  <button type="button" style="align-items: center; background: #fff; border: 1px solid #cbd5e1; border-radius: 999px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08); color: #1e293b; display: inline-flex; font: inherit; font-size: 13px; font-weight: 700; gap: 6px; padding: 6px 14px">
                    <span aria-hidden="true" style="color: #2563eb; font-size: 12px; font-weight: 800">✓</span>
                    <span style="white-space: nowrap">Standard English</span>
                    <span style="background: #eff6ff; border-radius: 999px; color: #2563eb; font-size: 11px; font-weight: 600; padding: 1px 6px">432</span>
                  </button>
                  <button type="button" style="align-items: center; background: #e8edf5; border: 1px solid transparent; border-radius: 999px; color: #475569; display: inline-flex; font: inherit; font-size: 13px; font-weight: 700; gap: 6px; padding: 6px 14px">
                    <span aria-hidden="true" style="color: #64748b; font-size: 12px; font-weight: 800">+</span>
                    <span style="white-space: nowrap">Extended English</span>
                    <span style="background: rgba(100, 116, 139, 0.12); border-radius: 999px; color: #64748b; font-size: 11px; font-weight: 600; padding: 1px 6px">1284</span>
                  </button>
                </div>
              </fieldset>

              <fieldset style="grid-column: 1 / -1; border: 0; padding: 0; min-width: 0">
                <legend style="font-size: 15px; font-weight: 700; margin-bottom: 5px; padding: 0">Allowed tools</legend>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px">
${["Brush", "Fill", "Shapes"].map((t) => `                  <button type="button" style="align-items: center; background: #fff; border: 1px solid #cbd5e1; border-radius: 999px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08); color: #1e293b; display: inline-flex; font: inherit; font-size: 13px; font-weight: 700; gap: 6px; padding: 6px 14px"><span aria-hidden="true" style="color: #2563eb; font-size: 12px; font-weight: 800">✓</span><span style="white-space: nowrap">${t}</span></button>`).join("\n")}
                </div>
              </fieldset>

              <fieldset style="grid-column: 1 / -1; border: 0; padding: 0; min-width: 0">
                <legend style="font-size: 15px; font-weight: 700; margin-bottom: 5px; padding: 0">Colors</legend>
                <div style="background: #e8edf5; border-radius: 999px; display: inline-grid; gap: 2px; grid-auto-flow: column; grid-auto-columns: 135px; padding: 3px; position: relative; width: max-content; max-width: 100%">
                  <span aria-hidden="true" style="background: #fff; border-radius: 999px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12); height: calc(100% - 6px); left: 3px; pointer-events: none; position: absolute; top: 3px; width: 135px; z-index: 0"></span>
${[["All colors", true], ["Palette only", false], ["Colorblind-safe", false], ["Black and white", false]].map(([l, on]) => `                  <button type="button" aria-pressed="${on}" style="background: transparent; border: 0; border-radius: 999px; color: ${on ? "#1e293b" : "#475569"}; font: inherit; font-size: 13px; font-weight: 700; padding: 8px 16px; position: relative; text-align: center; white-space: nowrap; z-index: 1">${l}</button>`).join("\n")}
                </div>
              </fieldset>

              <details style="border-top: 1px solid #e2e8f0; grid-column: 1 / -1; padding-top: 18px">
                <summary style="cursor: pointer; font-weight: 800">Advanced settings</summary>
              </details>

            </div>

            <div style="color: #475569; display: flex; font-size: 13px; font-weight: 700; justify-content: flex-end; margin-top: 20px; min-height: 18px">Saved</div>
          </section>

          <section style="background: #fff; border: 1px solid #dfe1e6; border-radius: 12px; padding: 20px; display: flex; justify-content: space-between; gap: 20px; align-items: center; margin-top: 16px">
            <div>
              <p style="color: #64748b; font-size: 12px; font-weight: 700; letter-spacing: .07em; margin: 0 0 5px; text-transform: uppercase">Host controls</p>
              <h2 style="color: #1e293b; margin: 0; font-size: 19px; font-weight: 700">Start when everyone is ready</h2>
              <p style="color: #64748b; margin: 6px 0 0">4 active players are ready to play.</p>
            </div>
            <div style="display: flex; flex: 0 0 auto; gap: 8px">
              <button type="button" style="background: #16a34a; border: 0; border-radius: 8px; color: #fff; flex: 0 0 auto; font-size: 15px; font-weight: 700; padding: 12px 18px; font-family: inherit">Start game</button>
            </div>
          </section>

        </main>`;

writeFileSync("WaitingRoom.dc.html", page(waitingMain, {
  restart: false, save: false, height: 1120,
  players: playersPanel("waiting"),
  chat: chatPanel({
    heading: "Chat while you wait",
    messages: [
      sys("Bruno joined the room"),
      said(P.marta, "ready when you are"),
      said(P.bruno, "one sec, grabbing a coffee"),
      sys("Yuki joined the room"),
      said(P.yuki, "hi all 👋"),
      sys("Sparrow-14 joined the room"),
      sys("Ines was marked AFK by vote."),
    ],
  }),
}));

// ---------------------------------------------------------------- 2. drawing
const MID_TURN_CHAT = [
  sys("Marta is choosing a prompt..."),
  said(P.bruno, "tower?"),
  said(P.yuki, "rocket"),
  said(P.bruno, "a candle"),
  said(P.sparrow, "chimney"),
];

writeFileSync("Drawing.dc.html", page(`        <main style="position: relative; display: flex; flex-direction: column; gap: 10px; align-items: center">

${roundInfo(47)}

          <div style="min-height: 28px; font-size: 24px; font-weight: 700; text-align: center; width: 100%; max-width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 6px">
            <span style="letter-spacing: 1px; max-width: 100%">lighthouse</span>
          </div>

${canvasStack(LIGHTHOUSE_SVG)}

TOOLBAR_SLOT

        </main>`, {
  restart: true, save: true, height: 940,
  players: playersPanel("playing"),
  chat: chatPanel({ heading: "Guess and chat", messages: MID_TURN_CHAT, input: false, drawerNote: true }),
}));

// ---------------------------------------------------------------- 3. guessing
// Timed hints (the room's setting): letters appear for everyone and the blanks
// are plain text — .hint-blank buttons belong to the buy-letters modes only.
writeFileSync("Guessing.dc.html", page(`        <main style="position: relative; display: flex; flex-direction: column; gap: 10px; align-items: center">

${roundInfo(31)}

          <div style="min-height: 28px; font-size: 24px; font-weight: 700; text-align: center; width: 100%; max-width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 6px">
            <span style="max-width: 100%; display: inline-flex; justify-content: center; align-items: center">
              <span style="display: inline-flex; align-items: baseline; max-width: 100%">
                <span style="order: 1; white-space: pre; letter-spacing: 3px">l__h______</span>
                <span style="order: 2; display: inline-flex; gap: 6px; margin-left: 8px; vertical-align: super; letter-spacing: normal"><sup style="color: #868e96; font-weight: 600">10</sup></span>
              </span>
            </span>
          </div>

${canvasStack(LIGHTHOUSE_SVG)}

        </main>`, {
  restart: true, save: true, height: 940,
  players: playersPanel("playing"),
  chat: chatPanel({
    heading: "Guess and chat",
    messages: [
      ...MID_TURN_CHAT,
      said(P.bruno, "light house"),
      close('"light house" is very close!'),
      said(P.yuki, "watchtower"),
    ],
    placeholder: "Type your guess...",
    value: "lighthou",
    hint: `\n                <sup style="color: #868e96">8</sup>`,
  }),
}));

// ------------------------------------------------------------ 4. turn results
const GUESSES = [[P.bruno, "1:02.4"], [P.sparrow, "1:06.0"], [P.yuki, "1:11.8"]];
const overlay = `          <div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(20, 22, 28, 0.6); border-radius: 10px; z-index: 10">
            <div style="background: #fff; border-radius: 10px; padding: 16px 20px; min-width: 260px; max-width: 90%; max-height: 90%; overflow-y: auto; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25)">
              <h3 style="margin: 0 0 2px; text-align: center; font-size: 18.72px; font-weight: 700">Turn results</h3>
              <p style="margin: 0 0 14px; text-align: center; font-size: 1.3rem; color: #495057">The prompt was <strong style="color: #1c2129; letter-spacing: 0.5px">lighthouse</strong></p>
              <p style="background: #eff6ff; border-radius: 7px; color: #1e3a8a; margin: 0 0 14px; padding: 8px 10px; text-align: center">Your turn: <strong>+120 points</strong> · now #3</p>
              <h4 style="margin: 0 0 6px; color: #495057; font-size: 16px; font-weight: 700">Correct guesses</h4>
              <ol style="margin: 0 0 14px; padding-left: 24px">
${GUESSES.map(([p, t]) => `                <li style="padding: 3px 0 3px 4px"><span style="margin-right: 24px">${nameSpan(p)}</span><time style="float: right; color: #495057; font-variant-numeric: tabular-nums; font-weight: 600">${t}</time></li>`).join("\n")}
              </ol>
              <ul style="list-style: none; margin: 0; padding: 0; overflow: hidden">
${POST.map(([p, total, delta], i) => {
  const rank = i + 1;
  const preRank = PRE.findIndex(([q]) => q === p) + 1;
  const change = preRank - rank;
  const arrow = change > 0
    ? `\n                  <span style="font-size: 0.85rem; font-weight: 600; color: #2f9e44">▲${change}</span>`
    : change < 0
      ? `\n                  <span style="font-size: 0.85rem; font-weight: 600; color: #e03131">▼${-change}</span>`
      : "";
  const drawer = p === P.marta ? "✏️ " : "";
  const you = p === P.marta ? `<span style="color: #64748b; font-size: 12px; font-weight: 600"> (you)</span>` : "";
  const bonus = p === P.marta ? `\n                  <span style="color: #a16207; font-size: 12px; font-weight: 700; white-space: nowrap">🎨 +120</span>` : "";
  return `                <li style="display: flex; align-items: center; gap: 8px; height: 44px; padding: 0 4px">
                  <span style="width: 24px; color: #868e96; font-weight: 600">#${rank}</span>
                  <span style="flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${drawer}${nameSpan(p)}${you}</span>${bonus}${arrow}
                  <span style="min-width: 36px; text-align: right; color: ${delta > 0 ? "#2f9e44" : "#868e96"}; font-weight: 600">${delta > 0 ? "+" : ""}${delta}</span>
                  <span style="min-width: 40px; text-align: right; font-weight: 700">${total}</span>
                </li>`;
}).join("\n")}
              </ul>
            </div>
          </div>`;

writeFileSync("TurnResults.dc.html", page(`        <main style="position: relative; display: flex; flex-direction: column; gap: 10px; align-items: center">

${roundInfo(null)}

          <div style="min-height: 28px; font-size: 24px; font-weight: 700; text-align: center; width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 6px">
            <span style="letter-spacing: 1px; max-width: 100%">lighthouse</span>
          </div>

${canvasStack(LIGHTHOUSE_SVG)}

${overlay}

        </main>`, {
  restart: true, save: true, height: 940,
  players: playersPanel("turn-results"),
  chat: chatPanel({
    heading: "Guess and chat",
    messages: [
      said(P.yuki, "watchtower"),
      correct(P.bruno, "lighthouse"),
      sys("Bruno guessed the prompt! (+161)"),
      sys("Sparrow-14 guessed the prompt! (+153)"),
      sys("Yuki guessed the prompt! (+141)"),
      sys('The prompt was "lighthouse"'),
    ],
  }),
}));

// ------------------------------------------------------------- 5 & 6. game end
const END_CHAT = chatPanel({
  heading: "Game chat",
  messages: [
    sys('The prompt was "bow and arrow"'),
    said(P.yuki, "gg everyone"),
    said(P.bruno, "that lighthouse was unfair"),
    said(P.marta, "rematch?"),
  ],
});

writeFileSync("GameOver.dc.html", page(`        <main style="align-items: center; display: flex; justify-content: center; min-height: 480px; width: 100%">
          <section style="background: #fff; border: 1px solid #dfe1e6; border-radius: 16px; box-shadow: 0 8px 24px rgba(15, 23, 42, .12); box-sizing: border-box; max-width: 520px; overflow-y: auto; padding: 28px; text-align: center; width: 100%">
            <p style="color: #64748b; font-size: 12px; font-weight: 800; letter-spacing: .08em; margin: 0; text-transform: uppercase">Game over</p>
            <h1 style="color: #1e293b; font-size: 26px; margin: 7px 0; font-weight: 700">${nameSpan(P.bruno)} takes the crown!</h1>
            <p style="color: #1d4ed8; font-weight: 800; margin: 0 0 14px">Your placement: #3</p>
            <ol style="list-style: none; margin: 0; padding: 0">
${FINAL.map(([p, s], i) => {
  const label = ["🥇", "🥈", "🥉"][i] ?? `#${i + 1}`;
  const you = p === P.marta;
  const style = you
    ? "align-items: center; border-top: 1px solid #e2e8f0; background: #eff6ff; color: #1e3a8a; display: flex; font-weight: 700; justify-content: space-between; margin: 0 -8px; padding: 11px 12px"
    : "align-items: center; border-top: 1px solid #e2e8f0; color: #334155; display: flex; font-weight: 700; justify-content: space-between; padding: 11px 4px";
  return `              <li style="${style}">
                <span>${label} ${nameSpan(p)}${you ? " (you)" : ""}</span>
                <strong style="color: #15803d">${s}</strong>
              </li>`;
}).join("\n")}
            </ol>
            <div style="display: flex; flex-wrap: wrap; gap: 9px; justify-content: center">
${["View highlights", "View drawings", "Continue to waiting room · 7s"].map((l) => `              <button type="button" style="background: #4c6ef5; border: 0; border-radius: 8px; color: #fff; font-weight: 800; margin-top: 18px; padding: 11px 16px; font-family: inherit; font-size: 16px">${l}</button>`).join("\n")}
            </div>
          </section>
        </main>`, {
  restart: false, save: false, height: 900,
  players: playersPanel("game-end"),
  chat: END_CHAT,
}));

const HIGHLIGHTS = [
  ["Hardest prompt", null, "roller coaster", "1 of 3 guessed it"],
  ["Fastest guess", P.bruno, "banana", "4.2s"],
  ["Best drawer", P.marta, null, "92% guessed"],
  ["Quickest on average", P.yuki, null, "12.7s"],
];

writeFileSync("Highlights.dc.html", page(`        <main style="align-items: center; display: flex; justify-content: center; min-height: 480px; width: 100%">
          <section style="background: #fff; border: 1px solid #dfe1e6; border-radius: 16px; box-shadow: 0 8px 24px rgba(15, 23, 42, .12); box-sizing: border-box; max-width: 560px; overflow-y: auto; padding: 24px 28px; width: 100%">
            <header style="align-items: flex-start; display: flex; gap: 12px; justify-content: space-between">
              <div>
                <p style="color: #64748b; font-size: 12px; font-weight: 800; letter-spacing: .08em; margin: 0; text-transform: uppercase">Last game</p>
                <h1 style="color: #1e293b; font-size: 24px; margin: 4px 0 0; font-weight: 700">Highlights</h1>
              </div>
              <button type="button" aria-label="Close highlights" style="background: transparent; border: 0; color: #475569; font-size: 18px; line-height: 1; padding: 4px 8px; font-family: inherit">✕</button>
            </header>
            <ul style="display: grid; gap: 2px; list-style: none; margin: 20px 0 0; padding: 0">
${HIGHLIGHTS.map(([label, who, prompt, value]) => {
  const promptSpan = prompt
    ? `<span style="font-style: italic; font-weight: 600${who ? "; margin-left: 6px" : ""}">${who ? `(${prompt})` : prompt}</span>`
    : "";
  return `              <li style="align-items: baseline; border-top: 1px solid #e2e8f0; display: grid; gap: 2px 14px; grid-template-columns: minmax(0, 1fr) auto; padding: 12px 2px">
                <p style="color: #64748b; font-size: 12px; font-weight: 800; grid-column: 1; letter-spacing: .04em; margin: 0; text-transform: uppercase">${label}</p>
                <p style="color: #1e293b; font-size: 16px; font-weight: 700; grid-column: 1; margin: 0; min-width: 0; overflow-wrap: anywhere">${who ? nameSpan(who) : ""}${promptSpan}</p>
                <p style="color: #15803d; font-size: 18px; font-weight: 800; grid-column: 2; grid-row: 1 / span 2; margin: 0; white-space: nowrap">${value}</p>
              </li>`;
}).join("\n")}
            </ul>
            <div style="display: flex; justify-content: center; margin-top: 20px">
              <button type="button" style="background: #4c6ef5; border: 0; border-radius: 8px; color: #fff; font-weight: 800; padding: 11px 16px; font-family: inherit; font-size: 16px">Back</button>
            </div>
          </section>
        </main>`, {
  restart: false, save: false, height: 900,
  players: playersPanel("game-end"),
  chat: END_CHAT,
}));

console.log("wrote 6 room artboards");
