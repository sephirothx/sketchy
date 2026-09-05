# Requirements

What Sketchy is required to do, what it is required *not* to do, and where each
requirement is implemented and proven. Requirements are numbered so they can be cited
from issues, PRs, and code comments.

Companion documents: [`architecture.md`](architecture.md) ·
[`wire-protocol.md`](wire-protocol.md) · [`database.md`](database.md) ·
[`../GLOSSARY.md`](../GLOSSARY.md)

**How to read this.** `MUST` is a hard requirement — breaking it is a bug. `MUST NOT`
is a deliberate non-goal or a safety boundary; adding the behaviour is a product
decision, not a fix. Where a requirement encodes a *reason* rather than only a rule, the
reason is stated, because that is what tells you whether a change violates it.

---

## Product statement

Sketchy is a self-hosted, online multiplayer drawing-and-guessing game
(iSketch/Pictionary-style), built for "friends playing together" scale. One player
draws a prompt while everyone else races to guess it in the chat. Accounts are optional
for play.

**Scale target (v1):** 50 simultaneous active rooms and 400 connected player seats on
one worker. This is a *validation target* on a documented reference environment, not a
claim that an arbitrary host will sustain it.

---

## 1. Platform and deployment

| # | Requirement |
| --- | --- |
| **R-PLAT-01** | The system MUST run with **zero configuration**, defaulting to an embedded SQLite database at `./sketchy.db` — in development and test only; see R-PLAT-11. [`db/__init__.py:23`](../backend/app/db/__init__.py) |
| **R-PLAT-02** | The system MUST also support PostgreSQL via `DATABASE_URL`, with identical behaviour. Cross-dialect equivalence is proven by replaying the migration chain both directions on both engines. [`tests/test_migrations.py`](../backend/tests/test_migrations.py) |
| **R-PLAT-03** | The whole game (UI + REST + WebSocket) MUST be servable from **one port** when `frontend/dist` exists. [`main.py:264`](../backend/app/main.py) |
| **R-PLAT-04** | The backend MUST refuse an interpreter older than Python 3.14, and the frontend requires Node ≥ 22.12. [`deployment.py`](../backend/app/deployment.py), [`frontend/package.json`](../frontend/package.json) |
| **R-PLAT-05** | Exactly **one application worker** is supported. Startup MUST reject `WEB_CONCURRENCY`/`UVICORN_WORKERS` values other than `1`. Live rooms, games, canvases, timers, Socket.IO sessions, and room-code lookup are process-owned. |
| **R-PLAT-06** | Multi-worker deployment MUST NOT be presented as supported. It requires shared room/session/timer state plus cross-worker Socket.IO delivery, and is outside v1. Shared PostgreSQL state does not change this. |
| **R-PLAT-07** | SQLite connections MUST enforce foreign keys, use WAL mode, and wait up to 5 s on a busy database — the test fixtures' connections included, checked per connection, because a suite whose database ignores foreign keys proves nothing about deletion. [`db/__init__.py:41`](../backend/app/db/__init__.py), [`tests/dbfixtures.py`](../backend/tests/dbfixtures.py) |
| **R-PLAT-08** | SQLite MUST migrate itself on startup. PostgreSQL migrations MUST be an explicit deploy step under an advisory lock; startup MUST verify the revision and fail with a direct instruction if the step was missed. [`db/migrate.py`](../backend/app/db/migrate.py) |
| **R-PLAT-09** | Fingerprinted `/assets/` MUST be served `immutable` with a one-year lifetime, and `index.html` (including client-route fallbacks) `no-cache`, so browsers discover deployments promptly. [`deployment.py`](../backend/app/deployment.py) |
| **R-PLAT-10** | Behind a proxy, the real client address MUST be recovered only with explicit trusted-proxy configuration (`PROXY_HEADERS=1`, `FORWARDED_ALLOW_IPS`). Without it, `X-Forwarded-For` MUST be ignored — it is attacker-controlled, and trusting it blindly would let a password-guesser sidestep rate limits by varying it per attempt. |
| **R-PLAT-11** | The deployment environment MUST be explicit in `SKETCHY_ENV` (`development` — the default — `test`, or `production`), and an unrecognised value MUST fail startup rather than fall back: a misspelling read as development disarms every production guard at once. With `SKETCHY_ENV=production`, startup MUST refuse a missing, blank, or SQLite `DATABASE_URL` before `init_db()` runs. The zero-config fallback is a *relative* file, so a production deploy that forgot the variable looks healthy while writing durable data to storage the next replacement discards. [`deployment.py`](../backend/app/deployment.py) |
| **R-PLAT-12** | `GET /api/ready` MUST test the dependencies this process needs to serve: a bounded, briefly cached database round-trip, and the supervised background loops. A required loop whose task has *stopped* MUST fail readiness; a loop that is merely erroring MUST NOT, so a failing email sweep cannot pull a playable game server out of rotation. `GET /api/health` MUST remain process-only and MUST NOT fail on a dependency — a restart cannot fix an outage the replacement comes back into — but MUST report each loop's run state, failure streak, and time since its last success. [`services/readiness.py`](../backend/app/services/readiness.py) |

### Planned shutdown

| # | Requirement |
| --- | --- |
| **R-SHUT-01** | `GET /api/ready` MUST return 503 **before** any drain work begins; `/api/health` remains a liveness check that reports readiness state. The shutdown state MUST be tested **first**, before the R-PLAT-12 dependency checks, so a draining process answers from the drain rather than being delayed or contradicted by a dependency. |
| **R-SHUT-02** | At drain start the server MUST send every connected client the versioned `server_shutdown` notice, and MUST refuse new room creation, new game starts, and restart votes — while leaving existing rooms connected so active games can finish. |
| **R-SHUT-03** | The drain window MUST be configurable via `SHUTDOWN_DRAIN_SECONDS` (0–300, default 30). A second termination signal MUST abandon the remaining window immediately — **whichever supported signal it is**, since a deployment stop sends `SIGTERM` twice rather than switching to `SIGINT`. The window a drain runs on MUST be fixed when the drain starts and reported from that fixed value, so a change to the configured default cannot make the notice and the deadline disagree. |
| **R-SHUT-04** | A game that outlives the deadline MUST NOT be recorded as completed history. Exactly one privacy-safe `planned_shutdown_abandonments` row MUST be written instead, retained 90 days. |
| **R-SHUT-05** | That diagnostic MUST NOT contain room codes, room or player names, prompts, chat, or canvas contents. |
| **R-SHUT-07** | An administrator MUST be able to start a planned shutdown from the operations surface, with a bounded window for this shutdown that does not change the configured default. It MUST ask the process to terminate rather than draining inside the request — a drain is one-way, and running it in a live process leaves the real shutdown nothing left to spend. A deployment whose runner cannot signal itself MUST say so rather than appear to succeed. The right to stop the process MUST be claimed once and refused thereafter — `draining` is false for the whole gap between asking and the drain starting, so without a claim a second request inside it is a second audited shutdown able to move the window the first was recorded with. A request that does not go through MUST leave the drain window and the claim exactly as it found them. Nothing in the API brings a server back. |
| **R-SHUT-06** | Live rooms, canvases, timers, scores, and games MUST NOT be serialized or restored. A crash still loses process-owned state; this is a stated property, not a defect. |

---

## 2. Gameplay

### Rooms and lobby

| # | Requirement |
| --- | --- |
| **R-ROOM-01** | The lobby MUST show a live list of public rooms, pushed rather than polled (R-PRESENCE-05), and MUST allow joining a private room by code. It MUST also show who is online (R-PRESENCE-01). |
| **R-ROOM-02** | Room codes MUST be six-character random invite **capabilities**, reserved in the database before being shown to a player. They MUST NOT be derived from an entity ID. |
| **R-ROOM-03** | When an ephemeral room empties, its code MUST be retired for 30 days, so a stale invite says the room ended instead of silently joining an unrelated group. Startup MUST retire reservations orphaned by a crash. |
| **R-ROOM-03a** | Codes permanently claimed by the removed persistent-room feature MUST stay claimed and MUST report a stale invite as ended. Releasing them would hand exactly those codes back to the allocator. |
| **R-ROOM-04** | Room settings MUST be settable at creation and editable by the host while waiting: name, visibility, max players (2–16), rounds (1–10), drawing time (a fixed preset list), scoring mode, hint mode, spectator prompt visibility, masked-prompt hiding, allowed tools, color mode, prompt lists, and custom prompts. |
| **R-ROOM-05** | A game MUST require at least 2 players before the host can start it. |
| **R-ROOM-06** | The host role is a **gameplay** role only. It MUST NOT confer any service-wide privilege. Conversely an administrator MUST NOT become host merely by holding the role. |
| **R-ROOM-07** | **Room** payloads MUST NOT carry account IDs. Anything that needs an account (reports, blocks, profile links) resolves the seat server-side. The lobby presence list is not a room payload: it MUST carry the account id, because there is no seat to resolve for a player idling in the lobby and a friend request needs a stable target — and it MUST NOT carry a room id, code, name, or any state beyond *in the lobby* / *in a game*, so that presence never becomes a directory of who is playing where or discloses that a private room exists. |
| **R-ROOM-13** | Room state MUST carry a player's kick and AFK vote lists only where votes exist. Every seat receives every other seat's entry on every broadcast, so an empty list per player is the payload paying a quadratic price for the state almost every player is in almost always. |
| **R-ROOM-08** | A socket MUST hold at most one live seat. Creating or joining a room MUST first release any seat that connection already holds, by the same path an explicit leave takes: room state re-emitted, timers cancelled, empty-room teardown and code retirement run. Seats MUST be matched by socket, never by account — two tabs of one account may sit in two different rooms. |
| **R-ROOM-09** | Opening a room MUST require a provisioned session. Joining, playing, and receiving a factual history seat MUST NOT — a visitor whose browser keeps no cookie can still play (R-HIST-10); they cannot host. |
| **R-ROOM-10** | Room creation MUST be bounded on four axes: live rooms per account, room creations per account per hour, live rooms per process, and quick-prompt characters retained across every live room. Each MUST be configurable, and each refusal MUST say which ceiling was reached in terms a player can act on. |
| **R-ROOM-14** | Database work on the way into a room MUST be bounded by a timeout and refuse the entry cleanly when it expires. Seat transitions hold the socket's seating gate and its disconnect queues at the same gate, so an entry that never returns is a seat that never reconciles — the leak R-ROOM-08 closed, reopened by a stall. |
| **R-ROOM-11** | A ceiling MUST be re-checked at the instant the room is created, not only when the command arrives: everything in between awaits, and a refusal at that point MUST release the room code it had already claimed. |

### Lobby presence

| # | Requirement |
| --- | --- |
| **R-PRESENCE-01** | The lobby MUST show every connected account, keyed by **account** rather than by socket, so several tabs of one player are one entry. A connection with no account (R-ACCT-02) MUST NOT appear, and that MUST follow from the registry's shape rather than from a filter that a later change could drop. There is **no opt-out**: this is a deliberate product decision, not an omission. |
| **R-PRESENCE-02** | Presence MUST be released the moment a socket closes, on **every** way out — including a handshake that fails after the account was registered, which never reaches the disconnect handler. It MUST NOT be held for the R-CONN-01 reconnect grace: that grace protects a *seat*, and a socket that cannot receive is not online. |
| **R-PRESENCE-03** | Presence MUST say only whether a player is in the lobby or in a game. It MUST NOT name the room, in any form, for a public or a private one alike. |
| **R-PRESENCE-04** | The list MUST be bounded and MUST report the true total alongside the bounded list, so a cap is never mistaken for a quiet server. The cap and the broadcast interval MUST both be configurable (R-ROOM-10's rule). |
| **R-PRESENCE-05** | Presence and the public room list MUST be delivered over one channel a client opts into, never a poll (#462). Each feed MUST carry its own sequence number, one acknowledgement MUST hand over both baselines, and a client MUST be able to detect a missed message and ask for a fresh snapshot, so its store is self-correcting rather than authoritative (#493). Lobby chat rides the same channel and the same acknowledgement but is exempt from the resync rule, for the reason R-LCHAT-01 gives. |

### Lobby chat

| # | Requirement |
| --- | --- |
| **R-LCHAT-01** | A lobby line MUST be delivered over the lobby channel the moment it is accepted, never from the broadcast tick, and MUST NOT be a revisioned feed: a line is an event with nothing to rebuild it from, and a gap in its numbering is *expected*, because a line is deliberately not delivered to somebody who blocked its author. A client MUST NOT resync over such a gap. The per-process `seq` exists only so the backlog and the lines that beat the acknowledgement can be put into one order without a duplicate. [`handlers/lobby.py`](../backend/app/handlers/lobby.py), [`lib/lobbyChat.ts`](../frontend/src/lib/lobbyChat.ts) |
| **R-LCHAT-02** | Anyone with an account MAY speak, a guest included — the same boundary as R-PRESENCE-01 — and only from a socket that is watching the lobby. A socket with no account MUST be able to read and MUST be refused a line, told to choose a name. Every refusal MUST come before the line is numbered or kept, so a refused line never appears in anybody's backlog. |
| **R-LCHAT-03** | Blocks MUST be honoured on both paths, by R-BLOCK-02's rule: a line by a muted author is delivered to everyone but the account that muted them, the sender included, and the backlog handed to an arrival omits the authors they muted. A socket with no account has no block list and MUST always receive. A lookup that cannot be answered MUST deliver unfiltered (R-BLOCK-06). |
| **R-LCHAT-04** | An arrival MUST be handed the recent lines in the same acknowledgement as the other baselines, oldest first and bounded (50), from memory. A restart MUST re-seed that memory from the most recent retained lines before the first socket is served — minus anything expired and anything a currently suspended account said — so a deploy does not empty the lobby; the read MUST be bounded and its failure MUST leave the process starting with an empty backlog rather than not starting. This is a buffer, not a transcript: nothing reads further back than the fifty, and N-05 stands. A client MUST keep what it holds across a dropped socket — those lines were said — and MUST replace it with the backlog of a new connection. |
| **R-LCHAT-05** | A lobby line MUST be retained under R-PRIV-07's 30 days with audience `lobby`, no room scope, no seat, and **no recipient list**: it was said to every lobby that was open, and recording every watcher per line would be a directory of who was around. It MUST be citable as report evidence through `POST /api/reports` on its own terms — the audience check does not apply to a public line, the author must still be the reported account, and a report MUST NOT mix lobby and room lines — and MUST NOT be selected automatically by an in-room `report_player`, which is scoped to that room. An account's deletion MUST take its lines out of the backlog as well as the database. |
| **R-LCHAT-06** | Lobby lines MUST answer to a budget of their own (`lobby_chat`), settable at runtime like every other (R-RATE-09), because a lobby line reaches every open lobby rather than one room's seats and tightening it must never tighten guessing. |
| **R-LCHAT-07** | Every line MUST carry the server's instant, the same one written to its retained row, and the lobby MUST show an age beside each line — fresh lines by how long ago, older ones by when or which day — so a line handed over in a backlog is never mistaken for one said just now. The payload carries an account id for R-ROOM-07's lobby reason and MUST NOT name a room. |
| **R-LCHAT-08** | A line said by another account MUST be reportable from the lobby, citing that line: over `POST /api/reports`, naming the `userId` the line carries and its `retainedMessageId`, never over `report_player`, which addresses a seat the lobby does not have. The control is the author's name on the line. A line delivered without a retained id MUST offer no report action and the lobby MUST NOT explain why — an action never offered owes no explanation, and "retention withheld this" is not something a player can act on. A player's own lines and every line seen by a guest offer none either, for R-MOD-06's reason and to match the room. The dialog offers only the reasons a line of words can be true of (harassment, spam, inappropriate name), shows the line it cites, and MAY be sent with no further detail, since the line is the complaint. [`LobbyChatPanel.tsx`](../frontend/src/components/LobbyChatPanel.tsx), [`ReportLobbyLineDialog.tsx`](../frontend/src/components/ReportLobbyLineDialog.tsx) |

### Friends

| # | Requirement |
| --- | --- |
| **R-FRIEND-01** | A friendship MUST be mutual, and MUST be reached by a request and an answer. A request sent to somebody whose own request is already waiting MUST resolve to one accepted friendship rather than two pending ones — asking back is how you say yes. |
| **R-FRIEND-02** | A friendship MUST be stored as **one row per pair, in a canonical order**, enforced by the database. Two directional rows can disagree and nothing could forbid it. The ordering MUST also make a self-friendship impossible, and the account that asked MUST be one of the pair. |
| **R-FRIEND-03** | Both sides MUST be registered accounts. A guest identity is a browser rather than a person and is purged after a month of not playing, so a friendship with one would outlive the account and vanish unexplained. The caller MUST be told why; the target MUST NOT be. Note the deliberate asymmetry with R-BLOCK-01: a block is a protection and every account has one, a friendship is a convenience. |
| **R-FRIEND-04** | A request MUST be answered identically whether it landed, hit a block, hit an earlier refusal, or named an id that was never an account. Anything else makes the endpoint a way to learn who has blocked you, or which ids are real. The only refusal that may name its reason is a ceiling the caller themselves reached. |
| **R-FRIEND-05** | A decline MUST be durable, so it cannot simply be re-sent into, and MUST be indistinguishable from success to the sender. The person who declined MUST still be able to ask in their own right later: saying no is not a commitment. Cancelling a request or ending a friendship MUST delete the row instead — neither is a refusal, and neither may suppress a future request. |
| **R-FRIEND-06** | A player seated in a room MAY invite a friend into it. The invitation MUST carry no room code, name, or id: it is a token the server resolves against the sender's live seat, so it cannot be forwarded, stops working when the sender leaves, and never tells anybody the code of a room they were not seated in. It MUST be single use and MUST expire. |
| **R-FRIEND-07** | A friend MAY take a seat in a room they cannot name. Uninvited, this MUST resolve only rooms whose **host** is an accepted friend of the caller — otherwise a private room gains a player because one of its occupants knows them, and the host never agreed. With an invitation, the sender's own seat is the consent, and the invitation names the room its **sending socket** was in. Resolution MUST NOT depend on iteration order: an account may hold seats in two rooms at once (R-ROOM-08), so a request that could mean either MUST be refused rather than answered with whichever was found first. |
| **R-FRIEND-08** | Entry by either path MUST run the ordinary seating lifecycle — the seating gate, R-ROOM-08's release of any seat the socket held, R-RATE-06's limits with their refunds, capacity, and the suspension checks on both sides of seating. It MUST NOT re-derive them. |
| **R-FRIEND-09** | Friendships MUST be bounded per account and MUST be rate limited, each refusal naming what was reached in terms the caller can act on — except one that would disclose a third party's state, which MUST stay generic. Every rule a friendship obeys - its ceilings, its rate limit, its silences, and telling the other account that their lists moved - MUST be enforced where the friendship is written rather than beside one of its callers, so that a second way in cannot be given a weaker rule than the first. Merging a guest into an account MUST carry its friendships across under R-BLOCK-04's rules, keeping the stronger status where a pair already exists. |

### Turn structure

| # | Requirement |
| --- | --- |
| **R-GAME-01** | A game MUST proceed as: waiting → *choosing* (15 s) → *drawing* (room-configured, default 90 s) → *turn results* (5 s) → next turn → *game over*. The phase lengths live on [`flow_timing.py`](../backend/app/flow_timing.py) and are tunable (R-CONF-01); `TURN_RESULTS_SECONDS` still supplies the boot value. [`game.py`](../backend/app/game.py) |
| **R-GAME-02** | Every active player MUST draw exactly once per round, for the configured number of rounds. A game MUST NOT start more than `rounds x max_players` turns in total: players joining and leaving re-base the turn cursor, and without that ceiling a room with churn runs past the length it advertised. Where churn makes the two rules disagree the ceiling wins, and a player may go without a turn in the final round. |
| **R-GAME-03** | The drawer MUST be offered **up to 3** prompt options, drawn from prompts not yet used this game (fewer only when the unused pool is smaller). Failing to choose in time MUST auto-pick, and the turn MUST record that it was auto-picked. |
| **R-GAME-04** | The drawing phase MUST end early once every eligible guesser has answered correctly. |
| **R-GAME-05** | Clients MUST read phase lengths off the payload rather than assuming constants, so a shortened phase (as E2E uses) is still a faithful turn. |
| **R-GAME-06** | Rounds contain turns. Points, hint spend, and the drawing limit MUST all be **per turn**, never per round. ([`../GLOSSARY.md`](../GLOSSARY.md)) |

### Guessing

| # | Requirement |
| --- | --- |
| **R-GUESS-01** | Guess matching MUST be language-aware, using the room's resolved prompt language: case-folded, whitespace-collapsed, and accent-folded for the supported Latin registry. [`prompt_content.py`](../backend/app/prompt_content.py) |
| **R-GUESS-02** | A guess MUST be accepted if it matches the canonical answer **or** any accepted alias attached to that exact immutable prompt version. |
| **R-GUESS-03** | A near miss MUST be detectable and reported **only to its author**, never to the room, so it cannot leak the prompt. Detection uses bounded Damerau-Levenshtein distance plus a similarity ratio, with position-independent word matching for multi-word prompts. [`game.py:204`](../backend/app/game.py) |
| **R-GUESS-04** | Guessers MUST see a masked prompt. If the room enables *hide masked prompt*, its length and composition MUST be hidden, and hints MUST be forced off (there are no blanks to reveal). |
| **R-GUESS-05** | When drawing begins, the eligible guesser seats MUST be **frozen**. Seats that were AFK or disconnected at that instant MUST be ineligible until the next turn, and their text MUST be treated as restricted chat rather than a guess. A seat that joins while the drawing is underway MUST instead be **added** to that population: it already sees the canvas and the masked prompt, so it guesses, scores, and holds the turn open like any other guesser, and its turn outcome is recorded as one. [`game.py`](../backend/app/game.py) |

### Scoring

| # | Requirement |
| --- | --- |
| **R-SCORE-01** | Everyone MUST start a game on zero points, in every scoring mode. |
| **R-SCORE-02** | Three modes MUST be offered: **Default**, **Pressure**, **No scoring**. |
| **R-SCORE-03** | **Default**: a correct guess scores `round(100 + 200 × remaining / drawing_seconds)` — between 100 and 300 points, falling linearly. |
| **R-SCORE-04** | **Pressure**: starts at 300 and decays exponentially (~2 %/s at the 90-second reference), the rate **doubling for everyone still guessing** once the first player answers. Floored at 50 gross. The per-second rate MUST be derived from the room's own drawing time so the curve has the same shape in a 15-second room and a 300-second one. Because the penalty scales with the *gap* after the first correct guess rather than applying as a step, a near-simultaneous second guess loses only a handful of points. |
| **R-SCORE-05** | **No scoring** games MUST still detect correct guesses and end turns normally, MUST leave everyone on zero, and MUST NOT show standings. They MUST record the same factual per-seat outcomes with zero awarded points, and MUST NOT invent hypothetical awards. |
| **R-SCORE-06** | **Hints are bought on credit.** Nothing is charged when a hint is bought; the turn's total hint spend is subtracted from that turn's guess award, floored at zero: `turn_score = max(0, guess_points − hint_spend)`. A turn can be wiped out, but a running total MUST NEVER go down, and hints MUST cost nothing to a player who never guesses the prompt. |
| **R-SCORE-07** | Hint spend MUST be capped at 300 per turn — the most a single guess can ever be worth. In Pressure mode the 50-point floor guarantees the **gross** award only; hint spend settles after it. |
| **R-SCORE-08** | The drawer MUST receive the sum of the **net** points earned by all correct guessers in that turn. This is the anti-sandbagging property: a drawer cannot game an easy prompt by stalling, because their bonus scales with how fast guessers actually answered. |
| **R-SCORE-09** | Standings MUST use standard competition ranking (1, 2, 2, 4). The live standings and the recorded ones MUST share one implementation, so a final screen saying two players tied for first cannot be written down as a first and a second. [`game.py:53`](../backend/app/game.py) |
| **R-SCORE-10** | Changing any outcome-producing constant or algorithm MUST bump `SCORING_RULES_VERSION`, and every completed game MUST freeze the full rule snapshot used for its scores. |

### Hints

| # | Requirement |
| --- | --- |
| **R-HINT-01** | Four modes MUST be supported: `none`, `checkpoints` (letters revealed to everyone at fixed points), `purchase` (a guesser buys a letter **slot**, visible only to them), `wheel` (a guesser buys a specific **letter**, revealing every occurrence, visible only to them). |
| **R-HINT-02** | Each hint a player buys in a turn MUST cost more than the last (12, 24, 36, …). |
| **R-HINT-03** | Wheel pricing MUST vary per letter — vowels cost more than consonants, and letters commoner across the room's own prompt pool cost more than rare ones, clamped so a never-appearing letter is still worth something small rather than free. The charge applies **whether or not** the letter is in the prompt. The distribution MUST be the pool the game draws from rather than the sample it drew, so it is summed from a per-revision letter histogram plus the room's quick prompts. Only content the game can actually reach may be priced: a room that keeps lists selected while playing custom-prompts-only MUST be priced on its quick prompts alone. That sum is approximate — a prompt in two selected lists counts twice, a quick prompt shadowing a curated answer does not remove it, and a revision is counted over its whole membership, so content hidden by moderation is priced even though no game can draw it. That last one is deliberate: membership is immutable and moderation is not, and a tally that tracked moderation would be wrong from the first takedown and stay wrong through any restore. On selections where those overlaps are incidental the error is a fraction of a percent and the clamped, max-normalised multiplier does not move; a selection built to overlap heavily — the same prompt repeated across many lists — can skew one letter's tally further, and prices with it. Pricing is a convenience, not an accounting record, and MUST NOT be relied on as one. |
| **R-HINT-04** | At least `MIN_HIDDEN_LETTERS` (2) MUST remain hidden — hints can never fully reveal the prompt. |
| **R-HINT-05** | Hint state (`maskedPrompt`, `hintCost`, `letterPrices`, `hintSpend`) MUST be delivered per socket, never room-wide. |

### Spectating and AFK

| # | Requirement |
| --- | --- |
| **R-SPEC-01** | Anyone MUST be able to join a room as a spectator **whose player seats are full** — that is what spectating is for. Watching is not unlimited: a room admits spectators up to its own ceiling, and refusing one MUST NOT offer spectating back, which would be a loop. |
| **R-SPEC-02** | Spectators MUST NOT draw, score, vote, or be selected as moderation targets. They MUST NOT buy hints in either purchase mode: a hint is bought on credit and settled against the points a correct guess earns, so a seat that can never guess would reveal letters for free — including in a room that keeps the prompt from spectators. The guard is seat eligibility for the turn (`is_turn_eligible`), which a spectator never holds: `_begin_drawing` snapshots the turn's participants from seated players alone, and the only other way into that population — joining while the drawing is underway (R-GUESS-05) — runs off the same rotation, which a spectator is never put in. [`handlers/chat.py`](../backend/app/handlers/chat.py), [`services/game_flow.py`](../backend/app/services/game_flow.py) |
| **R-SPEC-03** | Spectators MUST see the masked prompt by default; the room may enable *Allow spectators to see the prompt*. |
| **R-SPEC-04** | Spectator chat MUST be restricted to the drawer, spectators, and players who have already guessed correctly, keeping active guessers spoiler-free. |
| **R-SPEC-05** | Spectators MUST be bounded per room, configurably, independently of `max_players`. Every spectator is another recipient of every broadcast, so an unbounded audience makes a room arbitrarily expensive to be in without anyone taking a player seat. |
| **R-AFK-01** | A player MUST be able to toggle their own AFK status at any time. AFK players MUST be skipped for drawing turns and not waited for during rounds. |

### Votes

| # | Requirement |
| --- | --- |
| **R-VOTE-01** | Active players MUST be able to propose and carry a **restart vote** by strict majority, without interrupting live gameplay. Window 20 s, cooldown 60 s, 3 s delay before the restart. [`handlers/restart.py:18`](../backend/app/handlers/restart.py) |
| **R-VOTE-02** | Room players MUST be able to vote to **kick** or **mark AFK** another player by strict majority (`majority_of(n) = n//2 + 1`). |
| **R-VOTE-03** | The voting population MUST be connected non-spectators. AFK players and the vote target **do** count toward it; disconnected players and spectators do **not**. [`rooms.py:371`](../backend/app/rooms.py) |

### Drawing

| # | Requirement |
| --- | --- |
| **R-DRAW-01** | The canvas MUST be synchronized in real time across every client in the room, including late joiners. |
| **R-DRAW-02** | Tools MUST include a freehand brush, an eraser, a flood fill, and rectangle/ellipse/triangle shapes. |
| **R-DRAW-03** | **Allowed tools** and **Color mode** MUST be enforced on the server, which refuses a disallowed tool or color **before** recording or rebroadcasting, so a stale or modified client gains nothing. |
| **R-DRAW-04** | At least one of brush/shapes MUST remain enabled — fill alone can only flood a blank canvas. |
| **R-DRAW-05** | Erasing is a white brush stroke on the wire, so it rides with the brush and **every color mode MUST permit white.** The brush and eraser can only be banned or admitted together. |
| **R-DRAW-06** | Undo MUST be available to the drawer and MUST be reconcilable: it carries the client's generation, sequence, revision, and history hash, and a disagreement MUST resolve to an authoritative sync rather than a divergent canvas. |
| **R-DRAW-07** | Per-turn drawing MUST be bounded: ≤ 20 000 actions, ≤ 25 000 path points, and ≤ 20 000 weighted replay-work units (a fill costs 200× a path). Every joining client replays the whole turn, so an unbounded turn is a way to grief a room. |
| **R-DRAW-08** | The client MUST be the **stricter** of the two — it greys the fill tool out before the budget runs down, so a drawer meets the limit as a disabled button rather than a refusal. The server value is the authoritative backstop. |
| **R-DRAW-09** | A player MUST be able to save the current canvas as a PNG at any time, produced by the browser. |
| **R-DRAW-10** | The server MUST NOT rasterize. It stores and replays actions, never pixels. |

### Reactions to drawings

A **Reaction** is one emoji a registered player leaves on a turn's drawing (#520). It
follows the drawing to every surface the drawing is shown on — the live canvas, turn
results, the **Recap**, and game history — and is a fact *about the drawing*, which is
what decides where it is stored and when it goes.

| # | Requirement |
| --- | --- |
| **R-REACT-01** | Only an account with lifecycle `registered` MUST be able to react. Guests and cookieless seats see reactions but cannot give them. **Not** email verification: registering does not require an address, so a verified-email gate would lock out ordinary registered players. |
| **R-REACT-02** | Spectators MUST NOT react. The drawer MUST NOT react to their own drawing — checked by seat **and** by account, because a drawer who left and rejoined holds a new seat. A seat ineligible to guess (AFK, disconnected at freeze) MAY react: they can see the drawing. |
| **R-REACT-03** | One reaction per registered account per drawing, chosen from the fixed positive **Reaction set**, changeable and removable at any time. Uniqueness MUST be a database constraint on `(turn, participant seat)` with no alias resolution behind it — a game holds one seat per linked account, and guests bring none across a merge (R-ACCT-04). |
| **R-REACT-04** | Reactions MUST be accepted from the moment the drawing is visible: during the Drawing phase and at turn results for the **current** turn only, in the Recap, and from game history at any later time. An earlier turn of a live game is no longer on anyone's screen and MUST be refused. |
| **R-REACT-05** | A live reaction MUST be broadcast to the whole room, the drawer included, and room payloads MUST carry the reactor's seat token and presentation only — never an account id (R-ROOM-07). State payloads (`turn_started`, `sync_game`, `turn_ended`, recap metadata) MUST carry the reaction **list**, not only a tally, so a reconnecting client recovers its own pick. |
| **R-REACT-06** | Reactions given while a game is live MUST be kept on the `Room` and folded into the all-or-nothing finished-game write (R-HIST-03), for a completed **and** an abandoned game (R-HIST-05). A game lost with the process loses them (R-SHUT-06). |
| **R-REACT-07** | A reaction given from the Recap or from history is a write to a finished game and MUST go through one repository path shared by the socket and the REST route. It MUST refuse while the history write is still pending, and when the game was never recorded. It MUST NOT touch the score ledger (R-HIST-11): reactions are not scored. |
| **R-REACT-08** | The REST write MUST sit beside the drawing route and **every refusal MUST be a 404** (R-HIST-16) — stranger, guest, drawer, erased drawing, unknown code and unknown game alike. |
| **R-REACT-09** | Emoji MUST be stored as stable codes with the set version, never as glyphs. A code, once shipped, MUST NEVER be removed or reused (the stored-drawing rule, R-HIST-18): retiring one stops it being offered and nothing else, so old history keeps rendering. Adding one is additive and bumps the set version. |
| **R-REACT-10** | A reaction hangs off the reactor's participant seat (R-PRIV-08), so a deleted reactor reads as **Deleted player** and still counts. An **Erased** drawing MUST take its reactions with it and accept no new ones; the turn and its scores remain. |
| **R-REACT-11** | Lifetime reactions received MUST be served from the daily projection (R-HIST-20), credited to the drawer on the game's day and adjusted by delta on later writes, so a rebuild reproduces the same totals. A decrement MUST NOT drive an erased projection row negative (R-HIST-21). |
| **R-REACT-12** | Reactions MUST answer to the existing per-caller `action` budget (R-RATE-08) and MUST NOT get a budget of their own. |
| **R-REACT-13** | The picker MUST be offered only where pressing it can work: guests see the tally and one line on creating an account; spectators and the drawer see a see-through tally with no control, and nothing until there is something to count. Reactions MUST be drawn from bundled artwork in a fixed square box, never from the platform's emoji font: every emoji font sits its glyphs on a different baseline, so a count beside a Unicode emoji lands somewhere different in every browser, and no CSS nudge fixes all of them at once. |

---

## 3. Prompts

| # | Requirement |
| --- | --- |
| **R-PROMPT-01** | Standard and Extended English lists MUST ship with the game. |
| **R-PROMPT-02** | A room MUST resolve **exactly one** prompt language, derived authoritatively from its selected lists. Missing, empty, or mixed-language selections MUST be visible validation failures, never silent fallback. |
| **R-PROMPT-03** | A prompt's identity MUST be independent of its spelling: a **Prompt concept** with immutable language-specific **Prompt versions**. Equal text MUST NOT merge concepts implicitly. |
| **R-PROMPT-04** | Aliases MUST be attached separately to each version, so changing an alias later cannot rewrite how an older game matched guesses. |
| **R-PROMPT-05** | Bundled seed entries MUST carry an explicit `conceptId`. Changing wording, aliases, or editorial metadata requires the same `conceptId` and a higher `promptVersion`; changing membership requires a higher list `version`. |
| **R-PROMPT-06** | Deploying different content under an already-seen list or prompt version MUST fail startup, not silently rewrite. |
| **R-PROMPT-07** | If prompt lists cannot be read at all, creating a room or changing its settings MUST be refused against the prompt-list field, rather than the room opening quietly on built-in prompts. A custom-prompts-only room is unaffected, because it was never going to read a list. |
| **R-PROMPT-08** | Rooms MUST resolve, and games MUST pin, exact immutable revision IDs. |
| **R-PROMPT-09** | Unsupported BCP-47 language tags MUST be rejected until their matching semantics are implemented. |

### Player-owned lists

| # | Requirement |
| --- | --- |
| **R-LIST-01** | Registered players MUST be able to save, revise, reuse, and delete their own prompt lists. Prompts are pasted in batches (one per line or comma separated) and merged, with duplicates and overlong entries **reported rather than silently dropped**. |
| **R-LIST-02** | Owned lists MUST default to **Private**; **Unlisted** MUST require a unique cryptographically random share code. `public` is reserved for a future moderation-approved discovery feature and MUST NOT be user-selectable in v1. |
| **R-LIST-03** | Share codes are **bearer capabilities**. They MUST be retained only in private in-memory room state and MUST NOT appear in room, history, preset, or log payloads. |
| **R-LIST-04** | Limits: ≤ 25 lists per account, ≤ 500 prompts per list. |
| **R-LIST-05** | Editing MUST use optimistic concurrency and MUST create a new immutable revision rather than rewriting the revision a running or finished game pinned. The content language MUST NOT change after creation. |
| **R-LIST-06** | **Quick custom prompts MUST remain ephemeral room input.** They are not auto-saved, acquire no implicit owner or list, and disappear with the in-memory room. A registered host may explicitly save them as a Private list; **nothing is stored merely because it was typed.** |
| **R-LIST-06a** | A room whose selected prompt lists cannot be read MUST be refused **visibly**, never opened on the built-in list while the host is shown the lists they chose. A custom-prompts-only room is the one exception: it was never going to draw from a list. |
| **R-LIST-07** | Waiting rooms MUST re-authorize their lists immediately before Start, closing stale-picker bypasses, and pin the revision each list is then on. Every prompt a game offers MUST come from those pinned revisions and MUST be active at the moment it is drawn. The draw is the snapshot boundary: an edit cannot reach a running game at all, because revisions are immutable and the game holds a pinned one, but a takedown lands only if it precedes the draw — content hidden afterwards stays in the sample that game already holds, and is removed from play when the game ends rather than mid-turn. A game already in progress keeps its pinned snapshot and MUST NOT be rewritten mid-turn. |
| **R-LIST-08** | A list with no usable prompts MUST fail **visibly**. |
| **R-LIST-09** | User-owned lists and their prompt stats MUST NOT enter the public official catalogue. |
| **R-LIST-10** | v1 MUST NOT expose community discovery, a favourite/star table, or a user-facing fork endpoint. |

### Prompt statistics

| # | Requirement |
| --- | --- |
| **R-STAT-01** | Pick rate and guess accuracy MUST be tracked per official prompt and be browsable from the lobby on a searchable, sortable page. |
| **R-STAT-02** | Difficulty MUST only be ranked once enough guessers have faced a prompt. Everything else MUST be listed as **unranked** rather than shown a zero it has not earned. The floor MUST apply independently to the selected slice. |
| **R-STAT-03** | Statistics MUST be derived by **stable prompt concept**, so a later wording revision keeps its history without matching on display text. |
| **R-STAT-04** | An ephemeral prompt MUST have a null curated source **even when its display text equals a curated prompt**, so neither its offers, picks, nor guess results can inflate curated statistics. |
| **R-STAT-05** | Windows (all-time, 30-day, 90-day) and scoring/hint segmentation MUST be supported. Pre-cutover counters carry null time/rule dimensions and MUST be excluded from bounded or segmented reads rather than attributed falsely. |

---

## 4. Accounts and identity

| # | Requirement |
| --- | --- |
| **R-ACCT-00** | Choosing a name MUST be what provisions a guest account. `GET /api/auth/me` MUST NOT provision: it runs on every page load, including ones nobody is behind, and provisioning there charged a crawler, a link preview and an uptime check two rows each. It may still write for a caller who already has an account — recording activity, rotating a session — but it MUST create nothing for one who does not. |
| **R-ACCT-01** | Playing MUST NOT require an account of its own: a visitor with no cookie at all MUST still be seatable (see R-HIST-10). A visitor who chooses a name MUST be given an account, remembered by an HttpOnly `sketchy_session` cookie. |
| **R-ACCT-02** | Guests MUST be provisioned **only** by choosing a name (`POST /api/auth/display-name`), and accounts otherwise only by registering. Merely opening a socket, or merely loading the page, MUST NOT create a user row. |
| **R-ACCT-03** | Setting a username and password later MUST claim that same account, so stats collected as a guest carry over. |
| **R-ACCT-04** | Logging in while carrying a guest identity MUST create an **immutable alias**, never rewrite historical seats. A game containing both identities keeps two factual seats. |
| **R-ACCT-05** | A registered player MUST always play as their username and account color, so a name in the player list is either a claimed account or an unclaimed guest — never one impersonating the other. Guests MUST be pinned to the guest grey. |
| **R-ACCT-06** | Accounts MUST have an explicit lifecycle state (`anonymous`/`registered`/`merged`/`deleted`) and a role (`user`/`moderator`/`admin`). The legacy guest boolean MUST be derived, never a separate value that can drift. |
| **R-ACCT-08** | A name colour MUST be readable wherever a name is drawn: at least 1.8:1 against the player-list panel of **both** themes — a floor that refuses a colour which vanishes on one panel (white on the light theme, slate on the dark), deliberately below WCAG's 3:1 because a name is a short bold label and 3:1 on both panels leaves no yellow, sky or pink at all, checked by the server on every path that writes one — the REST route, the `update_player_settings` socket command, and seating (#571). Shape is not enough: a well-formed `#rrggbb` can be white on the light panel or near-black on the dark one, and the palette Settings offers is a client-side courtesy that a modified client need not observe. A value that fails is treated as unset and re-rolled from the palette rather than refused after the fact, so a colour stored before the rule existed heals itself. The palette MUST itself clear the rule and MUST NOT hold two near-duplicate colours, so the swatches and the server can never disagree and each swatch is a different choice; `tests/test_name_color.py` proves both, and that the two hex surfaces the server mirrors are still the theme's panel colours. [`app/rooms.py`](../backend/app/rooms.py) |
| **R-AVA-01** | A registered player MAY upload a picture to stand in for their initial. The browser MUST let the player frame a square of it (drag and zoom), then re-encode that square to 256×256 before sending — WebP where the browser can encode one, PNG where it cannot, because a photograph at that size is ~136 KiB as lossless PNG (over the cap) and ~22 KiB as WebP; the server MUST accept only a WebP or PNG of exactly that size under 128 KiB, checked from the fixed-position header of either format without decoding the image, and MUST serve it only ever as the image type it found, with sniffing disabled. That is the whole surface a modified client has: any valid WebP or PNG up to the cap, shown as an image and nothing else. [`auth/avatars.py`](../backend/app/auth/avatars.py) |
| **R-AVA-02** | A guest MUST NOT have a picture, in storage or on the wire: R-ACCT-05 makes a name in the player list either a claimed account or an unclaimed guest, and a picture on a guest would break exactly that. Every identity payload MUST carry `avatarUrl` beside `nameColor`, null for a guest, so one render component draws every disc. Finished-game history MUST NOT carry it (R-PRIV-08). |
| **R-AVA-03** | Pictures are content-addressed: the key is the SHA-256 of the bytes plus the format's extension (`.webp` or `.png`), so the same picture has one URL for ever and a changed picture is a new URL, which is what lets every picture be cached as immutable. One picture per account, replaced whole. The bytes live in `uploaded_avatar_assets` — small by construction, which is what keeps them defensible in the primary database until object storage (#471) exists. |
| **R-AVA-04** | A picture is player-submitted content: it MUST be reportable (`inappropriate_avatar`, the sixth report reason), the moderation queue MUST show it, and a moderator MUST be able to remove it **through the report** (R-MOD-02: never by holding an account id). Removal MUST be audited and MUST block the account from uploading for **7 days**, because a removal a re-upload can undo a minute later is not a removal. Taking your own picture down is not a punishment and sets no block. |
| **R-AVA-05** | The picture is the player's own upload: the data export MUST carry the bytes (R-PRIV-01), and deletion MUST remove the asset row in the same transaction as the account (R-PRIV-05). A change MUST reach live seats and the lobby's identity cache without a reconnect. |
| **R-ACCT-07** | The first administrator MUST be created by a guarded command that refuses to run once an administrator exists and records the promotion and a required reason in the audit log. |

### Passwords, sessions, email

| # | Requirement |
| --- | --- |
| **R-AUTH-01** | Passwords MUST use Argon2id. Every successful login MUST compare against current cost parameters and replace a stale hash atomically, so raising the cost upgrades active accounts without a bulk migration. |
| **R-AUTH-02** | Session cookies MUST carry opaque 256-bit random tokens; **only SHA-256 hashes may be stored.** The database MUST NOT contain a replayable credential. |
| **R-AUTH-03** | Tokens MUST rotate halfway through their one-year maximum lifetime. Registered players MUST be able to inspect and revoke individual devices, or log out everywhere. |
| **R-AUTH-04** | Socket.IO handshakes MUST resolve the same revocable record as HTTP requests, so revocation applies on the next connection without a shared signing secret. |
| **R-AUTH-05** | An email address MUST be **optional and stay optional** — requiring one would break registration on every deployment with no SMTP configured, including the zero-configuration default. |
| **R-AUTH-06** | An address MUST be recorded **only once confirmed**. Until then it lives in the confirmation token and nowhere else, so a typo cannot hand the account to whoever owns the typed address, and nobody can reserve a mailbox they do not control. |
| **R-AUTH-07** | Only a confirmed address may be sent a reset link. |
| **R-AUTH-08** | A reset link MUST be checked when the page opens, not when the form is sent, so nobody chooses a password only to be told the link was spent. Checking MUST NOT consume it, and MUST be throttled separately from requesting a reset. |
| **R-AUTH-09** | `POST /api/auth/password/forgot` MUST answer identically whether or not the account exists. The response MUST NOT be a place to learn which usernames are real. |
| **R-AUTH-10** | A completed reset MUST revoke every session on the account — including one held by whoever forced the recovery — and sign the person performing it back in. The token claim MUST admit exactly one consumer (a conditional `DELETE … RETURNING`, decided by the database), and the new password, the revocation, and the audit and mail effects MUST commit in one transaction, so a failure between them leaves the old password, the live sessions, and the unspent link, never a new password with old devices still authorised. [`auth/tokens.py`](../backend/app/auth/tokens.py), [`auth/recovery.py`](../backend/app/auth/recovery.py) |
| **R-AUTH-17** | A signed-in password change (`POST /api/auth/password/change`) MUST prove the current password first, MUST hold the same password rules a reset does, and MUST end the same way R-AUTH-10 requires: every session revoked, the caller signed back in, in the same transaction as the new password. Changing a password is how somebody evicts a device they no longer trust, so a change that left other sessions standing would be the failure worth avoiding. A guest MUST be refused — there is no password to change — and the reset link stays the only route for somebody who does not know theirs. |
| **R-AUTH-11** | Mail MUST be queued in the same transaction as the action that causes it, and delivered afterwards, so an unreachable relay never undoes a suspension. Reset messages retry with backoff and are then recorded as failed rather than disappearing. |
| **R-AUTH-11a** | Delivery MUST claim a batch, send outside every transaction, and record each outcome separately: no database transaction may be held across network I/O, and one slow recipient MUST NOT delay the messages behind it. A claim MUST be a lease rather than a state, so a process that dies mid-send leaves a message that comes due again, and every message MUST carry the identity of its outbox row so a resend is a duplicate rather than a second message. |
| **R-AUTH-11b** | An outbox payload may hold a raw link token only while its row is `pending` — a retry has to rebuild the link. The update that makes a row `sent` or `failed` MUST scrub the token in the same transaction, so the database never holds a replayable credential beside the hash `auth_tokens` keeps. Terminal rows MUST be purged after 30 days. |
| **R-AUTH-12** | With no `SMTP_HOST`, messages MUST be **logged instead of sent**, including confirmation and reset links — the only way that flow can complete on a deployment without mail. |
| **R-AUTH-13** | Email MUST be used only to reset a password and to tell someone their account was suspended or their content hidden. **Nothing else is ever sent to it.** |
| **R-AUTH-14** | A deployment without mail MUST be able to reset a password from the server. This MUST NOT be an API — there is no authentication that would make a remote password reset safe — and it MUST record the reason in the audit log. |
| **R-AUTH-15** | An account with no recovery address MUST be reminded weekly, with the interval kept **on the account** so it neither restarts on each new device nor disappears when browser storage is cleared. |
| **R-AUTH-16** | That reminder MUST stay out of rooms: being in a room suppresses it **without spending it**. A room lays itself out to the viewport rather than flowing beneath a banner, and account hygiene can wait until somebody is not mid-game. The deploy banner deliberately does not behave this way, because a game about to be ended under you is worth interrupting for. |

### Authentication rate limits

| # | Requirement |
| --- | --- |
| **R-RATE-01** | Login, registration, and lookup limits MUST be persistent, shared database buckets, so they survive restarts and apply once across every replica. A limit MUST NOT be decided by reading a bucket, deciding in the application, and writing it back: every statement MUST carry its own condition, so the database evaluates the ceiling against the row as it stands. `SELECT … FOR UPDATE` MUST NOT be relied on for this — SQLite ignores row locks and is the documented default, so a read-then-write ceiling is soft by however many attempts are in flight together. |
| **R-RATE-02** | Bucket keys MUST be HMAC-SHA-256 digests under `IP_HASH_SECRET`. **Raw IP addresses MUST NOT be stored.** |
| **R-RATE-03** | Expired buckets MUST be cleaned in bounded batches. |
| **R-RATE-04** | Rotating the secret MUST start fresh buckets without exposing or re-identifying old keys. |
| **R-RATE-08** | Every client-originated Socket.IO command MUST answer to a per-caller budget, sized by what the client actually does: drawing at the drawer's own flush rate, conversation at a message or two a second, a floor between full canvas replays, and a human's pace for everything else. The budget MUST be checked **before** parsing, authorization or mutation, so a refused command costs only the check. Windows MUST be keyed by the **kind** of traffic rather than by the command, or two commands of one kind each get the allowance their kind was given. A refusal MUST do no work: `draw` frames, which nobody awaits, MUST drop silently, and every command a person pressed a control for — `undo_stroke` included, which shares drawing's budget but is awaited — MUST answer a bounded acknowledgement rather than leave them looking at a control that did nothing. Exhaustion MUST be recorded as a runtime observation **once per window** — not once per refusal, which would be the write amplification the budgets exist to stop, and not once per caller, which would make a two-second mistake and a twenty-minute flood indistinguishable. |
| **R-RATE-09** | Budgets MUST carry their default, bounds and purpose beside them, and MUST NOT be read from the environment: #446 tunes them from an admin panel without a deploy, and a value fixed at startup forecloses that. The bounds MUST refuse a limit the client cannot live with — drawing below the drawer's own flush rate is not a setting, it is a broken room. |
| **R-RATE-07** | Guest provisioning MUST be bounded per address **and** by a daily ceiling for the whole deployment — the bucket is a shared database row, so replicas count against one number, not one each — and stale guest rows MUST be purged on a schedule the application owns. A retention policy nothing runs is not a policy. |
| **R-RATE-06** | Seating joins MUST be rate-limited per socket, and rebinding an existing seat to a new socket MUST be rate-limited **per seat** — a per-socket key cannot see that churn, because every attempt arrives on a new socket with a fresh allowance and the one it supersedes is closed. Confirming a seat already held MUST NOT be charged: a client heartbeats through that path, and a liveness check must never be able to lock a player out of their own room. |
| **R-RATE-05** | The room-creation limit MUST use the same persistent buckets, keyed by **account**, and an attempt that opens no room MUST be given back rather than spent. A per-address key MUST NOT be introduced until a trustworthy client address exists to key on: behind a reverse proxy every socket presents the proxy, and the forwarded header is attacker-controlled. |

### Player settings

| # | Requirement |
| --- | --- |
| **R-SET-01** | Registered players' settings MUST follow them across devices: theme, time format (`system`, `12h`, `24h`, with `system` — the device's own convention — as the default), sound and confetti switches, volume, brush cursor, keyboard shortcuts, and the colorblind-safe preference. Every clock and date-time a player is shown MUST go through one formatter that honours the time format, so the preference means one thing everywhere. |
| **R-SET-02** | Values MUST be bounded at both the API and database layers (key bindings must describe the complete supported action set). |
| **R-SET-03** | Guests keep settings in browser local storage only. Creating an account MUST copy that browser's settings **exactly once**; logging in later makes the account copy authoritative. |
| **R-SET-04** | Settings already stored in a browser MUST NOT be renamed — they MUST be migrated on load. A setting that is **retired** MUST have its stored key cleared, in the same module: nothing reads it, so leaving it there hands a data export a field the document no longer has and lets a value nobody can see come back. [`store/settingsMigrations.ts`](../frontend/src/store/settingsMigrations.ts) |
| **R-SET-05** | Every preference MUST apply the moment it is changed, and the surface MUST NOT offer a Save: none of them is a transaction, and a theme that does nothing until a button is pressed — and silently reverts on Discard — is a control lying about its own state. Only a value the **server can refuse** (the display name, the email address, the password) may keep a button, because it needs somewhere to report the refusal. Writes MAY be merged, so a dragged slider is one request rather than one per step. Success is silent; a write the account refuses raises a notice, and the value stays applied locally. |
| **R-SET-06** | Settings MUST be addressable: it is a route (`/settings/:section`, sections `account`, `appearance`, `sound`, `shortcuts`) so it can be linked, bookmarked and pointed at from an answer, and it MUST open **over** the page it was reached from so opening it never gives up a live room. A visitor arriving on the URL itself MUST get the lobby behind it rather than nothing. One rail on every device: the same four sections in the same order, scrolling sideways on a phone rather than becoming a different control. Guests keep every section, with account-only rows locked and the reason on the row. |
| **R-SET-07** | A setting MUST NOT exist in storage without a way to see it. A preference that has no interface is either given one or removed from the browser, the account, the API and the data export together — a synced value nobody can read is dead weight that the export contract still has to carry. |
| **R-SET-08** | An email address MUST be shown back to its owner with its middle hidden one dot per letter (`s•••••o@e•••••e.com`, so the shape and length survive), beside a **Verified** / **Not verified** symbol — not only a sentence — and with a control to reveal it in full on demand. Settings is opened on screens other people can see, the address is the one value on it worth copying down, and whether it is verified decides whether the account can be recovered at all; the reveal exists for somebody who needs to read it back. Masking is presentation only: the wire, the confirmation link and any typed correction use the real value. The same masking applies to the recovery banner, which is on every screen. |

### Colorblind-safe suggestion

| # | Requirement |
| --- | --- |
| **R-CB-01** | While an opted-in **player** (not a spectator) is seated in a room using another color mode, **only the host** MUST receive an unattributed suggestion. |
| **R-CB-02** | It MUST NOT change room settings automatically, MUST disappear when the last opted-in player leaves, and a dismissed one MUST stay gone. |
| **R-CB-03** | It belongs to the waiting room, where the palette can still be changed: an unanswered one MUST clear when a game starts and return afterwards. |
| **R-CB-04** | The preference and the dismissal MUST NOT appear in player, room-state, room-list, invite-preview, or session payloads. |

---

## 5. Room-setting presets

| # | Requirement |
| --- | --- |
| **R-PRESET-01** | Registered players MUST be able to save up to **20** private room-setting presets: a named, versioned copy of typed settings with no code, members, host identity, game, scores, timers, chat, or canvas. |
| **R-PRESET-02** | Applying a preset MUST fill the create form only. Creating from a preset allocates a fresh code like any other room. |
| **R-PRESET-03** | Borrowed Unlisted share codes and quick custom prompts MUST NOT be stored in a preset. |
| **R-PRESET-04** | v1 MUST NOT ship a built-in preset catalogue or preset sharing. |

---

## 6. Connection resilience

| # | Requirement |
| --- | --- |
| **R-CONN-01** | On disconnect, a player MUST have 30 seconds to reconnect with their private stored secret and keep their score and place in the turn order. |
| **R-CONN-02** | A successful reconnect MUST replace the player's active socket, so the superseded socket can no longer issue commands. |
| **R-CONN-03** | If the drawer disconnects and does not return in time, their turn MUST be skipped and they MUST be evicted from the rotation. |
| **R-CONN-04** | If everyone disconnects, the room MUST be cleaned up — and if a game was live, an `abandoned` game record MUST be written. |
| **R-CONN-05** | An action that expects an answer MUST NEVER be handed to a socket that is not connected. It waits for the connection and is sent once, or it times out **having never been sent** — so a request reported as failed cannot arrive later on reconnect. |
| **R-CONN-06** | Actions that only make sense in the moment (a guess, a vote, leaving, toggling AFK) MUST be dropped outright rather than replayed into whatever the room has become. |
| **R-CONN-07** | A disconnect MUST reconcile against every room the socket actually holds a seat in, rather than the single room its session names, so a seat stranded by an earlier build still becomes disconnected and is evicted on the ordinary grace. |
| **R-CONN-08** | The process MUST bound how many sockets it holds at once, configurably. A socket past the ceiling MUST be **told and then closed**, never refused at the handshake: `ConnectionRefusedError` is reserved for suspensions, and a refusal carries no signal the client can explain to a player. The ledger MUST be keyed by socket id rather than counted, so a missed or repeated close cannot drift it, and it MUST be balanced on **every** way out of the handshake — a refusal never reaches the disconnect handler, so a socket counted in and refused out would hold its place for ever. |

---

## 7. Moderation and safety

### Reports

| # | Requirement |
| --- | --- |
| **R-MOD-01** | Any signed-in player, **including a guest account**, MUST be able to submit a private report. Reports use one of six bounded reasons (harassment, offensive drawing, inappropriate name, cheating, spam, inappropriate avatar) plus ≤ 2000 characters of detail and an optional ≤ 32 KiB JSON context snapshot. The detail MUST be optional on both routes: the evidence — the cited lines, the drawing — is usually the whole complaint, and a reporter mid-turn, or one reporting a lobby line from the line itself, is not made to write it out. An empty detail is stored empty and shown as *no details given*, never padded with stand-in words a moderator could read as the reporter's. |
| **R-MOD-02** | A player report from a **room** MUST name their **seat**, never their account. Wanting to complain about somebody is not a reason to learn their account ID. The lobby is the one exception, and only because there is no seat: a lobby line already carries its author's account id for R-ROOM-07's reason, and a report of it names that id over REST (R-LCHAT-08). |
| **R-MOD-03** | The **server** MUST select the evidence — the reported player's recent messages as the reporter actually received them — which makes *"is this message theirs"* and *"did you see it"* true by construction rather than checks against a client's claims. |
| **R-MOD-04** | Up to 20 unexpired messages may be pinned, and only when the reported player authored them and the reporter was in each stored audience. Expired, cross-room, wrong-author, and mismatched game/turn evidence MUST be rejected. A lobby line is public by construction, so the audience check does not apply to it; a report mixing lobby and room lines MUST be rejected (R-LCHAT-05). These are the **cited** lines; R-MOD-13 adds the lines around them. |
| **R-MOD-13** | A report MUST carry the conversation around what it cites, because a line on its own is often unreadable: the **server** copies up to **10 lines before and 5 after** the latest cited line, within **12 hours** of it, from the same room instance or the lobby, by anyone — but only lines the reporter received: a room line by R-MOD-04's stored audience, a lobby line by re-applying the reporter's blocks (R-LCHAT-03), since a lobby row records no recipients and a muted author's text must not reach the reporter through a report they can export — and never a cited line twice. A room report with nothing cited anchors on the moment it was filed; a REST report with nothing cited copies nothing. Context MUST be marked as such (`role`), shown to a moderator as one thread in the order it was said, and MUST NOT be shown back to the reported player: a Warning or Suspension names their own words only (R-MOD-12). A third party's line copied this way MUST be tombstoned on that account's deletion exactly as cited evidence is (R-PRIV-07). [`player_reports.py`](../backend/app/services/player_reports.py) |
| **R-MOD-05** | One reporter MUST hold **one open report per target**. Once decided, the same reporter may raise a new one — that is a new incident, not the same complaint repeated. |
| **R-MOD-06** | Reporting MUST require an account, because a report a moderator cannot follow up on helps nobody. |
| **R-MOD-07** | Review MUST be one-way: a pending report receives one resolution and cannot later be silently rewritten. |
| **R-MOD-08** | Submitted context MUST be preserved as **reporter-supplied evidence**, and MUST NOT be treated as a server-verified fact merely because it was stored. |
| **R-MOD-08a** | Message retention MUST NOT sit on the delivery path. A message's identifier is issued before its row is written, so live chat never waits for the database; a report naming a message that was never retained MUST be refused as unavailable rather than accepted without its evidence. Retention that cannot keep up MUST withhold the identifier rather than delay the message or grow without bound. |
| **R-MOD-09** | Player-authored prompt content MUST have a separate, target-specific report flow against a list or an exact prompt version. Official bundled content, inaccessible content, and self-reports MUST be rejected. |
| **R-MOD-10** | Prompt-content moderation MUST be **post-moderation**: a report alone never changes availability. Resolution explicitly chooses Active or Hidden; a dismissal MUST NOT mutate content. |
| **R-MOD-11** | Hidden prompts MUST be filtered from future selection. Owners see moderation state in *My prompt lists*, and editing MUST NOT silently override a moderator decision. |
| **R-MOD-12** | A moderator MUST have a consequence between dismissal and **Suspension**: a formal **Warning** shown to the reported player once, in their own reported words — and, when the report carried one, their own drawing (R-MOD-14), for the same reason — restricting nothing. Its acknowledgement MUST be recorded, and it follows the same role boundaries and same-report rule as a suspension. |
| **R-MOD-14** | A report filed from a room about the player **drawing** MUST be able to carry the canvas as it stood when the report was sent, because an offensive drawing is undone, cleared, or drawn over long before a moderator looks, and the turn's own stored drawing is its final state, written only when the game ends and erased with the drawer's account. The reporter asks for it (`includeDrawing`) and never supplies it: the **server** copies its own canvas frame, and only when the reported seat holds the pen this turn in a phase where the canvas still shows it (drawing, turn results) — a report about a guesser, or one sent once the next drawer is choosing, is accepted without it and the acknowledgement says so, since the turn can end under an open dialog. The copy MUST be kept for as long as the report is, under the stored-drawing rules (format named, checksum verified on read, the same size bound), and MUST be shown to a moderator drawn rather than described, with the prompt the drawer was given. The bytes MUST be readable only by a reviewer; the reporter's export records that a drawing was attached and of which turn, never the bytes. The client MUST offer the option only where the server would copy, and the server's rule is the one that holds. [`player_reports.py`](../backend/app/services/player_reports.py), [`ReportPlayerDialog.tsx`](../frontend/src/components/ReportPlayerDialog.tsx) |
| **R-MOD-15** | Decided cases MUST stay reachable. The open queues are small and may be held whole; closed cases accumulate for as long as the service runs, so they MUST be served as one stream across player and content reports, **newest decision first**, under a bounded page (`limit` ≤ 100, `offset` ≤ 1000) that says whether an older page exists — a fixed window from the oldest end, which is what the queue's own ordering gives, would make the newest decisions the ones a moderator could never reach. A closed case MUST show what its open one did, evidence and drawing included, plus the **decision**: what was done, in one word read from the warning or suspension that names the report or the state a content decision set rather than from the report's own status, who decided it — the name resolved when read, never stored beside the case (R-AUDIT-02) — when, and the note. The list MUST carry the outcome beside each closed case so a queue can be scanned. [`api/moderation.py`](../backend/app/api/moderation.py), [`ModerationPage.tsx`](../frontend/src/pages/ModerationPage.tsx) |

### Suspensions

| # | Requirement |
| --- | --- |
| **R-BAN-01** | Moderators and administrators MUST be able to create temporary or permanent suspensions. Moderators MUST NOT suspend peers; administrators MUST NOT be targeted. |
| **R-BAN-02** | Creating a suspension MUST revoke every signed-in device and remove any live room seat immediately. Ending an account — suspended or deleted — MUST close every **socket** it holds, not only the ones found holding a seat: an entry awaiting the database has no seat to find and would seat itself after the sweep had passed. Because closing a socket waits at that socket's seating gate, an entry holding it MUST also refuse to seat an account the sweep has reached — and MUST give back a seat it had already taken when the sweep reaches the account mid-entry, rather than leaving it to the reconnect grace. The sweep MUST mark the account's sockets before its own first await, since every step of it yields. Login, authenticated HTTP requests, and Socket.IO handshakes MUST all reject an active suspension. |
| **R-BAN-03** | A token revoked at ban time MUST stay recognizable until expiry, so its next request cannot be mistaken for a new cookieless guest. |
| **R-BAN-04** | **Data export, account deletion, and logout MUST remain available** through that ban-time credential — moderation MUST NOT erase privacy rights. |
| **R-BAN-05** | A suspension MAY carry an end date (24 h / 7 d / 30 d / none) and one with an end date MUST lift itself, because the list reports what is in force rather than trusting something to have run. Permanent MUST NOT be the default. |
| **R-BAN-06** | A suspension lifted by hand MUST keep its row and record who lifted it and why. Suspending from a report MUST resolve that report — acting on a report is deciding it. |
| **R-BAN-07** | A suspended player MUST be told before being signed out. Mid-game they hear it on the socket; otherwise from the first refused request, which carries the reason and end date rather than only saying no. |
| **R-BAN-08** | When decided from a report, the notice MUST show the messages that report was about — their own words, as they were when it was made — and the drawing it carried, if one did (R-MOD-14): their own work, for the same reason. The drawing's bytes reach a suspended account over `GET /api/suspension/drawing`, the one path beside R-BAN-04's that the ban-time credential may use, because every other request of theirs is the refusal that names it. **A ban naming a report about somebody else MUST be refused**, so a suspension cannot be used to show one player another's messages. |

### Blocks

| # | Requirement |
| --- | --- |
| **R-BLOCK-01** | Every account, including a guest, MUST have a directional block list. Self-blocks MUST be rejected; each pair is unique at the database layer. |
| **R-BLOCK-02** | Blocking MUST filter **only ordinary player-authored chat**, and only for the player who created the block. The sender still sees their own line. |
| **R-BLOCK-03** | Room state, players, scores, turns, correct-guess events, votes, and room-authored announcements MUST NEVER be hidden by a block. A block MUST NOT change gameplay facts or create a different game state per player. |
| **R-BLOCK-04** | Login MUST merge both incoming and outgoing blocks without creating duplicates or a self-block; a historical guest alias resolves to its registered account. |
| **R-BLOCK-06** | The block filter MUST be answerable from memory on the chat path: it is warmed when a player takes a seat and at the handshake of any socket with an account (a lobby line has no seat to warm it at), and invalidated on every change. The lobby backlog is filtered by the same lookup under the same failure rule. A lookup that cannot be answered in time MUST deliver the line **unfiltered** rather than delay or withhold it — a block is a presentation filter, and a message silently withheld is a failure its sender cannot see. |
| **R-BLOCK-05** | Direct delivery between players — a friend request, an invitation, and a friend's request to join a game — MUST consult `user_blocks` in **both** directions before delivery. A block MUST also remove any existing friendship for the pair, in the same transaction as the block: a surviving friendship is a room-join capability the blocker has just tried to revoke. Removal MUST be a delete rather than a refusal, so unblocking does not silently restore a friendship neither party re-agreed to. A room link obtained independently remains usable, because a Block is not a service-wide Suspension. |

### Roles and audit

| # | Requirement |
| --- | --- |
| **R-ROLE-01** | The account payload carries the role so the menu knows what to **show**. It MUST NEVER be what grants access. Every endpoint behind those entries MUST re-check the role and answer **404** to anyone else — **including for a malformed request**. A gate that runs after body validation answers 422 to an ordinary player, which confirms the endpoint exists. |
| **R-ROLE-02** | An account MUST be told when its own service-wide role changes — over its socket if it is connected, and from a pending notice on its next visit otherwise. The notice carries the new role and **nothing else**: the reason recorded with the change is written for other administrators and can name a report or a second account. Acknowledging it MUST record that it landed and settle every older notice, since a role is one current fact rather than a queue of events. Applying the pushed role to what the menu offers MUST remain a display decision (R-ROLE-01), never an authorization one. |
| **R-AUDIT-01** | Report submission and review, suspension, and revocation MUST each append an audit event recording who acted, the request it belonged to, a hashed client address, and what was acted on. |
| **R-AUDIT-02** | The audit table MUST be append-only. Names MUST NOT be written into it — a stored name would be personal data that erasing an account could not reach. The admin view resolves names when the ledger is read, so a deleted account reads *Deleted player* while the entry stands exactly as it was. |
| **R-AUDIT-03** | An action on no single row MUST record no target and say so by leaving both target fields empty, rather than inventing a subject. |
| **R-AUDIT-04** | Raw addresses, report text, and context evidence MUST NOT be copied into ordinary request logs or into public player, room, preview, or lobby payloads. |
| **R-AUDIT-06** | An administrative command whose effect lives in process memory rather than the database cannot share a transaction with its audit event. Those MUST record **before** acting: a ledger that can name an action which then failed is a smaller harm than one that can miss an irreversible action that happened. |
| **R-AUDIT-05** | Every use of the per-player operations view MUST write an audit event naming both who looked and who was looked at, because it is a surveillance surface on the game's own players. |
| **R-AUDIT-07** | The administrator's player search MUST stay bounded to what a room already shows every player seated in it, plus the role being changed — administrator-only, capped, and writing nothing to the ledger. Anything about how an account has *behaved* stays behind the audited per-player view (R-AUDIT-05); a search that grows into a player directory would be a surveillance surface with no record of its use. |

---

## 8. Privacy and data rights

| # | Requirement |
| --- | --- |
| **R-PRIV-01** | Every guest or registered player MUST be able to request a private, versioned JSON export of their own data. |
| **R-PRIV-02** | The export MUST NOT contain password or session hashes, other players' profile fields, or other players' message or guess bodies. It includes a reporter's own report text and submitted evidence — and, for a drawing attached under R-MOD-14, that one was attached and of which turn — never the bytes, which are the reported player's work kept for a moderator, and never the prompt, which a guesser reporting mid-turn has not earned — but excludes the reported account ID, reviewer identity, and internal resolution note. |
| **R-PRIV-03** | Export jobs MUST be stored **before** work begins, so a crash leaves a retryable row — and the row is the queue: one supervised in-process loop MUST build jobs **one at a time**, woken by the request and sweeping on an interval, and that sweep is also the retry. A row left `processing` by a process that died is reclaimed once it is 15 minutes stale; a planned shutdown MUST hand a claimed row back to `pending` rather than make the next process wait that out. One at a time because one worker (N-01) means a build's working set is every player's latency, so what has to be bounded is how much one build holds and that there is only ever one; a separate worker process or an external queue is N-12. Format v1 exports expire after seven days, and only the owning account may read any of those records. |
| **R-PRIV-04** | Deletion MUST require the current password for a registered account and an explicit confirmation in the UI. Guests may delete without a password, because possession of the HttpOnly session is their only credential. |
| **R-PRIV-05** | Deletion MUST leave the stable anonymized row, scores, prompts, and shared game structure intact, so **another player's history is never damaged.** |
| **R-PRIV-06** | Deletion MUST NOT invent or silently decrement a server-wide gameplay observation. Prompt usage facts contain no user identifier and stay reconcilable with retained anonymized outcomes. |
| **R-PRIV-07** | Retained message text MUST expire after 30 days. There MUST NOT be a transcript or profile-history endpoint. After 30 days the raw strings deliberately cannot be replayed through a new matcher; durable per-seat and per-turn counts still support difficulty and attempt analysis, and that bounded loss is the accepted tradeoff. |
| **R-PRIV-08** | Historical names, colors, and guest/registered state MUST remain as other players saw them. Ordinary profile edits MUST NOT rewrite them. Username and avatar are not rendered by finished-game history and MUST NOT be copied into it. |
| **R-PRIV-09** | Avatars MUST NOT hotlink arbitrary third-party URLs; only the content address of a picture this deployment stores may be recorded, and it is served from this origin (R-AVA-03). |
| **R-PRIV-10** | Anonymous retention MUST be based on `last_active_at` — deliberately separate from page-load/login time and ordinary profile writes — MUST be bounded per run, MUST preview by default, and MUST record aggregate audit evidence when applied. |
| **R-PRIV-12** | Export requests MUST be spaced: at most one per account per **7 days**, never two live at once, and a **failed** build MUST NOT count. Building an export walks every game the account ever played, so an account with thousands of them is a real cost, and R-PRIV-01's right to a copy is not a right to a fresh copy on every click. The rule MUST be enforced where the job is written, so a second way in cannot be given a weaker one, and "never two live" MUST be held by the database — a unique index on one `pending`/`processing` job per account — because two requests arriving together can each read "nothing live" and only a constraint sees them at once; a refusal MUST say **when** the next request is accepted (`429`, `Retry-After`, and `nextRequestAt` on the listing), so the interface can disable the control and name the date rather than offer a request that will be refused. |
| **R-PRIV-11** | A stale guest's session MUST be removed with the account, so an old cookie provisions a new guest rather than resurrecting retained data. |
| **R-PRIV-13** | One export document MUST be bounded **while it is written**, not after: the builder MUST page the account's history rather than hold it, MUST count the JSON bytes as they go, and MUST refuse past `EXPORT_MAX_BYTES` (default 64 MiB before compression) by failing the job as `too_large` with no document stored — a refusal the status names, so the interface can say the size is the reason rather than a fault. The ceiling is the deployment's to raise, and a failed build does not count against the week (R-PRIV-12), so the right to a copy (R-PRIV-01) is met by raising it rather than by building at any size. Reason: a document built whole is one process's memory (N-01), the same reasoning as R-BUG-12, and a size that is a real cost for a heavy account is an unbounded one for an abusive account. |
| **R-PRIV-15** | Every writer of account-owned content — the message retention queue, the finished-game write and its retries, avatar, list and report writes — MUST re-read the account's lifecycle inside its own transaction under a shared, id-ordered row lock, and MUST drop or tombstone what an erased account authored, because a deletion can only erase what is already stored and a write composed before it would otherwise put the erased name, text or pixels back. Game facts stay (R-PRIV-05); the deletion and the writer end in the same state whichever commits first. [`auth/erasure.py`](../backend/app/auth/erasure.py), [`database.md`](database.md) §11 |
| **R-PRIV-14** | The stored document MUST be served by this origin to the owning session and MUST NOT be reachable through a bearer URL. It MUST NOT be held whole or compressed twice on the way out: a client that accepts gzip is handed the stored bytes as they are, one that does not gets them decompressed a chunk at a time, and either answer declares its length. The HttpOnly session is the stronger credential: a signed link in a URL travels through history, referrers and logs for no gain while the bytes live where the session already is. If artifacts move to object storage (#471), a short-lived signed download is that design's to make, not a stronger version of this one. |

---

## 9. Durability and history

| # | Requirement |
| --- | --- |
| **R-HIST-01** | Each live game MUST receive a stable UUIDv7 when it starts, reused by the history row and the prompt-usage batch. |
| **R-HIST-02** | Retrying the same ID **with the same content** MUST be idempotent, even if collection order changed. Reusing an ID for **different** content MUST raise an operator-visible conflict rather than duplicating or silently replacing history. |
| **R-HIST-03** | The finished-game write MUST be **all-or-nothing** in one transaction, and MUST run after every client-visible emit, so nothing a player is waiting to see sits behind a database round trip. |
| **R-HIST-04** | Every completed game MUST store a scoring-rules version and a versioned exact rule snapshot. Legacy rows MUST use version `0` and an **empty** snapshot rather than claiming parameters that cannot be reconstructed. |
| **R-HIST-05** | Games that **stop** MUST be recorded, as an ordinary row with `outcome = 'abandoned'`. A room everyone walked out of must not leave no trace. |
| **R-HIST-06** | An abandoned game MUST carry **no placing** — not in the row and not in its standings — because a rank is a claim about how a game ended. Scores stay, since points earned in the turns that were played are a fact. It contributes turns but **not** a game played, a game won, or a score. |
| **R-HIST-07** | Finished-game guesses MUST reference the UUID of their turn explicitly. Persistence MUST NOT infer that relationship from the positions of two independently ordered lists. |
| **R-HIST-08** | Database constraints MUST enforce: at most one participant seat per linked account, one turn per game/round/turn number, and one correct guess per participant seat and turn. Multiple accountless seats remain distinct. |
| **R-HIST-09** | Account foreign keys on history rows MUST be nullable with `ON DELETE SET NULL`, so even a physical user-row removal cannot cascade away turns, guesses, or another player's game. |
| **R-HIST-10** | A live player MUST receive a seat identity when the game starts **even without a session cookie**. Such a seat still counts toward the recorded player total and keeps every factual turn and correct guess; history MUST NOT drop or coalesce it merely because its account link is null. |
| **R-HIST-11** | Scored games MUST keep an ordered, append-only score-event ledger. Corrections append a new delta pointing at an earlier event; **prior events MUST NEVER be rewritten.** |
| **R-HIST-12** | The writer MUST prove the gameplay events agree with correct guesses and hint spend, then require every participant's ledger sum to equal the cached final score **in the same transaction**. |
| **R-HIST-13** | Legacy games MUST use ledger version `0`, because gross awards and drawer bonuses cannot be reconstructed from net totals. No-scoring games use the current version with an empty event list. |
| **R-HIST-14** | Every drawing from a completed game MUST be kept for as long as that game, in the same transaction that records it. |
| **R-HIST-15** | Stored bytes MUST be the canvas frame itself — the actions, not a picture of them — so a drawing can be replayed at any size and a PNG stays something the browser produces on demand. |
| **R-HIST-16** | A drawing endpoint MUST answer only to a player who was in that game, and **every refusal MUST be a 404**, so it never reveals whether a game exists. |
| **R-HIST-17** | A turn whose bytes the recap dropped for budget MUST be recorded as **unavailable**, not omitted. A recap that quietly listed fewer turns than were played would be a worse answer than one admitting a drawing is gone. |
| **R-HIST-18** | Every stored drawing format MUST keep its decoder forever, and every decoder MUST answer in the **current wire format** — so clients never learn a stored format exists and the wire format stays free to change without migrating a row. |
| **R-HIST-19** | An operator command MUST be able to verify stored drawings in bounded batches, reporting checksum failures and unreadable formats, because a database column has no integrity check of its own. |
| **R-HIST-20** | Lifetime profile summaries MUST be served from the rebuildable daily projection. **Profile reads MUST NOT query participant, turn, or guess fact tables.** |
| **R-HIST-21** | The projection MUST be disposable: a missing or erased row reads as **zero** rather than silently falling back to an unbounded history scan. Operators repair drift explicitly. |
| **R-HIST-22** | Prompt-list counts MUST be derived from membership on read, so adding or removing a prompt cannot leave a cached total out of sync. |

---

## 10. Observability

| # | Requirement |
| --- | --- |
| **R-OBS-01** | Live counts of rooms, players, and running games MUST be in memory and MUST vanish on restart — a live count is not a historical fact, and one worker owns all of it, so an in-process count is the true count. |
| **R-OBS-02** | Observations MUST be buffered and written in batches; a database round trip per join would be felt as lag inside a drawing. |
| **R-OBS-03** | The buffer MUST be bounded, drop oldest when full, and **count what it dropped**, so a gap is visible rather than silent. |
| **R-OBS-04** | Raw observations MUST be rolled into permanent daily totals **before** being purged. Unbounded event rows on embedded SQLite is a disk that fills up quietly. |
| **R-OBS-05** | `GET /metrics` MUST be disabled entirely until `METRICS_TOKEN` is set, and MUST require that bearer token. |
| **R-OBS-06** | The in-app operations page MUST require the administrator role. |
| **R-OBS-07** | Every HTTP request and every client command MUST be counted and timed in-process, labelled by route template, status class and command name so that label cardinality is bounded by construction. A handler exception MUST be counted before it propagates, never instead. |
| **R-OBS-08** | Event-loop lag, process CPU and memory, pool occupancy, statement latency, queue depth and age, loop health, and socket byte volume in and out (packet bytes before compression, plus per-command and per-event payload-size distributions) MUST be exposed on both `GET /metrics` and the operations overview from one store, and MUST NOT be written to the database. |
| **R-OBS-09** | The operations overview MUST poll only while it is the selected tab in a visible document. |
| **R-OBS-10** | A finished-game or prompt-usage write that is abandoned (timeout or error) MUST be counted with its kind and reason, on the persisted recorder and on `/metrics`; the swallow itself stays (#482). |
| **R-OBS-11** | Every log line MUST carry the request id, or the socket id and command, it was written inside; every response MUST echo the request's id as `X-Request-ID`; the audit ledger MUST record the same id. A supplied id that is not a UUID MUST be replaced. |
| **R-OBS-12** | In production log lines MUST be JSON objects, one per line, each passed through redaction - credentials, session values, database passwords, e-mail local parts - before it is written. The text format is the development console and MUST stay verbatim: plain lines, uvicorn's own output, nothing redacted, so the links the console mail transport prints remain usable. |
| **R-OBS-13** | The service objectives and the alert rules that enforce them MUST live in the repository (`docs/slo.md`, `ops/prometheus/rules/`), every series a rule names MUST be one the server exposes (checked in CI), and a synthetic game (`app.probe`) MUST be runnable against a deployment with no dependency beyond the standard library. |

### Runtime tuning

| # | Requirement |
| --- | --- |
| **R-CONF-01** | Values that decide how the running game *feels* MUST be changeable by an administrator without a deploy, and without a restart wherever the value is reached through an object rather than baked into one. The motivating case is a cadence no benchmark settles: the byte curve says to raise the drawer's flush interval and looking at a viewer's screen says otherwise, and the tolerance is far tighter than the numbers suggest. |
| **R-CONF-02** | Every tunable MUST carry its compiled default, its bounds, its unit and a one-line description of what it trades off, and the endpoint MUST serve all of them — so the panel needs to know nothing about any particular setting, and adding one does not mean editing the page. |
| **R-CONF-03** | Every value MUST be bounded **server-side**. The bounds MUST refuse a value the rest of the system could not live with, including pairs that are individually legal and jointly impossible: a client cadence and the budget that admits it are one setting wearing two hats. |
| **R-CONF-04** | A change carrying several settings MUST be validated as a set and applied as a set. Applying them one at a time would leave a refused request half-committed to a configuration nobody chose, and would measure each value against the ones not yet moved. Changes MUST also be serialized against **each other**: validation reads the values in force and the write is several awaits later, so two requests that each pass alone can otherwise land together on a pair the bounds exist to refuse. |
| **R-CONF-05** | Changes MUST survive a restart, MUST be adopted **before** the process admits players, and MUST fall back to the compiled default when unset. Whether a stored override **exists** MUST be tracked separately from whether its value happens to equal the boot value: inferring one from the other hides a row rather than removing it, leaves no way to clear it, and lets it win again the next time the environment moves. A reset MUST therefore remove the row even when nothing numeric changes. One unusable stored value MUST NOT prevent startup or cost the others — a release that tightens a bound leaves an old number behind it, and the answer is that value at its default plus a line in the log. Such a row MUST remain visible and clearable rather than being forgotten: an override the panel calls absent is one no reset can reach, and one that returns to force the day a later release widens that bound. |
| **R-CONF-06** | Every change MUST append an audit event naming the administrator, the setting, and the values moved from and to, **in the same transaction as the change itself**. Taking a durable override away MUST be recorded too, even when no number moves: how the deployment starts has changed. Only a submission that changes neither the value nor the override MUST be silent, or a panel posting its whole form buries the one change that was made. |
| **R-CONF-07** | Abuse backstops MUST NOT be tunable: the authentication and submission limits, and the canvas and replay ceilings. Nor MUST anything that can change a score, since every completed game freezes a rule snapshot. Nor MUST a value the frontend duplicates, which is a wire contract rather than a setting — including a *default* the client compiles in and always sends, since tuning that server-side changes nothing an ordinary player would see while the panel reports it as in force. Each value made tunable is one that can be set wrong in production. |
| **R-CONF-08** | A tunable is **not** a test setting. Client-side intervals MUST keep being fast-forwarded with the page's own clock (R-ENG-10) rather than made configurable, and the suite MUST NOT reach for the administrator surface to make itself faster. Configuring the *server* through the environment before it starts — as the E2E harness already does with `TURN_RESULTS_SECONDS` — is the boot value doing its documented job and is not what this forbids. |

### Bug reports

| # | Requirement |
| --- | --- |
| **R-BUG-01** | Any player holding an identity, **including a guest**, MUST be able to report that the app is broken, from any screen. The bugs that go unreported are the ones met before anybody signs up. |
| **R-BUG-02** | A bug report MUST NOT be a moderation surface. It is about the software, not a person; it carries build and diagnostic data rather than safety evidence, and it is triaged by administrators, not moderators. |
| **R-BUG-03** | A report MUST name one of ten bounded areas and one of three severities, plus a ≤ 200-character summary and ≤ 4000 characters of detail. |
| **R-BUG-04** | Context MUST arrive in two halves that are never conflated. `client_context` is what the reporter's browser said about itself and MUST be presented as **reporter-supplied evidence**; `server_context` is what the server observed of their live seat and is the only half a reader may treat as fact. |
| **R-BUG-05** | The server MUST resolve room, game and turn from the reporter's **live seat**, never from the code the client sent. Naming a room you are not sitting in MUST attach nothing. |
| **R-BUG-06** | A report MUST NOT carry the prompt in play, chat text, or any query string. A guesser filing a bug is still a guesser. The **server** MUST cut a stored route back to its path — that the rule holds cannot depend on the client keeping its own promise. |
| **R-BUG-07** | A screenshot MUST be optional, captured only through the browser's own picker, and validated server-side — real PNG or WebP magic bytes, ≤ 2 MB, with byte size and SHA-256 re-derived rather than believed. |
| **R-BUG-12** | A request body MUST be bounded **before** it is read. Sketchy runs one worker (N-01), so an unbounded body is one process's memory: the default ceiling MUST be sized against the largest body the API itself declares; an over-length `Content-Length` MUST be refused without invoking the application, and a body that declares no length or a false one MUST be cut off as it streams. The screenshot field MUST also be bounded in its encoded form, so an oversized image is refused before it is decoded rather than after. |
| **R-BUG-11** | The report dialog MUST conceal itself before the frame is taken and MUST wait for the capture stream to show the page without it. A screenshot of the form asking for a screenshot is worth nothing. The dialog MUST be restored however the capture ends, including on failure. |
| **R-BUG-08** | Screenshot bytes MUST be **erased when the report is decided**, and that erasure MUST be structural: a row whose screenshot status is `erased` cannot hold a payload. The metadata stays, so the record still says a picture existed. |
| **R-BUG-09** | Review MUST be one-way and require a note: a pending report receives one decision and cannot later be silently rewritten. |
| **R-BUG-10** | Submission and each decision MUST append an audit event. The ledger records that a bug was filed and acted on, **never what it said**. |

---

## 11. Accessibility and UX

| # | Requirement |
| --- | --- |
| **R-A11Y-01** | Core flows MUST pass automated accessibility checks. [`tests/e2e/test_a11y_core_flows.py`](../backend/tests/e2e/test_a11y_core_flows.py), [`tests/e2e/a11y.py`](../backend/tests/e2e/a11y.py) |
| **R-A11Y-02** | A colorblind-safe palette MUST be available as a room color mode (Okabe-Ito plus white). |
| **R-A11Y-03** | Game state changes MUST be announced to assistive technology. [`components/GameAnnouncer.tsx`](../frontend/src/components/GameAnnouncer.tsx) |
| **R-A11Y-04** | Dialogs MUST trap focus. [`hooks/useFocusTrap.ts`](../frontend/src/hooks/useFocusTrap.ts) |
| **R-UX-01** | A room MUST lay itself out to the viewport rather than flowing beneath a banner. |
| **R-UX-02** | UI copy MUST be American English and sentence case, and MUST use the canonical term from [`../GLOSSARY.md`](../GLOSSARY.md). |
| **R-UX-03** | A new player-visible concept MUST get a glossary entry **in the same change** that ships it. |
| **R-UX-04** | Renaming a term MUST rename it everywhere in one change. Browser-stored settings are the exception that cannot be renamed at all — migrate them on load. |
| **R-UX-05** | A URL the client has no page for MUST answer **404** and show the not-found page. Serving the application shell is what draws that page; answering 200 with it tells every non-browser client that a page exists where none does. [`app/client_routes.py`](../backend/app/client_routes.py), `tests/test_client_routes.py`, `tests/e2e/test_not_found.py` |
| **R-UX-06** | A render error MUST be caught at the application root and again around the live room, and MUST show the **crash page** rather than a blank screen. The page MUST offer reload and a way back to the lobby **once the report below has been sent** — or once sending it has failed, so the page can always be left; the room's way back MUST release the seat (`leave_room`), because the socket is a module singleton that outlives the crashed tree. Recovery MUST NOT touch browser-stored settings (R-SET-04) or the upgrade-reload marker — only the in-memory game store is suspect. The crash MUST be recorded as a redacted `render` entry in the client error tail, and the page MUST offer a bug report already filled with it, which the player may send with their own words or as their words alone (R-BUG-01, R-BUG-06). [`components/CrashBoundary.tsx`](../frontend/src/components/CrashBoundary.tsx), [`pages/CrashPage.tsx`](../frontend/src/pages/CrashPage.tsx), [`lib/crashReport.ts`](../frontend/src/lib/crashReport.ts), `tests/e2e/test_crash_page.py` |

---

## 12. Engineering constraints

| # | Requirement |
| --- | --- |
| **R-ENG-01** | `game.py` and `rooms.py` MUST stay pure logic with no sockets, covered by direct unit tests. |
| **R-ENG-02** | Client JSON commands MUST be validated as strict object payloads: values are not coerced, booleans are never accepted as integers, unknown fields are rejected, and **bounded validation completes before authorization or mutation.** |
| **R-ENG-03** | The binary drawing and fixed-array undo commands MUST have dedicated parsers for their documented wire formats. |
| **R-ENG-04** | The names the two sides share MUST be pinned by `test_wire_contract.py`, which also rejects wire names built from retired glossary vocabulary. |
| **R-ENG-05** | Malformed, unsupported, unauthorized, and out-of-phase drawing payloads MUST be rejected **before** being recorded or rebroadcast. |
| **R-ENG-06** | Extending a stored enum set MUST require one coordinated code, migration, contract, README, and glossary review. |
| **R-ENG-07** | Persisted timestamps MUST require timezone-aware inputs and normalize to aware UTC, so SQLite and PostgreSQL behave identically. |
| **R-ENG-08** | Entity IDs MUST NOT be used as capabilities. Session tokens, room codes, and share codes stay independently random. |
| **R-ENG-09** | An E2E test MUST wait on the condition it actually cares about, never a fixed sleep sized to outlast it — and never `locator.count()`, which samples once and so asserts on whatever had rendered by that instant. `expect(locator).to_have_count(n)` and `locator.nth(n).wait_for()` retry; a count that loses the race fails as wrong data rather than as too early — such a sleep costs its full length on every run and silently stops covering anything when the thing it waits for gets slower. |
| **R-ENG-10** | Where a test must sit out a production interval, it MUST fast-forward the page's own clock (`page.clock`) rather than spend the time, keeping the interval a production constant instead of something bent for the tests. |
| **R-ENG-11** | Benchmarks are **diagnostic baselines, not CI thresholds** — browser and machine timings vary. |
| **R-ENG-12** | CI MUST run backend lint and tests, PostgreSQL migrations and the whole backend suite against PostgreSQL, frontend test/lint/build, and multi-browser E2E. |
| **R-ENG-13** | CI MUST refuse a credential committed to the tree **or to any commit the change adds**, merge commits included — a value removed a commit later is burned just the same, the tree it leaves behind looks clean, and a value introduced only while resolving a conflict appears in no parent's diff at all. [`ci.yml`](../.github/workflows/ci.yml) |
| **R-ENG-14** | CI MUST fail on a known advisory in either Python manifest or in the frontend lockfile. Build and test dependencies count: they run in CI with a checkout before anything they touched reaches a player. |
| **R-ENG-15** | Coverage MUST be gated **per risk-critical module**, not only in total, and each module MUST carry **both** a statement floor and a **branch** floor. Per module, because a suite this size absorbs one module losing its tests without moving the total more than a rounding error. Both numbers, because either alone can be met by a suite that is not exercising the code: a statement measure marks an `if` covered the moment it is reached, and a branch measure is trivially met by a module with few branches. The gate MUST read `percent_statements_covered` and `percent_branches_covered` — **not** `percent_covered`, which under `--cov-branch` is a combined ratio reading far higher than branch coverage alone — and MUST refuse a report produced without branch measurement. A module named in the floor table that disappears from the report MUST fail, so a rename cannot retire a floor silently. [`scripts/check-coverage.py`](../scripts/check-coverage.py) |

---

## 13. Explicit non-goals for v1

These are decisions, not gaps. Implementing one is a product change that needs its own
design, not a bug fix.

| # | Non-goal |
| --- | --- |
| **N-01** | **Multi-worker or horizontally scaled deployment.** Requires shared room/session/timer state and cross-worker Socket.IO delivery. |
| **N-02** | **Live-state snapshots or crash recovery of an active game.** Rooms, canvases, timers, and scores are never serialized. |
| **N-03** | **Ratings, seasons, achievements, competitive-mode eligibility, or server-wide standings.** The durable *foundation* exists; the policy does not, and MUST NOT be introduced as mutable counters or by rewriting finished games. |
| **N-04** | **Community prompt-list discovery**, a favourite/star table, or a user-facing fork endpoint. `public` visibility is reserved. |
| **N-05** | **A chat transcript or profile message-history endpoint.** |
| **N-06** | **Invitations to players who are not friends, and any notification that carries a room code.** An invitation between friends exists (R-FRIEND-06) and carries a token rather than a code; nothing else does. There is still no way to reach a stranger directly. |
| **N-07** | **External identity providers.** Schema is reserved; no provider-login API is enabled until identity-linking flows ship. Avatar uploads left this list with #573 (R-AVA-01…05) once validation, moderation and the export/deletion paths existed. |
| **N-08** | **A built-in room-preset catalogue or preset sharing.** |
| **N-09** | **Prompt languages beyond the Latin registry** (`en`, `de`, `es`, `fr`, `it`, `nl`, `pt`) until their matching semantics are implemented. |
| **N-10** | **A remote password-reset API.** There is no authentication that would make one safe; the server-side command exists instead. |
| **N-11** | **Server-side PNG rendering.** The server stores and replays actions, never pixels. |
| **N-12** | **A separate worker process or an external queue for deferred work.** Mail, account exports, retention and metrics are supervised loops in the one application worker (N-01, and the #456 risk acceptance), with a database table as the queue wherever the work has to survive a restart. Object storage for large artifacts is not on this list — it is #471. |

---

## 14. Traceability

| Area | Implementation | Proof |
| --- | --- | --- |
| Game rules, scoring, hints, guess matching | [`app/game.py`](../backend/app/game.py) | `tests/test_game.py`, `test_standings.py`, `test_prompts.py` |
| Room model, votes, recap budget | [`app/rooms.py`](../backend/app/rooms.py) | `tests/test_rooms.py`, `tests/handlers/test_rooms.py` |
| Reactions to drawings | [`services/drawing_reactions.py`](../backend/app/services/drawing_reactions.py), [`handlers/reactions.py`](../backend/app/handlers/reactions.py), [`api/profiles.py`](../backend/app/api/profiles.py), [`lib/reactions.ts`](../frontend/src/lib/reactions.ts) | `tests/test_drawing_reactions.py`, `tests/handlers/test_reactions.py`, `tests/test_api_profiles.py`, `tests/test_game_history_builder.py`, `frontend/tests/reactions.test.mjs`, `tests/e2e/test_drawing_reactions.py` |
| Friends | [`services/friends.py`](../backend/app/services/friends.py), [`api/friends.py`](../backend/app/api/friends.py), [`handlers/friends.py`](../backend/app/handlers/friends.py), [`services/friend_invites.py`](../backend/app/services/friend_invites.py) | `tests/test_friends.py`, `tests/test_friends_api.py`, `tests/handlers/test_friends.py`, `frontend/tests/friends.test.mjs`, `tests/e2e/test_friends.py` |
| Lobby presence | [`app/services/presence.py`](../backend/app/services/presence.py), [`handlers/lobby.py`](../backend/app/handlers/lobby.py), [`lib/lobbyPresence.ts`](../frontend/src/lib/lobbyPresence.ts) | `tests/test_presence.py`, `tests/handlers/test_lobby_presence.py`, `frontend/tests/lobbyPresence.test.mjs`, `tests/e2e/test_lobby_online_players.py`, `fixtures/lobby_presence_v1.json` |
| Lobby chat | [`services/lobby_chat.py`](../backend/app/services/lobby_chat.py), [`handlers/lobby.py`](../backend/app/handlers/lobby.py), [`lib/lobbyChat.ts`](../frontend/src/lib/lobbyChat.ts) | `tests/test_lobby_chat.py`, `tests/handlers/test_lobby_chat.py`, `frontend/tests/lobbyChat.test.mjs`, `tests/e2e/test_lobby_chat.py` |
| Socket.IO commands and payloads | [`app/handlers/`](../backend/app/handlers/) | `tests/handlers/`, `tests/test_payloads.py` |
| Wire naming agreement | both trees | `tests/test_wire_contract.py` |
| Drawing wire format | [`app/live_drawing.py`](../backend/app/live_drawing.py) | `tests/test_live_drawing.py`, `frontend/tests/canvasProtocol*.test.mjs`, `fixtures/canvas_protocol_v1.json` |
| Canvas history and sequencing | [`canvas_history.py`](../backend/app/canvas_history.py), [`canvas_session.py`](../backend/app/canvas_session.py) | `tests/test_canvas_history.py`, `test_canvas_session.py`, `frontend/tests/canvasSyncRequests.test.mjs` |
| Stored drawing policy | [`canvas_storage.py`](../backend/app/canvas_storage.py) | `tests/test_canvas_storage.py` |
| Drawing rules enforcement | [`drawing_rules.py`](../backend/app/drawing_rules.py) | `tests/test_drawing_rules.py`, `tests/e2e/test_drawing_rules.py` |
| Schema, migrations, repositories | [`app/db/`](../backend/app/db/), [`app/repositories/`](../backend/app/repositories/) | `tests/test_db_models.py`, `test_migrations.py`, `test_repositories.py` |
| Finished-game history and ledger | [`services/game_history.py`](../backend/app/services/game_history.py) | `tests/test_game_history_builder.py`, `test_competitive_projection_foundation.py` |
| Daily projection | [`services/user_stats_projection.py`](../backend/app/services/user_stats_projection.py) | `tests/test_user_stats_projection.py`, `benchmarks/user_stats.py` |
| Accounts, sessions, recovery | [`app/auth/`](../backend/app/auth/) | `tests/test_auth.py`, `test_sessions.py`, `test_account_recovery.py`, `test_email_identity.py`, `test_identity_merge.py` |
| Player settings and the name-colour rule | [`api/user_settings.py`](../backend/app/api/user_settings.py), [`app/rooms.py`](../backend/app/rooms.py), [`components/SettingsOverlay.tsx`](../frontend/src/components/SettingsOverlay.tsx), [`lib/settingsSync.ts`](../frontend/src/lib/settingsSync.ts) | `tests/test_user_settings.py`, `test_name_color.py`, `tests/e2e/test_settings_e2e.py`, `frontend/tests/settingsSync.test.mjs`, `settingsMigrations.test.mjs` |
| Data export and deletion | [`auth/account_data.py`](../backend/app/auth/account_data.py), [`services/data_export_worker.py`](../backend/app/services/data_export_worker.py), [`lib/accountData.ts`](../frontend/src/lib/accountData.ts) | `tests/test_account_data.py`, `test_data_export_worker.py`, `fixtures/account_data_export_v2_fields.json`, `frontend/tests/accountData.test.mjs` |
| Retention | [`auth/retention.py`](../backend/app/auth/retention.py), [`services/message_retention.py`](../backend/app/services/message_retention.py) | `tests/test_anonymous_retention.py`, `test_message_retention.py` |
| Bug reports and triage | [`api/bug_reports.py`](../backend/app/api/bug_reports.py), [`request_limits.py`](../backend/app/request_limits.py), [`lib/bugReports.ts`](../frontend/src/lib/bugReports.ts), [`lib/clientErrorLog.ts`](../frontend/src/lib/clientErrorLog.ts), [`lib/screenCapture.ts`](../frontend/src/lib/screenCapture.ts), [`lib/crashReport.ts`](../frontend/src/lib/crashReport.ts), [`components/CrashBoundary.tsx`](../frontend/src/components/CrashBoundary.tsx) | `tests/test_bug_reports.py`, `tests/test_request_limits.py`, `tests/e2e/test_bug_reporting.py`, `tests/e2e/test_crash_page.py`, `frontend/tests/bugReports.test.mjs`, `clientErrorLog.test.mjs`, `crashReport.test.mjs`, `screenCapture.test.mjs` |
| Moderation, reports, bans, blocks | [`api/moderation.py`](../backend/app/api/moderation.py), [`services/player_reports.py`](../backend/app/services/player_reports.py), [`auth/bans.py`](../backend/app/auth/bans.py), [`auth/blocks.py`](../backend/app/auth/blocks.py) | `tests/test_moderation_api.py`, `tests/handlers/test_moderation.py`, `test_user_blocks.py`, `test_prompt_content_moderation.py`, `tests/e2e/test_player_reporting.py`, `tests/e2e/test_moderation_queue.py`, `frontend/tests/moderation.test.mjs` |
| Prompt content and governance | [`prompt_content.py`](../backend/app/prompt_content.py), [`api/prompt_lists.py`](../backend/app/api/prompt_lists.py) | `tests/test_prompt_content.py`, `test_prompt_list_governance.py`, `test_owned_prompt_lists.py`, `test_prompt_list_seeding.py` |
| Prompt usage and stats | [`services/prompt_usage.py`](../backend/app/services/prompt_usage.py) | `tests/test_prompt_usage.py`, `test_api_prompt_stats.py` |
| Presets, room codes | [`services/room_presets.py`](../backend/app/services/room_presets.py), [`services/room_codes.py`](../backend/app/services/room_codes.py) | `tests/test_room_presets.py`, `test_room_codes.py` |
| Shutdown drain | [`services/shutdown.py`](../backend/app/services/shutdown.py) | `tests/test_shutdown.py`, `tests/handlers/test_shutdown.py` |
| Runtime analytics | [`services/runtime_metrics.py`](../backend/app/services/runtime_metrics.py) | `tests/test_runtime_analytics.py` |
| Process signals, logs, correlation, SLOs, probe | [`services/telemetry.py`](../backend/app/services/telemetry.py), [`request_timing.py`](../backend/app/request_timing.py), [`services/queue_depths.py`](../backend/app/services/queue_depths.py), [`logging_config.py`](../backend/app/logging_config.py), [`correlation.py`](../backend/app/correlation.py), [`probe.py`](../backend/app/probe.py), [`ops/prometheus/rules/`](../ops/prometheus/rules/) | `tests/test_telemetry.py`, `test_request_timing.py`, `test_db_telemetry.py`, `tests/handlers/test_socket_telemetry.py`, `tests/handlers/test_socket_wire.py`, `test_logging_config.py`, `tests/handlers/test_correlation.py`, `test_alert_rules.py`, `test_probe.py`, `tests/e2e/test_probe.py`, `tests/handlers/test_game_history.py` (#482) |
| Runtime tuning | [`services/runtime_settings.py`](../backend/app/services/runtime_settings.py), [`services/tunables.py`](../backend/app/services/tunables.py), [`services/config_store.py`](../backend/app/services/config_store.py), [`api/admin_settings.py`](../backend/app/api/admin_settings.py) | `tests/test_runtime_settings.py`, `test_admin_tunables_api.py` |
| CI supply-chain and quality gates | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`scripts/check-coverage.py`](../scripts/check-coverage.py) | `tests/test_repo_gates.py`, `tests/test_repo_artifacts.py` |
| Deployment, environment mode, static delivery, worker topology | [`deployment.py`](../backend/app/deployment.py), [`client_routes.py`](../backend/app/client_routes.py) | `tests/test_deployment.py`, `test_static_delivery.py`, `test_client_routes.py` |
| Health, readiness, loop supervision | [`services/readiness.py`](../backend/app/services/readiness.py) | `tests/test_readiness.py` |
| Connection resilience | [`handlers/connection.py`](../backend/app/handlers/connection.py) | `tests/handlers/test_connection.py`, `tests/e2e/test_network_resilience.py`, `test_player_afk_reconnect.py` |
