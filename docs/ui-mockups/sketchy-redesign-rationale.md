# Sketchy redesign rationale

A UI/UX review of every shipped Sketchy screen, and the reasoning behind the
redesigned mockups that answer it.

- **The redesigned mockups** — 21 artboards on one canvas, each with a
  light/dark theme tweak:
  <https://claude.ai/code/artifact/1c717d8a-994f-4cfe-9a66-8308f4218958>
  (source in this directory; regenerate with `node tools/build.mjs`).
- **The clickable explorer** — navigate the mockups like the real app, step
  through a whole game with ◀ ▶, outline the wired controls with Hotspots,
  and toggle dark mode:
  <https://claude.ai/code/artifact/992e6b17-17f8-41cf-bdf1-33a05ab91e95>
  (regenerate with `node tools/build-explorer.mjs`).
- Both canvases tell the same story (room *Coffee break doodles*, code
  `BQ7F2K`, round 2, Marta drawing *lighthouse*), so every screen can be
  compared side by side. Reviewed against `0e48d50`, 2026-08-25.

The redesign has shipped: these artboards are the living reference for the
interface, kept in sync with the frontend (see §4b for the documented
deviations). The pre-redesign mockups this review responded to were removed
from the tree; they live in history at `0e48d50` (`docs/ui-mockups/`).

---

## 1. What's wrong today

### 1.1 The game has no identity

Every screen is built from the same anonymous parts — system-ui type, Tailwind
slate greys, `#4c6ef5` buttons, white cards on `#f2f3f7`. It is a competent
admin-dashboard vocabulary applied to a party game. Nothing on any screen says
"drawing", "friends", or "fun", and nothing distinguishes Sketchy from a
settings page. Successful games in this genre (skribbl.io, Gartic Phone)
invest heavily in a playful, recognizable surface because the audience decides
in seconds whether the game feels worth pulling friends into.

### 1.2 Emoji do the work of icons

`👀` for spectators, `✏️` for the drawer, `🥇🥈🥉` for ranks, `zzz` text for
AFK, `🎨` for the drawer bonus. Emoji render differently on every OS, can't be
recolored or sized to the design, and fail silently in grayscale/high-contrast
settings. They also sit oddly next to R-UX-02's carefully controlled copy.

### 1.3 Action hierarchy is flat — or inverted

- The in-room header lines up **Restart · avatar · AFK · Leave · Save ·
  Settings** as six equal-weight buttons. The destructive one (*Leave*) sits
  between two routine ones — a misclick away from abandoning a live game with
  a 30-second reconnect penalty for the room.
- Game over offers three identical primary buttons (*View highlights*, *View
  drawings*, *Continue to waiting room · 7s*) — the countdown lives **inside a
  button label**, and there is no way to cancel the auto-navigation.
- The lobby's join card makes *Join by code* and *Spectate* twin primary
  buttons; room cards repeat the pattern.

When everything is primary, nothing is. Every screen should answer "what do
most people do here?" with exactly one loud control.

### 1.4 The most important game state is the quietest

- **The timer is a bare `47s` text node** in the top-right of the status row.
  For a game whose entire tension mechanism is the clock (both scoring modes
  decay with time), the countdown deserves to be the most visible element on
  the play screen, with an urgency state as it runs out.
- **Who has already guessed is invisible.** The frozen-eligibility rules
  (R-GUESS-05) and the drawer bonus (R-SCORE-08) both revolve around who has
  answered, yet the player list shows nothing until turn results. skribbl-class
  games mark guessed players green the instant they answer — it is the room's
  live scoreboard of the turn.
- **The masked prompt is underscores**: `l__h______` plus a superscript `10`.
  Underscores at 24px with letter-spacing are genuinely hard to count, word
  breaks are ambiguous for multi-word prompts, and the superscript number
  (hint countdown) is unexplained.
- **Turn context is split**: "Round 2/3" is shown, but who draws, and how far
  through the round the turn order is, must be inferred from a small pencil
  emoji in the sidebar.

### 1.5 Hints — a rich mechanic with no surface

The backend implements four hint modes with per-letter pricing, escalating
costs, and credit-based settlement (R-HINT-01…05, R-SCORE-06/07). The shipped
guessing screen surfaces all of this as two cryptic superscript numbers. A
player who has not read the docs cannot discover that hints exist, what they
cost, or that buying one only settles against a *successful* guess. The
mechanic may as well not ship.

### 1.6 The waiting room buries its one job

A waiting room's job is to fill the room. The shipped screen leads with a
full-width **settings editor** (the host's secondary task) while the invite
affordance is a small `Code: BQ7F2K` button in the corner. Tellingly,
`.waiting-invite-button` exists in the CSS but nothing renders it
([`game-room.css:508`](../../frontend/src/styles/game-room.css) — already
flagged in the mockups README). Guests also see a screen that is mostly a
form they cannot use.

### 1.7 Forms explain nothing and group nothing

- Create-room is one undifferentiated column of ~15 controls. *Scoring:
  Default / Pressure / No scoring* and *Hints: Timed / Buy letters / Wheel of
  Fortune* are offered as bare labels — the difference between scoring modes
  is a paragraph of math in the requirements, and the UI gives the host zero
  help choosing.
- **Drawing time renders as a free stepper**, but R-ROOM-04 defines it as "a
  fixed preset list". The control promises a granularity the server refuses.
- *Keep this room for future games* — a persistence decision — is the **first
  field on the form**, before the room even has a name.
- The five-second `TURN_RESULTS_SECONDS` overlay tries to show a headline,
  your delta, a correct-guess time table *and* full standings with movement
  arrows. It cannot be read in five seconds.

### 1.8 Broken and inconsistent details that read as neglect

- The lobby's *Prompt stats* link renders in **browser-default link blue**
  (`.header-action-link` sets no color — known issue, mockups README §6).
- Prompt-stats filters and moderation controls use **unstyled native
  selects/buttons**, and two moderation selects have `width: 100%` inside a
  flex row, stretching the suspend-duration dropdown across the card —
  directly under the *Suspend* button.
- The lobby search bar sits on `rgba(0,0,0,0.15)` — a dark translucent well
  on a light page, unlike any other control.
- The moderation *Suspend* button and its duration dropdown are two unrelated
  controls; nothing binds the chosen duration to the action.

---

## 2. The redesigned system

One committed direction: **a warm, crafted "paper and crayon" surface with
disciplined, information-dense game UI on top.** Playful where the game is
playful, quiet where the player is reading numbers.

| Token | Choice | Why |
| --- | --- | --- |
| Ground | Warm paper `#FAF6EF`, warm ink `#292520`, warm borders | Reads as a drawing surface instead of a SaaS console; neutrals are chosen, not inherited. |
| Accent | Crayon indigo `#5157D8` (actions) + marker orange `#E8703A` (energy: timers, Start, celebration) | Two accents with distinct jobs — the orange marks *game moments*, so it never competes with routine actions. Continuity with the shipped indigo keeps the change feel evolutionary. |
| Type | **Fredoka** (display: headings, prompts, big numbers) over **Nunito Sans** (UI/body) | A rounded, hand-drawn-adjacent display face gives the game a face; the body face stays neutral and dense enough for scores and tables. Both from Google Fonts with real fallbacks. |
| Wordmark | The drawn logo — brush script over a marker-orange swoosh, shipped as vector paths | Supersedes the Fredoka-set wordmark this table originally specified (§1.1's "no identity"). Paths are painted with `--ink` and `--warm` rather than baked colours, so one mark serves both themes and no third webfont is loaded. |
| Icons | One stroke-based inline SVG set | Replaces every emoji (§1.2): consistent cross-platform, recolorable, sized to the grid. |
| Feedback colors | Green = correct/success, amber = review/warning, red = destructive only | Semantic color is separated from the accents, so green *always* means "guessed/ok" and red is never decoration. |
| Controls | 44px minimum hit targets, 10–14px radii, one primary per view | Touch-friendly (the toolbar buttons grow from 34px), and the hierarchy problem in §1.3 is solved structurally. |

Player identity is upgraded from colored text to **avatar chips** (colored
disc + initial) used identically in the player list, chat, results, podium and
history. Guests keep their mandated grey (R-ACCT-05) but become visually
first-class: a dashed-border chip instead of apologetic italic-only text.

Every color is a **CSS custom property with a light and a dark value**,
switched by one `data-theme` attribute — so the whole system carries a dark
theme for free. The dark values reuse the shipped app's own dark palette
(`theme-overrides.css`): slate ground `#0f172a`, `#1e293b` surfaces,
`#334155`/`#475569` borders, slate text, and its semantic accents — so
night mode matches what today's players already know, while the
crayon/marker accents carry the redesign's identity across both themes
(the drawing canvas deliberately stays white paper in both). Avatar discs keep the fixed account color while player *name text*
uses a theme-adjusted token, so dark-leaning account colors stay legible on
the dark ground. On the canvas, every artboard has a `theme` tweak chip; the
explorer has a Dark toggle. This also retires the shipped approach of a
separate 35k dark override stylesheet — the mockups and the app could share
one token sheet.

---

## 3. Screen by screen

### Lobby (`Main`)

- **Wordmark + a single account button.** The header carries only the
  player's name; Profile, Prompt stats, My prompt lists, Settings and Sign
  out all live in its dropdown (drawn open on the artboard). One entry point
  instead of four header controls — and the default-blue link bug is deleted
  by design (§1.8).
- **Prompt language as a flag on every room card** (drawn as inline SVG, so
  it renders identically on every OS), with a matching **language filter**
  beside the search — the room's one resolved language (R-PROMPT-02) becomes
  scannable before joining.
- **"Start a game" is the single hero action**; *Quick start with defaults*
  serves the returning group that never changes settings.
- **Segmented 6-character code input** replaces the free text field —
  it matches the shape of the thing being typed, shows progress, and makes
  paste-vs-type equally obvious.
- Room cards get **capacity meters** (a glance answers "can we fit?"), iconed
  metadata, and **one consistent action grammar**: *Join* is always the blue
  primary, *Join in progress* is always marker-orange (a different commitment
  — you land mid-game), and *Spectate* is always the outlined button with the
  eye icon. A full room's only button is *Spectate*. The status chip shows
  *round progress* ("Round 2 of 3") instead of a bare "In progress" — how
  long a wait joining implies.
- Filters become toggle chips on a light search well (§1.8 fixed).

### Create a room (`CreateRoom`)

- **Four labeled sections** — Basics, Prompts, Drawing, Scoring & hints —
  replace the single column. Only Basics opens by default: the other three
  are **collapsed disclosures whose headers summarize their current values**
  ("English · Standard English · 432 prompts", "Brush, Fill, Shapes · All
  colors", "Default scoring · Timed hints"), so the defaults-are-fine host
  sees a short form and still knows exactly what they're getting.
- Basics itself explains its consequences: visibility is an iconed
  Public/Private segmented control with a caption saying what the active
  choice means ("Listed in the lobby — anyone can wander in"), a dice button
  makes the random-name behavior discoverable, and a **live game-length
  estimate** ("about 45 minutes with a full room of 8") turns three abstract
  numbers into the one thing the host actually cares about.
- **Players, rounds and drawing time are matching stepper cards** — big
  display numbers with − / + buttons and the legal range as a caption. The
  **drawing-time stepper snaps through the fixed preset list** (30s–300s),
  matching R-ROOM-04 instead of contradicting it (§1.7).
- **Every on/off setting is a labeled toggle switch**, not a native checkbox
  — spectator prompt visibility, hide blanks, custom-prompts-only, and room
  persistence read as state and render identically on every OS.
- **Scoring and hint modes are option cards with one-line explanations**
  ("Points decay — and decay doubles once someone guesses"). The host chooses
  a rule, not a word.
- **A summary footer** restates the whole configuration in one line next to
  the only primary button — misconfiguration is caught before the room
  exists. *Keep this room* moves here, where a persistence decision belongs.
- Custom prompts collapse behind a disclosure — the 90% case never sees them.

### Waiting room (`WaitingRoom`)

- **The invite is the hero**: big code tiles, *Copy invite link* as the
  primary action (resurrecting the designed-but-dead invite button, §1.6).
- **Settings collapse to a chip summary** with an *Edit settings* button for
  the host. Guests now see a sensible screen: who's here, how to invite, what
  the rules are. The full editor already has a home (the create form).
- **Start game is marker-orange** — the one "game moment" button on the
  screen — with an honest readiness line ("Ines is AFK and will sit out").

### Prompt choice (`PromptChoice`) — new screen

The choosing phase (R-GAME-01, R-GAME-03) had no mockup at all, yet it is the
drawer's highest-pressure moment. The redesign gives it one:

- Three plain **prompt cards** — just the words, nothing competing with the
  decision — under a 15s ring countdown and an explicit "auto-picks when time
  runs out" caption (the auto-pick rule of R-GAME-03, surfaced instead of
  sprung).

### Drawing — drawer view (`Drawing`)

- **One lean header row carries everything**: room name and code on the left,
  **Round 2 of 3 · Turn 1 of 4 and the ring timer** (orange as time runs low,
  §1.4) in the center, and compact controls on the right — restart vote, AFK,
  save, settings, with the destructive *Leave* separated at the far edge.
- **Above the canvas: only the prompt.** No "You're drawing" label, no
  guessed-count chip — the pencil status and the per-player *Got it* lines
  already say both, and the canvas gets the reclaimed space.
- **Every player row carries a live status line** under the name — *✓ Got it ·
  1:03* on a green-tinted row, *Drawing* on an indigo one, *AFK* in amber —
  so the sidebar is the turn's scoreboard at a glance (§1.4). Correct guesses
  also land in the feed as **event cards** (left accent, guess time, +points),
  and **post-guess chat is marked with a dashed rule** — the drawer sees it;
  active guessers never receive it (R-SPEC-04).
- Toolbar: 44px targets, tools/size/palette/undo groups separated, **Clear
  restyled as quietly destructive** and separated from Undo — the two most
  opposite actions on the screen no longer look like twins.

### Guessing — guesser view (`Guessing`)

- **Letter tiles** replace underscores: countable boxes, revealed letters
  highlighted (lowercase, vertically anchored on the midpoint of Fredoka's
  cap and x bands so mixed-case glyphs split the centering error evenly),
  each word's letter count kept as a superscript numeral beside
  its tile group (a multi-word prompt reads ³ ³ ⁵), and a visible hint status
  ("Next free letter in 9s" for this room's timed-hints mode). Purchase and
  wheel modes get the same slot for their buy-a-letter affordances — the
  hidden mechanic of §1.5 now has a home on screen.
- **The guess box is visually a guess box** — accented border, chevron send —
  with the shipped GUI's **live per-word letter counts kept above the field**
  under its existing rules: grey while a word is being typed, green when its
  length matches the masked word, red when it can't — hidden when the room
  hides the masked prompt.
- **Near-miss feedback attaches to the input**, kept terse — *"'light house'
  is very close!"* — instead of impersonating a chat line (R-GUESS-03).
- The artboard is honestly drawn **from Yuki's seat**, still guessing while
  two players have answered; the shipped mockup showed a guesser screen with
  the drawer's sidebar, which no player can see.

### Turn results (`TurnResults`)

Redesigned to be readable in its five-second budget (§1.7): prompt reveal in
display type, **one outcome line for you** ("3 of 4 guessed your drawing ·
+120 for you"), then a single standings list carrying delta, movement and
total per row — the separate guess-time table is dropped (it lives on in the
profile's turn history). A **"Next turn: Bruno draws" progress bar** replaces
the unexplained pause, telling players both what happens next and when.

### Game over (`GameOver`)

- **A real podium** — the game's one celebration moment gets height, medal
  colors and the winner's crown, instead of a fifth identical list.
- **One primary action** — a pill **Continue** button that carries the
  auto-advance countdown *inside itself* as a ring around the remaining
  seconds; highlights and drawings are secondary, and a quiet *Stay here*
  link keeps the auto-continue escapable (§1.3). The countdown is part of
  the button it will press, not a caption to hunt for.

### Highlights (`Highlights`)

Four **superlative cards** (icon, label, avatar, stat) in a 2×2 grid instead
of a table-like list — these are trophies, and now read as such; each stat
gains a clarifying unit ("of guessers got it", "per correct guess").

### Prompt stats (`PromptStats`)

Filters become one styled toolbar (no more per-OS native selects), and the
redundant text-plus-percent difficulty columns merge into a **label + meter**
pair — sortable difficulty you can scan without reading. Unranked rows are
dimmed with their reason inline, keeping R-STAT-02's "unranked, not zero"
honesty visible.

### My prompt lists (`MyPromptLists`)

- **Capacity meters** for the 500-prompt and 25-list limits (R-LIST-04) —
  limits stop being surprise errors.
- The duplicate-reporting requirement (R-LIST-01) gets a surface: *"2
  duplicates skipped last paste"* beside the meter.
- **Language is shown as locked** ("locked after creation", R-LIST-05) instead
  of a select that would reject the change.
- Visibility is a Private/Unlisted segmented control with the share-code
  behavior explained in place; **Delete becomes a left-isolated quiet-danger
  action** with an ellipsis (confirmation implied), no longer Save's neighbor.

### Profile (`Profile`)

Four **hero stat tiles** (games, wins, win rate, average) with the secondary
counters demoted to one quiet line — eight identical tiles said nothing.
History rows lead with a **placement badge** (gold/silver/bronze tinted), the
expanded game highlights *your* row, rules metadata becomes chips, and the
turn table's guesser outcomes get check/color coding instead of prose in
parentheses.

### Server operations / Moderation (`AdminOps`, `Moderation`)

Both are full-width operator pages, reached from the lobby like every other
page; Moderation cross-links back to operations from its action row.

- **Server operations** leads with a status banner ("All systems operational
  · single worker · accepting rooms" — R-PLAT-05 stated where an operator
  reads it), four metric cards (live counts note "resets on restart" per
  R-OBS-01; the abandonment rate is the one flagged card), an **hourly
  rooms-opened bar chart** with real axis labels, a **recorder health list**
  (stored, waiting, dropped-this-window — surfacing R-OBS-03's drop counter
  even at zero — daily roll-up, and R-HIST-19's stored-drawing checks) with a
  short "Attention" verdict, and the **append-only audit ledger** as timed
  rows (a suspension, a retention preview, a logged use of the per-player
  view — R-AUDIT-05).
- **Moderation** becomes a **queue / case master-detail**: an open-reports
  queue with filter pills on the left; the selected case on the right with
  the pinned evidence in a quote block (*"pinned by the server exactly as
  the reporter received them — up to 20 messages"*, R-MOD-03/04), an
  **account-context card** (registered, age, prior reports, active
  suspension), the required resolution note ("kept in the append-only audit
  ledger; a warning or suspension from here also resolves this report",
  R-BAN-06), and a clean action row — Dismiss, **Warn player** (the R-MOD-12
  formal warning), **Suspend…** whose ellipsis opens the duration step
  (R-BAN-05) instead of a permanently-visible dropdown.

### Reset password (`AccountRecovery`)

A **split auth layout**: a friendly indigo art panel ("Even the best
guessers forget sometimes.") beside the form — wordmark, one field, one
primary action, quiet back link. The copy stays honest to R-AUTH-09: the
response never reveals whether the account exists.

### Settings (`Settings`) — new screen

The settings surface was on the shipped canvas's "not covered" list; this
canvas gives it a **full page**: a category rail (General / Game /
Shortcuts, with the signed-in player pinned on top) beside two-column
preference groups — each group's purpose on the left, its rows on the
right. The categories are **real, separated tabs**: the pane shows one at a
time (a `tab` tweak switches them on the canvas; the rail switches them
live in the explorer). It covers exactly the R-SET-01 set, nothing
invented:

- **You**: username with a *Manage account* action, and the **account name
  color** with live preview swatches ("guests stay grey", R-ACCT-05).
- **Appearance**: theme as three **preview cards** (Light / Dark / System
  with the current resolution), and the **colorblind-safe preference** with
  its guarantee written where the choice is made (R-CB-01).
- **Audio / Game**: sound, volume, confetti, brush cursor
  (crosshair/outline), guess-box clearing, and **brush presets** against
  the 20-preset cap (R-SET-02).
- **Keyboard shortcuts** as a grid of editable key caps showing **both the
  main and the secondary key** per action (P·1 … C·6, plus brush size and
  undo), with a reset.
- The footer states the honest sync rule — *"changes apply immediately, on
  every device you're signed in on"* (local-only for guests, R-SET-03).

In the explorer, every Settings gear (lobby and in-room) opens it; *Done*
returns to the lobby.

---

## 4. Worth fixing regardless of any redesign

Findings that were app defects or requirement mismatches on their own. All of
them shipped with the redesign implementation:

1. ~~`.header-action-link` has no color.~~ The lobby *Prompt stats* link moved
   into the account menu; the rule is gone.
2. ~~`.waiting-invite-button` is dead CSS.~~ Deleted; the waiting room is now
   built around the invite-first card.
3. ~~Drawing time UI contradicts R-ROOM-04.~~ The stepper card snaps to the
   preset list and says so in its caption.
4. ~~Moderation's `width: 100%` selects break the action row.~~ Restyled with
   the shared field recipes.
5. ~~Emoji-as-icons.~~ Every UI glyph is now an SVG from the shared icon set;
   emoji remain only where they are player content.
6. ~~Turn-results overlay content vs `TURN_RESULTS_SECONDS`.~~ The overlay
   slimmed to one readable card with a next-turn progress bar.
7. ~~No choosing-phase screen existed.~~ The reference canvas covers it
   (PromptChoice artboard) and the app matches.

### Frontend-only degradations (backend follow-ups)

The implementation is frontend-only, so four mockup elements that need data
the client does not receive were deliberately degraded. Each becomes a small
backend follow-up:

- **"Turn 1 of 4"** — the header shows only "Round 2 of 3"; the turn index
  within a round is not in any payload.
- **Lobby round-progress chip** — public room cards say "In progress" rather
  than "Round 2 of 3" for the same reason.
- **"Next free letter in 9s"** — the timed-hints countdown chip needs the
  hint checkpoint schedule; letter tiles ship without it.

## 4b. Where the implementation deviates from the artboards

Small, deliberate divergences between the shipped React frontend and these
artboards, kept for stability or clarity rather than drift:

- **Lobby button copy** — the lobby CTA stays "Create room" (matching the
  create page's submit) and the code card's action stays "Join by code";
  the artboards say "Create a room" / "Join".
- **"Quick start with defaults"** — not implemented; the create page opens
  with the same defaults one click away.
- **The name-roll dice** — random room names remain a server behavior
  (leave the field blank); no client-side dice button.
- **Settings is a modal, not a page** — as decided at planning; the modal
  carries the artboard's separated tabs, theme cards, and shortcut chips.
  The Brush presets and clear-guess-box rows are omitted by decision.
- **Waiting-room settings chips** — chip values reuse the app's established
  copy ("Custom prompts only (2)", "2 custom prompts + curated lists")
  rather than the artboards' shortened variants.
- **Ops chart granularity** — the operations dashboard draws the artboard's
  bar chart from daily aggregates (metric selectable); hourly buckets are
  not recorded.
- **Operator tabs** — the operations page is one workspace with five tabs
  (Overview, Tuning, Controls, Activity, Audit ledger), shown here as three
  artboards because an artboard holds one state. The Controls tab — the
  maintenance pause, the live-room table and the role control — has no
  artboard of its own; it is built from the same card, table and chip parts
  the other operator screens already use. The shutdown control there is marked
  out from them — a warm border and a two-step confirm — because it is the one
  control on the page that ends the process, and nothing in the app starts it
  again.
- **Identity chip stays in the room header** — the artboards drop it, but
  it is the only in-room path to claiming an account and account menus.

## 5. What was deliberately kept

- The three-column room layout (players / stage / chat) — it matches how the
  game is actually watched, and R-UX-01's viewport rule.
- Chat-as-guess-input — guessing *is* chatting in this genre; the redesign
  clarifies the input's role rather than splitting it into two boxes.
- Player colors, the story, all copy facts, and the server-driven truth of
  every number shown — the redesign adds no data the backend doesn't already
  have.
- Desktop widths only, matching the existing canvas's documented deviation.
  (The light-only deviation is gone: dark ships as a token swap, above.)

## Sources

Genre-convention research consulted for §1.4–1.6:

- [skribbl.io](https://skribbl.io/) — timer prominence, guessed-player
  marking, word-choice overlay conventions.
- [Building a Skribbl.io clone (DEV Community)](https://dev.to/divyanshulohani/building-a-skribblio-clone-from-concept-to-completion-1on4) —
  interface anatomy of the genre.
- [skribbl.io judging-game analysis (Mechanics of Magic)](https://mechanicsofmagic.com/2024/04/23/skribbl-io-judging-game-analysis/) —
  social-context limits of anonymous play; informs the invite-first waiting
  room.
- [Multiplayer waiting-lobby design (Medium)](https://medium.com/@ahtashamali263/multiplayer-waiting-lobby-e652b82793b5) and
  [Heroic Labs lobby guide](https://heroiclabs.com/docs/nakama/guides/concepts/lobby/) —
  invite prominence, readiness signaling, countdown transparency.
