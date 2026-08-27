# Wire protocol

The complete contract between the Sketchy browser client and the Sketchy server:
transport, framing, every Socket.IO event in both directions, the binary drawing and
canvas-history formats, and the REST surface.

Companion documents: [`architecture.md`](architecture.md) ·
[`database.md`](database.md) · [`requirements.md`](requirements.md) ·
[`../GLOSSARY.md`](../GLOSSARY.md)

> **The rule that governs this document.** Nothing in either language checks that the
> two sides agree on a name. A payload key is a plain string in Python and a plain
> property in TypeScript, so a rename on one side compiles, lints, and passes every
> other test while the feature silently stops working.
> [`backend/tests/test_wire_contract.py`](../backend/tests/test_wire_contract.py) is the
> only thing that catches it. **Rename on both sides in one change, and update this
> document in the same change.**

---

## 1. Transport

| Concern | Value |
| --- | --- |
| Socket.IO path | `/socket.io` (mounted by `socketio.ASGIApp`, [`backend/app/main.py:266`](../backend/app/main.py)) |
| Client transports | `["websocket", "polling"]` ([`frontend/src/lib/socket.ts:13`](../frontend/src/lib/socket.ts)) |
| Origin | Always same-origin: the backend serves the built SPA in production and E2E, and Vite proxies `/api` and `/socket.io` in dev |
| Authentication | The HttpOnly `sketchy_session` cookie, read from `HTTP_COOKIE` at handshake |
| REST base | `/api`, relative to whatever origin served the page |
| Default ack timeout | 8000 ms (`DEFAULT_ACK_TIMEOUT_MS`) |

The client does **not** auto-connect. The handshake reads the session cookie exactly
once, and on a first visit that cookie does not exist until `GET /api/auth/me` has
provisioned the account, so `App.tsx` connects only after identity has settled.

### Handshake

[`backend/app/handlers/connection.py:22`](../backend/app/handlers/connection.py) resolves
the cookie to a session record and stores `{"user_id": …}` on the Socket.IO session.

- No cookie → `user_id = None`. The visitor plays normally, without reconnect or
  history. **Opening a socket never creates a user row.**
- An active suspension → the handshake is refused with
  `ConnectionRefusedError("This account is suspended.")`, surfacing to the client as
  `connect_error`.
- A drain already in progress → the socket is immediately sent `server_shutdown`.

---

## 2. Acknowledgement convention

Commands the client needs an answer to are emitted with an acknowledgement callback.
Every acknowledgement is a JSON object sharing these fields
([`frontend/src/types.ts` `AckResponse`](../frontend/src/types.ts)):

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | `boolean` | Whether the command was accepted |
| `error` | `string?` | Human-readable refusal |
| `field` | `string?` | The payload field that failed validation, for form binding |

Command-specific additions, all optional: `roomId`, `code`, `playerId`,
`isAnonymous`, `needsRebind`, `roomFull` (player slots are taken but spectating is
open), `codeRetired` (the code was valid but its ephemeral room has ended),
`serverDraining` (refused because a bounded deployment drain has begun).

A payload that fails validation is refused by
`PayloadError.acknowledgement()` ([`backend/app/handlers/payloads.py:71`](../backend/app/handlers/payloads.py))
as `{"ok": false, "error": …, "field": …}` — before any authorization or mutation runs.

### Client-side delivery guarantees

`emitWithAckOn` ([`frontend/src/lib/socket.ts:67`](../frontend/src/lib/socket.ts))
never hands a packet to a disconnected socket. Socket.IO would queue it and deliver it
on reconnect, and no `disconnect` event would arrive to reject against — so the timeout
would tell the player the action failed while the packet still lands seconds later. On
these paths that means a second room, or a game started twice. Instead:

- **Acknowledged actions** (create a room, join, start, vote to restart) wait for the
  connection and are sent exactly once, or they time out having never been sent.
- **Momentary actions** (`guess`, `vote_player`, `toggle_afk`, `leave_room`) go through
  `emitTransient` ([`frontend/src/lib/socket.ts:148`](../frontend/src/lib/socket.ts)),
  which uses `socket.volatile.emit` so the packet is **dropped** rather than replayed
  into whatever the room has become — a vote cast in a turn that has ended, a guess
  against a prompt nobody is drawing any more, a `leave_room` that evicts the player
  from the room they just rejoined.
- **Live drawing is deliberately not routed through either.** Its frames carry a
  generation and sequence the server checks, and it has an explicit resync path, so
  replay is already answered there (§7).

`SocketRequestError` carries `code: "disconnected" | "timeout"`.

---

## 3. Payload policy for inbound commands

Defined and enforced in
[`backend/app/handlers/payloads.py`](../backend/app/handlers/payloads.py):

- JSON commands accept **objects only**. Commands with no fields also accept `null`.
- **Values are never coerced.** Strings and booleans must have their JSON types;
  integers must be integers and must not be booleans.
- **Unknown fields are rejected** (`extra="forbid"`).
- All strings and integers are **bounded here**, before a handler authorizes or mutates.
- Camel-case wire names are declared as pydantic `Field(alias=…)`; the alias is what the
  client sends.

The drawing protocol is the deliberate exception to the JSON-object rule: `draw`
carries a binary frame (or a bare integer control) plus an optional two-integer action
identity, and `undo_stroke` carries a fixed four-integer array. Both have dedicated
parsers.

Shared bounds:

| Constant | Value | Source |
| --- | --- | --- |
| `MAX_CHAT_MESSAGE_LENGTH` | 500 | [`message_limits.py`](../backend/app/message_limits.py) |
| `MAX_PROMPT_LENGTH` | 32 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_RAW_INPUT_LENGTH` (custom prompts blob) | 400 000 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_CUSTOM_PROMPTS` | 10 000 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_ROOM_NAME_LENGTH` | 40 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_NICKNAME_LENGTH` | 16 (`MAX_NAME_LENGTH`, shared with usernames) | [`auth/names.py`](../backend/app/auth/names.py) |
| `MAX_IDENTIFIER_LENGTH` | 128 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_PROMPT_LISTS` per room | 20 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_CANVAS_SEQUENCE` | 2³¹ − 1 | [`payloads.py`](../backend/app/handlers/payloads.py) |

---

## 4. Client → server events

Registered in each domain's `register(ctx)`. The **Ack** column says whether the
client uses the acknowledgement.

| Event | Payload model | Ack | Handler |
| --- | --- | --- | --- |
| `create_room` | `CreateRoomPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `join_room` | `JoinRoomPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `leave_room` | `EmptyPayload` | — | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_room_preview` | `RoomPreviewPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_room_settings` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `update_room_settings` | `UpdateRoomSettingsPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_custom_prompts` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_recap_drawing` | `RecapDrawingPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `update_player_settings` | `PlayerSettingsPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `rename_player` | `RenamePlayerPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `become_player` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `session_ping` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `archive_persistent_room` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `accept_colorblind_suggestion` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `dismiss_colorblind_suggestion` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `start_game` | `EmptyPayload` | ✓ | [`game.py`](../backend/app/handlers/game.py) |
| `select_prompt` | `SelectPromptPayload` | ✓ | [`game.py`](../backend/app/handlers/game.py) |
| `draw` | binary frame + optional `[generation, sequence]` | — | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `undo_stroke` | `[generation, sequence, revision, historyHash]` | ✓ | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `request_sync_strokes` | `EmptyPayload` | — | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `send_chat` | `TextPayload` | ✓ | [`chat.py`](../backend/app/handlers/chat.py) |
| `guess` | `TextPayload` | — | [`chat.py`](../backend/app/handlers/chat.py) |
| `buy_hint` | `HintPayload` | ✓ | [`chat.py`](../backend/app/handlers/chat.py) |
| `buy_wheel_letter` | `WheelLetterPayload` | ✓ | [`chat.py`](../backend/app/handlers/chat.py) |
| `toggle_afk` | `ToggleAfkPayload` | — | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `vote_player` | `VotePayload` | — | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `report_player` | `ReportPlayerPayload` | ✓ | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `propose_restart_vote` | `EmptyPayload` | ✓ | [`restart.py`](../backend/app/handlers/restart.py) |
| `cast_restart_vote` | `RestartVotePayload` | ✓ | [`restart.py`](../backend/app/handlers/restart.py) |

### Room settings fields

`RoomSettingsFields` is the shared base for `create_room`; `UpdateRoomSettingsPayload`
mirrors it with every field optional (absent means *unchanged*).

| Wire key | Type | Default | Bounds |
| --- | --- | --- | --- |
| `name` | string | `""` | ≤ 40, trimmed |
| `isPublic` | boolean | `true` | — |
| `maxPlayers` | integer | `8` | 2 – 16 |
| `rounds` | integer | `3` | 1 – 10 |
| `drawingSeconds` | integer | `90` | one of 15, 30, 60, 90, 120, 180, 240, 300 |
| `customPrompts` | string | `""` | ≤ 400 000 chars, trimmed; newline/comma separated |
| `customPromptsOnly` | boolean | `false` | — |
| `hintMode` | string | `"checkpoints"` | `none \| checkpoints \| purchase \| wheel` |
| `scoringMode` | string | `"default"` | `none \| default \| pressure` |
| `spectatorsSeePrompt` | boolean | `false` | — |
| `hideMaskedPrompt` | boolean | `false` | forces hints off |
| `allowedTools` | string[] | `["brush","fill","shapes"]` | at least one of `brush`/`shapes` must remain |
| `colorMode` | string | `"all"` | `all \| palette \| colorblind_safe \| black_and_white` |
| `promptListSlugs` | string[] | `["english_standard"]` | ≤ 20, trimmed/lowercased/deduped; empty ⇒ default on create, refused on update |
| `promptListShareCodes` | string[] | `[]` | ≤ 20, each 8 – 24 chars |

`create_room` adds `persistent` (boolean), `nickname`, `nameColor`
(`#rrggbb`), and `colorblindSafeColors`.

`join_room` takes `roomId` **or** `code` (at least one required; `code` is upper-cased),
plus `nickname`, `nameColor`, `colorblindSafeColors`, `asSpectator`, `soft`, and
`reconnectOnly` — the last used by the invite screen to ask *"do I already hold a seat
here?"* without seating a visitor who is still deciding whether to play or spectate.

> **Names and colors are resolved server-side, not taken from the payload.**
> A registered player always plays as their username and their account color
> ([`backend/app/handlers/identity.py:30`](../backend/app/handlers/identity.py)), so a
> name in the player list is either a claimed account or an unclaimed guest and never
> one impersonating the other. Guests are pinned to the guest grey `#888888`.

### `report_player`

Addresses the reported player **by room seat, never by account**. Room payloads
deliberately carry no account IDs, so a client could not name one even if it wanted to;
the server resolves the seat against the live room and selects the evidence itself.

```jsonc
{ "targetPlayerId": "…", "reason": "harassment", "details": "…" }
```

`reason` ∈ `harassment | offensive_drawing | inappropriate_name | cheating | spam`;
`details` is 1 – 1000 characters.

> Note the deliberate asymmetry: the **socket** report bounds `details` at 1000, while
> the **REST** `POST /api/reports` bounds it at `MAX_REPORT_DETAILS` = 2000 and also
> accepts `contextSnapshot` (≤ 32 768 bytes) and `messageIds` (≤ 20, which must be
> unique). The socket path exists so a player can report from the room without leaving
> it, and the server selects the evidence itself.

---

## 5. Server → client events

| Event | Payload | Scope |
| --- | --- | --- |
| `room_state` | `RoomStatePayload` | room |
| `player_joined` / `player_reconnected` | `{playerId, nickname}` | room |
| `player_left` | `{playerId}` | room |
| `player_disconnected` | `{playerId, nickname}` | room |
| `game_started` | `{}`, or `{restarted: true}` after a restart vote | room |
| `turn_starting` | `{drawerId, drawerNickname, drawerNameColor, roundNumber, totalRounds, seconds}` | room |
| `your_prompt_choices` | `{choices: string[], seconds}` | drawer only |
| `you_are_drawing` | `{prompt}` | drawer only |
| `turn_started` | `{drawerId, maskedPrompt, roundNumber, totalRounds, seconds, hintCost, letterPrices, hintSpend, maxHintSpend}` | **per socket** |
| `sync_game` | same shape as `turn_payload` | one socket |
| `turn_ended` | `TurnEndedPayload` | room |
| `game_ended` | `{scores, highlights, drawings}` | room |
| `chat_message` | `ChatMessage` | room or a filtered recipient list |
| `correct_guess` | `{playerId, nickname, points}` | room |
| `you_guessed_correctly` | `{prompt, points, basePoints, hintSpend}` | guesser only |
| `hint_revealed` | `buy_hint`: `{maskedPrompt, hintCost, hintSpend}`. `buy_wheel_letter`: `{maskedPrompt, letterPrices, hintSpend}` | buyer only |
| `canvas_reset` | `[revision, generation, sequence, historyHash]` | room |
| `draw` | the drawer's exact wire frame, rebroadcast verbatim | room, `skip_sid` drawer |
| `canvas_commit` | `[generation, sequence, revision, historyHash]` | room (or one socket) |
| `canvas_undo` | `[generation, sequence, revisionBefore, revisionAfter, historyHash]` | room (or one socket) |
| `sync_strokes` | `(binaryHistory, revision, generation, sequence, historyHash)` | one socket |
| `request_canvas_actions` | `[generation, expectedSequence, receivedSequence]` | one socket |
| `voted_afk` | `{message}` | the player who was voted AFK |
| `kicked` | `{reason}` | one socket |
| `colorblind_safe_suggestion` | `{active}` | **host only**, unattributed |
| `session_superseded` | `{reason}` — then the socket is disconnected | the superseded socket |
| `account_suspended` | `{detail, suspended, reason, expiresAt, …}` — the same body the HTTP refusal returns | every socket of the suspended account (each socket joins a `user:{id}` broadcast room at connect), which is then disconnected |
| `moderator_warning` | `{warning: {id, reason, createdAt, messages}}` — the same body `GET /api/warnings/pending` returns | every socket of the warned account |
| `server_shutdown` | `ServerShutdownNotice` | every socket |

Plus Socket.IO's own `connect`, `disconnect`, and `connect_error`.

### Key payload shapes

**`room_state`** ([`backend/app/rooms.py:511`](../backend/app/rooms.py) →
`RoomStatePayload` in [`frontend/src/types.ts`](../frontend/src/types.ts)) carries the
room identity (`id`, `code`, `name`, `isPublic`, `isPersistent`), every setting listed
in §4, `state` (`waiting | playing`), `customPromptCount` (a count, never the prompts),
`promptLanguage`, `moderation` (`{eligibleVoterIds, requiredVotes}`), `restartVote`,
`restartVoteCooldownUntil` (epoch ms), the previous game's `lastGameScores`,
`lastGameHighlights`, `lastGameDrawings`, and `players[]`:

```ts
{ playerId, nickname, nameColor?, isAnonymous?, score,
  connected, isHost, isSpectator, isAfk, kickVotes[], afkVotes[] }
```

**Room payloads deliberately carry no account IDs.** Reports, blocks, and profile links
all resolve seats server-side.

**`turn_started`** is emitted per socket because `maskedPrompt`, `hintCost`,
`letterPrices`, and `hintSpend` are private to that viewer. A spectator sees the masked
prompt unless the room enabled `spectatorsSeePrompt`; the drawer sees the answer.

**`chat_message`** (`ChatMessage`) has `id`, `nickname`, `text`, `correct`, and the
optional `retainedMessageId`, `playerId`, `nameColor`, `isAnonymous`, `system`, `close`
(a near-miss hint), `restricted` (delivered only to the drawer, spectators, and correct
guessers), and `isSpectator`. Room-authored announcements use
`system_chat_message()` ([`backend/app/presenters.py:13`](../backend/app/presenters.py)),
which is authorless by construction so no caller can accidentally attribute one to a
player.

**Blocking is a presentation filter only.** When a sender is blocked, the recipient
list is narrowed for that one `chat_message`
([`backend/app/handlers/chat.py:27`](../backend/app/handlers/chat.py)); the sender still
sees their own line, and room state, players, scores, turns, correct-guess events,
votes, and announcements keep normal room-wide delivery. Blocking never creates a
different game state per player.

**`turn_ended`** carries `prompt`, `drawerId`, `drawerBonus`, `seconds`, the ordered
`guesses[]` (each with the guesser's `seconds`), and `scores[]` — each entry carrying
`score`, `delta`, `previousRank`, and `newRank` so the client can animate the standings
without recomputing ranks. Ranks use standard competition ranking (1, 2, 2, 4) via
`competition_ranks()` ([`backend/app/game.py:53`](../backend/app/game.py)), shared with
the recorded standings so the final screen and the history row can never disagree.

**`server_shutdown`**:

```ts
{ contractVersion: 1, reason: "deployment", drainSeconds: number, startedAt: string }
```

---

## 6. The live drawing protocol

Source: [`backend/app/live_drawing.py`](../backend/app/live_drawing.py).
Golden fixtures: [`fixtures/canvas_protocol_v1.json`](../fixtures/canvas_protocol_v1.json),
exercised from both sides by
[`backend/tests/test_live_drawing.py`](../backend/tests/test_live_drawing.py) and
[`frontend/tests/canvasProtocolFixtures.test.mjs`](../frontend/tests/canvasProtocolFixtures.test.mjs).

All live drawing rides on **one** Socket.IO event, `draw`. This is a *hybrid* protocol:

- **Data-bearing actions** (path start, path points, shape, fill) are binary
  attachments.
- **Control actions** (path end, clear) send their single header byte as a bare
  **integer**, avoiding Socket.IO's binary-attachment envelope when it would be larger
  than the action itself.

### Header byte

```
bit  7 6 5 4 | 3 2 1 0
     version | tag
```

`LIVE_DRAWING_VERSION = 1`, so every current frame starts with `0x1_`.

| Tag | Value | Event | Frame |
| --- | --- | --- | --- |
| `PATH_START` | 0 | `draw_start` | binary, 8 bytes |
| `PATH_POINTS` | 1 | `draw_move` | binary, 1 + 4·n bytes |
| `PATH_END` | 2 | `draw_end` | integer `0x12` |
| `SHAPE` | 3 | `draw_shape` | binary, 14 bytes |
| `FILL` | 4 | `draw_fill` | binary, 8 bytes |
| `CLEAR` | 5 | `clear_canvas` | integer `0x15` |

### Frame layouts

All multi-byte integers are **little-endian** except colors, which are big-endian RGB.

| Frame | `struct` | Fields |
| --- | --- | --- |
| `draw_start` | `<B3sBhh` | header, color (3 B, RGB), width (1 B), x, y (int16) |
| `draw_move` | `B` + `<hh` × n | header, then n points; 1 ≤ n ≤ 256 (`MAX_POINTS_PER_FRAME`) |
| `draw_end` | `B` | header only |
| `draw_shape` | `<BB3sBhhhh` | header, shape id (1 B), color, width, x₀, y₀, x₁, y₁ |
| `draw_fill` | `<B3sHH` | header, color, x, y as **absolute uint16 pixels** |
| `clear_canvas` | `B` | header only |

Shape IDs: `rectangle = 0`, `ellipse = 1`, `triangle = 2` (`SHAPE_IDS`,
[`backend/app/canvas_history.py:32`](../backend/app/canvas_history.py)).

### Coordinates

Path and shape coordinates are **normalized** (0.0 – 1.0 across the canvas, and
allowed to overshoot) and packed to signed 16-bit **quarter-pixels**:

```
packed = round(normalized × canvasSize × COORDINATE_SCALE)
```

with `CANVAS_WIDTH = 800`, `CANVAS_HEIGHT = 600`, `COORDINATE_SCALE = 4`, and the
packed value bounded to `[-32768, 32767]`. That gives quarter-pixel precision and
about ±10 canvases of overshoot headroom before a coordinate is refused.

Fill coordinates are different on purpose: they are sent as **absolute pixel indices**
(`uint16`), because a fill's seed point must land on an exact pixel. The encoder
requires `0 ≤ x < 1` and `0 ≤ y < 1` normalized and clamps to
`CANVAS_WIDTH − 1` / `CANVAS_HEIGHT − 1`.

Colors are `#rrggbb` strings on the payload side and three raw bytes on the wire.
`width` is 1 – `MAX_BRUSH_WIDTH` (64).

### Worked examples (from the fixture)

| Event | Payload | Wire (hex) |
| --- | --- | --- |
| `draw_start` | `{x: 0.25, y: 0.75, color: "#aabbcc", width: 4}` | `10 aabbcc 04 2003 0807` |
| `draw_move` | `{points: [{0.1,0.2}, {1.2,-0.1}]}` | `11 4001 e001 000f 10ff` |
| `draw_end` | — | `12` |
| `draw_shape` | ellipse `#123456`, width 64, (0.1,0.2)→(0.8,0.9) | `13 01 123456 40 4001 e001 000a 7008` |
| `draw_fill` | `{x: 0.25, y: 0.75, color: "#fedcba"}` | `14 fedcba c800 c201` |
| `clear_canvas` | — | `15` |

### Server-side refusals

`decode_live_drawing` ([`backend/app/live_drawing.py:150`](../backend/app/live_drawing.py))
rejects, before anything is recorded or rebroadcast:

- A non-integer, non-bytes payload, or an empty frame.
- An integer control outside 0 – 255, or an integer carrying a **data-bearing** tag —
  "data-bearing drawing actions must be binary".
- A version other than 1.
- Any frame whose length does not exactly match its tag's layout.
- A brush width outside 1 – 64, an unknown shape id, a fill point outside the canvas.

On top of the codec, [`drawing.py`](../backend/app/handlers/drawing.py) refuses:

- A sender who is not the current drawer, or a phase other than `drawing`.
- A tool or color the room's **drawing rules** disallow
  (`packet_allowed`, [`backend/app/drawing_rules.py`](../backend/app/drawing_rules.py)).
  Nothing is recorded and nothing is rebroadcast — but the sender already drew it
  locally, so the server replies with a canvas sync onto server truth. Only the frame
  that *opens* an action is answered; points and the end frame trailing a refused path
  are dropped in silence, so one refusal costs one sync however many frames follow.

### Drawing rules

Two room settings, deliberately shaped differently
([`backend/app/drawing_rules.py`](../backend/app/drawing_rules.py)):

- **Allowed tools** are independent flags (`brush`, `fill`, `shapes`), so they are a
  set. At least one of `brush`/`shapes` must stay on, since fill alone can only flood a
  blank canvas.
- **Color mode** picks one of four mutually exclusive alternatives: `all`, `palette`
  (13 light/dark pairs, mirroring `COLOR_PAIRS` in `Toolbar.tsx`), `colorblind_safe`
  (Okabe-Ito plus white), `black_and_white`.

**Erasing is a white brush stroke on the wire.** It is indistinguishable from drawing
in white, so the server can ban the brush and the eraser together or admit both, but
never one alone — which is also why **every color mode permits white**, and why the
mode is called *black and white* rather than *black only*.

---

## 7. The canvas sequencing protocol

Source: [`backend/app/canvas_session.py`](../backend/app/canvas_session.py) (server) and
[`frontend/src/hooks/useCanvasProtocol.ts`](../frontend/src/hooks/useCanvasProtocol.ts)
(client).

The drawer's canvas is optimistic: strokes appear locally before the server confirms
them. Four numbers keep the two canvases reconcilable.

| Name | Meaning |
| --- | --- |
| **generation** | Which turn's canvas this is. Allocated by `Room.allocate_canvas_generation()` at each turn start. A frame naming a stale generation is discarded and answered with a sync. |
| **sequence** | A monotonically increasing per-turn number identifying one *semantic* mutation (one whole path, one shape, one fill, one clear, one undo). Strictly `previous + 1`. |
| **revision** | How many actions the authoritative history contains. Undo *increments* the revision while shrinking the history. |
| **historyHash** | A CRC32 over the length-delimited canonical records of every action, so both sides can compare whole histories in one integer. |

### The exchange

```
drawer                                     server                       everyone else
  │  draw(frame, [generation, sequence])      │
  │──────────────────────────────────────────▶│  validate rules, generation, sequence
  │                                           │  CanvasSession.record_stroke(...)
  │                                           │────── draw(frame verbatim) ──────────▶
  │◀──── canvas_commit [gen, seq, rev, hash] ─│──────────────────────────────────────▶
```

- Only the frame that **starts** an action carries `[generation, sequence]`. Path
  points and the path-end frame carry none — the parser refuses an identity on those
  and requires one on the others.
- A path is committed on `draw_end`, using the sequence its `draw_start` carried. A
  shape or fill commits immediately. A clear commits immediately.
- The rebroadcast to other clients is the drawer's **exact wire bytes**, never a
  re-encoded frame.

### Recovery paths

| Situation | Server response |
| --- | --- |
| `generation` is stale | `sync_strokes` (full authoritative history) |
| `sequence` ≤ committed | replay the stored `canvas_commit` for it if the recorded mutation matches, else `sync_strokes` |
| `sequence` > expected (a gap) | `request_canvas_actions [generation, expected, received]` |
| A new action arrives while a path is still open | `request_canvas_actions`, unless it is a `draw_start` repeating the open sequence, which restarts that path |
| A refused tool or color | `sync_strokes` |
| `undo_stroke` whose `revision`/`historyHash` disagree | `sync_strokes` + `{"ok": false, "error": "Canvas history is out of sync"}` |

`sync_strokes` is emitted as a **tuple**:
`(binaryHistory, revision, generation, sequence, historyHash)`.

`MAX_CANVAS_COMMITS = 512` bounds the acknowledgement window — twice the 256
unacknowledged mutations the browser retains — so ordinary duplicate deliveries are
answerable without per-turn state growing with the sequence number forever.

### `undo_stroke`

A fixed four-integer array, not an object:

```jsonc
[generation, sequence, revision, historyHash]
```

`generation` and `sequence` are 1 – 2³¹−1, `revision` is 0 – 2³¹−1, `historyHash` is
0 – 0xFFFFFFFF. Only the drawer may undo. Undo emits `canvas_undo` with **five**
elements — `[generation, sequence, revisionBefore, revisionAfter, historyHash]` — so a
client that missed the commit can tell an undo from an ordinary action.

### Replay-work budget

Every client that joins or resynchronizes replays the whole turn, so an unbounded turn
is a way to grief a room rather than merely a way to waste a server.

| Constant | Value | Meaning |
| --- | --- | --- |
| `MAX_CANVAS_ACTIONS` | 20 000 | Actions per turn |
| `MAX_CANVAS_POINTS` | 25 000 | Path points per turn |
| `MAX_TURN_REPLAY_WORK` | 20 000 | Weighted replay cost per turn |
| `REPLAY_WORK_BY_TAG` | path 1, shape 1, **fill 200**, clear 0 | Measured in Chromium: a worst-case fill repaints all 480 000 pixels (~6.1 ms) against ~0.02 ms for a path |

In practice this is a **fill budget**: cheap actions hit `MAX_CANVAS_ACTIONS` first.
Undo refunds what the removed action was charged. The client greys the fill tool out
before the budget runs down (`canvasBudgetStore.ts`), so a drawer meets this as a
disabled button; the server value is the authoritative backstop for a client that does
not, and the client is deliberately the stricter of the two.

---

## 8. Canvas history formats

Source: [`backend/app/canvas_history.py`](../backend/app/canvas_history.py).

### Binary replay envelope (`SKCH`) — the format on the wire

```
┌────────┬─────────┬───────────────┬──────────────────────────┬───────────────┐
│ "SKCH" │ version │ actionCount   │ offsetTable              │ packed records│
│  4 B   │  1 B    │  uint16 (2 B) │ (actionCount+1) × uint32 │   variable    │
└────────┴─────────┴───────────────┴──────────────────────────┴───────────────┘
```

Header is `<4sBH`; the offset table is `(n+1)` little-endian `uint32`s, the last being
the total data length, which makes every record self-delimiting. `CANVAS_HISTORY_VERSION = 1`.

Packed record layouts (tags are **history** tags, distinct from the live-drawing tags):

| Tag | Value | `struct` | Fields |
| --- | --- | --- | --- |
| `PATH` | 0 | `<B3sB` + `<hh` × n | tag, color, width, then points |
| `SHAPE` | 1 | `<BB3sBhhhh` | tag, shape id, color, width, x₀, y₀, x₁, y₁ |
| `FILL` | 2 | `<B3sHH` | tag, color, x, y (absolute pixels) |
| `CLEAR` | 3 | `<B` | tag |

`MAX_BINARY_CANVAS_HISTORY_BYTES` is derived from the layout as an invariant, not a
target: all 20 000 action slots, all 25 000 points in one path, and the remaining slots
filled with the larger fixed-size shape record.

### Compact JSON fallback (`{v, a}`)

`wire_payload()` produces `{"v": 1, "a": [...]}`, each action a positional array:

```jsonc
[0, colorInt, width, x0, y0, x1, y1, …]   // path
[1, shapeId, colorInt, width, x0, y0, x1, y1]  // shape
[2, colorInt, x, y]                        // fill
[3]                                        // clear
```

Colors are integers here, and coordinates are the unpacked normalized floats. The
frontend retains this decoder as a **compatibility fallback**
([`frontend/src/lib/canvasHistory.ts`](../frontend/src/lib/canvasHistory.ts)); the binary
envelope is what `sync_strokes` actually carries.

### History hash

`extend_history_hash(previous, record)` CRC32s a `uint32` length prefix followed by the
record bytes, chained across every action from `HISTORY_HASH_INITIAL = 0`. The length
prefix is what makes it unambiguous: two different action sequences cannot produce the
same byte stream. `CanvasSession` keeps the prefix array so the common case (a path
still being drawn) extends the stored prefix instead of rescanning the whole history.

### Stored format — a different commitment

[`backend/app/canvas_storage.py`](../backend/app/canvas_storage.py) is the boundary
between two promises:

> A drawing **on the wire** only has to be understood by the client on the other end of a
> connection that is open right now, so both ends deploy together and a version bump is
> coordinated by definition. A drawing **in the database** has to be readable by every
> future decoder, forever.

Two rules, and only two:

1. **Every format ever written keeps its entry in `_STORED_DECODERS`.** An entry is
   added when a format starts being written and is **never removed**.
2. **A decoder returns bytes in the current wire format.** Clients therefore never
   learn that a stored format exists, and the wire format stays free to change without
   migrating a single row.

Today a stored drawing is a byte-identical `SKCH` frame, so its decoder is the identity
function. The `(magic, version)` pair at offset 0 is the discriminator, which is why no
envelope is needed to tell formats apart. Because a database column has no integrity
check of its own, an operator command decodes stored drawings in bounded batches:

```bash
cd backend && .venv/bin/python -m app.services.drawing_storage
```

---

## 9. REST API

Base path `/api` unless noted. `SessionAuthMiddleware`
([`backend/app/auth/middleware.py`](../backend/app/auth/middleware.py)) resolves the
hashed session cookie for every request. Role-gated endpoints answer **404**, not 403,
to anyone without the role — the account menu decides what is *shown* and nothing more.

### Health, discovery, metrics

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness. `{"status":"ok","readiness":…}` |
| `GET` | `/api/ready` | 200 only when startup finished and no drain has begun; 503 otherwise |
| `GET` | `/api/rooms` | Public room summaries (`RoomSummary[]`), polled by the lobby |
| `GET` | `/metrics` | Prometheus text, bearer token. **Disabled entirely until `METRICS_TOKEN` is set** |

### Accounts and sessions — [`backend/app/auth/routes.py`](../backend/app/auth/routes.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/auth/me` | Provisions a guest account on first call. **The only path that creates a user row for a visitor.** |
| `GET` | `/api/auth/nickname-available` | Rate limited (`AUTH_LOOKUP_LIMIT`) |
| `POST` | `/api/auth/display-name`, `/api/auth/name-color` | Profile edits |
| `POST` | `/api/auth/register` | Claims the current account (`AUTH_REGISTER_LIMIT`) |
| `POST` | `/api/auth/login` | Argon2id; rehashes stale-cost hashes on success (`AUTH_LOGIN_LIMIT`) |
| `POST` | `/api/auth/logout`, `/api/auth/logout-all` | |
| `GET` | `/api/auth/sessions` | Signed-in device list |
| `DELETE` | `/api/auth/sessions/{session_id}` | Revoke one device |
| `GET`/`PUT` | `/api/auth/email` | `PUT` is rate limited (`AUTH_VERIFY_LIMIT`) |
| `POST` | `/api/auth/email/verify`, `/api/auth/email/reminder-seen` | |
| `POST` | `/api/auth/password/forgot` | **Answers identically whether or not the account exists** (`AUTH_RESET_LIMIT`) |
| `POST` | `/api/auth/password/reset/check` | Checks without consuming the token (`AUTH_RESET_CHECK_LIMIT`) |
| `POST` | `/api/auth/password/reset` | Revokes every session, then signs the user in |
| `POST`/`GET` | `/api/auth/data-exports` | Request a job / list the caller's jobs |
| `GET` | `/api/auth/data-exports/{export_id}` | Job status |
| `GET` | `/api/auth/data-exports/{export_id}/download` | The artifact. Owner-only; v1 exports expire after 7 days |
| `DELETE` | `/api/auth/account` | Password required for a registered account |

### Profiles and history — [`backend/app/api/profiles.py`](../backend/app/api/profiles.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/users/{user_id}/stats` | Served from the daily projection, never four history scans |
| `GET` | `/api/users/{user_id}/games` | `?includeAbandoned=true` to include games that stopped |
| `GET` | `/api/games/{game_id}` | Participant-only detail: exact rule snapshot, offers, outcomes, ledger |
| `GET` | `/api/games/{game_id}/turns/{turn_id}/drawing` | Participants only. **Every refusal is a 404**, so it never reveals whether a game exists |

### Prompt lists — [`backend/app/api/prompt_lists.py`](../backend/app/api/prompt_lists.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/prompt-lists` | Official catalogue; localized copy selected from `Accept-Language` |
| `GET` | `/api/prompt-lists/mine` | The caller's own lists |
| `GET`/`PUT` | `/api/prompt-lists/mine/{prompt_list_id}` | Owner only; `PUT` uses optimistic concurrency and creates a new immutable revision |
| `POST` | `/api/prompt-lists/shared` | Resolve an Unlisted list by its bearer share code |
| `GET` | `/api/prompt-lists/{slug}/prompt-stats` | Window (all-time / 30 d / 90 d) and scoring/hint segmentation |

### Settings, blocks, presets, persistent rooms

| Method | Path | Notes |
| --- | --- | --- |
| `GET`/`PATCH` | `/api/users/me/settings` | Cross-device Player settings; bounded at API and database layers |
| `GET`/`POST` | `/api/users/me/blocks` | Directional; self-blocks rejected |
| `DELETE` | `/api/users/me/blocks/{user_id}` | Idempotent |
| `GET`/`POST` | `/api/room-presets` | ≤ 20 per account |
| `GET`/`PUT`/`DELETE` | `/api/room-presets/{preset_id}` | `PUT` uses an optimistic version check |
| `GET` | `/api/persistent-rooms` | The caller's own rooms |

### Reports and moderation — [`backend/app/api/moderation.py`](../backend/app/api/moderation.py)

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/reports` | any signed-in | ≤ 2000 chars detail, ≤ 32 768 bytes context, ≤ 20 **unique** `messageIds`. One open report per reporter/target |
| `POST` | `/api/prompt-content-reports` | any signed-in | Targets a list or an exact `promptVersionId`. Official content and self-reports rejected |
| `GET` | `/api/moderation/reports` | moderator+ | The queue; each report carries `reportedPlayer` standing (name, registered, age, prior reports/warnings, active suspension) |
| `PATCH` | `/api/moderation/reports/{report_id}` | moderator+ | Review is one-way |
| `GET` | `/api/moderation/prompt-content-reports` | moderator+ | The queue |
| `PATCH` | `/api/moderation/prompt-content-reports/{report_id}` | moderator+ | A resolution chooses Active or Hidden; a dismissal cannot mutate content |
| `GET`/`POST` | `/api/moderation/bans` | moderator+ | Moderators cannot suspend peers; administrators cannot be targeted. With `reportId`, resolves that report in the same transaction (`409` if already decided) |
| `POST` | `/api/moderation/bans/{ban_id}/revoke` | moderator+ | Preserves the historic record and reason |
| `POST` | `/api/moderation/warnings` | moderator+ | Formal warning; same role boundaries as a suspension, restricts nothing. With `reportId`, resolves that report in the same transaction (`409` if already decided) |
| `GET` | `/api/warnings/pending` | any signed-in | The caller's own oldest unacknowledged warning, with the reported messages behind it |
| `POST` | `/api/warnings/{warning_id}/acknowledge` | any signed-in | Own warnings only (`404` otherwise); records that the notice landed |

### Bug reports — [`backend/app/api/bug_reports.py`](../backend/app/api/bug_reports.py)

Not a moderation surface: the queue is administrator-only, and a moderator gets the
same `404` as anybody else.

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/bug-reports` | any identity, guests included | One of ten `area` values and three `severity` values, ≤ 200-char `summary`, ≤ 4000-char `details`, ≤ 32 768 bytes `clientContext`, optional base64 `screenshot`. 5 per hour per client. Room, game and turn are resolved from the reporter's **live seat**, never from the `roomCode` sent |
| `GET` | `/api/admin/bug-reports` | administrator | The queue, newest first, optionally filtered by `status`. Screenshot **metadata** only |
| `GET` | `/api/admin/bug-reports/{report_id}/screenshot` | administrator | The raw bytes, `Cache-Control: private, no-store`; `404` once erased |
| `PATCH` | `/api/admin/bug-reports/{report_id}` | administrator | Review is one-way (`409` if already decided) and requires a note. Erases the screenshot in the same transaction |

A screenshot is validated rather than believed: real PNG or WebP magic bytes, ≤ 2 MB,
with byte size and SHA-256 re-derived server-side. Anything else is `422` — never a
silently dropped attachment.

### Operations — [`backend/app/api/operations.py`](../backend/app/api/operations.py)

Administrator role required for all of these.

| Method | Path |
| --- | --- |
| `GET` | `/api/admin/metrics`, `/api/admin/metrics/daily`, `/api/admin/metrics/events` |
| `GET` | `/api/admin/players/{user_id}/activity` — **writes an audit event on every use** |
| `GET` | `/api/admin/audit` |

### Static delivery

When `frontend/dist` exists it is mounted on the same FastAPI app
([`backend/app/deployment.py`](../backend/app/deployment.py)): gzip for eligible
responses, Vite's fingerprinted `/assets/` served `immutable` with a one-year lifetime,
and `index.html` (including client-route fallbacks) served `no-cache` so browsers
discover new deployments promptly. A reverse proxy may replace the gzip layer but must
preserve that cache distinction and send `Vary: Accept-Encoding`.

---

## 10. Rate limits

Persistent, shared-database buckets keyed on an HMAC-SHA-256 digest of the client
address under `IP_HASH_SECRET` — **raw IP addresses are never stored**
([`backend/app/auth/rate_limit.py`](../backend/app/auth/rate_limit.py)).

| Variable | Default | Applies to |
| --- | --- | --- |
| `AUTH_LOGIN_LIMIT` | 10 / 5 min | `POST /api/auth/login` |
| `AUTH_REGISTER_LIMIT` | 10 / hour | `POST /api/auth/register` |
| `AUTH_LOOKUP_LIMIT` | 60 / min | Name availability and display-name changes |
| `AUTH_RESET_LIMIT` | 5 / hour | `POST /api/auth/password/forgot` |
| `AUTH_RESET_CHECK_LIMIT` | 30 / hour | `POST /api/auth/password/reset/check` |
| `AUTH_VERIFY_LIMIT` | 10 / hour | `PUT /api/auth/email` |

Lower-risk profile and prompt-statistics throttles remain process-local.

Limits are keyed on the *connecting* address. Behind a reverse proxy or tunnel every
request arrives from the proxy, so production must run with `PROXY_HEADERS=1` and
`FORWARDED_ALLOW_IPS=<proxy address>`. Without that trusted-proxy configuration
`X-Forwarded-For` is **ignored on purpose**: it is attacker-controlled, and trusting it
blindly would let a password-guesser sidestep the limit by varying it per attempt.

---

## 11. Versioning and change rules

| Version constant | Governs | Bump when |
| --- | --- | --- |
| `LIVE_DRAWING_VERSION` (1) | The live `draw` frame | The frame layout changes. Both ends deploy together |
| `CANVAS_HISTORY_VERSION` (1) | `SKCH` and the `{v,a}` JSON | The history layout changes |
| Stored `(magic, version)` | A durable drawing blob | **Add** a decoder; never remove one |
| `SCORING_RULES_VERSION` (1) | Any constant or algorithm that can change a score | Any such change; every completed game freezes its rule snapshot |
| `GAME_RULE_SNAPSHOT_VERSION` (1) | The stored rule-snapshot JSON contract | The snapshot's *shape* changes |
| `score_ledger_version` | The score-event ledger contract | The ledger's semantics change |
| `contractVersion` on `server_shutdown` | The shutdown notice | The notice's shape changes |
| Data export `schema_version` (1) | The export document, pinned by [`fixtures/account_data_export_v1_fields.json`](../fixtures/account_data_export_v1_fields.json) | The export's field surface changes |

**Checklist for any wire change:**

1. Change the server (handler, payload model, presenter).
2. Change the client (`frontend/src/types.ts`, the listener, the emitter).
3. Update the fixture if the binary formats moved
   (`fixtures/canvas_protocol_v1.json`).
4. Run `backend/.venv/bin/pytest tests/test_wire_contract.py`.
5. Update **this document**, and [`../GLOSSARY.md`](../GLOSSARY.md) if a
   player-visible name changed.
