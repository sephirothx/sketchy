/** The two scales a stylesheet cannot enforce on itself: stacking layers and breakpoints.

Both were literals once. Nineteen z-index values, each chosen to clear whatever
the last bug was: dialogs at 1000 sat under Settings (1095), the banners (1150)
and the room's drawers (1200), so the report, suspension and AFK dialogs were
lifted one at a time - over the toasts, which then reported a dialog's outcome
under its scrim. And twenty-odd media widths with near misses (479/480,
600/639/640, 700/701/720/760, 860/900/901, 999/1000), one of which put the lobby
in both its layouts at exactly 900px.

The layers are custom properties now (styles/layout-primitives.css), declared in
order, and this holds three things: a z-index is a layer or a bare 0-4 (order
among one component's own children); the layers stay in the order the comment
beside them argues for; and the surfaces the bugs were about stay on theirs.

A media query cannot read a custom property, so the breakpoints are a fixed set
instead, each written as the first width of the wider side. A `min-width` is one
of them and a `max-width` is one less, so no width is on both sides. The same
applies to the queries components make through `useMediaQuery`.
*/
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, relative } from "node:path";

const SRC = "src";

function walk(dir, keep) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...walk(path, keep));
    else if (keep(name)) out.push(path);
  }
  return out;
}

const withoutComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
const lineOf = (text, index) => text.slice(0, index).split("\n").length;

const cssFiles = walk(SRC, (name) => name.endsWith(".css")).map((path) => ({
  path: relative(".", path),
  text: withoutComments(readFileSync(path, "utf8")),
}));
const scriptFiles = walk(SRC, (name) => /\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")).map((path) => ({
  path: relative(".", path),
  text: readFileSync(path, "utf8"),
}));

// ------------------------------------------------------------------ layers

const LAYERS_FILE = join(SRC, "styles", "layout-primitives.css");
const layers = [...withoutComments(readFileSync(LAYERS_FILE, "utf8")).matchAll(/--z-([a-z]+):\s*(\d+);/g)].map(
  ([, name, value]) => ({ name, value: Number(value) }),
);
const layer = Object.fromEntries(layers.map(({ name, value }) => [name, value]));
const LOCAL_MAX = 4;

test("the layers are declared once, in the order their comment gives, above every local value", () => {
  assert.deepEqual(
    layers.map(({ name }) => name),
    ["float", "dock", "notice", "popover", "confetti", "banner", "overlay", "sheet", "modal", "blocking", "toast"],
  );
  for (let i = 1; i < layers.length; i += 1) {
    assert.ok(layers[i].value > layers[i - 1].value, `--z-${layers[i].name} is not above --z-${layers[i - 1].name}`);
  }
  assert.ok(layers[0].value > LOCAL_MAX, "the lowest layer has to clear a component's own 0-4");
  for (const { path, text } of cssFiles) {
    if (path === relative(".", LAYERS_FILE)) continue;
    assert.doesNotMatch(text, /--z-[a-z]+\s*:/, `${path} redefines a layer`);
  }
});

test("the stacking bugs stay fixed", () => {
  // A toast reports what a dialog just did; under the scrim nobody saw it.
  assert.ok(layer.toast > layer.blocking);
  // Blocking notices over every other dialog; dialogs over the drawers they
  // are opened from, the route overlays and the banners.
  assert.ok(layer.blocking > layer.modal);
  assert.ok(layer.modal > layer.sheet);
  assert.ok(layer.sheet > layer.overlay);
  // A banner over Settings sat on its header and close button (R-UX-07).
  assert.ok(layer.overlay > layer.banner);
  // The offline chip's popover opened under the offline card.
  assert.ok(layer.popover > layer.notice);

  const expected = [
    ["global-feedback.css", ".toast-viewport", "toast"],
    ["global-feedback.css", ".lazy-overlay-notice", "toast"],
    ["global-feedback.css", ".app-banners", "banner"],
    ["dialogs.css", ".modal-overlay", "modal"],
    ["dialogs.css", ".modal-overlay.suspension-overlay", "blocking"],
    ["dialogs.css", ".modal-overlay.afk-check-overlay", "blocking"],
    ["overlays.css", ".bottom-sheet-scrim", "sheet"],
    ["settings.css", ".settings-overlay", "overlay"],
    ["friends.css", ".friends-overlay", "overlay"],
    ["lobby-page.css", ".friend-invite-notice", "notice"],
    ["game-room.css", ".room-stage-overlay", "notice"],
  ];
  for (const [file, selector, name] of expected) {
    const { text } = cssFiles.find(({ path }) => basename(path) === file && !path.includes("lazy"));
    const start = text.search(new RegExp(`(^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\{`));
    assert.ok(start >= 0, `${selector} not found in ${file}`);
    const block = text.slice(start, text.indexOf("}", start));
    assert.match(block, new RegExp(`z-index: var\\(--z-${name}\\);`), `${selector} is not on --z-${name}`);
  }
});

test("every z-index is a layer or a component's own 0-4", () => {
  const wrong = [];
  for (const { path, text } of cssFiles) {
    for (const match of text.matchAll(/z-index\s*:\s*([^;}\n]+)/g)) {
      const value = match[1].trim();
      const named = /^var\(--z-([a-z]+)\)$/.exec(value);
      const local = /^\d+$/.test(value) && Number(value) <= LOCAL_MAX;
      if ((named && named[1] in layer) || local) continue;
      wrong.push(`${path}:${lineOf(text, match.index)} z-index: ${value}`);
    }
  }
  for (const { path, text } of scriptFiles) {
    for (const match of text.matchAll(/zIndex\s*:\s*([^,}\n]+)/g)) {
      const named = /^["']var\(--z-([a-z]+)\)["']$/.exec(match[1].trim());
      if (named && named[1] in layer) continue;
      wrong.push(`${path}:${lineOf(text, match.index)} zIndex: ${match[1].trim()}`);
    }
  }
  assert.deepEqual(wrong, []);
});

test("the toasts stand on a friend invite rather than landing on it", () => {
  const feedback = cssFiles.find(({ path }) => path.endsWith("styles/global-feedback.css")).text;
  const viewport = feedback.slice(feedback.indexOf(".toast-viewport {"));
  assert.match(viewport.slice(0, viewport.indexOf("}")), /bottom: calc\(20px \+ var\(--friend-invite-clearance\)\);/);
  const invite = scriptFiles.find(({ path }) => path.endsWith("components/FriendInviteNotice.tsx")).text;
  assert.match(invite, /setProperty\("--friend-invite-clearance"/);
});

// ------------------------------------------------------------- breakpoints

// The first width of the wider side. `min-width: N`, `max-width: N - 1`.
const WIDTHS = [481, 641, 721, 901, 1001, 1200, 1500, 2100];
// A landscape phone (max-height 520), a desktop window tall enough to pin
// (R-UX-01), and the game-over panel's fit.
const HEIGHTS = [521, 640, 781];
// Measured against content, not devices, and left where they fit.
const EXCEPTIONS = [
  // The room's name leaves the desktop header where the header stops fitting it.
  { file: "game-room.css", query: "max-width", value: 1100 },
  // The waiting room's two share buttons lose padding, then stack, on the
  // narrowest phones.
  { file: "game-room.css", query: "max-width", value: 400 },
  { file: "game-room.css", query: "max-width", value: 340 },
];

function queries() {
  const found = [];
  const collect = (path, text, index, source) => {
    for (const match of source.matchAll(/\((min|max)-(width|height)\s*:\s*([^)]*)\)/g)) {
      found.push({ path, line: lineOf(text, index), query: `${match[1]}-${match[2]}`, raw: match[3].trim() });
    }
  };
  for (const { path, text } of cssFiles) {
    for (const media of text.matchAll(/@media([^{]*)\{/g)) {
      assert.doesNotMatch(media[1], /(width|height)\s*[<>]/, `${path}: range syntax is not checked here`);
      collect(path, text, media.index, media[1]);
    }
  }
  for (const { path, text } of scriptFiles) {
    for (const literal of text.matchAll(/["'`]([^"'`\n]*\((?:min|max)-(?:width|height)[^"'`\n]*)["'`]/g)) {
      collect(path, text, literal.index, literal[1]);
    }
  }
  return found;
}

test("every media query width and height is one of the breakpoints", () => {
  const found = queries();
  assert.ok(found.length > 50, "the scan found almost nothing - is it still reading the stylesheets?");
  const used = new Set();
  const wrong = [];
  for (const { path, line, query, raw } of found) {
    const px = /^(\d+)px$/.exec(raw);
    const value = px ? Number(px[1]) : NaN;
    const steps = query.endsWith("width") ? WIDTHS : HEIGHTS;
    const onStep = query.startsWith("min") ? steps.includes(value) : steps.includes(value + 1);
    if (onStep) continue;
    const exception = EXCEPTIONS.find((e) => e.file === basename(path) && e.query === query && e.value === value);
    if (exception) {
      used.add(exception);
      continue;
    }
    wrong.push(`${path}:${line} (${query}: ${raw})`);
  }
  assert.deepEqual(wrong, [], "min-width is a breakpoint, max-width one less - see layout-primitives.css");
  assert.deepEqual(EXCEPTIONS.filter((e) => !used.has(e)), [], "an exception nothing uses any more");
});
