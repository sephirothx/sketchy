# Sketchy

An online multiplayer drawing & guessing game, iSketch/Pictionary-style: one player is given a
prompt to draw while everyone else races to guess it in the chat. Join a public room from the
lobby, or create a private room and share its code — no mandatory accounts required to play.

Terminology is fixed in [GLOSSARY.md](GLOSSARY.md): one agreed name per concept, for UI
copy and docs alike. Read it before naming anything a player can see.

## Features

- Lobby with a live, polled list of public rooms, or join a private room by code.
- Prompt lists selectable during room creation, combined with optional custom prompts. Standard and Extended English ship with the game; registered players can also save, revise, reuse, and delete their own lists from **My prompt lists**, keep them Private, or make them Unlisted with a share code. The picker and stats catalogue show each official list's content language; every room resolves exactly one language and cannot combine lists with different matching rules. Pick rate and guess accuracy stats are tracked per official prompt and browsable from the lobby on a searchable, sortable prompt stats page. Difficulty is only ranked once enough guessers have faced a prompt, so a rarely offered one is never mistaken for a hard one; the rest are listed as unranked rather than shown a zero they have not earned.
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
        REST["FastAPI REST\n/api/health, /api/rooms"]
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
| Testing  | pytest + pytest-asyncio (backend unit tests), Playwright (multi-browser E2E testing) |

## Database & Configuration

Sketchy requires zero configuration by default, using an embedded SQLite
database stored locally at `./sketchy.db`. SQLite migrations run automatically
on server startup via Alembic.
SQLite connections enforce foreign keys, use WAL mode for concurrent readers,
and wait up to five seconds for a busy database before failing a write.

Persisted entity IDs are time-ordered UUIDv7 values. SQLAlchemy stores them as
native 16-byte `uuid` columns on PostgreSQL and dialect-compatible `CHAR(32)`
columns on SQLite; API and Socket.IO boundaries continue to expose canonical
UUID strings. UUID order improves index locality, but timestamps such as
`created_at` remain the authoritative event time. Security tokens and room
codes remain independently random and are not derived from entity IDs.

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
hide content automatically; one moderator review may dismiss the report or set
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
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PostgreSQL connections are checked before checkout, recycled after 30 minutes,
and bounded to five persistent plus five overflow connections per server
process. These deployment settings can be tuned without code changes:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_POOL_SIZE` | `5` | Persistent connections per process |
| `DB_MAX_OVERFLOW` | `5` | Temporary connections above the pool size |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Maximum wait for an available connection |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Maximum age before a connection is replaced |

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
suggestion for that live room. It disappears when the last opted-in player
leaves, never changes room settings automatically, and the preference and
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

Set the same high-entropy `IP_HASH_SECRET` on every deployment that shares the
database if you manage secrets externally. Rotating it starts fresh buckets
without exposing or re-identifying old keys.

Limits are keyed on the connecting address. Behind a reverse proxy or tunnel
every request arrives from the proxy, so run uvicorn with `--proxy-headers` and
`--forwarded-allow-ips=<proxy address>` to have the real client address
recovered from `X-Forwarded-For`. Without that flag the header is ignored on
purpose: it is attacker-controlled, and trusting it blindly would let a
password-guesser sidestep the limit by varying it on every attempt.

### Reports and suspensions

Any signed-in player, including a guest account, can submit a private **Report**
with `POST /api/reports`. Reports use one of five bounded reasons—harassment,
offensive drawing, inappropriate name, cheating, or spam—plus up to 2,000
characters of detail and an optional 32 KiB JSON context snapshot. Game and
turn references are validated when supplied. Submitted context is preserved as
versioned, reporter-supplied evidence; it is not treated as a server-verified
fact merely because it was stored.

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

Requires Python 3.11+ and Node 20+.

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
.venv/bin/uvicorn app.main:app --port 8000
```

Runs on http://localhost:8000. `GET /api/health` should return `{"status": "ok"}`.
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

# Backend performance micro-benchmarks
backend/.venv/bin/python benchmarks/backend.py
backend/.venv/bin/python benchmarks/live_drawing.py

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
cd ../backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
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

### Reconnection & disconnection

- On disconnect, a player has 30 seconds to reconnect with their private stored secret and keep
  their score and place in the turn order. A successful reconnect replaces the player's active
  socket, so the superseded socket can no longer issue commands.
- If the drawer disconnects and doesn't return in time, their turn is skipped and evicted from
  the rotation.
- If everyone disconnects, the room is cleaned up.

## Key design decisions & limitations

- **Durable persistence with in-memory gameplay**: persistent domain data (users, game history records, official lists, and explicitly saved player prompt lists) is stored via SQLAlchemy with zero-config embedded SQLite by default and optional PostgreSQL support. Real-time game state (rooms, active games, strokes, timers, and prompt-list share capabilities) remains purely in memory for minimal latency.
- **Single process**: no horizontal scaling story; one uvicorn worker holds all rooms. Fine for
  small deployments, not for internet-scale traffic.
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
