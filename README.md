# Sketchy

An online multiplayer drawing & guessing game, iSketch/Pictionary-style: one player is given a
prompt to draw while everyone else races to guess it in the chat. Join a public room from the
lobby, or create a private room and share its code — no mandatory accounts required to play.

Terminology is fixed in [GLOSSARY.md](GLOSSARY.md): one agreed name per concept, for UI
copy and docs alike. Read it before naming anything a player can see.

## Features

- Lobby with a live, polled list of public rooms, or join a private room by code.
- Prompt lists selectable during room creation, combined with optional custom prompts. Standard and Extended English ship with the game; registered players can also save, revise, reuse, and delete their own lists from **My prompt lists**, where prompts are pasted in batches - one per line or comma separated - and merged into the list with duplicates and overlong entries reported rather than silently dropped, keep them Private, or make them Unlisted with a share code. The picker and stats catalogue show each official list's content language; every room resolves exactly one language and cannot combine lists with different matching rules. Pick rate and guess accuracy stats are tracked per official prompt and browsable from the lobby on a searchable, sortable prompt stats page. Difficulty is only ranked once enough guessers have faced a prompt, so a rarely offered one is never mistaken for a hard one; the rest are listed as unranked rather than shown a zero they have not earned. If the lists cannot be read at all, creating a room or changing its settings is refused against the prompt-list field instead of the room opening quietly on the built-in prompts; a room drawing only on custom prompts is unaffected, since it was never going to read a list.
- Turn-based rounds: each player draws once per round, choosing from 3 prompt options.
- Real-time synced canvas (freehand brush + rectangle/ellipse/triangle shape tools).
- Drawing rules — two room settings the host sets at creation and edits while waiting.
  **Allowed tools** turns the brush, fill, and shapes on and off independently (at least one
  of brush and shapes stays on, since fill alone can only flood a blank canvas), and
  **Color mode** picks between all colors, the built-in palette only, a colorblind-safe
  palette, and black and white. Both are enforced on the server, which refuses a disallowed
  tool or color before recording or rebroadcasting it, so a stale or modified client gains
  nothing. Erasing is a white brush stroke on the wire, so it rides with the brush and every
  color mode permits white.
- Spectator mode — join any room as a spectator (even when full), with optional room creation setting to reveal the prompt, and private spectator chat restricted to the drawer, spectators, and correct guessers.
- AFK mode — toggle AFK status anytime so you are skipped for drawing turns and not waited for during rounds.
- Restart vote — active players can propose and vote to restart the current game by a strict majority without interrupting live gameplay.
- Kick vote and AFK vote — room players can vote to kick or mark another player AFK by a strict majority of connected, non-spectator players. AFK players and the vote target count toward that population; disconnected players and spectators do not. Spectators cannot cast votes or be selected as moderation targets.
- Save image — save the current canvas directly as a PNG file at any time.
- Game highlights — the hardest prompt, the fastest guess, the best drawer, and the quickest
  guesser on average, on a screen of their own reached from the game over screen or from the
  waiting room afterwards. Derived from guess counts and timings rather than points, so the
  same four appear in a no-scoring game, and each is dropped when the game gives it nothing
  to say.
- Customization option to always hide the masked prompt's length and composition from guessers (forces hints off).
- Optional scoring, selected when the room is created.
- Grace period (30s) — refreshing mid-game reconnects you with your score intact.
- Scoring designed to resist "sandbagging": drawers can't game an easy prompt by stalling,
  since their bonus scales with how fast guessers actually answered (see
  [Scoring](#scoring) below).

## Architecture

Single-process backend holding all live game and room state in memory, with durable storage
for accounts, game history, and prompt lists backed by async SQLAlchemy (embedded SQLite by default,
or PostgreSQL). Built for self-hosting at "friends playing together" scale.

```mermaid
flowchart LR
    subgraph Browser
        UI[React SPA]
    end
    subgraph Server[Single Python process]
        REST["FastAPI REST\n/api/health, /api/ready, /api/rooms"]
        IO["python-socketio\nAsyncServer"]
        State["In-memory state\nRoomManager + Game"]
        Repo["Repository Layer\nUserRepository\nGameHistoryRepository\nPromptListRepository"]
    end
    subgraph Database[Storage]
        DB[("SQLite / PostgreSQL\n(SQLAlchemy + Alembic)")]
    end
    UI -- "GET (polled)" --> REST
    UI <-- "WebSocket (all gameplay)" --> IO
    REST --> State
    IO --> State
    IO --> Repo
    REST --> Repo
    Repo --> DB
```

- **REST** is used for health checks, room discovery, and data queries.
- **WebSocket (Socket.IO)** powers all real-time gameplay interactions, drawing replication, and room events.
- **In-Memory Engine**: Active rooms, canvas sessions, timers, and game progression run entirely in memory.
- **Durable Persistence**: Accounts, game history records, and official or player-owned prompt lists are stored via abstract repository interfaces backed by SQLAlchemy.

## Tech stack

| Layer    | Technology |
|----------|------------|
| Backend  | Python 3.14, FastAPI, python-socketio (`AsyncServer`, ASGI), uvicorn, SQLAlchemy 2.0 (async), PostgreSQL, aiosqlite, Alembic |
| Frontend | React 19, TypeScript, Vite, react-router-dom, zustand, socket.io-client |
| Testing  | pytest + pytest-asyncio (backend unit tests), ruff (backend lint), Playwright (multi-browser E2E testing) |

## Database & Configuration

Sketchy requires zero configuration by default, using an embedded SQLite
database stored locally at `./sketchy.db`. SQLite migrations run automatically
on server startup via Alembic.
SQLite connections enforce foreign keys, use WAL mode for concurrent readers,
and wait up to five seconds for a busy database before failing a write.

Persisted entity IDs are time-ordered UUIDv7 values from the standard
library's `uuid.uuid7()`, generated through a single wrapper in
`app/identifiers.py`. It keeps a counter inside each millisecond, so a burst
of ids stays ordered without stamping any of them into the future.
SQLAlchemy stores them as native 16-byte `uuid` columns on PostgreSQL and
dialect-compatible `CHAR(32)` columns on SQLite; API and Socket.IO boundaries
continue to expose canonical UUID strings. UUID order improves index
locality, but timestamps such as `created_at` remain the authoritative event
time. Consecutive ids within one millisecond are guessable from each other by
design, so they are never used as capabilities: security tokens, room codes,
and share codes remain independently random and are not derived from entity
IDs.

All persisted timestamps require timezone-aware inputs and are normalized to
aware UTC values when written and read. This keeps SQLite and PostgreSQL
behavior identical; application code never has to infer a local timezone for a
naive database value.
Configuration rows, prompt memberships, and each finished-game fact also carry
their database write time. `game_records.persisted_at` is intentionally separate
from `started_at` and `finished_at`, making delayed/retried-save lag measurable
for performance and incident diagnosis. Rows from before timestamp coverage
keep a null write time rather than receiving a fabricated migration timestamp;
all new writes receive the database clock automatically.

Finished-game guesses reference the UUID of their turn explicitly. Persistence
never infers that relationship from the positions of two independently ordered
lists.

Every drawing from a completed game is kept for as long as that game, in the
same transaction that records it. The stored bytes are the canvas frame itself
- the actions, not a picture of them - so a drawing can be replayed and redrawn
at any size, and a PNG stays something the browser produces on demand rather
than something the server keeps. `GET
/api/games/{game_id}/turns/{turn_id}/drawing` returns one, and only to a player
who was in that game; every refusal is a 404, so the endpoint never reveals
whether a game exists. A turn whose bytes the recap had to drop for budget is
recorded as unavailable rather than omitted, and deleting an account erases the
drawings that account made while leaving the row saying so.

Persisting a drawing makes its encoding a stored format, which has to stay
readable by every future decoder rather than only by the client on the other
end of an open connection. `app/canvas_storage.py` holds that commitment: a
registry keyed on the magic and version the blob declares, whose entries are
never removed and whose decoders answer in the current wire format. Clients
therefore never see a stored format at all, and the wire format stays free to
change without rewriting a single stored row. Because a database column has no
integrity check of its own, an operator command decodes stored drawings in
bounded batches and reports any that fail their checksum or name a format this
build cannot read:

```bash
cd backend
.venv/bin/python -m app.services.drawing_storage
.venv/bin/python -m app.services.drawing_storage --batch-size 2000
```
Each live game receives its stable UUIDv7 when it starts. The finished-game
writer reuses that ID for the history row and prompt-usage batch, and stores a
canonical SHA-256 payload digest with the history row. Retrying the same ID and
content is idempotent—even if collection order changes—while reusing an ID for
different content raises an operator-visible conflict instead of duplicating or
silently replacing history. The digest is an integrity/idempotency aid, not a
credential or an event timestamp.
Finished games also store a scoring-rules version and a versioned exact rule
snapshot. The snapshot freezes the numeric default/pressure/hint parameters,
drawer-bonus algorithm, drawing time, permitted tools and colors, prompt
visibility/language, and pinned prompt-source revisions. Historical points can
therefore be interpreted under the rules that produced them after defaults or
algorithms change. Legacy rows use version `0` and an empty snapshot rather
than claiming parameters that cannot be reconstructed. Participant-only game
detail and private account export include the exact snapshot; public history
summaries expose only its versions and typed mode/time fields.
Prompt provenance is normalized as well as snapshotted. Each game records the
immutable list revisions that were actually present after custom-prompt
shadowing—not merely configured slugs—and classifies its real pool as curated,
custom, mixed, or built-in fallback. Every prompt option offered in a completed
turn gets an ordered immutable row with its text snapshot, selected flag,
curated prompt-version ID when applicable, and every list revision containing
that version. Custom and fallback options have explicit source kinds and null
curated identities, so collisions cannot inflate curated statistics or make a
bad prompt untraceable. Exact offers are participant-only history and private
export data; share codes are never stored with them.
The turn row also carries the selected option's source kind and a nullable
foreign key directly to its immutable prompt version. Curated turns are
therefore joinable without text normalization; custom/fallback turns retain
only their factual text snapshot. Database checks and the history writer keep
the selected offer, turn text, source kind, and version identical. Rows from
before provenance coverage use `legacy_unknown`, never a fabricated source.
Finished games also enforce at most one participant seat per linked account,
one turn per game/round/turn number, and one correct guess per participant seat
and turn at the database layer. Multiple accountless seats remain distinct.
Participant, drawer, and guess rows freeze the player's display name, name
color, and guest status when the game is saved. Their account foreign keys are
nullable and use `ON DELETE SET NULL`; even a physical user-row removal cannot
cascade away turns, guesses, or another player's game. The history API uses a
stable participant seat ID and renders the frozen presentation when an account
link is absent. A live player receives that UUIDv7 seat identity when the game
starts even if no session cookie supplied an account. Such a player still
counts toward the recorded player total and keeps every factual turn and
correct guess; history never drops or coalesces the seat merely because its
account link is null.
Historical names, colors, and guest/registered state deliberately remain as
other players saw them; ordinary profile edits never rewrite them. Username
and avatar are not rendered by finished-game history, so they are not copied
into the historical record. A linked account ID may still support a live
profile link while presentation comes from the frozen seat. Account deletion
replaces identifying snapshots with the neutral **Deleted player** tombstone.
If guest identities later merge into one account, their factual seats stay
separate rather than collapsing an already-played game.
When drawing begins, the server freezes the eligible guesser seats. Players who
were AFK or disconnected then, and players who join after that instant, remain
ineligible until the next turn; their text is treated as restricted chat rather
than a guess that could reveal the prompt. Every completed turn stores one
participant outcome per current or late-arriving non-drawer seat: eligibility
and its reason, correct/incorrect/no-attempt/ineligible result, terminal
active/AFK/disconnected/left state, correct time when applicable, and per-seat
wrong, near-miss, and hint totals. The successful-guess row is the optional
scoring child of a correct outcome. Ordinary history retains these numeric
facts but not guess text; text retention and evidence are governed separately.
No-scoring games record the same factual outcomes with zero awarded points and
never invent hypothetical score awards.
Accepted player-authored chat, wrong guesses, and correct-guess text are kept
for 30 days in an audience-aware **Retained message** store. Each live turn
receives its UUIDv7 before play, so a message written during an unfinished game
can carry the same game, turn, and participant-seat correlation IDs as eventual
history without making active games durable. Stored audience account IDs are
the recipients who actually received the line after Blocks and prompt-visibility
rules were applied: ordinary chat and guesses use the Room audience, while
near misses, correct guesses, spectator chat during play, and other restricted
text use the Prompt-aware audience. There is intentionally no transcript or
profile-history endpoint.

Retention is best-effort and does not delay live availability when storage
fails; successful writes add `retainedMessageId` to the `chat_message` payload.
Expired rows are removed at startup and by bounded hourly cleanup during new
writes. A report may select up to 20 unexpired `messageIds`, but only when the
reported player authored them and the reporter was in each stored audience.
The server copies those lines into immutable **Message evidence** before the
ordinary rows expire. Account export includes a player's own unexpired authored
messages and evidence they submitted. Account deletion erases ordinary authored
messages immediately and tombstones the presentation on copied evidence; the
evidence text continues under the protected report retention policy. Numeric
wrong/near-miss outcomes remain in game history independently, supporting game
analysis without turning 30-day message text into lifetime player tracking.
During that window, correlated wrong-guess text and its near-miss classification
can support matching-rule evaluation and abuse investigation. After 30 days the
raw strings intentionally cannot be replayed through a new matcher: durable
per-seat and per-turn counts still support difficulty and attempt analysis, and
that bounded loss is the accepted privacy and storage-volume tradeoff.
Scored games additionally keep an ordered, append-only **score-event ledger**.
Each UUIDv7 event identifies the participant seat and turn, carries the scoring
and rule-snapshot versions, and records one signed delta as a gross guess award,
hint charge, drawer bonus, or later correction. Corrections point to an earlier
event and append a new delta; prior events are never rewritten. The history
writer proves the gameplay events agree with correct guesses and hint spend,
then requires every participant's ledger sum to equal the cached final score in
the same transaction. Legacy games explicitly use ledger version `0` because
gross awards and drawer bonuses cannot be reconstructed from their net totals.
No-scoring games use the current ledger version with an empty event list. Game
detail, the profile breakdown, and private account export expose these audit
facts to participants.
Prompt-list counts are derived from prompt membership on read, so adding or
removing a prompt cannot leave a cached total out of sync.
Prompt usage is not stored as mutable totals on the current display row.
Each finished game appends an idempotent **Prompt-usage fact** for every used
prompt/version and pinned list revision, carrying the authoritative occurrence
time plus scoring and hint modes. Stats are derived by stable prompt concept,
so a later wording revision keeps its history without matching on display text.
The fact indexes support time-window and rule filters; the Prompt stats page
offers all-time, 30-day, and 90-day windows plus scoring/hint segmentation.
The minimum-guesser ranking floor applies independently to the selected slice.
Pre-cutover counters migrate into facts with null time/rule dimensions rather
than fabricated metadata: all-time unfiltered reads retain them, while bounded
or segmented reads deliberately exclude what cannot be attributed truthfully.
Lifetime profile summaries are likewise served from a rebuildable **Daily
user-stat projection**, not four scans across a player's complete participant,
turn, and guess history. A finished-game transaction atomically adds one UTC
day's games, wins, score, turns in participated games, correct guesses, and
drawings for each canonical account. Multiple same-day saves use database
upserts, so concurrent games cannot overwrite one another; idempotent game
retries do not increment twice. Guest-to-account merges rebuild the target and
deduplicate games shared by its factual identities. Ratios and averages remain
derived on read rather than stored.

The projection is disposable: migration backfill and the maintenance command
derive it entirely from immutable game facts. A missing or deliberately erased
projection row reads as zero rather than silently falling back to an unbounded
history scan; operators repair drift explicitly with a full or targeted rebuild:

```bash
cd backend
.venv/bin/python -m app.services.user_stats_projection
.venv/bin/python -m app.services.user_stats_projection --user <account-uuid>
```

### Recalculable competitive foundation

Finished-game facts—not profile counters—are the source for any future rating,
season, achievement, or competitive-standings work. The durable foundation includes game
event times and exact rule versions, factual participant seats with canonical
identity aliases, frozen eligibility and per-turn outcomes, prompt provenance,
and the append-only score-event ledger. Derived rows such as the daily user-stat
projection may be deleted and rebuilt without changing those facts.

This is deliberately a foundation, not a competitive feature. Sketchy v1 has no
rating algorithm, season identity, achievement definitions, competitive-mode
eligibility policy, or server-wide competitive standings. Those choices require a later
product decision and a versioned projection of the retained facts; they must not
be introduced as mutable counters or inferred by rewriting finished games.
Legacy facts with unknown rule/provenance versions remain explicitly unknown so
a future projection can exclude or classify them according to its own declared
policy rather than treating invented metadata as truth.

Prompt content has a stable identity independent of its spelling. A
**Prompt concept** may have immutable, language-specific **Prompt versions**;
equal text never merges concepts implicitly. Versions store a canonical
display answer, a language-aware match key, editorial difficulty, content
rating, explicit category tags, and an exact set of accepted **Prompt aliases**.
Aliases are unique within a concept and language, and are attached separately
to each version so changing an alias later cannot rewrite how an older game
matched guesses. The initial supported Latin-language registry—English,
German, Spanish, French, Italian, Dutch, and Portuguese—case-folds, collapses
whitespace, and folds canonically decomposable accents. Other BCP-47 tags are
rejected until their matching semantics are implemented.
Each room's **Prompt language** is derived authoritatively from its selected
lists, carried into exact and near-match game logic, and exposed in room
payloads. Missing, empty, or mixed-language selections are visible validation
failures rather than silent fallback. A custom-prompts-only room may continue
when the list store is unavailable because it does not consume that content.
List `name` and `description` are authored catalogue copy; optional translated
copy is stored separately by interface locale and selected from
`Accept-Language`, so translating the UI never changes a list's content
language.
Bundled JSON entries carry an explicit UUIDv7 `conceptId`; equal text shares a
concept only when the checked-in files deliberately repeat that ID. Every
language-specific wording has an immutable `promptVersion`, and every bundled
list version becomes a content-hashed immutable **Prompt-list revision** with
ordered membership. Deploying different content under an already-seen list or
prompt version is a startup-failing seed conflict, not an in-place rewrite.
Rooms resolve and games pin the exact revision IDs at start. During the
transition to rebuildable projections, the legacy counter row is linked by
concept and updated in place when a new prompt version rewords it, preserving
its existing statistics; old revisions keep referencing the old wording.

The checked-in seed shape is therefore identity-based rather than text-keyed:

```json
{"conceptId":"01a02b7b-b42d-7afc-a278-fc0ecc83b994","answer":"anchor",
 "promptVersion":1}
```

Changing only capitalization, punctuation, wording, aliases, or editorial
metadata requires both the same `conceptId` and a higher `promptVersion`.
Adding/removing/reordering membership requires a higher top-level list
`version`. Optional `aliases`, `difficulty`, `contentRating`, and `tags` belong
to that immutable prompt version.
Prompt-list governance is schema-first and deny-by-default. User-owned lists
default to **Private**; **Unlisted** requires a unique share code. Official
bundled lists alone are currently **Public**. Ownership, exact source-revision
fork provenance, structured revision tags, moderation actor/time, and the
Active/Under review/Hidden moderation state are relational fields with
portable constraints—never JSON tags or a lossy `is_nsfw` flag. Difficulty and
content rating remain on the exact immutable prompt version where their
meaning belongs. The `public` value is reserved for future moderation-approved
discovery: this v1 baseline intentionally exposes no community discovery,
favorite/star table, or user-facing fork endpoint.
Quick **Custom prompts** remain deliberately ephemeral room input: they are
not auto-saved, do not acquire an implicit owner/list, and disappear with the
in-memory room. A registered host can explicitly send usable quick prompts to
**My prompt lists** and save them as a reusable Private list; nothing is stored
merely because it was typed. An account may own at most 25 lists and a saved
list may contain at most 500 prompts. Editing uses optimistic concurrency and
creates a new immutable revision instead of rewriting the revision a running or
finished game pinned. The content language cannot change after creation.

Private lists resolve only for their owner. Switching a list to Unlisted creates
a cryptographically random **Prompt-list share code**; a host must add that code
in the prompt picker before the server will resolve the list. These codes are
bearer capabilities, not UUIDs: they are retained only in private in-memory
room state and never appear in shared room, history, or log payloads.
User-owned lists and their prompt stats never enter the public official
catalogue. A player who resolves an Unlisted list can privately report the
whole list or one exact immutable prompt version from the picker. Reports use
post-moderation: submission preserves a bounded evidence snapshot but does not
hide content automatically. One reporter may hold one open report per target,
so reporting the same list twice is refused while the first is unread, while
the list and a single prompt inside it stay separately reportable and a
resolved report frees the target to be raised again; one moderator review may dismiss the report or set
the exact target Active or Hidden, with actor/time provenance and an append-only
audit event. Hidden prompts are filtered from future selection, and a list with
no usable prompts fails visibly. Waiting rooms re-authorize the list and every
prompt immediately before Start, closing stale-picker bypasses. A game already
in progress keeps its pinned prompt snapshot and is not rewritten mid-turn.
Owners see list/prompt moderation state in **My prompt lists**, but editing does
not silently override a moderator decision.

Report snapshots survive list and account deletion even after target foreign
keys are cleared. Account data exports include the owner's complete revision
history and a reporter's own prompt-content report text/status, while excluding
owner, reviewer, and internal-note identities. Account deletion removes the
lists and their owned prompt concepts rather than leaving ownerless content.

Runtime attribution observes the ephemeral/persistent boundary: completed
turns snapshot nullable prompt-version source IDs, and usage writes intersect
those IDs with the game's pinned list revisions.
An ephemeral prompt has a null source even when its display text equals a
curated prompt, so neither its offers, picks, nor guess results can inflate the
curated list's statistics (#330).
Stored scoring modes, hint modes, turn outcomes, supported prompt languages,
and supported prompt-list catalogue locales
are string enums backed by portable database `CHECK` constraints. Extending a
set requires one coordinated code, migration, contract, README, and glossary
review.

The UUID change rewrites the pre-v1 initial migration rather than converting
old text keys. Databases created before this baseline must be rebuilt; preserve
no production data on a preproduction schema.

PostgreSQL migrations are an explicit deployment step protected by a database
advisory lock, so concurrent deploy jobs cannot race. Run the migration command
before starting or replacing any application replicas; application startup
verifies the revision and fails with a direct instruction if the step was
missed:

```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy
.venv/bin/python -m app.db.migrate
HOST=0.0.0.0 PORT=8000 .venv/bin/python -m app.server
```

Sketchy v1 supports exactly one application worker. Do not pass Uvicorn
`--workers`, and leave `WEB_CONCURRENCY`/`UVICORN_WORKERS` unset or set to `1`;
startup rejects other values. Live rooms, games, canvases, timers, Socket.IO
sessions, and room-code lookup are process-owned, so a second worker would
split one logical service into inconsistent islands. Shared PostgreSQL state
does not change that boundary, and a Socket.IO message queue alone would not
make multi-worker gameplay correct.

The v1 release-load target for this topology is 50 simultaneous active rooms
and 400 connected player seats on one worker. This is a validation target, not
a claim that an arbitrary host will sustain that load: the checked-in #323
load scenario must measure handler latency, event-loop lag, memory, and drawing
traffic on the documented reference environment before the production baseline
is declared complete. Deployments needing multiple workers are outside v1 and
require shared room/session/timer state plus cross-worker Socket.IO delivery.

Planned deploys use a bounded drain; they do not snapshot or restore live
rooms. `GET /api/ready` returns 200 only after startup is complete and switches
to 503 before shutdown work begins, while `/api/health` remains a liveness check
and reports the current readiness state. At drain start the server sends every
connected client the versioned `server_shutdown` notice, rejects new room
creation, persistent-room materialization, new game starts, and restart votes,
but leaves existing rooms connected so active games can finish. Set
`SHUTDOWN_DRAIN_SECONDS` to a value from 0 through 300 (default 30), and give the
process supervisor a termination grace period longer than that value plus the
normal 10-second finished-history write bound. A second termination signal
abandons the rest of the window immediately, so an operator who cannot wait can
press Ctrl+C (or send `SIGTERM`) again; that forced exit also skips the
abandonment diagnostic below.

A game that finishes during the window follows the ordinary all-or-nothing
history and prompt-usage paths. If the deadline expires first, the server does
not misrepresent a partial game or canvas as completed history. It stores one
idempotent `planned_shutdown_abandonments` diagnostic row for 90 days instead:
runtime game/room UUIDs, phase and round, completed-turn and canvas-action
counts, coarse connected/seated/spectator counts, and timestamps. It never
stores room codes, room/player names, prompts, chat, or canvas contents. A hard
crash cannot run this planned-shutdown hook; failed finished-history writes and
crash-safe retry are handled by the #323 durable spool rather than by live-state
serialization.

PostgreSQL connections are checked before checkout, recycled after 30 minutes,
and bounded to five persistent plus five overflow connections per server
process. These deployment settings can be tuned without code changes:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_POOL_SIZE` | `5` | Persistent connections per process |
| `DB_MAX_OVERFLOW` | `5` | Temporary connections above the pool size |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Maximum wait for an available connection |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Maximum age before a connection is replaced |
| `SHUTDOWN_DRAIN_SECONDS` | `30` | Planned-deploy game drain window, 0-300 seconds |
| `SMTP_HOST` | unset | Mail relay. Unset means messages are logged, not sent |
| `SMTP_PORT` | `587` | Relay port |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | unset | Relay credentials, if it wants them |
| `SMTP_STARTTLS` | `1` | Upgrade the connection before sending |
| `SMTP_FROM` | `sketchy@localhost` | Envelope sender |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Where confirmation and reset links point |
| `EMAIL_SWEEP_SECONDS` | `30` | How often the outbox is emptied |
| `LOG_LEVEL` | `info` | Level for the application's own logs as well as uvicorn's |
| `METRICS_TOKEN` | unset | Bearer token for `GET /metrics`. Unset disables scraping entirely |
| `RUNTIME_EVENT_RETENTION_DAYS` | `30` | How long raw observations are kept before roll-up |
| `RUNTIME_METRICS_FLUSH_SECONDS` | `15` | How often buffered observations are written |

CI upgrades a fresh PostgreSQL 17 database with Alembic, replays the complete
migration chain down and up on PostgreSQL and SQLite, checks schema drift and
the hand-written username index, then runs the repository suite against the
migrated schema. To reproduce the PostgreSQL checks locally, point both
variables at a disposable test database:

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/python -m app.db.migrate
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/pytest -q tests/test_migrations.py tests/test_repositories.py
```

The repository suite deletes application rows from `TEST_DATABASE_URL`; never
point it at a development or production database.

### Accounts

Every visitor is given an account automatically on their first page load, and
it is remembered by an HttpOnly `sketchy_session` cookie. Guests play under a
name of their choosing; setting a username and password later claims that same
account, so stats collected as a guest carry over.

#### Recovery

Claiming an account can offer an email address. It is optional, and stays
optional: requiring one would break registration on every deployment with no
SMTP configured, which includes the zero-configuration default this project
documents. An account without one is reminded weekly that a forgotten password
cannot be reset - a note that can be closed and returns, with the interval kept
on the account so it neither restarts on each new device nor disappears when
browser storage is cleared. It stays out of rooms entirely: a room lays itself
out to the viewport rather than flowing beneath a banner, so the note landed on
the drawing tools, and a note about account hygiene can wait until somebody is
not mid-game. Being in a room suppresses it without spending it - it returns to
the lobby rather than counting as seen. The deploy banner deliberately does not
behave this way, because a game about to be ended under you is worth
interrupting for.

**Email & recovery** in the account menu is where an address is added, replaced
or simply looked at. The weekly reminder is a prompt and nothing more; a prompt
somebody has dismissed is not a place to go back to, so the menu entry is
always there. The dialog opens by saying what the account already has - a
confirmed address, one waiting to be confirmed, or, on a deployment with no
SMTP configured, that a lost password has to be reset by whoever runs the
server.

An address is recorded only once it has been confirmed. Until then it lives in
the confirmation token and nowhere else, so a typo cannot hand the account to
whoever owns the address that was typed, and nobody can reserve a mailbox they
do not control. Only a confirmed address can be sent a reset link.

A reset link is checked when the page opens, not when the form is sent, so
nobody chooses a password only to be told the link was already spent. Checking
deliberately does not consume it - the person has not chosen anything yet - and
is throttled separately from requesting a reset, since it costs a lookup rather
than somebody else's inbox.

`POST /api/auth/password/forgot` answers identically whether or not the account
exists: the response is not a place to learn which usernames are real. A
completed reset revokes every session on the account, including one held by
whoever forced the recovery, and signs the person performing it back in.

Mail is queued in `email_outbox` in the same transaction as the action that
causes it, and delivered by a sweeper. A suspension is never undone by an
unreachable relay, and a reset message is retried with backoff and then
recorded as failed rather than disappearing. With no `SMTP_HOST` set the
messages are logged instead of sent, so a self-hoster can see what would have
gone out - including the confirmation and reset links, which is the only way
that flow can be completed on a deployment without mail.

The address is used to reset a password, and to tell someone their account was
suspended or their content hidden. Nothing else is ever sent to it.

Deployments that cannot send mail reset a password from the server instead.
This is deliberately not an API - there is no authentication that would make a
remote password reset safe - and it records the reason in the audit log:

```bash
cd backend
.venv/bin/python -m app.auth.password_reset \
  --username Forgetful --reason "Asked in person, identity confirmed"
```

Queued mail can also be flushed by hand, for cron-driven deployments or to see
what is stuck:

```bash
cd backend
.venv/bin/python -m app.services.mail_delivery
```

Anonymous retention is based on `last_active_at`, which changes when a player
successfully takes or reconnects to a non-spectator room seat and when a game
is persisted. It is deliberately separate from page-load/login time and
ordinary profile writes. The default policy removes guests with no completed
game after 30 inactive days and guests with history after 365 inactive days;
history rows survive through frozen presentation snapshots. Cleanup is bounded
to 500 accounts per run, previews by default, and records aggregate audit
evidence when applied:

```bash
cd backend
.venv/bin/python -m app.auth.retention
.venv/bin/python -m app.auth.retention --apply
```

Use `--unused-days`, `--player-days`, and `--batch-size` to set an explicit
deployment policy. A stale guest's session is removed with the account, so an
old cookie provisions a new guest rather than resurrecting retained data.

Accounts have an explicit lifecycle state (`anonymous`, `registered`, `merged`,
or `deleted`) and an authorization role (`user`, `moderator`, or `admin`). The
legacy guest boolean is derived from the lifecycle state and is no longer a
separate database value that can drift. Create the first administrator only
after its registered account exists; the guarded command refuses to run once
an administrator exists and records the promotion and required reason in the
append-only audit log:

```bash
cd backend
.venv/bin/python -m app.auth.admin \
  --username Operator --reason "Initial production administrator"
```

Every entry in that log records who acted, the request it belonged to, a
hashed client address, and what was acted on. The subject is named twice on
purpose: `target_user_id` is a real foreign key, so a deleted account leaves
the entry standing with its subject blanked rather than taking it along, while
a `target_type` and `target_id` pair names whatever row the action touched -
a prompt list, a single prompt version, a room, a configuration key. An action
that acts on no single row, such as a bulk retention purge, records neither
and says so by leaving both empty rather than inventing a subject.

Both staff surfaces are reached from the account menu, and only appear for an
account that holds the role: a moderator is offered **Moderation**, an
administrator that and **Server operations**. The account payload carries the
role so the menu knows what to offer; it is never what grants access. Every
endpoint behind those entries checks the role again for itself and answers 404
to anyone else, so the menu decides what is *shown* and nothing more.

A player is reported from the same menu on their row that carries the kick and
AFK votes. The report names their **seat**, never their account: room payloads
deliberately carry no account ids, and wanting to complain about somebody is
not a reason to learn theirs, so the server resolves the seat against the live
room. It also selects the evidence - the reported player's recent messages, as
the reporter actually received them - which is what makes "is this message
theirs" and "did you see it" true by construction rather than checks against a
client's claims. Reporting requires an account, because a report a moderator
cannot follow up on helps nobody.

**Moderation** carries a third tab for suspensions: who is suspended, why, and
until when. A suspension can be given an end date - 24 hours, 7 days, 30 days,
or none - and one with an end date lifts itself, because the list reports what
is in force rather than trusting something to have run. Permanent is
deliberately not the default: most misbehaviour is somebody having a bad
evening, and forever should be chosen rather than arrived at. A suspension
lifted by hand keeps its row and records who lifted it and why, and suspending
somebody from a report resolves that report - acting on a report is deciding
it, and leaving it open puts it back in front of the next moderator.

**Moderation** is where reports are read and acted on - player reports with
their preserved message evidence, and prompt-content reports against a list or
a single prompt. Resolving a content report records that it was looked at;
hiding the list or prompt is the separate decision that acts on it, and the
owner is told when it happens if they have a confirmed address. Every review
takes a note, so no decision is anonymous.

Roles are service-wide privileges. A room **host** remains an ordinary
gameplay role and is never an administrator merely because they created a
room.

Account email identity is nullable, normalized only by trimming and
lowercasing, and protected by a case-insensitive unique index. Verification is
recorded separately in `email_verified_at`. Sketchy does not expose email-based
account recovery until a delivery and verification flow exists; merely storing
an address never makes it a trusted recovery channel.

Avatars never hotlink arbitrary third-party URLs. An account may store only a
key from the deployment-hosted built-in catalog (`initial`, `pencil`, `palette`,
or `spark`); an absent key uses the existing generated initial. Schema for
future uploaded assets and external identity providers is reserved, but no
upload or provider-login API is enabled until storage validation, moderation,
and identity-linking flows ship.

Session cookies contain opaque 256-bit random tokens. Only SHA-256 token hashes
are stored; the database never contains a credential that can be replayed.
Each server-side session records a coarse device label, creation, last use,
expiry, rotation, and revocation. Tokens rotate halfway through their one-year
maximum lifetime, logout revokes the current token immediately, and registered
players can inspect and revoke individual devices or log out everywhere from
the account menu. Socket.IO handshakes resolve the same revocable record as
HTTP requests, so revocation applies on the next connection across all server
processes without a shared signing secret.

Logging in while carrying a guest identity links that guest to the registered
account through an immutable alias. Historical participant, drawer, and guess
rows keep their original IDs and presentation, so a game that contains both
identities keeps two factual seats rather than violating a uniqueness rule or
losing a player. Account history and statistics resolve the account plus all
of its guest aliases; the guest's sessions are revoked during the merge.

Registered players' **Player settings** follow them across devices. Theme,
sound and confetti switches, volume, brush cursor, keyboard shortcuts,
colorblind-safe color preference, guess-field clearing, and reserved custom
brush presets live in `user_settings` and are read or partially updated through
`GET`/`PATCH /api/users/me/settings`. Values are bounded at the API and database
layers; keyboard shortcuts must describe the complete supported action set and
custom brush presets are limited to 20 entries and 16 KiB of JSON.

Guests keep Player settings in browser local storage only. Creating an account
copies that browser's current settings to the account exactly once; logging in
later makes the account copy authoritative on the new device. The
colorblind-safe preference remains private account/browser data. While an
opted-in player (not a spectator) is seated in a room that uses another color
mode, only the host receives an unattributed **Colorblind-safe suggestion**.
The host can switch the room to the colorblind-safe palette or dismiss the
suggestion for that live room. It belongs to the waiting room, where the
palette can still be changed, so an unanswered one clears when a game starts
and returns afterwards; a dismissed one stays gone. It disappears when the
last opted-in player leaves, never changes room settings automatically, and the preference and
dismissal never appear in player, room-state, room-list, invite-preview, or
session payloads. Registered preferences are read from server-side settings;
guest preferences stay local and are supplied only to the live seat.

Every guest or registered player can open **Your data** from the account menu.
An export request creates a durable asynchronous job and produces a private,
versioned JSON document containing that player's account fields, linked guest
identities, session metadata, game seats, drawn turns, correct guesses, and
account-event metadata. Password/session hashes, other players' profile fields,
and other players' message or guess bodies are never included. Format v1
exports expire after seven days. The HTTP flow is `POST
/api/auth/data-exports`, `GET /api/auth/data-exports/{id}`, then the returned
`downloadUrl`; only the owning account may read any of those records.

The application schedules generation after returning the request. Jobs are
stored before work begins, so an operator can retry a bounded batch left
pending—or processing for more than 15 minutes after a crash—with:

```bash
cd backend
.venv/bin/python -m app.auth.account_data --limit 25
```

**Delete account** requires the current password for a registered account and
an explicit `DELETE` confirmation in the UI. Guests can delete the
automatically provisioned account without a password because possession of its
HttpOnly session is their only credential. Deletion immediately revokes every
linked session, removes export/provider/avatar records, clears login and profile
identity, and replaces the player's frozen participant/drawer/guess names with
**Deleted player**. The stable anonymized row, scores, prompts, and shared game
structure remain, so another player's history is never damaged. Prompt usage
facts contain no user identifier and remain reconcilable with retained,
anonymized game outcomes; deletion neither invents nor silently decrements a
server-wide gameplay observation.

Passwords use Argon2id. On every successful login, Sketchy compares the encoded
hash with the current cost parameters and replaces stale hashes atomically;
raising the configured Argon2 cost therefore upgrades active accounts without
a bulk plaintext migration. The encoded hash carries its algorithm and cost
parameters, so a redundant schema version column is not used.

The authentication endpoints are rate limited per client address in shared
database buckets. Login, registration, and account/name lookup limits survive
restarts and apply once across every replica. Bucket keys are HMAC-SHA-256
digests under `IP_HASH_SECRET` (or an automatically generated database secret),
so raw IP addresses are never stored. Expired buckets are cleaned in bounded
batches. Lower-risk profile and prompt-statistics throttles remain
process-local. The defaults suit a normal deployment; raise them if many of
your players share one address:

| Variable | Default | Applies to |
| --- | --- | --- |
| `AUTH_LOGIN_LIMIT` | 10 per 5 minutes | `POST /api/auth/login` |
| `AUTH_REGISTER_LIMIT` | 10 per hour | `POST /api/auth/register` |
| `AUTH_LOOKUP_LIMIT` | 60 per minute | name availability and display-name changes |
| `AUTH_RESET_LIMIT` | 5 per hour | `POST /api/auth/password/forgot` |
| `AUTH_RESET_CHECK_LIMIT` | 30 per hour | `POST /api/auth/password/reset/check` |
| `AUTH_VERIFY_LIMIT` | 10 per hour | `PUT /api/auth/email` |

Set the same high-entropy `IP_HASH_SECRET` on every deployment that shares the
database if you manage secrets externally. Rotating it starts fresh buckets
without exposing or re-identifying old keys.

Limits are keyed on the connecting address. Behind a reverse proxy or tunnel
every request arrives from the proxy, so run the production server with
`PROXY_HEADERS=1` and `FORWARDED_ALLOW_IPS=<proxy address>` to have the real
client address recovered from `X-Forwarded-For`. Without that trusted-proxy
configuration the header is ignored on purpose: it is attacker-controlled, and
trusting it blindly would let a password-guesser sidestep the limit by varying
it on every attempt.

### Reports and suspensions

Any signed-in player, including a guest account, can submit a private **Report**
with `POST /api/reports`. Reports use one of five bounded reasons—harassment,
offensive drawing, inappropriate name, cheating, or spam—plus up to 2,000
characters of detail and an optional 32 KiB JSON context snapshot. Game and
turn references are validated when supplied. Submitted context is preserved as
versioned, reporter-supplied evidence; it is not treated as a server-verified
fact merely because it was stored. The optional `messageIds` field pins up to
20 server-retained messages authored by the reported player. The server proves
the reporter actually received every selected line and rejects expired,
cross-room, wrong-author, or mismatched game/turn evidence.

Only moderators and administrators can list and resolve or dismiss reports via
`/api/moderation/reports`. Review is one-way: a pending report receives one
resolution and cannot later be silently rewritten. Protected report evidence
survives account anonymization. A player's data export includes their own
report text and submitted evidence, but excludes the reported account ID,
reviewer identity, and internal resolution note.

Player-authored prompt content has a separate, target-specific report flow.
After resolving an Unlisted list by its bearer code, a signed-in player may use
`POST /api/prompt-content-reports` to report the list or an exact
`promptVersionId`; official bundled content, inaccessible content, and
self-reports are rejected. Reasons are inappropriate, hateful or abusive,
sexual content, violence, spam, or other, with up to 2,000 characters of
detail. Moderators and administrators list and one-time review the queue at
`/api/moderation/prompt-content-reports`. A resolved review explicitly chooses
Active or Hidden; a dismissal cannot mutate content. The workflow is
post-moderation, so a report alone never changes availability.

Moderators and administrators can create temporary or permanent account
**Suspensions** through `/api/moderation/bans`; moderators cannot suspend peers,
and administrators cannot be targeted. Creating a suspension revokes every
signed-in device and removes any live room seat immediately. Correct-password
login, authenticated HTTP requests, and Socket.IO handshakes all reject an
active suspension. A token revoked when the suspension was created remains
recognizable until expiry, so its next request cannot be mistaken for a new
cookieless guest. Data export, account deletion, and logout remain available
through that ban-time credential so moderation cannot erase privacy rights.
Expired suspensions stop applying automatically; revocation preserves the
historic record and its reason.

Player-report and prompt-content-report submission/review, suspension, and
revocation each append an audit
event. Audit rows store a canonical request UUID and an HMAC-SHA-256 client IP
hash under the deployment's `IP_HASH_SECRET`; raw addresses, report text, and
context evidence are never copied into ordinary request logs or public player,
room, preview, or lobby payloads.

### Player blocks

Every account, including a guest, has a directional **Block** list at
`GET`/`POST /api/users/me/blocks`; `DELETE
/api/users/me/blocks/{user_id}` removes an entry idempotently. Self-blocks are
rejected and each pair is unique at the database layer. A historical guest
alias resolves to its registered account, and login merges both incoming and
outgoing blocks without creating duplicates or a self-block. Account deletion
removes every block owned by or targeting the anonymized identities; a data
export includes the requester's block IDs and timestamps.

Blocking filters only ordinary player-authored chat for the player who created
the block. The sender still sees their own line, while room state, players,
scores, turns, correct-guess events, votes, and room-authored announcements are
never hidden. This keeps blocking from changing gameplay facts or creating a
different game state for each player. Block lookups use a bounded 1,024-sender
LRU populated from PostgreSQL/SQLite and invalidated immediately by the REST
mutation in the supported single-worker process, avoiding one database query
per chat line.

Sketchy currently has shareable room invite links, not direct player-to-player
invites, so there is no direct-invite delivery path to filter yet. Any future
direct invite feature must consult `user_blocks` before delivery; a room link
someone obtains independently remains usable because a Block is not a
service-wide **Suspension**.

## Project structure

```
backend/
  alembic/        Alembic migration environment and versioned migration scripts
  data/
    prompt_lists/ Identity-based bundled prompt list JSON definitions
  app/
    db/           SQLAlchemy models, engine setup, seeding, and migration runner
    repositories/ Abstract repository interfaces and SQLAlchemy implementations
    api/          REST routers: player profiles, prompt lists, and prompt stats
    main.py       ASGI entrypoint - wires FastAPI + Socket.IO together, health and room endpoints
    handlers/
      __init__.py    Registers all handler domains and returns their lifecycle context
      context.py     Shared HandlerContext for Socket.IO, rooms, timers, and repositories
      auth.py        Current-player authentication and stale-socket rejection
      rooms.py       Room creation, joining, settings, previews, and player lifecycle
      game.py        Game start and prompt-selection transport handlers
      drawing.py     Drawing, undo, and canvas synchronization handlers
      chat.py        Guessing, chat, and purchasable hint handlers
      moderation.py Vote-kick and AFK handlers
      restart.py    Majority-vote game restart handlers
      connection.py Socket connect/disconnect and reconnect-grace handling
      payloads.py    Typed boundary models and parsers for every client command
    services/
      game_flow.py Shared turn, round, timer, and player-removal workflows
      game_highlights.py Pure derivation of a finished game's highlights
      timers.py    Application-owned asynchronous timer lifecycle
    presenters.py Pure construction of room, turn, round, and session payloads
    game.py       Pure game state machine (turns, prompt choice, scoring) - no I/O, unit-testable
    rooms.py      In-memory Room/Player/RoomManager domain model
    state.py      Shared RoomManager singleton
    prompts.py    Prompt list + random choice helper
    drawing_rules.py Which tools and colors a room allows, and the palettes behind them
  tests/
    handlers/     Focused asyncio integration suites for each Socket.IO handler domain
    e2e/          Multi-browser Playwright scenarios
    test_*.py     Domain, protocol, payload, wire-contract, timer, DB, repository, and performance unit tests
frontend/
  src/
    components/   Canvas, Toolbar, PlayerList, PromptDisplay, Timer, GuessChat
    pages/        LobbyBrowserPage (home), GameRoomPage (room/gameplay), ProfilePage, PromptStatsPage
    store/        zustand global game state store
    hooks/        useGameSocketListeners - registers all socket listeners once
    lib/socket.ts socket.io-client singleton + REST base URL
    lib/drawingRules.ts The client's copy of the room's tool and color rules
    types.ts      Shared TypeScript types for all socket payloads
```

## Getting started

Requires Python 3.14+ and Node 20+. Startup refuses an older interpreter.

### Quick start

```bash
./scripts/serve.sh
```

Installs backend/frontend dependencies, builds the frontend, runs the backend test suite, then
starts a single local server on http://localhost:8000 that serves the built frontend alongside
the API/WebSocket (see [Production build](#production-build) below). Useful flags:

```bash
./scripts/serve.sh --skip-build   # reuse the existing frontend/dist
./scripts/serve.sh --skip-tests   # skip the pytest run
./scripts/serve.sh --force        # kill whatever is already listening on the port first
PORT=9000 ./scripts/serve.sh      # serve on a custom port
```

For frontend development with hot-reload instead, follow the Backend/Frontend steps below and
run each independently.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # runtime only
# .venv/bin/pip install -r requirements-dev.txt  # runtime + pytest/Playwright
.venv/bin/python -m app.server
```

Runs on http://localhost:8000. `GET /api/health` should report
`{"status":"ok","readiness":"ready"}` and `GET /api/ready` should return
`{"status":"ready"}` after startup.
Install `requirements-dev.txt` instead when you plan to run unit, integration, or E2E tests.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173 (Vite dev server). The frontend requests `/api` and
`/socket.io` relative to whatever origin served it, and the dev server proxies both
to the backend on http://localhost:8000 (see `server.proxy` in
`frontend/vite.config.ts`). Everything is therefore same-origin in dev, under
`scripts/serve.sh`, and in E2E — which is what keeps cookie-based sessions working
without CORS credentials. Point the proxy elsewhere if your backend is not on 8000.

Open the dev server URL in two separate browser profiles/incognito windows to test with
multiple players.

### Running tests

```bash
# Install test/dev deps once (pytest, Playwright, …)
cd backend && .venv/bin/pip install -r requirements-dev.txt

# Unit & integration tests
.venv/bin/pytest

# Lint (undefined/unused names, mutable defaults, truncating zips, async sleeps)
.venv/bin/ruff check app tests

# Backend performance micro-benchmarks
backend/.venv/bin/python benchmarks/backend.py
backend/.venv/bin/python benchmarks/live_drawing.py
backend/.venv/bin/python benchmarks/user_stats.py --games 10000 --reads 100

# Near-limit canvas payload, server-memory, encoding, and decoding measurements
backend/.venv/bin/python benchmarks/canvas_history.py --near-limit

# Near-limit browser decode/replay on desktop and 4× CPU throttling
./benchmarks/run_canvas_history_browser.sh

# End-to-end canvas benchmarks (desktop + throttled mobile)
./benchmarks/run_canvas.sh

# Faster local iteration on one profile, with optional JSON output
./benchmarks/run_canvas.sh --profiles desktop --json-output /tmp/canvas-benchmark.json

# Also capture Chrome DevTools timeline traces and heap allocation profiles
./benchmarks/run_canvas.sh --trace-dir /tmp/canvas-traces

# Multi-browser Playwright E2E tests (install browsers once first)
backend/.venv/bin/python -m playwright install chromium firefox
./scripts/test-e2e.sh
```

`test-e2e.sh` builds the frontend, starts a server on its own throwaway
database, and runs the Playwright suite across as many xdist workers as the
machine has cores, capped at eight — past that the browsers contend for CPU and
timing-sensitive tests start to flake. Override with `E2E_WORKERS=<number>`.
The E2E server also runs with `TURN_RESULTS_SECONDS=0.5`, because the suite
plays whole games end to end and the production five-second pause after every
turn otherwise dominates the run. Clients read the phase length off the
payload, so a shortened pause is still a faithful turn.

Two rules keep the suite fast as it grows. A test waits on the condition it
actually cares about — the next phase arriving, the element appearing — never on
a fixed sleep sized to outlast it, because such a sleep costs its full length on
every run and silently stops covering anything when the thing it waits for gets
slower. And where a test genuinely has to sit out a production interval, such as
the lobby's four-second room-list poll, it fast-forwards the page's own clock
with Playwright's `page.clock` rather than spending the time. That keeps the
interval a production constant instead of something bent for the tests, and it
is the tool to reach for before making a timing value configurable.

The user-stat benchmark seeds deterministic finished-game facts, rebuilds the
daily projection, and compares the former four lifetime aggregates with the
current repository read. On a local 10,000-game/10,000-turn SQLite run on
2026-08-23, 100 reads measured 6.85 ms versus 0.698 ms median (9.81×); treat
those timings as a reproducible diagnostic, not a CI threshold or a PostgreSQL
capacity claim. The structural invariant is tested separately: profile reads
must not query participant, turn, or guess fact tables.

The canvas benchmark starts the built application on an isolated local port
(`8765` by default), creates a real two-player game, and reports
drawer-to-guesser stroke latency, large-fill latency, Undo/replay latency,
and the `sync_strokes` WebSocket payload size. It also instruments local drawer
interaction-handler time, canvas readback calls/time/pixels, heap deltas, long
tasks, a nested-boundary fill, and repeated Undo. Optional trace output includes
raw DevTools timeline JSON and a sampled heap profile per browser profile; the
timeline can be loaded into Chrome DevTools or Perfetto. Results are diagnostic
baselines, not CI pass/fail thresholds, because browser timings vary by machine.
The `mobile` profile uses a 390×844 viewport and 4× CPU throttling. Override
the port with `PORT=<number>` when needed.

The canvas-history benchmarks construct deterministic path-heavy, shape-heavy,
fill-heavy, fill-bounded, realistic, mixed, and theoretical-maximum histories.
The Python benchmark reports packed payload, retained server memory, and
encode/decode costs. The browser benchmark runs the production decoder and
renderer for cold late-join and repeated reconnect-style replay; expensive
fill/mixed histories are evenly sampled and clearly reported as diagnostic
projections rather than full-run timings.

Read the fill fixtures as a pair. `fill-heavy` is a ceiling, not a workload: it
fills an empty canvas and never repeats a color, so every fill repaints all
480,000 pixels, which is the most a client could ever ask of a replay rather
than what one costs. `fill-bounded` is the same fill count with the canvas
ruled into cells first, and runs an order of magnitude cheaper, because a real
fill lands inside something once anything has been drawn. `realistic` is a busy
drawing rather than a limit, and is the fixture to set a latency budget
against. `fill-bounded` and `realistic` are replayed whole rather than
sampled, so neither of their numbers is a projection.

`game.py` and `rooms.py` are pure logic (no sockets), covered by direct unit tests. Top-level Socket.IO handlers are grouped by domain under `app/handlers` and covered by focused asyncio integration suites in `backend/tests/handlers`. Cross-domain turn, round, timer, and player-removal workflows live in `services/game_flow.py`, while pure outgoing payload construction lives in `presenters.py`. Client JSON commands are validated as strict object payloads in `handlers/payloads.py`; values are not coerced, booleans are never accepted as integers, and bounded validation completes before authorization or mutation. The compact binary drawing and fixed-array undo commands have dedicated parsers for their documented wire formats. `tests/test_wire_contract.py` pins the names the two sides share - the events each direction sends, the camelCase keys the server puts in its payloads, and the aliases its command parsers accept - by reading both trees as text. It also rejects wire names built from vocabulary the glossary retired, because agreement alone cannot tell a current name from an old one both sides kept, and pins the exact retired phrases that previously drifted back into player-facing copy and this README. Nothing else checks those: a payload key is a plain string here and a plain property there, so renaming one side alone compiles, lints, and passes every other test while the feature silently stops working. Playwright E2E tests in `backend/tests/e2e` cover real-time multi-browser room sessions, settings persistence, AFK status, and disconnection sync across Chromium and Firefox.

### Production build

```bash
cd frontend && npm run build   # outputs frontend/dist
cd ../backend && HOST=0.0.0.0 .venv/bin/python -m app.server
```

When `frontend/dist` exists, `app/main.py` mounts it as static files on the same FastAPI app,
so the whole game (UI + API + WebSocket) is served from a single port. The built-in server
gzip-compresses eligible responses, serves Vite's fingerprinted `/assets/` files with a
one-year `immutable` cache policy, and serves `index.html` (including client-route fallbacks)
with `no-cache` so browsers discover new deployments promptly.

If a reverse proxy handles compression instead, it may replace the gzip layer, but it should
preserve the same cache distinction: fingerprinted assets are immutable while the SPA HTML
must revalidate. Ensure compressed proxy responses include `Vary: Accept-Encoding`.

## Game flow

1. **Lobby**: pick a nickname, then create a room (public or private, with a max player count
   and number of rounds), pick a scoring mode, or join one by code.
2. **Waiting room**: once 2+ players have joined, the host clicks **Start game**.
3. **Choosing** (15s): the current drawer picks one of 3 prompt options.
4. **Drawing** (90s by default, configurable): the drawer draws; everyone else sees a masked
   prompt (`_ _ _ _`) and guesses in the chat. The turn ends early once everyone's guessed
   correctly.
5. **Turn results** (5s by default): the prompt is revealed and scores update, then the next
   player's turn begins.
6. Repeat until every player has drawn once per configured round count, then **Game over**
   shows the final standings.

Room codes are random six-character invite capabilities reserved in the
database before they are shown to a player. The reservation primary key makes
allocation global and race-safe even though v1 runs one application worker.
When an ephemeral room empties, its code is retired for 30 days; a stale invite
during that window says the room ended instead of silently joining an unrelated
group. Startup retires any ephemeral reservations orphaned by a restart or
crash. Expired ephemeral reservations may be reused, while codes allocated to
future persistent rooms are permanent and never enter the reuse pool.

Registered players may choose **Keep this room for future games** during room
creation. A **Persistent room** keeps its permanent code and typed configuration
under that owner's account, appears under **My persistent rooms** in the lobby,
and may be joined by anyone who has the code. Up to ten active persistent rooms
may belong to one account. Only the registered owner becomes host and may edit
or archive the durable configuration.

Persistence stops at configuration. When an empty persistent room is opened—or
opened again after a restart—the server creates a new in-memory room instance
from the saved settings. Players, scores, current game/phase, timers, reconnect
grace, canvas, recap, chat, and quick custom prompts are never restored. Durable
configuration may reference current active built-in prompt lists or lists owned
by the room owner using stable list IDs; the latest authorized revision is
resolved each time and snapshotted when a game starts. A missing, deleted,
hidden, or no-longer-authorized list blocks opening visibly instead of falling
back to default prompts. Quick custom prompts must first be saved as a private
prompt list.

Registered players may also save up to 20 private **Room-setting presets** from
the room-creation page. A preset is a named, versioned copy of typed settings
for a future ordinary room; it has no room code, members, host identity, game,
scores, timers, chat, canvas, or other live state. Applying one fills the create
form but does not enable **Keep this room for future games**, so creating from a
preset allocates a fresh ephemeral code unless the player independently chooses
to create a persistent room. Presets can be updated with optimistic version
checks or deleted, are included in the owner's private data export, and are
erased on account deletion.

Like persistent rooms, presets retain stable IDs for active built-in prompt
lists or lists owned by the preset owner, then resolve their latest authorized
revision when applied. Deleted, hidden, or no-longer-owned references produce a
visible error. Borrowed Unlisted-list share codes and quick custom prompts are
never stored in a preset; save that prompt content as an owned list first. No
built-in preset catalogue or preset sharing exists in v1.

Archiving prevents a new live instance from being created and permanently
reserves the old code. If people are still in the room, their current instance
becomes ordinary ephemeral state and lasts until empty. Account deletion does
the same for every room owned by that account; the private account export
includes the saved configuration and archive state.

### Scoring

- Everyone starts a game on zero points, in every scoring mode.
- Room creators can choose **Default**, **Pressure**, or **No scoring**.
  No-scoring games still detect correct guesses and end turns normally, but everyone remains
  on zero points and no standings are shown.
- **Default**: a correct guess scores between 100 and 300 points, falling linearly with the time
  left in the turn: `round(100 + 200 * remaining_seconds / drawing_seconds)`. Guess quickly for
  up to 300 points, or 100 points minimum at the deadline.
- **Pressure**: a correct guess starts at 300 points, the same as default scoring, and decays
  exponentially — roughly 2% per second — and the decay rate **doubles for everyone still
  guessing once the first player gets the prompt**. Points are floored at 50, so a late correct guess is always worth something. The
  per-second rate is derived from the room's own drawing time, so the curve has the same shape in
  a 15-second room and a 300-second one. Because the penalty scales with the *gap* after the first
  correct guess rather than applying as a step, a near-simultaneous second guess loses only a
  handful of points.
- **Hints are bought on credit.** In the **Buy letters** and **Wheel of Fortune** hint modes,
  nothing is charged when a hint is bought. Instead, the turn's total hint spend is subtracted from
  the points that turn's correct guess earns, floored at zero: `turn_score = max(0, guess_points -
  hint_spend)`. A turn can be wiped out, but a player's running total never goes down, and hints
  cost nothing at all to a player who never guesses the prompt. Spend is capped at 300 per turn — the
  most a single guess can ever be worth. In Pressure mode the 50-point floor guarantees the *gross*
  award only; the hint spend is settled after it.
- The drawer receives the sum of points earned by all correct guessers in that turn (`drawer_score = sum of guesser scores`, after each guesser's hint spend), balancing drawing and guessing potential across complete rotations.
- These parameters are scoring rules version 1. Changing an outcome-producing
  constant or algorithm requires a version bump; every completed game freezes
  the full rule snapshot used for its scores.

### Spectating

- Players can join any room (including full rooms) as a spectator. Spectators do not draw or earn scores.
- By default, spectators see the masked prompt like active guessers, but room creators can enable **Allow spectators to see the prompt**.
- Spectator chat messages are restricted to the drawer, spectators, and players who have already guessed, keeping active guessers spoiler-free.

### Runtime analytics

Nothing durable recorded how the server behaved. `RoomManager` had the natural
instrumentation points - `create_room`, `add_player`, `remove_player`,
`remove_room_if_empty` - and counted nothing at any of them, so peak
concurrency, room lifetime, reconnect rate, timer overruns and real drawing
sizes were unknowable, and the release load target was unmeasurable.

Two things are now recorded, answering two different questions. Live counts of
rooms, players and running games live in memory: one worker owns all of it
(#382), so an in-process count is the true count, and it is meant to vanish on
restart because a live count is not a historical fact. Observations - joins,
disconnects, evictions after the reconnect grace window, games started,
finished and abandoned, timer overruns past 250ms, stored drawing sizes,
drawings dropped by the recap budget - are buffered and written in batches,
because a database round trip per join would be felt as lag in a drawing. The
buffer is bounded and drops oldest when full, counting what it dropped, so a
gap is visible rather than silent.

Raw observations are kept for 30 days and rolled into permanent daily totals
first. What retention costs is the ability to ask about one particular minute
last month; the shape of the month survives. Unbounded event rows on embedded
SQLite is a disk that fills up quietly.

Migrations run with SQLite foreign keys off and finish with a
`PRAGMA foreign_key_check`. Batch mode rebuilds a table by copy, drop, rename,
and with enforcement on, `DROP TABLE` performs an implicit delete that fires
`ON DELETE CASCADE` - altering a table others point at empties them and hands
back a table that still looks correct. Suspending enforcement stops that;
checking at the end is what keeps the suspension honest, so a migration that
orphans rows fails loudly instead of leaving a database that only looks intact.

**Games that stop are now recorded.** Persistence used to run only for a game
that reached its end, so a room everyone walked out of left no trace at all -
the games most worth looking at were the only invisible ones. An abandoned game
is written as an ordinary `game_records` row with `outcome = 'abandoned'`;
`finished_at` keeps meaning when the game ended, not that it finished. Player
history shows finished games unless `?includeAbandoned=true` is asked for, and
an abandoned game contributes the turns actually drawn and guessed but not a
game played, a game won, or a score - counting it would let a room that keeps
emptying inflate everyone's totals and drift the average score upward.

Operators read this two ways. `GET /metrics` returns Prometheus text behind a
bearer token and is disabled entirely until `METRICS_TOKEN` is set. The
in-app page at `/admin/operations` needs the administrator role and carries
live counts, trends over the retained window, the raw activity table, and the
audit ledger as its own tab. Its per-player view answers "which account keeps
disconnecting", and because that is a surveillance surface on the game's own
players, every use writes an audit event naming both who looked and who was
looked at.

The running server flushes and purges on its own. For cron-driven deployments,
or to see what is stuck:

```bash
cd backend
.venv/bin/python -m app.services.runtime_metrics --purge
```

### Reconnection & disconnection

- On disconnect, a player has 30 seconds to reconnect with their private stored secret and keep
  their score and place in the turn order. A successful reconnect replaces the player's active
  socket, so the superseded socket can no longer issue commands.
- If the drawer disconnects and doesn't return in time, their turn is skipped and evicted from
  the rotation.
- If everyone disconnects, the room is cleaned up.
- An action that expects an answer - creating a room, joining, starting, voting to restart -
  is never handed to a socket that is not connected. It waits for the connection and is sent
  once, or it times out having been sent at all, so a request reported as failed cannot arrive
  later on reconnect. Actions that only make sense in the moment - a guess, a vote, leaving,
  toggling AFK - are dropped outright rather than replayed into whatever the room has become.

## Key design decisions & limitations

- **Durable persistence with in-memory gameplay**: persistent domain data (users, game history records, official lists, explicitly saved player prompt lists, persistent-room configuration, global room-code reservations, and the bounded retained-message window) is stored via SQLAlchemy with zero-config embedded SQLite by default and optional PostgreSQL support. Real-time game state (live room instances, active games, strokes, timers, and prompt-list share capabilities) remains purely in memory for minimal latency; durable configuration and message correlation IDs do not make an active game recoverable.
- **Single application worker**: one Uvicorn worker owns every live room,
  Socket.IO session, timer, and canvas. Startup rejects common environment-based
  multi-worker settings, deployment commands pin one worker, and the v1 release
  gate targets 50 simultaneous active rooms / 400 connected player seats. This
  is an explicit product ceiling, not an undiscovered horizontal-scaling mode.
- **Bounded planned-deploy drain, no live snapshots**: readiness fails before
  the process rejects new rooms and games and warns connected clients. Existing
  games have a configured bounded window to finish normally. A deadline
  leftover receives only a 90-day privacy-safe abandonment fact; partial games,
  canvases, timers, scores, and rooms are never serialized or restored, and a
  crash still loses process-owned state.
- **Versioned hybrid drawing protocol**: live drawing actions share one compact Socket.IO
  event. Data-bearing path, shape, and fill actions use binary attachments with fixed-width
  colors, widths, shape IDs, and quarter-pixel signed coordinates. Path-end and clear use
  their version/action byte directly as a numeric control payload, avoiding Socket.IO's
  binary-attachment envelope when it would be larger than the action itself. The server
  rejects malformed, unsupported, unauthorized, and out-of-phase payloads before recording
  or rebroadcasting them.
- **Versioned canvas history**: rooms keep drawing actions in a contiguous packed byte buffer
  with compact action offsets, and send replay history in a versioned binary envelope
  containing its action-offset table and packed records. Packed paths use quarter-pixel
  signed 16-bit coordinates and one-byte widths; packed shapes additionally use a one-byte
  shape enum. The frontend retains the versioned `{v, a}` JSON history decoder as a
  compatibility fallback.
