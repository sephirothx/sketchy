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
    ["float", "dock", "notice", "popover", "confetti", "banner", "overlay", "sheet", "modal", "blocking", "toast", "scrollbar"],
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
    ["scroll-handles.css", ".scroll-handle-layer", "scrollbar"],
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

test("the invite stands on the bottom dock, and the toasts on both (R-UX-07)", () => {
  const block = (file, selector) => {
    const text = cssFiles.find(({ path }) => path.endsWith(`styles/${file}`)).text;
    const start = text.indexOf(`${selector} {`);
    return text.slice(start, text.indexOf("}", start));
  };
  assert.match(block("lobby-page.css", ".friend-invite-notice"), /bottom: calc\(18px \+ var\(--dock-clearance\)\);/);
  assert.match(
    block("global-feedback.css", ".toast-viewport"),
    /bottom: calc\(20px \+ var\(--dock-clearance\) \+ var\(--friend-invite-clearance\)\);/,
  );
  // And between a column docked down either side, rather than into it (#1175).
  for (const [file, selector] of [
    ["global-feedback.css", ".toast-viewport"],
    ["global-feedback.css", ".lazy-overlay-notice"],
    ["lobby-page.css", ".friend-invite-notice"],
  ]) {
    assert.match(block(file, selector), /- 2 \* var\(--dock-inline-inset\)\)/, selector);
  }
  const source = (file) => scriptFiles.find(({ path }) => path.endsWith(file)).text;
  assert.match(source("components/FriendInviteNotice.tsx"), /setProperty\("--friend-invite-clearance"/);
  assert.match(source("hooks/useBottomDock.ts"), /setProperty\("--dock-clearance"/);
  // Every bar a phone page docks at the bottom says how tall it is.
  const docks = [
    ["pages/LobbyBrowserPage.tsx", "lobby-dock"],
    ["components/InviteEntryPage.tsx", "invite-join-form"],
    ["pages/CreateRoomPage.tsx", "create-room-footer"],
    ["components/WaitingRoomPanel.tsx", "waiting-start-card"],
    ["components/RoomShell.tsx", "room-shell-dock"],
  ];
  for (const [file, className] of docks) {
    const text = source(file);
    for (const tag of text.matchAll(new RegExp(`<div className="(?:[^"]* )?${className}(?: [^"]*)?"[^>]*>`, "g"))) {
      assert.match(tag[0], /ref=\{dockRef\}/, `${file}: .${className} does not publish its height`);
    }
    assert.match(text, /useBottomDock\(\)/, file);
  }
  assert.match(source("components/RoomChatPanel.tsx"), /ref=\{composerRef\}/);
  // The verdict on a guess floats above the field, outside its box, and is
  // the only feedback with the keyboard up: the field reserves its slot then,
  // and only then, since it is not shown with the keyboard down (#1199).
  assert.match(block("game-room.css", ".game-room.guess-focused .chat-input"), /--dock-reserve: \d+px;/);
  assert.doesNotMatch(block("chat.css", ".chat-input"), /--dock-reserve/);
  assert.match(source("hooks/useBottomDock.ts"), /getPropertyValue\("--dock-reserve"\)/);
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
  // ...and the waiting room's heading takes over below it, so the name is on
  // screen once at every width (#1107).
  { file: "game-room.css", query: "min-width", value: 1101 },
  // The footer's short labels follow the same line (#1107).
  { file: "WaitingRoomPanel.tsx", query: "max-width", value: 1100 },
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

// -------------------------------------------------------- the room's switch

// A room is the phone's shell or the desktop's columns by one rule
// (lib/roomLayout.ts). The components ask it through useMediaQuery and the
// stylesheets restate it, so the two are held together here: above 900px a
// short landscape viewport once got the desktop DOM under the phone's
// landscape stylesheet, and a 0 x 0 canvas (#1261).
const ROOM_QUERY = /PHONE_ROOM_QUERY = "([^"]+)"/.exec(readFileSync(join(SRC, "lib", "roomLayout.ts"), "utf8"))[1];
const ROOM_STYLESHEETS = ["game-room.css", "chat.css", "drawing-recap.css"];
const ROOM_COMPONENTS = [
  "ActiveGameRoom.tsx",
  "GameHeaderStatus.tsx",
  "GameRoomRegions.tsx",
  "RoomChatPanel.tsx",
  "Toolbar.tsx",
  "WaitingRoomPanel.tsx",
];

test("the room's phone and desktop sides are one breakpoint definition", () => {
  assert.equal(ROOM_QUERY, "(max-width: 900px), (max-height: 520px)");
  for (const name of ROOM_COMPONENTS) {
    const { path, text } = scriptFiles.find((file) => basename(file.path) === name);
    assert.match(text, /useMediaQuery\(PHONE_ROOM_QUERY\)/, `${path} does not ask the room's rule`);
    assert.doesNotMatch(text, /\(max-width: 900px\)/, `${path} asks a width of its own`);
  }
  let phoneBlocks = 0;
  for (const name of ROOM_STYLESHEETS) {
    const { path, text } = cssFiles.find((file) => basename(file.path) === name);
    for (const [, query] of text.matchAll(/@media([^{]*)\{/g)) {
      const q = query.trim();
      if (q === ROOM_QUERY) phoneBlocks += 1;
      // Either side of 900px alone is the old rule: the phone's needs the
      // short viewport too, the desktop's has to leave it out.
      assert.ok(!/^\(max-width: 900px\)$/.test(q), `${path}: @media ${q} leaves out short viewports`);
      if (/min-width: 9\d\d|min-width: 1\d\d\dpx/.test(q) && !/min-height: (521|640)px/.test(q)) {
        assert.fail(`${path}: @media ${q} also matches a short viewport the room draws as a phone`);
      }
    }
  }
  assert.ok(phoneBlocks >= 4, `only ${phoneBlocks} room stylesheet blocks use the room's query`);
  // The overlays that belong to the room follow it; the bottom sheets and
  // dialogs everywhere else keep the site's own 900px, and the room's own
  // sheets take the phone's shape in its short half.
  const overlays = cssFiles.find((file) => basename(file.path) === "overlays.css").text;
  assert.equal([...overlays.matchAll(/@media \(max-width: 900px\), \(max-height: 520px\) \{/g)].length, 2);
  assert.match(overlays, /@media \(min-width: 901px\) and \(max-height: 520px\) \{\s*\.game-room \.bottom-sheet-scrim/);
  // The landscape layout is the rule's short half: the same height, so every
  // viewport it styles is one the components drew as a phone. A taller one
  // here put the desktop DOM under it again - 0 x 0 at 1180 x 600.
  const short = /\(max-height: (\d+)px\)/.exec(ROOM_QUERY)[1];
  const gameRoom = cssFiles.find((file) => basename(file.path) === "game-room.css").text;
  const landscape = [...gameRoom.matchAll(/@media \(orientation: landscape\) and \(max-height: (\d+)px\) and \(min-width: 481px\) \{/g)];
  assert.equal(landscape.length, 1, "the landscape block moved or changed shape");
  assert.equal(landscape[0][1], short);
  const toolbar = cssFiles.find((file) => file.path.endsWith(join("styles", "toolbar.css")) && !file.path.includes("lazy")).text;
  assert.match(toolbar, new RegExp(`\\(min-width: 901px\\) and \\(max-height: ${short}px\\) \\{`));
});
