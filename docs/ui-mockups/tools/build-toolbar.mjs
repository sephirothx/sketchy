/** Splices the drawing toolbar into Drawing.dc.html at TOOLBAR_SLOT. */
import { readFileSync, writeFileSync } from "node:fs";

const COLOR_PAIRS = [
  ["#ffffff", "#000000"], ["#c1c1c1", "#4c4c4c"], ["#ed1c24", "#7f0000"],
  ["#ff7f27", "#a0522d"], ["#fff200", "#c9a227"], ["#b5e61d", "#2d5b1e"],
  ["#22b14c", "#1c6b5a"], ["#7ac9e8", "#2e5090"], ["#3f48cc", "#1b1b6e"],
  ["#a349a4", "#5c2d91"], ["#ec6ea8", "#7b3f61"], ["#ffae85", "#a9714b"],
  ["#c69c6d", "#5b3a1e"],
];
const SELECTED = "#000000";
const I = "            ";

const swatch = (c) => {
  const on = c === SELECTED;
  return `${I}<button type="button" aria-label="${c}" style="width: 24px; height: 24px; border-radius: 4px; padding: 0; background-color: ${c};${
    on
      ? " border: 1px solid #ffffff; box-shadow: 0 0 0 2px #3b82f6, 0 1px 3px rgba(0, 0, 0, 0.2); transform: scale(1.15);"
      : " border: 1px solid rgba(0, 0, 0, 0.15);"
  }"></button>`;
};

const TOOLS = [
  ["Brush", "P", '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>'],
  ["Fill", "F", '<path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2a2 2 0 0 0 2.8 0L19 11Z"/><path d="m5 2 5 5"/><path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 2-4 2-4s2 2.4 2 4Z"/>'],
  ["Eraser", "E", '<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l12-12a1 1 0 0 1 1.4 0l4.3 4.3a1 1 0 0 1 0 1.4L8.4 21a1 1 0 0 1-1.4 0Z"/><path d="m22 21-15 0"/><path d="m5 11 9 9"/>'],
  ["Rectangle", "R", '<rect x="3" y="3" width="18" height="18" rx="2"/>'],
  ["Triangle", "T", '<path d="M13.73 4a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'],
  ["Ellipse", "C", '<circle cx="12" cy="12" r="9"/>'],
];

const tools = TOOLS.map(([name, key, path]) => {
  const on = name === "Brush";
  const box = on
    ? "border: 1px solid #3b82f6; background: #eff6ff; color: #2563eb; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);"
    : "border: 1px solid #cbd5e1; background: #f8fafc; color: #475569;";
  return `${I}<button type="button" aria-label="${name} (${key})" title="${name} (${key})" style="position: relative; width: 34px; height: 34px; border-radius: 7px; display: flex; align-items: center; justify-content: center; ${box}">
${I}  <span style="display: flex; align-items: center; justify-content: center"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg></span>
${I}  <span style="position: absolute; bottom: 1px; right: 3px; font-size: 9px; font-weight: 700; line-height: 1; color: ${on ? "#3b82f6" : "#94a3b8"}; pointer-events: none">${key}</span>
${I}</button>`;
}).join("\n");

const palette = COLOR_PAIRS.map(([l, d]) => swatch(l) + "\n" + swatch(d)).join("\n");
const divider = `          <div style="width: 1px; height: 28px; background: #e2e8f0; margin: 0 1px"></div>`;

// .toolbar-tools (gap 3) ships after .toolbar-group (gap 5) in toolbar.css and wins.
const toolbar = `          <div style="width: fit-content; max-width: 100%; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 6px 12px; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04)">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center">

          <div style="display: flex; align-items: center; gap: 3px">
${tools}
          </div>

${divider}

          <div style="display: flex; align-items: center; gap: 5px; position: relative">
            <button type="button" style="height: 36px; padding: 0 10px; border-radius: 8px; border: 1px solid #cbd5e1; background: #f8fafc; display: flex; align-items: center; gap: 6px; font-family: inherit">
              <span style="border-radius: 50%; display: inline-block; width: 8px; height: 8px; background-color: #000000"></span>
              <span style="font-size: 12px; font-weight: 600; color: #475569; font-variant-numeric: tabular-nums">8px</span>
            </button>
          </div>

${divider}

          <div style="display: grid; grid-template-rows: repeat(2, 1fr); grid-auto-flow: column; gap: 2px">
${palette}
${I}<label style="grid-row: span 2; width: 24px; height: 50px; border-radius: 4px; background: conic-gradient(red, yellow, lime, cyan, blue, magenta, red); position: relative; overflow: hidden; display: block"></label>
          </div>

${divider}

          <div style="display: flex; align-items: center; gap: 4px">
            <span style="font-size: 11px; font-weight: 600; color: #64748b; margin-right: 2px; user-select: none">Recent:</span>
${["#ed1c24", "#fff200", "#7ac9e8"].map((c) => `            <button type="button" aria-label="${c}" style="width: 24px; height: 24px; border-radius: 4px; border: 1px solid rgba(0, 0, 0, 0.15); padding: 0; background-color: ${c}"></button>`).join("\n")}
          </div>

${divider}

          <div style="display: flex; gap: 6px">
            <button type="button" title="Undo last stroke (Ctrl+Z)" style="display: flex; align-items: center; gap: 5px; font-size: 13px; font-weight: 600; padding: 7px 11px; border-radius: 8px; border: 1px solid #cbd5e1; background: #f8fafc; color: #475569; font-family: inherit">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
              <span>Undo</span>
            </button>
            <button type="button" title="Clear canvas" style="display: flex; align-items: center; gap: 5px; font-size: 13px; font-weight: 600; padding: 7px 11px; border-radius: 8px; border: 1px solid #cbd5e1; background: #f8fafc; color: #475569; font-family: inherit">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
              <span>Clear</span>
            </button>
          </div>

        </div>
          </div>`;

const file = "Drawing.dc.html";
const src = readFileSync(file, "utf8");
if (!src.includes("TOOLBAR_SLOT")) throw new Error("TOOLBAR_SLOT not found in " + file);
writeFileSync(file, src.replace("TOOLBAR_SLOT", toolbar));
console.log("toolbar spliced into " + file);
