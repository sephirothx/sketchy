# Sketchy redesign rationale

A UI/UX review of every shipped Sketchy screen, and the reasoning behind the
redesigned mockups that answer it.

- **The redesigned mockups** — 15 artboards on one canvas:
  <https://claude.ai/code/artifact/1c717d8a-994f-4cfe-9a66-8308f4218958>
  (source in this directory; regenerate with `node tools/build.mjs`).
- **The as-shipped mockups** they respond to: [`../ui-mockups/`](../ui-mockups/).
- Both canvases tell the same story (room *Coffee break doodles*, code
  `BQ7F2K`, round 2, Marta drawing *lighthouse*), so every screen can be
  compared side by side. Reviewed against `0e48d50`, 2026-08-25.

This is a proposal, not a record of the app. Nothing here is implemented.

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
| Type | **Fredoka** (display: wordmark, headings, prompts, big numbers) over **Nunito Sans** (UI/body) | A rounded, hand-drawn-adjacent display face gives the game a face; the body face stays neutral and dense enough for scores and tables. Both from Google Fonts with real fallbacks. |
| Icons | One stroke-based inline SVG set | Replaces every emoji (§1.2): consistent cross-platform, recolorable, sized to the grid. |
| Feedback colors | Green = correct/success, amber = review/warning, red = destructive only | Semantic color is separated from the accents, so green *always* means "guessed/ok" and red is never decoration. |
| Controls | 44px minimum hit targets, 10–14px radii, one primary per view | Touch-friendly (the toolbar buttons grow from 34px), and the hierarchy problem in §1.3 is solved structurally. |

Player identity is upgraded from colored text to **avatar chips** (colored
disc + initial) used identically in the player list, chat, results, podium and
history. Guests keep their mandated grey (R-ACCT-05) but become visually
first-class: a dashed-border chip instead of apologetic italic-only text.

---

## 3. Screen by screen

### Lobby (`Main`)

- **Wordmark + header nav.** The product gets a face, and *Prompt stats* /
  *My lists* / settings / profile become one consistent nav — which also
  deletes the default-blue link bug by design (§1.8).
- **"Start a game" is the single hero action**; *Quick start with defaults*
  serves the returning group that never changes settings.
- **Segmented 6-character code input** replaces the free text field —
  it matches the shape of the thing being typed, shows progress, and makes
  paste-vs-type equally obvious.
- Room cards get **capacity meters** (a glance answers "can we fit?"), iconed
  metadata, and one primary action each; a full room's only button is
  *Spectate*, an in-progress room's join is demoted to secondary. The status
  chip shows *round progress* ("Round 2 of 3") instead of a bare "In
  progress" — how long a wait joining implies.
- Filters become toggle chips on a light search well (§1.8 fixed).

### Create a room (`CreateRoom`)

- **Four labeled sections** — Basics, Prompts, Drawing, Scoring & hints —
  replace the single column, so the host can stop reading after Basics.
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
  screen — with an honest readiness line ("Ines has stepped away and will sit
  out").
- AFK is renamed **"Step away"** everywhere: self-describing, sentence-case,
  and no longer jargon (R-UX-02 spirit).

### Prompt choice (`PromptChoice`) — new screen

The choosing phase (R-GAME-01, R-GAME-03) had no mockup at all, yet it is the
drawer's highest-pressure moment. The redesign gives it one:

- Three **prompt cards** with a 15s ring countdown and an explicit "auto-picks
  when time runs out" caption (the auto-pick rule, surfaced instead of sprung).
- Each card carries a **difficulty chip derived from prompt stats**
  ("Usually guessed" / "Often missed"). The server already computes this
  (R-STAT-01); showing it at pick time turns a dead stats page into a live
  gameplay aid and makes the pick an informed risk/reward decision.

### Drawing — drawer view (`Drawing`)

- **Ring timer** with numeric center, turning orange as time runs low — the
  clock finally looks like the main mechanic (§1.4).
- Status strip: **Round 2 of 3 · Turn 1 of 4**, and the prompt is presented as
  *"You're drawing: lighthouse"* with a live **"2 of 4 guessed it"** chip —
  the drawer's bonus (R-SCORE-08) gets a running indicator.
- **Guessed players get a green check badge and row tint** in the player list
  the moment they answer (§1.4).
- Toolbar: 44px targets, tools/size/palette/undo groups separated, **Clear
  restyled as quietly destructive** and separated from Undo — the two most
  opposite actions on the screen no longer look like twins.
- Header: *Leave* is isolated behind a divider at the far edge; *Vote to
  restart* moves under the player list, with the other social/vote actions,
  instead of masquerading as a personal header control.

### Guessing — guesser view (`Guessing`)

- **Letter tiles** replace underscores: countable boxes, revealed letters
  highlighted, each word's letter count kept as a superscript numeral beside
  its tile group (a multi-word prompt reads ³ ³ ⁵), and a visible hint status
  ("Next free letter in 9s" for this room's timed-hints mode). Purchase and
  wheel modes get the same slot for their buy-a-letter affordances — the
  hidden mechanic of §1.5 now has a home on screen.
- **The guess box is visually a guess box** — accented border, pencil glyph —
  not a generic chat field that happens to score points.
- **Near-miss feedback attaches to the input** ("'light house' is very close —
  only you can see this") instead of impersonating a chat line, making its
  private-to-you nature (R-GUESS-03) visible instead of implied.
- The artboard is honestly drawn **from Bruno's seat**; the shipped mockup
  showed a guesser screen with the drawer's sidebar, which no player can see.

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
- **One primary action** (*Back to waiting room*); highlights and drawings are
  secondary. The auto-continue becomes an honest caption — *"Heading back
  automatically in 7s · stay here"* — restoring player control (§1.3).

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

Kept deliberately utilitarian, but on the same tokens:

- Live counts note "resets on restart" (the R-OBS-01 property, stated where
  an operator will read it); the recorder line gains a health chip and
  "nothing dropped" (surfacing R-OBS-03's drop counter when it's zero, too).
- Report reasons become **severity-tinted chips**; pinned evidence sits in a
  labeled quote block — *"as the reporter received them"* — wording the
  server-side guarantee of R-MOD-03.
- **Suspend and its duration fuse into one split button** (§1.8): the chosen
  duration is visibly part of the action. Broken full-width selects are gone.

### Reset password (`AccountRecovery`)

Same form, on brand: wordmark, one primary action, quiet back link — the
first screen a locked-out player sees no longer looks like a different
product.

---

## 4. Worth fixing regardless of any redesign

Findings that are app defects or requirement mismatches on their own:

1. `.header-action-link` has no color — the lobby *Prompt stats* link is
   browser-blue (already in the mockups README §6).
2. `.waiting-invite-button` is dead CSS; the waiting room ships without an
   invite affordance (README §6).
3. **Drawing time UI contradicts R-ROOM-04** — a stepper for a fixed preset
   list.
4. Moderation's `width: 100%` selects inside flex rows break the action-row
   layout.
5. Emoji-as-icons render inconsistently across platforms and can't follow a
   theme (dark mode ships today; the emoji don't adapt).
6. The turn-results overlay's content exceeds what `TURN_RESULTS_SECONDS = 5`
   allows anyone to read — either the overlay slims down (this proposal) or
   the constant grows.
7. No screen exists for the choosing phase in the mockup suite; it's a real
   phase (R-GAME-01) and should be covered by the reference canvas.

## 5. What was deliberately kept

- The three-column room layout (players / stage / chat) — it matches how the
  game is actually watched, and R-UX-01's viewport rule.
- Chat-as-guess-input — guessing *is* chatting in this genre; the redesign
  clarifies the input's role rather than splitting it into two boxes.
- Player colors, the story, all copy facts, and the server-driven truth of
  every number shown — the redesign adds no data the backend doesn't already
  have.
- Light theme only and desktop widths only, matching the existing canvas's
  documented deviations.

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
