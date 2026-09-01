# Sketchy on phones

A UI/UX review of every Sketchy screen **as it behaves on a portrait phone**, and
the layouts that answer it. The desktop set one directory up
([`../sketchy-redesign-rationale.md`](../sketchy-redesign-rationale.md)) is
explicitly "desktop widths only"; this is the other half.

- **The artboards** — 17 screens, 23 of them, each rendered as a light/dark pair
  at a true 390 × 844, with a real soft keyboard drawn where the keyboard is part
  of the problem:
  <https://claude.ai/code/artifact/afdba7d2-a8b0-4374-80e1-af68510f72ff>
  ([`index.html`](index.html) is the source and the same page — one self-contained
  file, no build step. Open it from disk, or publish it as an Artifact.)
- Same story as the desktop canvas — room *Coffee break doodles*, code `BQ7F2K`,
  round 2, Marta drawing *lighthouse* — so the two sets can be read side by side.

**This has shipped.** These artboards are the reference for the phone build the
way the desktop set is for the wide one. Where a note says "used to", it
describes behaviour measured on `51bf7da`, before the change. §"Where the build
departs from the artboards" records the deviations, and §"Corrections" the two
claims in the original review that did not survive contact with the code.

## How the review was done

The app was run at a genuine 390 px viewport (inside a sized iframe, since the
usual emulation left `window.innerWidth` at the pane's own width and the
breakpoints never fired) with a headless Socket.IO client as the second player,
and a full three-round game was played through. The two cold-arrival states —
opening the site with no account and no name, and tapping an invite link in the
same condition — were measured separately, by clearing the session through
`POST /api/auth/logout` and reloading. Every measurement below is from those
sessions, not estimated.

## What it got wrong, and what it does now

Sorted by how much it cost a player.

1. **The keyboard-open guesser lost the game.** Focusing the guess field adds
   `.guess-focused`, which set `display:none` on the header, the round line, the
   chat heading and the whole message list. While you typed — which is most of a
   turn — you could not see other players' guesses, who had just scored, the
   round, or the score. The clock became a **6 px rule at y 49–55 with 49 px of
   empty space above it**, and no number anywhere, in a game whose points decay
   per second. A further 49 px sat unused between canvas and field.
   → The playing shell is three bands pinned to the visible viewport, and the
   canvas takes whichever cap binds first — the column's width, or the height
   the other bands leave — deriving the other side from 4:3.

   With the keyboard up, everything that is not the drawing or the field you
   type into goes: the clock numeral, the pip row and the feed are all things a
   guesser reads *between* guesses, and the depleting rule alone says "running
   out" without costing a line. What survives is the letter tiles, that rule,
   the canvas, and the composer — which is the letter counts, the field and the
   send button, with no panel drawn around them, because a surface, a border
   and a shadow around a single text field is chrome around emptiness. The
   verdict on your own guess is a chip above the field, the one piece of
   feedback that is about the guess being typed; it hangs over the canvas when
   the canvas reaches that far, translucent over a blur so the strokes stay
   readable through it. Measured against keeping the pips and a line of feed: **390 × 293 vs
   349 × 262** at a 480 px viewport, **387 × 290 vs 296 × 222** at 440. At 520
   and up both reach 390 × 293, which is the protocol ceiling at this width.
2. **`/create` overflowed horizontally on every common phone.**
   `.create-room-sections` was a bare `display:grid`, so its implicit `auto`
   column sized to a 402 px card inside a 358 px track: `scrollWidth 419`
   against `innerWidth 390`. The room-name field, both visibility toggles and
   all three steppers were clipped.
   → `grid-template-columns: minmax(0, 1fr)`. A live bug rather than a design
   opinion, and the one change here that is not about phones specifically.
3. **The colour popover covered the whole canvas.** The drawer could not see
   what they were colouring, and every colour change cost two taps and a look
   away. Tools sat in a 66 px strip in the *middle* of the screen, the hardest
   region to reach, between canvas and chat.
   → The strip moved rather than grew. The toolbar renders into a slot after the
   chat region (`#room-shell-dock`), so it lands under the thumb rather than
   between canvas and feed, and it stays a row of collapsed chips — tool,
   colour, size, undo, clear — each opening a popover above itself. Trying it
   with the palette permanently unrolled cost the canvas two rows of swatches
   for a control that is one tap away, and the original complaint was about
   *where* the controls sat, which the dock already answers.
4. **Turn results were crammed into a 250 px box.** `.turn-results-overlay` is
   `position:absolute; inset:0` *inside the canvas*, and the panel was
   `max-height:90%` of a 278 px canvas: the word, your score, the guess order,
   the standings and the progress bar all competing for it, with the bottom of
   the standings below the clipped edge, while the bottom 45% of the phone was
   an idle chat card and 164 px of nothing.
   → A sheet that takes what it needs, so the drawing you were staring at stays
   visible above the answer. The panel itself never scrolls: it is a column
   whose standings take what is left and scroll inside themselves, so the word,
   your score and the countdown cannot be pushed below the fold — which is what
   a single scrolling block did to the countdown, the one thing that tells you
   how long you have to read the rest.

   Two things were removed rather than fitted. A "Correct guesses" list under
   its own heading repeated every name that the standings underneath were
   already listing; the only thing it carried that they did not was when each
   player got it, which now sits on their own row. And the drawer's row said
   the same thing twice over: a pencil chip reading "drew" beside the name, and
   a bonus beside the score that the score delta already contained. One brush
   against the delta, in its own colour, says both.
5. **Confetti at `z-index: 9999` painted over everything** — the results panel,
   the players drawer (`z-index: 1200`), the settings dialog, the game-over
   copy. On a 390 px screen the same particle count lands on a third of the
   area, so "Marta isn't saved…" was genuinely unreadable.
   → `z-index: 999`: above the page (which tops out around 120), below every
   dialog, drawer, sheet and toast (all ≥ 1000). Particles also fade in ~2.5 s
   rather than 4+, and the canvas is `100dvh` rather than `100vh`.
6. **The guess field rendered above the message list** (`.chat-input { order:
   -1 }`), so you typed at the top and read below, and each new message
   travelled away from the caret.
   → The field reads below the feed, as in every other messaging surface.
7. **Start game sat at y = 822 on an 844 px screen**, clipped by the fold, on a
   1 376 px page whose player list was dead last at y 1 153–1 360, below chat.
   → Start is `position: sticky` at the bottom of the waiting room, always one
   thumb away, and who is here comes before chat as a grid of faces with the
   ready state on the tile — the phone's version of the players column, which
   is not rendered at all below 900px because it would put every nickname on
   the page twice. The eight-chip settings summary is one line that opens the
   editor. The page goes from 1 432px to 988.
8. **Hint tiles were 19 × 26 px tap targets** in buy-a-letter and Wheel modes
   (`.masked-tile.hint-blank` is a `<button>`); wheel letters about 28 × 22.
   Both far under 44 × 44 (iOS) and 48 × 48 (Android).
   → 44 × 44 minimums on both, and tiles at 29 × 38 on phones so the letters are
   worth reading. Popover swatches went 36 → 44.
9. **Who had already guessed was invisible during play** —
   `.room-shell-players` is `display:none` while playing, and the drawer
   slide-out covered 74% of the width, full height, for two rows of content.
   → A pip row under the canvas shows who has it, in what order, and who is
   still hunting. The row is itself the way into the players sheet, which rises
   to 55% and leaves the canvas visible.
10. **Prompt stats was a 25 496 px page** — 592 unpaginated rows, five stacked
    native `<select>`s, and a table clipped at the right edge with no scroll
    affordance (the `.prompt-stats-table-scroll` wrapper had no rule).
    → Paged 40 at a time with the total stated, rows become cards below 900 px,
    and the wrapper scrolls.
11. **Settings was a 340 × 699 desktop dialog** with 901 px scrolling inside it,
    including a **Shortcuts tab** offering keyboard bindings on a touch device.
    → Full-screen sheet below 900 px, and the Shortcuts tab is hidden when
    `(pointer: fine)` does not match — keyed on the pointer rather than the
    width, so a tablet with a keyboard keeps it.
12. **Arriving from an invite put Join below the fold.** Cold at 390 × 844 the
    actions sat at **y 839–937** on an 844 px screen, under 380 px of room
    configuration (a 2×2 table of Players / Rounds / Draw time / Scoring, then
    four chips) and 315 px of account decision — on a screen reached by
    somebody who had already decided to play. The page was 990 px for what is
    fundamentally a yes.
    → The settings fold behind one summary line on phones (open by default on
    a wide screen, where there is room). Join moves to **y 604** and the page
    fits in 844. Spectate becomes a link, and the name field's own button
    steps back to secondary inside the invite card, since **Join already
    commits a typed name** — the two-step was never required.
13. **The first landing led with an account decision.** A visitor who has
    never seen the game met *"Play as yourself · Keep your username and your
    stats on every device"* first, with the fastest path — type a name, play —
    lowest and quietest, under a divider and a label reading "Just playing
    once?".
    → On phones the block is one field and one loud **Play**, with Create an
    account and Log in as a single quiet line underneath. The account offer is
    made again at the end of the first game, where the game-over screen already
    asks it and there is finally something worth keeping. Wide screens keep the
    shipped order, which was a considered decision for a surface with room for
    both. An earlier draft of this screen opened with a tagline; it was cut, so
    the screen is one decision tall and the rooms below say what the game is.

The wordmark is on every page now, sub-pages included. It used to be replaced
by the back button there, so the one screen a first-time visitor might arrive
on from a link was the one that never said whose site it was. On a phone the
back control is the arrow alone, with the label kept as its accessible name.

Alongside those: the eight-icon header strip — which put a red **Leave** one
thumb-width from **Settings** — is now a code chip, the round and countdown
ring, and a ⋯ sheet holding the rest as labelled rows, with leaving separated
and styled as the destructive thing it is. Game over drops from five
near-equal actions to one loud **Continue**. The drawings recap gains horizontal
swipe and a dot pager. The lobby puts open rooms first and demotes **Spectate**
from a twin primary to a link.

## The layout contract

Every in-game screen is the same three bands, pinned to the visible viewport,
never page-scrolled:

    ┌──────────────────────────┐
    │ status band     ~56 px   │  code · round · countdown ring · ⋯
    ├──────────────────────────┤
    │ stage           flex     │  prompt + clock, canvas, guessed pips
    ├──────────────────────────┤
    │ dock            auto     │  the palette, or the guess field
    └──────────────────────────┘

- **The canvas is 4:3 and that is not negotiable** — 800 × 600 is baked into the
  wire protocol, so on a 390 px-wide phone it can never exceed ~293 px tall. The
  layout spends the rest rather than fighting the ratio.
- **The shell height is `min(var(--vv-height), 100dvh)`.** The two signals
  disagree in both directions: iOS resizes the visual viewport but not the
  layout one, so `dvh` stays tall with the keyboard up and `--vv-height` is
  right; and if a `visualViewport` resize is ever missed, `--vv-height` goes
  stale tall and `dvh` is right. The minimum means the dock cannot be pushed off
  the bottom by either. `interactive-widget=resizes-content` was already in the
  viewport meta.
- **The clock is a number, until the keyboard is up.** The countdown ring runs
  in the status band on phones; with the keyboard up the band goes and only the
  depleting rule beneath the letter tiles remains, because a rule reads at a
  glance and digits cost a line of canvas.
- **The race is visible between guesses.** The pip row shows who has guessed and
  in what order — the state that frozen eligibility (R-GUESS-05) and the drawer
  bonus (R-SCORE-08) both turn on. It is hidden while typing, along with the
  feed, and comes back the moment the keyboard does.
- **`orientation: landscape` is not a phone lying on its side.** It is a
  viewport wider than it is tall, which a portrait handset with a big soft
  keyboard also is. Every landscape rule carries `min-width: 600px` for that
  reason; without it a 360 × 340 Android with the keyboard up got the two-column
  rail layout and a 76 px-wide guess field.
- **One loud control per screen**; destructive actions live behind a sheet or a
  confirm, never beside routine ones.
- **44 px minimum targets**, including buyable hint tiles and wheel letters.
- Overlays are **bottom sheets** rather than boxes floating on the canvas, so
  the drawing stays visible above them. Above 900 px the same `BottomSheet`
  markup centres as an ordinary dialog.

## Landscape

Turned sideways, the toolbar chips stack into a rail on the holding side, the
feed becomes a narrow column, and the canvas takes everything between:
**403 × 302 against 375 × 281 in portrait**, about 1.15× the area. The side
columns are kept deliberately tight, because every pixel they take comes
straight off the canvas — the guess pips are dropped here for the same reason,
since the feed already says who has guessed.

Popovers open *sideways* out of the rail, over the canvas. Anchored above their
chip, as they are in portrait, they had nowhere to go: the rail is full height,
so `bottom: calc(100% + 8px)` put them off the top of the screen. Covering part
of the drawing for as long as a colour takes to pick is the cheaper trade.

## Corrections

Two claims in the original review were wrong, and the artboards still carry
them:

- **The room code was never six inputs.** `RoomCodeInput` is a single field with
  six cells rendered beside it, already carrying `autoCapitalize="characters"`
  and `enterKeyHint="go"`. The six-boxes-six-focus-stops complaint (artboards 01
  and 02) does not apply; nothing needed changing.
- **Landscape does not double the drawing area.** Artboard 06-B claims
  520 × 390, which assumed the canvas could use the full 844 px of width. The
  toolbar rail and the guess feed take about 220 px of it, and height binds
  before width does, so the real figure is 403 × 302 — a 1.15× gain, not 2×.
  Worth having, but not the transformation the artboard promised.

## Where the build departs from the artboards

- **First landing ships variant A**: one field, one Play, and the account offer
  as a quiet line, with the rooms list below it. Variant B — browse freely with
  a sticky name dock — is not built; it trades a visitor being able to scroll a
  long way without ever learning they need a name against a much lower barrier
  to looking, and that is a product call rather than a layout one.

- **The lobby keeps its existing structure**, reordered rather than rebuilt:
  open rooms move to the top, the entry copy is hidden, and Spectate becomes a
  link. The docked create/join bar and the join-code sheet (artboards 01–02)
  are not built.
- **Create a room keeps its single scrolling form.** The two-step *More
  options* split (artboard 03) is not built. What is: the docked Create bar,
  with the summary of what is about to be created beside it, so the point of
  the page is under the thumb from the first screen rather than at the end of
  settings most people never change; and the three numbers as full-width rows,
  label left and stepper right, in one card with dividers — 184px against the
  273px they took as stacked cards, with 44px ± targets. Three across, which
  the artboard warns off, cannot hold a 44px target on a phone: it overflowed
  by 3px at 360 and 10px at 320.

  Their hints are gone. The ranges are enforced by the controls, "everyone
  draws once per round" is what a round is, and the line under them already
  says what the three add up to in minutes.

  The overflow bug is fixed, and a second one of the same kind with it:
  `.setting-cards` was `repeat(3, 1fr)`, whose implicit per-column minimum is
  the column's content, so it laid out a 560px row inside a 390px phone.
- **Game over keeps its separate highlights and drawings panels** rather than
  folding them into tabs on the result screen (artboard 10). It does drop to one
  primary action, and it takes the screen: on a phone it was a section inside
  the stacked room page, players panel above and chat below, so at 390 x 844
  the document was 1671px tall and the result was something you scrolled to.
  It is a fixed layer now, a column whose standings scroll inside themselves
  while the result, the podium and the way out stay put. Everything above the
  podium was paying for that: 44px of confetti over a headline that is already
  the celebration, a headline at 28px that wrapped to three lines, and an
  account nudge that took 116px to say one sentence. With six players the panel
  is 643px inside a 667px viewport with nothing clipped and nothing scrolling
  but the standings.

  The compact treatment is keyed on `(max-width: 900px), (max-height: 780px)`,
  because what runs out is vertical: a 1024 x 700 desktop window had the same
  problem, and being `overflow: hidden` it clipped the buttons rather than
  scrolling to them.
- **Turn results** keeps its existing content; only its placement changed.
- **The waiting room is the artboard**, minus the ⋯ status band and the chat
  dock tab: invite hero, the roster grid, one settings line, docked start.
  Chat stays a card below rather than a tab.
- **The host's editor is the creation form.** Both render one
  `RoomSetupForm` — the same four sections in the same order — where the
  editor used to be a flat column of the same controls, so the same room was
  described two different ways depending on which screen you were on.
- **Settings are a draft, saved in one piece.** Every field used to go to the
  server as it was touched, which was right when settings were a panel
  permanently open beside the room. Behind a dialog it is wrong: a half-made
  decision is not a decision, and every intermediate value on the way to "5
  rounds" was broadcast to everyone waiting. Measured: two stepper presses and
  a prompt list now cost the room one `room_state`, where before each settled
  edit cost its own.

## The screens

**Bold** is the variant that ships; the viewer marks the same ones *built*.

| # | Screen | Artboard variants |
| --- | --- | --- |
| 01 | First landing | **A · name and go** · B · browse first · C · naming, keyboard up |
| 02 | Arriving from an invite | invite landing |
| 03 | Lobby | **A · rooms first** · B · one big play |
| 04 | Join with a code | sheet over the keyboard |
| 05 | Create a room | basics + presets, rest behind *More options* |
| 06 | Waiting room | invite-first, docked start |
| 07 | Pick a prompt | choices in the thumb zone |
| 08 | Drawing | **A · palette always out** · **B · landscape focus** (both) |
| 09 | Guessing | keyboard closed |
| 10 | Guessing, keyboard up | **A · nothing overlaps** · B · HUD over the drawing · **C · correct guess** |
| 11 | Turn results | bottom sheet |
| 12 | Game over | podium, one primary, highlights and drawings as tabs |
| 13 | The drawings | swipe gallery |
| 14 | Players & score | bottom sheet |
| 15 | Settings | full-screen grouped rows |
| 16 | Profile | stat tiles and a guess-speed sparkline |
| 17 | Prompt stats | cards, one *Filters* sheet, paged |

The admin, moderation and bug-report surfaces are deliberately absent: they are
operator tools, and the desktop artboards remain their reference.

## Sources

Mobile-specific research consulted for the layout contract:

- [Prevent content from being hidden underneath the Virtual Keyboard (Bram.us)](https://www.bram.us/2021/09/13/prevent-items-from-being-hidden-underneath-the-virtual-keyboard-by-means-of-the-virtualkeyboard-api/)
  and [Fix mobile keyboard overlap with visualViewport (DEV)](https://dev.to/franciscomoretti/fix-mobile-keyboard-overlap-with-visualviewport-3a4a) —
  iOS resizes the visual viewport but not the layout viewport, Android resizes
  both; `interactive-widget=resizes-content`, `dvh`, and sticky over fixed.
- [Tap targets and thumb zones beyond the 44px rule (72Technologies)](https://www.72technologies.com/blog/tap-targets-thumb-zones-mobile-ux)
  and [Mastering the thumb zone (Parachute Design)](https://parachutedesign.ca/blog/thumb-zone-ux/) —
  primary actions in the lower two thirds; 44 pt / 48 dp floors.
- [Designing for mobile, iOS and Android (Smart Interface Design Patterns)](https://smart-interface-design-patterns.com/articles/designing-for-mobile-ios-android-guide/) —
  sheet-based modals with bottom-anchored actions on both platforms.
- [Doodle Duel vs skribbl.io](https://doodleduel.ai/blog/doodle-duel-vs-skribbl-io-comparison) —
  the genre's own account of what breaks when a desktop drawing game is opened
  on a phone: tiny canvas, chat eating the screen, keyboard covering the drawing.
