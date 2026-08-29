# Sketchy on phones

A UI/UX review of every Sketchy screen **as it behaves on a portrait phone**, and
the mockups that answer it. The desktop set one directory up
([`../sketchy-redesign-rationale.md`](../sketchy-redesign-rationale.md)) is
explicitly "desktop widths only"; this is the other half.

- **The mockups** — 15 screens, 19 artboards, each rendered as a light/dark pair
  at a true 390 × 844, with a real soft keyboard drawn where the keyboard is part
  of the problem:
  <https://claude.ai/code/artifact/afdba7d2-a8b0-4374-80e1-af68510f72ff>
  ([`index.html`](index.html) is the source and the same page — one self-contained
  file, no build step. Open it from disk, or publish it as an Artifact.)
- Same story as the desktop canvas — room *Coffee break doodles*, code `BQ7F2K`,
  round 2, Marta drawing *lighthouse* — so the two sets can be read side by side.

**These are proposals, not a record of what ships.** Nothing here is implemented.
Where a note says "today", it describes the behaviour measured on `51bf7da`.

## How the review was done

The app was run at a genuine 390 px viewport (inside a sized iframe, since the
usual emulation left `window.innerWidth` at the pane's own width and the
breakpoints never fired) with a headless Socket.IO client as the second player,
and a full three-round game was played through. Every "today" number below is
measured from that session, not estimated.

## What the phone build gets wrong

Sorted by how much it costs a player.

1. **The keyboard-open guesser loses the game.** Focusing the guess field adds
   `.guess-focused`, which sets `display:none` on the header, the round line, the
   chat heading and the whole message list. While you type — which is most of a
   turn — you cannot see other players' guesses, who just scored, the round, or
   the score. The clock becomes a **6 px rule at y 49–55 with 49 px of empty
   space above it**, and no number anywhere, in a game whose points decay per
   second. A further 49 px sits unused between canvas and field.
2. **`/create` overflows horizontally on every common phone.** `.create-room-sections`
   is a bare `display:grid`, so its implicit `auto` column sizes to a 402 px card
   inside a 358 px track: `scrollWidth 419` against `innerWidth 390`. The
   room-name field, both visibility toggles and all three steppers are clipped.
   The fix is `grid-template-columns: minmax(0, 1fr)`; this one is a live bug
   rather than a design opinion.
3. **The colour popover covers the whole canvas.** The drawer cannot see what
   they are colouring, and every colour change costs two taps and a look-away.
   Tools sit in a 66 px strip in the *middle* of the screen, the hardest region
   to reach, between canvas and chat.
4. **Turn results are crammed into a 250 px box.** `.turn-results-overlay` is
   `position:absolute; inset:0` *inside the canvas*, and the panel is
   `max-height:90%` of a 278 px canvas. The word, your score, the guess order,
   the standings, the progress bar and the button all compete for it; the button
   and the bottom of the standings fall below the clipped edge. Meanwhile the
   bottom 45% of the phone is an idle chat card and 164 px of nothing.
5. **Confetti at `z-index: 9999` paints over everything** — the results panel,
   the players drawer (`z-index: 1200`), the settings dialog, the game-over
   copy. On a 390 px screen the same particle count lands on a third of the
   area, so "Marta isn't saved…" is genuinely unreadable.
6. **The guess field renders above the message list** (`.chat-input { order: -1 }`),
   so you type at the top and read below, and new messages travel away from the
   caret.
7. **Start game sits at y = 822 on an 844 px screen**, clipped by the fold, on a
   1 376 px page whose player list is dead last at y 1 153–1 360 — below the chat.
8. **Hint tiles are 19 × 26 px tap targets** in buy-a-letter and Wheel modes
   (`.masked-tile.hint-blank` is a `<button>`); wheel letters are about 28 × 22.
   Both are far under 44 × 44 (iOS) and 48 × 48 (Android).
9. **Who has already guessed is invisible during play** — `.room-shell-players`
   is `display:none` while playing, and the drawer slide-out covers 74% of the
   width, full height, for two rows of content.
10. **Prompt stats is a 25 496 px page** — 592 unpaginated rows, five stacked
    native `<select>`s, and a table clipped at the right edge with no scroll
    affordance.
11. **Settings is a 340 × 699 desktop dialog** with 901 px scrolling inside it,
    including a **Shortcuts tab** offering keyboard bindings on a touch device.

## The layout contract the mockups apply

Every in-game screen is the same three bands, pinned to `visualViewport`, never
page-scrolled:

    ┌──────────────────────────┐
    │ status band     ~56 px   │  code · round · countdown ring · ⋯
    ├──────────────────────────┤
    │ stage           flex     │  canvas, tiles, feed
    ├──────────────────────────┤
    │ dock            auto     │  the primary action, in the thumb zone
    └──────────────────────────┘

- **The canvas is 4:3 and that is not negotiable** — 800 × 600 is baked into the
  wire protocol, so at 390 px wide it can never exceed ~292 px tall. The
  redesign spends the other two thirds rather than fighting the ratio, and
  offers a landscape focus mode (520 × 390, twice the drawing area) for anyone
  who wants to actually draw.
- **The clock is always a number.** The ring collapses to a numeral beside the
  word tiles when the keyboard is up, with the depleting rule underneath for
  peripheral read. Both go red at 10 s.
- **The race stays visible.** A pip row shows who has guessed, in what order,
  and who is still hunting — the state that frozen eligibility (R-GUESS-05) and
  the drawer bonus (R-SCORE-08) both turn on, and which is currently invisible.
- **One loud control per screen.** Destructive actions (Leave, Clear) move
  behind a sheet or a confirm, never adjacent to routine ones.
- **48 px minimum targets, 8 px apart**, including buyable hint tiles.
- Overlays are **bottom sheets**, not boxes floating on the canvas, so the
  drawing stays visible above them.

Implementation notes carried in the artboard captions: add
`interactive-widget=resizes-content` to the viewport meta, keep the existing
`useVisualViewportCssVars` vars, prefer `position:sticky` to `fixed` for the
dock, and drop the confetti canvas below the dialog layer with a 2.5 s cap.

Measured against today, the keyboard-open guesser keeps the canvas at the same
size — **374 × 284 against today's 378 × 284** — and gains the countdown, the
pips, a live feed line and a persistent verdict chip in the space currently
spent on nothing.

## The screens

| # | Screen | Proposals |
| --- | --- | --- |
| 01 | Lobby | A · rooms first · B · one big play |
| 02 | Join with a code | sheet over the keyboard |
| 03 | Create a room | basics + presets, rest behind *More options* |
| 04 | Waiting room | invite-first, docked start |
| 05 | Pick a prompt | choices in the thumb zone |
| 06 | Drawing | A · palette always out · B · landscape focus |
| 07 | Guessing | keyboard closed |
| 08 | Guessing, keyboard up | A · nothing overlaps · B · HUD over the drawing · C · correct guess |
| 09 | Turn results | bottom sheet at 62% |
| 10 | Game over | podium, one primary, highlights and drawings as tabs |
| 11 | The drawings | swipe gallery |
| 12 | Players & score | bottom sheet at 55% |
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
