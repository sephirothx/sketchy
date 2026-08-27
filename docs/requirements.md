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
| **R-PLAT-01** | The system MUST run with **zero configuration**, defaulting to an embedded SQLite database at `./sketchy.db`. [`db/__init__.py:23`](../backend/app/db/__init__.py) |
| **R-PLAT-02** | The system MUST also support PostgreSQL via `DATABASE_URL`, with identical behaviour. Cross-dialect equivalence is proven by replaying the migration chain both directions on both engines. [`tests/test_migrations.py`](../backend/tests/test_migrations.py) |
| **R-PLAT-03** | The whole game (UI + REST + WebSocket) MUST be servable from **one port** when `frontend/dist` exists. [`main.py:264`](../backend/app/main.py) |
| **R-PLAT-04** | The backend MUST refuse an interpreter older than Python 3.14, and the frontend requires Node ≥ 22.12. [`deployment.py`](../backend/app/deployment.py), [`frontend/package.json`](../frontend/package.json) |
| **R-PLAT-05** | Exactly **one application worker** is supported. Startup MUST reject `WEB_CONCURRENCY`/`UVICORN_WORKERS` values other than `1`. Live rooms, games, canvases, timers, Socket.IO sessions, and room-code lookup are process-owned. |
| **R-PLAT-06** | Multi-worker deployment MUST NOT be presented as supported. It requires shared room/session/timer state plus cross-worker Socket.IO delivery, and is outside v1. Shared PostgreSQL state does not change this. |
| **R-PLAT-07** | SQLite connections MUST enforce foreign keys, use WAL mode, and wait up to 5 s on a busy database. [`db/__init__.py:36`](../backend/app/db/__init__.py) |
| **R-PLAT-08** | SQLite MUST migrate itself on startup. PostgreSQL migrations MUST be an explicit deploy step under an advisory lock; startup MUST verify the revision and fail with a direct instruction if the step was missed. [`db/migrate.py`](../backend/app/db/migrate.py) |
| **R-PLAT-09** | Fingerprinted `/assets/` MUST be served `immutable` with a one-year lifetime, and `index.html` (including client-route fallbacks) `no-cache`, so browsers discover deployments promptly. [`deployment.py`](../backend/app/deployment.py) |
| **R-PLAT-10** | Behind a proxy, the real client address MUST be recovered only with explicit trusted-proxy configuration (`PROXY_HEADERS=1`, `FORWARDED_ALLOW_IPS`). Without it, `X-Forwarded-For` MUST be ignored — it is attacker-controlled, and trusting it blindly would let a password-guesser sidestep rate limits by varying it per attempt. |

### Planned shutdown

| # | Requirement |
| --- | --- |
| **R-SHUT-01** | `GET /api/ready` MUST return 503 **before** any drain work begins; `/api/health` remains a liveness check that reports readiness state. |
| **R-SHUT-02** | At drain start the server MUST send every connected client the versioned `server_shutdown` notice, and MUST refuse new room creation, new game starts, and restart votes — while leaving existing rooms connected so active games can finish. |
| **R-SHUT-03** | The drain window MUST be configurable via `SHUTDOWN_DRAIN_SECONDS` (0–300, default 30). A second termination signal MUST abandon the remaining window immediately. |
| **R-SHUT-04** | A game that outlives the deadline MUST NOT be recorded as completed history. Exactly one privacy-safe `planned_shutdown_abandonments` row MUST be written instead, retained 90 days. |
| **R-SHUT-05** | That diagnostic MUST NOT contain room codes, room or player names, prompts, chat, or canvas contents. |
| **R-SHUT-06** | Live rooms, canvases, timers, scores, and games MUST NOT be serialized or restored. A crash still loses process-owned state; this is a stated property, not a defect. |

---

## 2. Gameplay

### Rooms and lobby

| # | Requirement |
| --- | --- |
| **R-ROOM-01** | The lobby MUST show a live, polled list of public rooms, and MUST allow joining a private room by code. |
| **R-ROOM-02** | Room codes MUST be six-character random invite **capabilities**, reserved in the database before being shown to a player. They MUST NOT be derived from an entity ID. |
| **R-ROOM-03** | When an ephemeral room empties, its code MUST be retired for 30 days, so a stale invite says the room ended instead of silently joining an unrelated group. Startup MUST retire reservations orphaned by a crash. |
| **R-ROOM-03a** | Codes permanently claimed by the removed persistent-room feature MUST stay claimed and MUST report a stale invite as ended. Releasing them would hand exactly those codes back to the allocator. |
| **R-ROOM-04** | Room settings MUST be settable at creation and editable by the host while waiting: name, visibility, max players (2–16), rounds (1–10), drawing time (a fixed preset list), scoring mode, hint mode, spectator prompt visibility, masked-prompt hiding, allowed tools, color mode, prompt lists, and custom prompts. |
| **R-ROOM-05** | A game MUST require at least 2 players before the host can start it. |
| **R-ROOM-06** | The host role is a **gameplay** role only. It MUST NOT confer any service-wide privilege. Conversely an administrator MUST NOT become host merely by holding the role. |
| **R-ROOM-07** | Room payloads MUST NOT carry account IDs. Anything that needs an account (reports, blocks, profile links) resolves the seat server-side. |
| **R-ROOM-13** | Room state MUST carry a player's kick and AFK vote lists only where votes exist. Every seat receives every other seat's entry on every broadcast, so an empty list per player is the payload paying a quadratic price for the state almost every player is in almost always. |
| **R-ROOM-08** | A socket MUST hold at most one live seat. Creating or joining a room MUST first release any seat that connection already holds, by the same path an explicit leave takes: room state re-emitted, timers cancelled, empty-room teardown and code retirement run. Seats MUST be matched by socket, never by account — two tabs of one account may sit in two different rooms. |
| **R-ROOM-09** | Opening a room MUST require a provisioned session. Joining, playing, and receiving a factual history seat MUST NOT — a visitor whose browser keeps no cookie can still play (R-HIST-10); they cannot host. |
| **R-ROOM-10** | Room creation MUST be bounded on four axes: live rooms per account, room creations per account per hour, live rooms per process, and quick-prompt characters retained across every live room. Each MUST be configurable, and each refusal MUST say which ceiling was reached in terms a player can act on. |
| **R-ROOM-11** | A ceiling MUST be re-checked at the instant the room is created, not only when the command arrives: everything in between awaits, and a refusal at that point MUST release the room code it had already claimed. |

### Turn structure

| # | Requirement |
| --- | --- |
| **R-GAME-01** | A game MUST proceed as: waiting → *choosing* (15 s) → *drawing* (room-configured, default 90 s) → *turn results* (5 s, `TURN_RESULTS_SECONDS`) → next turn → *game over*. [`game.py:139`](../backend/app/game.py) |
| **R-GAME-02** | Every active player MUST draw exactly once per round, for the configured number of rounds. |
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
| **R-GUESS-05** | When drawing begins, the eligible guesser seats MUST be **frozen**. Seats that were AFK or disconnected at that instant, and seats joining afterwards, MUST be ineligible until the next turn, and their text MUST be treated as restricted chat rather than a guess. |

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
| **R-HINT-03** | Wheel pricing MUST vary per letter — vowels cost more than consonants, and letters commoner across the room's own prompt pool cost more than rare ones, clamped so a never-appearing letter is still worth something small rather than free. The charge applies **whether or not** the letter is in the prompt. |
| **R-HINT-04** | At least `MIN_HIDDEN_LETTERS` (2) MUST remain hidden — hints can never fully reveal the prompt. |
| **R-HINT-05** | Hint state (`maskedPrompt`, `hintCost`, `letterPrices`, `hintSpend`) MUST be delivered per socket, never room-wide. |

### Spectating and AFK

| # | Requirement |
| --- | --- |
| **R-SPEC-01** | Anyone MUST be able to join a room as a spectator **whose player seats are full** — that is what spectating is for. Watching is not unlimited: a room admits spectators up to its own ceiling, and refusing one MUST NOT offer spectating back, which would be a loop. |
| **R-SPEC-02** | Spectators MUST NOT draw, score, vote, or be selected as moderation targets. |
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
| **R-LIST-07** | Waiting rooms MUST re-authorize the list and every prompt immediately before Start, closing stale-picker bypasses. A game already in progress keeps its pinned snapshot and MUST NOT be rewritten mid-turn. |
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
| **R-ACCT-01** | Playing MUST NOT require an account. Every visitor MUST be given one automatically on first page load, remembered by an HttpOnly `sketchy_session` cookie. |
| **R-ACCT-02** | Guests MUST be provisioned **only** by `GET /api/auth/me`. Merely opening a socket MUST NOT create a user row. |
| **R-ACCT-03** | Setting a username and password later MUST claim that same account, so stats collected as a guest carry over. |
| **R-ACCT-04** | Logging in while carrying a guest identity MUST create an **immutable alias**, never rewrite historical seats. A game containing both identities keeps two factual seats. |
| **R-ACCT-05** | A registered player MUST always play as their username and account color, so a name in the player list is either a claimed account or an unclaimed guest — never one impersonating the other. Guests MUST be pinned to the guest grey. |
| **R-ACCT-06** | Accounts MUST have an explicit lifecycle state (`anonymous`/`registered`/`merged`/`deleted`) and a role (`user`/`moderator`/`admin`). The legacy guest boolean MUST be derived, never a separate value that can drift. |
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
| **R-AUTH-10** | A completed reset MUST revoke every session on the account — including one held by whoever forced the recovery — and sign the person performing it back in. |
| **R-AUTH-11** | Mail MUST be queued in the same transaction as the action that causes it, and delivered afterwards, so an unreachable relay never undoes a suspension. Reset messages retry with backoff and are then recorded as failed rather than disappearing. |
| **R-AUTH-12** | With no `SMTP_HOST`, messages MUST be **logged instead of sent**, including confirmation and reset links — the only way that flow can complete on a deployment without mail. |
| **R-AUTH-13** | Email MUST be used only to reset a password and to tell someone their account was suspended or their content hidden. **Nothing else is ever sent to it.** |
| **R-AUTH-14** | A deployment without mail MUST be able to reset a password from the server. This MUST NOT be an API — there is no authentication that would make a remote password reset safe — and it MUST record the reason in the audit log. |
| **R-AUTH-15** | An account with no recovery address MUST be reminded weekly, with the interval kept **on the account** so it neither restarts on each new device nor disappears when browser storage is cleared. |
| **R-AUTH-16** | That reminder MUST stay out of rooms: being in a room suppresses it **without spending it**. A room lays itself out to the viewport rather than flowing beneath a banner, and account hygiene can wait until somebody is not mid-game. The deploy banner deliberately does not behave this way, because a game about to be ended under you is worth interrupting for. |

### Authentication rate limits

| # | Requirement |
| --- | --- |
| **R-RATE-01** | Login, registration, and lookup limits MUST be persistent, shared database buckets, so they survive restarts and apply once across every replica. |
| **R-RATE-02** | Bucket keys MUST be HMAC-SHA-256 digests under `IP_HASH_SECRET`. **Raw IP addresses MUST NOT be stored.** |
| **R-RATE-03** | Expired buckets MUST be cleaned in bounded batches. |
| **R-RATE-04** | Rotating the secret MUST start fresh buckets without exposing or re-identifying old keys. |
| **R-RATE-06** | Seating joins MUST be rate-limited per socket. Confirming a seat already held MUST NOT be charged — a client heartbeats through that path, and a liveness check must never be able to lock a player out of their own room. |
| **R-RATE-05** | The room-creation limit MUST use the same persistent buckets, keyed by **account**, and an attempt that opens no room MUST be given back rather than spent. A per-address key MUST NOT be introduced until a trustworthy client address exists to key on: behind a reverse proxy every socket presents the proxy, and the forwarded header is attacker-controlled. |

### Player settings

| # | Requirement |
| --- | --- |
| **R-SET-01** | Registered players' settings MUST follow them across devices: theme, sound and confetti switches, volume, brush cursor, keyboard shortcuts, colorblind-safe preference, guess-field clearing, and custom brush presets. |
| **R-SET-02** | Values MUST be bounded at both the API and database layers (key bindings must describe the complete supported action set; brush presets ≤ 20 entries and ≤ 16 KiB JSON). |
| **R-SET-03** | Guests keep settings in browser local storage only. Creating an account MUST copy that browser's settings **exactly once**; logging in later makes the account copy authoritative. |
| **R-SET-04** | Settings already stored in a browser MUST NOT be renamed — they MUST be migrated on load. [`store/settingsMigrations.ts`](../frontend/src/store/settingsMigrations.ts) |

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
| **R-CONN-08** | The process MUST bound how many sockets it holds at once, configurably. A socket past the ceiling MUST be **told and then closed**, never refused at the handshake: `ConnectionRefusedError` is reserved for suspensions, and a refusal carries no signal the client can explain to a player. The ledger MUST be keyed by socket id rather than counted, so a missed or repeated close cannot drift it. |

---

## 7. Moderation and safety

### Reports

| # | Requirement |
| --- | --- |
| **R-MOD-01** | Any signed-in player, **including a guest account**, MUST be able to submit a private report. Reports use one of five bounded reasons plus ≤ 2000 characters of detail and an optional ≤ 32 KiB JSON context snapshot. |
| **R-MOD-02** | A player report MUST name their **seat**, never their account. Wanting to complain about somebody is not a reason to learn their account ID. |
| **R-MOD-03** | The **server** MUST select the evidence — the reported player's recent messages as the reporter actually received them — which makes *"is this message theirs"* and *"did you see it"* true by construction rather than checks against a client's claims. |
| **R-MOD-04** | Up to 20 unexpired messages may be pinned, and only when the reported player authored them and the reporter was in each stored audience. Expired, cross-room, wrong-author, and mismatched game/turn evidence MUST be rejected. |
| **R-MOD-05** | One reporter MUST hold **one open report per target**. Once decided, the same reporter may raise a new one — that is a new incident, not the same complaint repeated. |
| **R-MOD-06** | Reporting MUST require an account, because a report a moderator cannot follow up on helps nobody. |
| **R-MOD-07** | Review MUST be one-way: a pending report receives one resolution and cannot later be silently rewritten. |
| **R-MOD-08** | Submitted context MUST be preserved as **reporter-supplied evidence**, and MUST NOT be treated as a server-verified fact merely because it was stored. |
| **R-MOD-09** | Player-authored prompt content MUST have a separate, target-specific report flow against a list or an exact prompt version. Official bundled content, inaccessible content, and self-reports MUST be rejected. |
| **R-MOD-10** | Prompt-content moderation MUST be **post-moderation**: a report alone never changes availability. Resolution explicitly chooses Active or Hidden; a dismissal MUST NOT mutate content. |
| **R-MOD-11** | Hidden prompts MUST be filtered from future selection. Owners see moderation state in *My prompt lists*, and editing MUST NOT silently override a moderator decision. |
| **R-MOD-12** | A moderator MUST have a consequence between dismissal and **Suspension**: a formal **Warning** shown to the reported player once, in their own reported words, restricting nothing. Its acknowledgement MUST be recorded, and it follows the same role boundaries and same-report rule as a suspension. |

### Suspensions

| # | Requirement |
| --- | --- |
| **R-BAN-01** | Moderators and administrators MUST be able to create temporary or permanent suspensions. Moderators MUST NOT suspend peers; administrators MUST NOT be targeted. |
| **R-BAN-02** | Creating a suspension MUST revoke every signed-in device and remove any live room seat immediately. Login, authenticated HTTP requests, and Socket.IO handshakes MUST all reject an active suspension. |
| **R-BAN-03** | A token revoked at ban time MUST stay recognizable until expiry, so its next request cannot be mistaken for a new cookieless guest. |
| **R-BAN-04** | **Data export, account deletion, and logout MUST remain available** through that ban-time credential — moderation MUST NOT erase privacy rights. |
| **R-BAN-05** | A suspension MAY carry an end date (24 h / 7 d / 30 d / none) and one with an end date MUST lift itself, because the list reports what is in force rather than trusting something to have run. Permanent MUST NOT be the default. |
| **R-BAN-06** | A suspension lifted by hand MUST keep its row and record who lifted it and why. Suspending from a report MUST resolve that report — acting on a report is deciding it. |
| **R-BAN-07** | A suspended player MUST be told before being signed out. Mid-game they hear it on the socket; otherwise from the first refused request, which carries the reason and end date rather than only saying no. |
| **R-BAN-08** | When decided from a report, the notice MUST show the messages that report was about — their own words, as they were when it was made. **A ban naming a report about somebody else MUST be refused**, so a suspension cannot be used to show one player another's messages. |

### Blocks

| # | Requirement |
| --- | --- |
| **R-BLOCK-01** | Every account, including a guest, MUST have a directional block list. Self-blocks MUST be rejected; each pair is unique at the database layer. |
| **R-BLOCK-02** | Blocking MUST filter **only ordinary player-authored chat**, and only for the player who created the block. The sender still sees their own line. |
| **R-BLOCK-03** | Room state, players, scores, turns, correct-guess events, votes, and room-authored announcements MUST NEVER be hidden by a block. A block MUST NOT change gameplay facts or create a different game state per player. |
| **R-BLOCK-04** | Login MUST merge both incoming and outgoing blocks without creating duplicates or a self-block; a historical guest alias resolves to its registered account. |
| **R-BLOCK-05** | Any future direct-invite feature MUST consult `user_blocks` before delivery. A room link obtained independently remains usable, because a Block is not a service-wide Suspension. |

### Roles and audit

| # | Requirement |
| --- | --- |
| **R-ROLE-01** | The account payload carries the role so the menu knows what to **show**. It MUST NEVER be what grants access. Every endpoint behind those entries MUST re-check the role and answer **404** to anyone else. |
| **R-AUDIT-01** | Report submission and review, suspension, and revocation MUST each append an audit event recording who acted, the request it belonged to, a hashed client address, and what was acted on. |
| **R-AUDIT-02** | The audit table MUST be append-only. Names MUST NOT be written into it — a stored name would be personal data that erasing an account could not reach. The admin view resolves names when the ledger is read, so a deleted account reads *Deleted player* while the entry stands exactly as it was. |
| **R-AUDIT-03** | An action on no single row MUST record no target and say so by leaving both target fields empty, rather than inventing a subject. |
| **R-AUDIT-04** | Raw addresses, report text, and context evidence MUST NOT be copied into ordinary request logs or into public player, room, preview, or lobby payloads. |
| **R-AUDIT-05** | Every use of the per-player operations view MUST write an audit event naming both who looked and who was looked at, because it is a surveillance surface on the game's own players. |

---

## 8. Privacy and data rights

| # | Requirement |
| --- | --- |
| **R-PRIV-01** | Every guest or registered player MUST be able to request a private, versioned JSON export of their own data. |
| **R-PRIV-02** | The export MUST NOT contain password or session hashes, other players' profile fields, or other players' message or guess bodies. It includes a reporter's own report text and submitted evidence but excludes the reported account ID, reviewer identity, and internal resolution note. |
| **R-PRIV-03** | Export jobs MUST be stored **before** work begins, so a crash leaves a retryable row. Format v1 exports expire after seven days, and only the owning account may read any of those records. |
| **R-PRIV-04** | Deletion MUST require the current password for a registered account and an explicit confirmation in the UI. Guests may delete without a password, because possession of the HttpOnly session is their only credential. |
| **R-PRIV-05** | Deletion MUST leave the stable anonymized row, scores, prompts, and shared game structure intact, so **another player's history is never damaged.** |
| **R-PRIV-06** | Deletion MUST NOT invent or silently decrement a server-wide gameplay observation. Prompt usage facts contain no user identifier and stay reconcilable with retained anonymized outcomes. |
| **R-PRIV-07** | Retained message text MUST expire after 30 days. There MUST NOT be a transcript or profile-history endpoint. After 30 days the raw strings deliberately cannot be replayed through a new matcher; durable per-seat and per-turn counts still support difficulty and attempt analysis, and that bounded loss is the accepted tradeoff. |
| **R-PRIV-08** | Historical names, colors, and guest/registered state MUST remain as other players saw them. Ordinary profile edits MUST NOT rewrite them. Username and avatar are not rendered by finished-game history and MUST NOT be copied into it. |
| **R-PRIV-09** | Avatars MUST NOT hotlink arbitrary third-party URLs; only a key from the deployment-hosted catalog may be stored. |
| **R-PRIV-10** | Anonymous retention MUST be based on `last_active_at` — deliberately separate from page-load/login time and ordinary profile writes — MUST be bounded per run, MUST preview by default, and MUST record aggregate audit evidence when applied. |
| **R-PRIV-11** | A stale guest's session MUST be removed with the account, so an old cookie provisions a new guest rather than resurrecting retained data. |

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
| **R-ENG-09** | An E2E test MUST wait on the condition it actually cares about, never a fixed sleep sized to outlast it — such a sleep costs its full length on every run and silently stops covering anything when the thing it waits for gets slower. |
| **R-ENG-10** | Where a test must sit out a production interval, it MUST fast-forward the page's own clock (`page.clock`) rather than spend the time, keeping the interval a production constant instead of something bent for the tests. |
| **R-ENG-11** | Benchmarks are **diagnostic baselines, not CI thresholds** — browser and machine timings vary. |
| **R-ENG-12** | CI MUST run backend lint and tests, PostgreSQL migrations and repositories, frontend test/lint/build, and multi-browser E2E. |

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
| **N-06** | **Direct player-to-player invites.** Only shareable room links exist, so there is no direct-invite delivery path to filter yet. |
| **N-07** | **Avatar uploads and external identity providers.** Schema is reserved; no API is enabled until storage validation, moderation, and identity-linking flows ship. |
| **N-08** | **A built-in room-preset catalogue or preset sharing.** |
| **N-09** | **Prompt languages beyond the Latin registry** (`en`, `de`, `es`, `fr`, `it`, `nl`, `pt`) until their matching semantics are implemented. |
| **N-10** | **A remote password-reset API.** There is no authentication that would make one safe; the server-side command exists instead. |
| **N-11** | **Server-side PNG rendering.** The server stores and replays actions, never pixels. |

---

## 14. Traceability

| Area | Implementation | Proof |
| --- | --- | --- |
| Game rules, scoring, hints, guess matching | [`app/game.py`](../backend/app/game.py) | `tests/test_game.py`, `test_standings.py`, `test_prompts.py` |
| Room model, votes, recap budget | [`app/rooms.py`](../backend/app/rooms.py) | `tests/test_rooms.py`, `tests/handlers/test_rooms.py` |
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
| Data export and deletion | [`auth/account_data.py`](../backend/app/auth/account_data.py) | `tests/test_account_data.py`, `fixtures/account_data_export_v1_fields.json` |
| Retention | [`auth/retention.py`](../backend/app/auth/retention.py), [`services/message_retention.py`](../backend/app/services/message_retention.py) | `tests/test_anonymous_retention.py`, `test_message_retention.py` |
| Bug reports and triage | [`api/bug_reports.py`](../backend/app/api/bug_reports.py), [`request_limits.py`](../backend/app/request_limits.py), [`lib/bugReports.ts`](../frontend/src/lib/bugReports.ts), [`lib/clientErrorLog.ts`](../frontend/src/lib/clientErrorLog.ts), [`lib/screenCapture.ts`](../frontend/src/lib/screenCapture.ts) | `tests/test_bug_reports.py`, `tests/test_request_limits.py`, `tests/e2e/test_bug_reporting.py`, `frontend/tests/bugReports.test.mjs`, `clientErrorLog.test.mjs`, `screenCapture.test.mjs` |
| Moderation, reports, bans, blocks | [`api/moderation.py`](../backend/app/api/moderation.py), [`auth/bans.py`](../backend/app/auth/bans.py), [`auth/blocks.py`](../backend/app/auth/blocks.py) | `tests/test_moderation_api.py`, `test_user_blocks.py`, `test_prompt_content_moderation.py`, `tests/e2e/test_player_reporting.py` |
| Prompt content and governance | [`prompt_content.py`](../backend/app/prompt_content.py), [`api/prompt_lists.py`](../backend/app/api/prompt_lists.py) | `tests/test_prompt_content.py`, `test_prompt_list_governance.py`, `test_owned_prompt_lists.py`, `test_prompt_list_seeding.py` |
| Prompt usage and stats | [`services/prompt_usage.py`](../backend/app/services/prompt_usage.py) | `tests/test_prompt_usage.py`, `test_api_prompt_stats.py` |
| Presets, room codes | [`services/room_presets.py`](../backend/app/services/room_presets.py), [`services/room_codes.py`](../backend/app/services/room_codes.py) | `tests/test_room_presets.py`, `test_room_codes.py` |
| Shutdown drain | [`services/shutdown.py`](../backend/app/services/shutdown.py) | `tests/test_shutdown.py`, `tests/handlers/test_shutdown.py` |
| Runtime analytics | [`services/runtime_metrics.py`](../backend/app/services/runtime_metrics.py) | `tests/test_runtime_analytics.py` |
| Deployment, static delivery, worker topology | [`deployment.py`](../backend/app/deployment.py) | `tests/test_deployment.py`, `test_static_delivery.py` |
| Connection resilience | [`handlers/connection.py`](../backend/app/handlers/connection.py) | `tests/handlers/test_connection.py`, `tests/e2e/test_network_resilience.py`, `test_player_afk_reconnect.py` |
