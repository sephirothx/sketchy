# Sketchy on phones

A UI/UX review of every Sketchy screen **as it behaves on a portrait phone**, and
the layouts that answer it. The desktop set one directory up
([`../sketchy-redesign-rationale.md`](../sketchy-redesign-rationale.md)) is
explicitly "desktop widths only"; this is the other half.

- **The artboards** — 15 screens, 19 of them, each rendered as a light/dark pair
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
and a full three-round game was played through. Every measurement below is from
that session, not estimated.

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
   the other bands leave — deriving the other side from 4:3. The clock is a
   numeral beside the letter tiles with the depleting rule under it; the pip row
   and one line of feed survive; the verdict on your own guess is a chip above
   the field that stays until you type again. Measured at a 508 px viewport:
   canvas **375 × 281** against the old 378 × 284, so none of it is paid for out
   of the drawing.
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
   → The palette is out permanently, two scrollable rows of 40 px swatches, in a
   dock at the bottom of the screen. The dock renders into a slot after the chat
   region (`#room-shell-dock`), so it lands under the thumb rather than between
   canvas and feed. Tool and size keep small popovers; neither is reached
   anything like as often as a colour.
4. **Turn results were crammed into a 250 px box.** `.turn-results-overlay` is
   `position:absolute; inset:0` *inside the canvas*, and the panel was
   `max-height:90%` of a 278 px canvas: the word, your score, the guess order,
   the standings and the progress bar all competing for it, with the bottom of
   the standings below the clipped edge, while the bottom 45% of the phone was
   an idle chat card and 164 px of nothing.
   → A sheet at 74%, so the drawing you were staring at stays visible above the
   answer.
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
   thumb away, and the player list moves above chat: who is here is what you
   actually watch while you wait.
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
- **The clock is always a number.** The countdown ring runs in the status band
  on phones too; when the keyboard hides that band, the numeral beside the
  letter tiles carries it, with the depleting rule beneath for peripheral read.
- **The race stays visible.** The pip row shows who has guessed and in what
  order — the state that frozen eligibility (R-GUESS-05) and the drawer bonus
  (R-SCORE-08) both turn on.
- **One loud control per screen**; destructive actions live behind a sheet or a
  confirm, never beside routine ones.
- **44 px minimum targets**, including buyable hint tiles and wheel letters.
- Overlays are **bottom sheets** rather than boxes floating on the canvas, so
  the drawing stays visible above them. Above 900 px the same `BottomSheet`
  markup centres as an ordinary dialog.

## Landscape

Turned sideways, the palette becomes a rail on the holding side, the feed a
narrow column, and the canvas takes everything between: **405 × 304 against
375 × 281 in portrait**, about 1.2× the area. The side columns are kept
deliberately tight, because every pixel they take comes straight off the canvas.

## Corrections

Two claims in the original review were wrong, and the artboards still carry
them:

- **The room code was never six inputs.** `RoomCodeInput` is a single field with
  six cells rendered beside it, already carrying `autoCapitalize="characters"`
  and `enterKeyHint="go"`. The six-boxes-six-focus-stops complaint (artboards 01
  and 02) does not apply; nothing needed changing.
- **Landscape does not double the drawing area.** Artboard 06-B claims
  520 × 390, which assumed the canvas could use the full 844 px of width. The
  palette rail and the guess feed take about 220 px of it, so the real figure is
  405 × 304 — a 1.2× gain, not 2×. Worth having, but not the transformation the
  artboard promised.

## Where the build departs from the artboards

- **The lobby keeps its existing structure**, reordered rather than rebuilt:
  open rooms move to the top, the entry copy is hidden, and Spectate becomes a
  link. The docked create/join bar and the join-code sheet (artboards 01–02)
  are not built.
- **Create a room keeps its single scrolling form.** The overflow bug is fixed;
  the preset row and the two-step *More options* split (artboard 03) are not.
- **Game over keeps its separate highlights and drawings panels** rather than
  folding them into tabs on the result screen (artboard 10). It does drop to one
  primary action.
- **Turn results and the waiting room** keep their existing content; only their
  placement changed (sheet, and sticky start).

## The screens

| # | Screen | Artboard variants |
| --- | --- | --- |
| 01 | Lobby | A · rooms first · B · one big play |
| 02 | Join with a code | sheet over the keyboard |
| 03 | Create a room | basics + presets, rest behind *More options* |
| 04 | Waiting room | invite-first, docked start |
| 05 | Pick a prompt | choices in the thumb zone |
| 06 | Drawing | A · palette always out · B · landscape focus |
| 07 | Guessing | keyboard closed |
| 08 | Guessing, keyboard up | A · nothing overlaps · B · HUD over the drawing · C · correct guess |
| 09 | Turn results | bottom sheet |
| 10 | Game over | podium, one primary, highlights and drawings as tabs |
| 11 | The drawings | swipe gallery |
| 12 | Players & score | bottom sheet |
| 13 | Settings | full-screen grouped rows |
| 14 | Profile | stat tiles and a guess-speed sparkline |
| 15 | Prompt stats | cards, one *Filters* sheet, paged |

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
