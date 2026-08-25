# UI mockups

Every screen Sketchy has, drawn to match the shipped interface, on one pan/zoom
canvas. This is the surface to argue about layout and copy on before writing
React — and the reference for what a screen looks like today.

Companion documents: [`../architecture.md`](../architecture.md) ·
[`../requirements.md`](../requirements.md) ·
[`../../GLOSSARY.md`](../../GLOSSARY.md)

> **The rule that governs this document.** Every colour, size, padding and
> radius in these artboards is a *copy* of a value in
> [`frontend/src/styles/`](../../frontend/src/styles/). Nothing checks that the
> copy is still right — a restyle in the app leaves the mockup silently wrong,
> and a mockup that is wrong while claiming to be faithful is worse than no
> mockup at all. **When you change a component's appearance, update the artboard
> that shows it in the same change.** When you cannot, say so in the artboard's
> annotation rather than leaving it to be discovered.

Snapshot of the interface as of `0e48d50`, 2026-08-25.

---

## 1. Where it lives

The canvas is published as a private Artifact. Open it to pan, zoom, edit any
element in place, and export PNG/PDF:

<https://claude.ai/code/artifact/1dacf382-3678-4fc9-b46c-4cd75e981b3a>

Saving from that page publishes a new version for everyone with write access.
This directory is the source it was seeded from; the two can drift, so read
§4 before editing either.

## 2. What is here

Fourteen artboards, laid out in five rows with a sticky note heading each row.

| Row | Artboard | Route or state | Shows |
| --- | --- | --- | --- |
| Getting in | `Main.dc.html` | `/` | Lobby: create, join by code, public room list |
| | `CreateRoom.dc.html` | `/create` | Full room setup, advanced settings open |
| | `AccountRecovery.dc.html` | `/forgot-password` | Reset-password form |
| In the room | `WaitingRoom.dc.html` | `/room/:code`, waiting | Host view: settings editor + Start game |
| | `Drawing.dc.html` | phase `drawing`, drawer | Canvas, full toolbar, prompt revealed |
| | `Guessing.dc.html` | phase `drawing`, guesser | Masked prompt, timed hints, guess input |
| After the turn | `TurnResults.dc.html` | phase `turn_results` | Scores overlay over the canvas area |
| | `GameOver.dc.html` | phase `game_end` | Podium, final standings |
| | `Highlights.dc.html` | highlights screen | The four superlatives |
| Library and profile | `PromptStats.dc.html` | `/prompt-lists` | Difficulty table with filters |
| | `MyPromptLists.dc.html` | `/my-prompt-lists` | List editor, bulk paste, prompt chips |
| | `Profile.dc.html` | `/profile` | Stat tiles, game history, expanded turns |
| Operator pages | `AdminOps.dc.html` | `/admin/operations` | Live counts, trends, recorder health |
| | `Moderation.dc.html` | `/moderation` | Player-report queue |

`canvas.json` is the layout: artboard positions, display titles, the row notes,
and which view a fresh open lands on.

**Not covered.** Dark theme (`theme-overrides.css`), mobile layouts, the
settings modal, invite entry, first-run identity, the dialogs, connection and
shutdown banners, drawing recap, and the prompt-content report flow.

## 3. The story the room artboards tell

The six room artboards are one moment in one game, not six unrelated screens —
so a score, a rank or a roster that disagrees between two of them is a bug in
the mockup:

- Room **Coffee break doodles**, code `BQ7F2K`, public, 5/8 players, 2
  spectating, 3 rounds, 90s draws, default scoring, timed hints.
- Players: **Marta** (host, and the viewer on every artboard), **Bruno**,
  **Yuki**, **Ines** (AFK), **Sparrow-14** (a guest — grey italic).
- Round 2, turn 1. Marta draws *lighthouse*. Bruno, Sparrow-14 and Yuki guess
  it; Ines is AFK and ineligible. Sparrow-14 overtakes Ines on that turn, which
  is the ▲/▼ pair in the turn-results overlay.

## 4. Editing

**In the canvas.** Click an element, edit it in the properties panel or type
into it directly, then Save. That publishes a new version but does **not** write
back here. To bring changes home, ask Claude Code to extract the published page
into this directory, or do it with the design skill's helper.

**In this directory.** Edit the `.dc.html` files, then reseed and republish.
Each file is one self-contained Design Component: canonical HTML with inline
styles, so the properties panel can edit everything a viewer clicks on.

The six room artboards are **generated** by [`tools/build-mains.mjs`](tools/)
from the shared shell and story in `tools/build-rooms.mjs`. That is what keeps
their rosters and scores agreeing. Running it **overwrites all six** — put
changes to the header, the players sidebar, the chat panel or the story in the
generator, not in the generated file, or the next run will discard them. The
other eight artboards have no generator and are edited directly.

```bash
node tools/build-mains.mjs && node tools/build-toolbar.mjs
```

To rebuild the canvas bundle (`sketchy-views.html`, gitignored) and publish it,
ask Claude Code to reseed with the `design` skill — it owns the payload and the
escaping. The bundle is ~2.3MB of editor code wrapped around these files; it is
never committed.

## 5. Deliberate deviations

Everything else is meant to match the app exactly. These do not:

| Deviation | Why |
| --- | --- |
| Light theme only | The dark override is a separate 35k stylesheet; doubling every artboard to carry it is not worth the drift risk. |
| Desktop widths only | Each artboard is the page's real `max-width`; the mobile breakpoints are a separate set of screens. |
| Tables and lists truncated | A 432-row prompt table and a 15-turn history are shown as a handful of representative rows. |
| Native controls approximated | Where the app styles no `<select>` or `<button>` (prompt stats, moderation filters), the artboard draws a plausible UA default rather than the exact one, which is per-OS. |
| No hover, focus or open states | Static artboards. Menus, tooltips and popovers are drawn closed. |

## 6. Two things the mockups surfaced

Both are in the app, not the artboards, and neither is fixed:

- **The lobby's "Prompt stats" link renders in the browser's default link
  blue.** `.header-action-link` ([`profile.css:398`](../../frontend/src/styles/profile.css))
  sets layout and `text-decoration: none` but no colour, and there is no global
  `a { color }` rule — so it does not match the two header buttons beside it.
  `Main.dc.html` draws it as it ships.
- **`.waiting-invite-button` is dead CSS.** It is defined in
  [`game-room.css:508`](../../frontend/src/styles/game-room.css) but nothing in
  `frontend/src` renders it; `WaitingRoomPanel.tsx` only puts "View highlights"
  and "View drawings" in that slot. No artboard shows an invite button.
