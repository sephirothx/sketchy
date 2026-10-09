# Database

Every table Sketchy persists, what lives in it, and the flows that write and read it.

Companion documents: [`architecture.md`](architecture.md) ·
[`wire-protocol.md`](wire-protocol.md) · [`requirements.md`](requirements.md) ·
[`../GLOSSARY.md`](../GLOSSARY.md)

Schema source of truth: [`backend/app/db/models.py`](../backend/app/db/models.py).
Migrations: [`backend/alembic/versions/`](../backend/alembic/versions/) — a baseline
revision, `f0a1b2c3d4e5_baseline_schema.py`, since the pre-launch chain was folded
into it (#557, §13), and the revisions written since. Current head:
`f8a9b0c1d2e5_account_inbox.py` (#1436). Both this line and the table
count below are pinned by `tests/test_doc_invariants.py`, because both had gone stale
by ten tables and eighteen revisions before anybody noticed (#893).

To regenerate an authoritative dump of this schema:

```bash
cd backend && .venv/bin/python -c "from app.db.models import Base; [print(t) for t in Base.metadata.tables]"
```

---

## 1. Engines and conventions

| Concern | Rule | Source |
| --- | --- | --- |
| Default engine | Embedded SQLite at `./sketchy.db`, zero configuration — **development and test only** | [`db/__init__.py:41`](../backend/app/db/__init__.py) |
| Alternative | PostgreSQL via `DATABASE_URL` (`postgresql+asyncpg://…`) | [`db/__init__.py:111`](../backend/app/db/__init__.py) |
| Production | With `SKETCHY_ENV=production`, startup **refuses** a missing, blank, or SQLite `DATABASE_URL`. The zero-config default is a *relative* file, so a production deploy that forgot the variable would look healthy while writing accounts, moderation evidence, and history to storage the next container replacement discards. SQLite also serializes every writer, which caps such a server at one write at a time | [`deployment.py`](../backend/app/deployment.py) |
| Indexes | **No standalone index on the leading column of a composite** on the same table — the composite already serves every lookup and scan on its own prefix. A single-column index that is *unique or partial* is exempt: it enforces an invariant rather than accelerating a lookup. Asserted by `test_no_index_duplicates_the_leading_column_of_a_composite` | [`db/models.py`](../backend/app/db/models.py) · [`tests/test_db_models.py`](../backend/tests/test_db_models.py) |
| Lifecycle invariants | **A row shape no writer produces is refused by the row** (#553): a registered account has credentials and only it does; a curated offer names its version and nothing else does; a prompt is picked at most as often as offered and guessed by at most everyone who faced it; a reviewed report carries when; a friendship is answered iff not pending; an export that is ready has its document, failed its code, both a completion time, anything past pending a start time; a stored drawing says when it was stored and holds exactly its declared bytes, an erased one when it was erased and no bytes or object key, and a drawing belongs to a turn of its own game (`fk_turn_drawings_turn_same_game`); a failed mail says why; public visibility is the official catalogue's; a session expires after it was created; an avatar has positive dimensions within the upload ceiling; a revocation has an actor and a reason only when it happened. The checks complement the transaction ordering of #606–#609; they do not replace it. Proven positive and negative on both engines in `tests/test_lifecycle_constraints.py` | [`db/models.py`](../backend/app/db/models.py) |
| Foreign-key indexes | **Every foreign key a delete walks has an index leading with its column(s)**, or a documented exemption: `ON DELETE CASCADE`, `SET NULL` and `RESTRICT` all make PostgreSQL find the referencing rows when the referenced row goes, and without such an index that is a scan of the whole child table per deleted parent (#551). A composite FK counts as covered when one of its columns references a key on its own (a globally unique id) and the child has an index leading with that column. Nullable actor references (`moderated_by_user_id`, `issued_by_user_id`, `revoked_by_user_id`) carry a **partial** index over the rows where they are set — one entry per action taken rather than one per row. Asserted by `test_every_foreign_key_a_delete_walks_has_an_index_or_a_documented_reason`; the exemptions live beside it — the two there now (`turn_records (game_id, drawer_participant_id)` and `score_events (game_id, turn_id)`, #890) reference a seat and a turn that are only ever deleted with their whole game, which history never is (R-PRIV-05); an operator deleting one game by hand walks that game's rows through the `game_id`-leading key | [`db/models.py`](../backend/app/db/models.py) · [`tests/test_db_models.py`](../backend/tests/test_db_models.py) |
| Read indexes | **Every non-unique index is read by something** (#890): it leads with a foreign key's column, which a delete walks, or with a column some statement in `backend/app` names. An index nothing reads is a write on every insert and update for no return, and on a table updated in place it stops the update from being heap-only — an update that changes an indexed column writes a new entry into *every* index of the table. #890 removed seven: `auth_sessions.idle_expires_at` (moved on every session touch), `room_messages (game_id, turn_id, created_at)` (the largest index on the table with the most rows), the friendship acceptance partial index, `planned_shutdown_abandonments.room_instance_id`, `turn_drawing_reactions.game_id`, and the two foreign-key indexes exempted in the row above. Asserted by `test_every_index_is_read_by_something`, with `UNREAD_INDEX_ALLOWED` for a reader the static search cannot see; `idx_scan = 0` in the monthly review (§13) is the live check | [`tests/test_db_models.py`](../backend/tests/test_db_models.py) |
| Page fill (PostgreSQL) | **`fillfactor = 85` on tables updated in place far more often than inserted** — `auth_sessions`, `auth_rate_limit_buckets`, `auth_login_lockouts`, `user_stats_daily` (#890; `runtime_stats_daily` had it too until #965 removed the table). At the default 100 an update finds its page full and has to put the new version on another page, which makes it non-heap-only even when no indexed column changed. Declared as `UPDATED_IN_PLACE` table info, set by revision `a1c2e3f4b5d6`, and held together by the migration chain test, because Alembic compares neither. Measured on 20,000 sessions, three rounds touching 12.5% each: 910 → 315 B of WAL per touch, 0 → 99.99% heap-only, and the table no longer grows under touches (`benchmarks/index_write_cost.py`) | [`db/models.py`](../backend/app/db/models.py) (`UPDATED_IN_PLACE`) |
| JSON columns | `jsonb` on PostgreSQL (parsed form, comparable, GIN-indexable), text on SQLite. A Python `None` stores as SQL `NULL`, never the JSON token `null` | [`db/models.py`](../backend/app/db/models.py) (`PortableJSON`) |
| SQLite pragmas | `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000` on **every** connection, test fixtures included | [`db/__init__.py:100`](../backend/app/db/__init__.py), [`tests/dbfixtures.py`](../backend/tests/dbfixtures.py) |
| SQLite migrations | Run automatically on startup | [`db/__init__.py`](../backend/app/db/__init__.py) |
| PostgreSQL migrations | An **explicit deploy step**, protected by an advisory lock (`POSTGRES_MIGRATION_LOCK_ID`). Startup only *verifies* the revision and fails with a direct instruction if the step was missed | [`db/migrate.py`](../backend/app/db/migrate.py) |
| Pool (PostgreSQL) | 5 persistent + 5 overflow, 10 s timeout, 30 min recycle; a connection is checked for a closed socket on every checkout and pinged only after 30 s unused, `DB_POOL_PING_IDLE_SECONDS` (#973: `pool_pre_ping`'s ping was three round trips before every session). The trade is stated where it bites: a connection that died without closing its socket less than that long after its last use fails the next caller's first statement once. What the narrowing changes is the **ping's** own verdict — a connection that fails it is replaced on its own, where `pool_pre_ping` raised `InvalidatePoolError` and recycled every pooled connection. A disconnect that surfaces in the middle of a statement is a different path and is untouched by this: SQLAlchemy's `_handle_dbapi_exception` calls `Pool._invalidate`, which stamps the pool so that **every connection opened before it is recycled at its next checkout** — stock behaviour, the same before and after #973. `DB_POOL_PING_IDLE_SECONDS=0` pings every checkout again, which is the old guarantee at the old price; single-statement hot reads run under `AUTOCOMMIT` (`read_session`), one round trip instead of three; all five tunable | [`db/__init__.py:43`](../backend/app/db/__init__.py) |
| Roles (PostgreSQL) | The web process connects as `sketchy_app`, which may read and write rows and only append to `audit_events` and `score_events`; the schema belongs to `sketchy_owner`, used only by the migration command, which grants the application its privileges. Production refuses an owner connection (#896, R-PLAT-22; §13 *Roles*) | [`db/roles.py`](../backend/app/db/roles.py) |
| Session budgets (PostgreSQL) | Every connection carries its role's `application_name` and server-enforced `statement_timeout` / `lock_timeout` / `idle_in_transaction_session_timeout`, sent by asyncpg at connect so a recycled or re-established connection carries them too: **web** 30 s / 5 s / 60 s, **migration** 600 s / 5 s / 60 s (the lock budget covers the deploy advisory lock), **maintenance** 600 s / 5 s / 120 s for every operator command. Validated from the environment at startup beside the pool settings; SQLite is untouched. They bound one statement, one lock wait and one idle transaction — not a whole sweep, which has budgets of its own (§10) (#555) | [`db/__init__.py`](../backend/app/db/__init__.py) (`POSTGRES_ROLE_BUDGETS`) |

### Identifiers

Persisted entity IDs are **time-ordered UUIDv7** from the standard library's
`uuid.uuid7()`, generated through the single wrapper in
[`backend/app/identifiers.py`](../backend/app/identifiers.py). It keeps a 42-bit counter
inside each millisecond, so a burst of IDs stays ordered without stamping any of them
into the future.

- Stored as native 16-byte `uuid` on PostgreSQL, dialect-compatible `CHAR(32)` on SQLite.
- API and Socket.IO boundaries always expose canonical UUID strings.
- UUID order improves index locality, but `created_at` and friends remain the
  **authoritative event time**.
- **They are never capabilities.** Consecutive IDs within one millisecond are guessable
  from each other by design, so session tokens, room codes, and invitation tokens
  stay independently random and are never derived from an entity ID.

### Timestamps

Every persisted timestamp uses `UTCDateTime`
([`backend/app/db/types.py`](../backend/app/db/types.py)): aware inputs are required and
raise on a naive value, and reads are normalized to aware UTC. SQLite and PostgreSQL
therefore behave identically and application code never infers a local timezone.

Write timestamps are `NOT NULL` everywhere: the schema was tightened before the
first deployment, so no row predates timestamp coverage.

### Enum discipline

Stored scoring modes, hint modes, turn outcomes, prompt languages, catalogue locales,
and every other closed set are **string enums backed by portable `CHECK` constraints**,
declared once in [`backend/app/domain_values.py`](../backend/app/domain_values.py).
Extending a set requires one coordinated code, migration, wire-contract, README, and
glossary review.

### Migration safety

Migrations run with SQLite foreign keys **off** and finish with a
`PRAGMA foreign_key_check`. Batch mode rebuilds a table by copy/drop/rename, and with
enforcement on, `DROP TABLE` performs an implicit delete that fires `ON DELETE CASCADE`
— altering a table others point at would silently empty them and hand back a table that
still looks correct. Suspending enforcement stops that; checking at the end is what
keeps the suspension honest.

---

## 2. Table map

64 tables in eight domains.

```mermaid
erDiagram
    users ||--o{ auth_sessions : "has devices"
    users ||--o| user_second_factors : "proves with"
    users ||--o{ user_recovery_codes : "falls back on"
    users ||--o{ identity_aliases : "merges guests"
    users ||--o{ user_blocks : "blocks"
    users ||--o{ friendships : "befriends"
    users ||--o| user_settings : "prefers"
    users ||--o{ user_stats_daily : "projects to"
    users ||--o{ prompt_lists : "owns"
    users ||--o{ prompt_list_stars : "stars"
    users ||--o{ room_presets : "owns"
    users ||--o{ user_bans : "suspended by"
    users ||--o{ user_warnings : "warned by"
    users ||--o{ inbox_entries : "told"
    users ||--o{ turn_drawing_shares : "shares"

    game_records ||--o{ game_participants : "seats"
    game_records ||--o{ turn_records : "turns"
    game_records ||--o{ game_prompt_sources : "source lists"
    game_records ||--o{ score_events : "ledger"
    turn_records ||--o| turn_drawings : "drawing"
    turn_records ||--o{ turn_participant_outcomes : "per seat"
    turn_records ||--o{ turn_prompt_offers : "options"
    game_participants ||--o{ turn_participant_outcomes : "seat"
    turn_records ||--o{ turn_drawing_reactions : "reactions"
    game_participants ||--o{ turn_drawing_reactions : "reactor seat"
    users ||--o{ profile_drawing_pins : "shelf"
    turn_records ||--o{ profile_drawing_pins : "pinned"
    turn_records ||--o{ turn_drawing_shares : "shared"
    game_participants ||--o{ turn_drawing_shares : "sharer seat"

    prompt_concepts ||--o{ prompt_versions : "wordings"
    prompt_concepts ||--o{ prompt_aliases : "accepted answers"
    prompt_versions ||--o{ prompt_version_aliases : "accepts"
    prompt_lists ||--o{ prompt_list_stars : "starred by"
    prompt_lists ||--o{ prompt_list_tags : "tagged"
    prompt_lists ||--o{ prompt_list_editions : "published as"
    prompt_list_editions ||--o{ prompt_list_edition_items : "membership"
    prompt_list_editions ||--o{ prompt_list_edition_tags : "tagged"
    prompt_lists ||--o{ prompt_usage_facts : "usage"
    prompt_lists ||--o{ prompts : "display rows"

    player_reports ||--o{ player_report_message_evidence : "pins"
    player_reports ||--o| player_report_drawing_evidence : "canvas"
    player_reports ||--o{ user_bans : "sources"
    player_reports ||--o{ user_warnings : "sources"
    room_messages ||--o{ player_report_message_evidence : "copied from"
```

| Domain | Tables |
| --- | --- |
| **Server & rooms** | `app_config`, `room_code_reservations`, `room_presets`, `planned_shutdown_abandonments` |
| **Accounts** | `users`, `auth_sessions`, `auth_tokens`, `auth_rate_limit_buckets`, `auth_login_lockouts`, `user_second_factors`, `user_recovery_codes`, `friendships`, `identity_aliases`, `user_settings`, `user_stats_daily`, `data_exports`, `external_identities`, `uploaded_avatar_assets`, `email_outbox`, `user_passkeys`, `webauthn_challenges`, `inbox_entries` |
| **Moderation** | `audit_events`, `player_reports`, `player_report_message_evidence`, `player_report_drawing_evidence`, `prompt_content_reports`, `prompt_takedowns`, `user_bans`, `user_warnings`, `user_blocks` |
| **Messages** | `room_messages` |
| **Game history** | `finished_game_envelopes`, `game_records`, `game_participants`, `turn_records`, `turn_drawings`, `turn_drawing_reactions`, `turn_drawing_shares`, `gallery_shelf_reviews`, `profile_drawing_pins`, `turn_participant_outcomes`, `score_events`, `game_prompt_sources` |
| **Prompt provenance** | `turn_prompt_offers`, `turn_prompt_offer_sources` |
| **Prompt content** | `prompt_concepts`, `prompt_versions`, `prompt_aliases`, `prompt_version_aliases`, `prompt_tags`, `prompt_version_tags`, `prompt_lists`, `prompt_list_tags`, `prompt_list_editions`, `prompt_list_edition_items`, `prompt_list_edition_tags`, `prompt_list_localizations`, `prompt_list_stars`, `prompts`, `prompt_usage_facts`, `prompt_usage_batches` |
| **Runtime analytics** | `runtime_events` |
| **Bug reports** | `bug_reports` |

---

## 3. Server and rooms

### `app_config`
Key/value storage for server configuration and auto-generated secrets (notably the
`IP_HASH_SECRET` fallback).

`key` VARCHAR(64) PK · `value` TEXT · `created_at` · `updated_at`.

Keys are namespaced by what writes them:

| Prefix | Written by | Meaning |
| --- | --- | --- |
| `ip_hash_secret` | [`auth/rate_limit.py`](../backend/app/auth/rate_limit.py) | The generated HMAC key, when `IP_HASH_SECRET` is unset |
| `tunable.` | [`api/admin_settings.py`](../backend/app/api/admin_settings.py) | One runtime tunable an administrator has changed |

**Absent means "whatever the default or the environment says."** A write only creates a
row when the value differs from what the process booted at, and setting a value back to
its boot value deletes the row rather than storing it, because a row saying "the default"
would pin the setting against a later change to the environment variable that supplies it.

The converse does **not** hold: a row can exist while its value equals the current boot
value, because the environment can change to match an override stored earlier. So
"a row exists" and "the value differs from boot" are tracked as separate facts. Inferring
the first from the second hid such a row instead of removing it — the panel reported the
setting as environment-sourced and offered no way to clear it, and the forgotten row won
again the next time the environment moved. The panel therefore reports a setting with a
row as `stored` whatever its value, and a reset deletes the row even when no number
changes.

A row whose value the running release refuses is kept and reported, not applied and not
forgotten — otherwise it is an override nothing can reach and everything ignores, until a
release widens the bound and it comes back. Reading them is a single prefix query at startup; writing one shares a transaction with
the `audit_events` row that records who changed it, including when only the row changed.

### `room_code_reservations`
The global claim on a six-character invite code. The reservation primary key makes
allocation race-safe even though v1 runs one worker.

| Column | Notes |
| --- | --- |
| `code` VARCHAR(6) **PK** | Uppercase alphanumeric, cryptographically random ([`services/room_codes.py`](../backend/app/services/room_codes.py)) |
| `kind` | `ephemeral \| persistent` — only `ephemeral` is written now; `persistent` rows are tombstones from the removed feature |
| `created_at` | |
| `retired_until` | Post-room cooling-off; indexed |

Constraints: `ck_room_code_kind`; `ck_persistent_room_code_never_retires` — a
`persistent` code must have a null `retired_until`.

**Flow.** A code is reserved *before* it is shown to a player. When an ephemeral room
empties, its code is retired for **30 days** (`EPHEMERAL_CODE_RETENTION`), so a stale
invite during that window says the room ended rather than silently joining an unrelated
group. Startup retires reservations orphaned by a restart or crash. Expired ephemeral
reservations may be reused. `persistent` rows are permanent tombstones left by the
removed persistent-room feature: they are never reused, and an invite carrying one is
told the room has ended.

### `room_presets`
A private, named, versioned copy of typed settings for a future *ordinary* room. Same
columns and `CHECK` set as a room's typed settings, with no code, plus `name_key` with
`uq_room_presets_owner_name (owner_user_id, name_key)`. `ON DELETE CASCADE` from
`users`. `name_key` is the case-folded name, bounded to its 64 characters *after* folding
(`ß` folds to "ss"), since a longer one was a 500 on PostgreSQL (#1017).

A preset has **no room code, members, host identity, game, scores, timers, chat, or
canvas.** Applying one fills the create form but does not enable *Keep this room for
future games*. Quick custom prompts are never stored; they must be saved as an owned
list first. ≤ 20 per account.

`prompt_language` is the language the room will declare (R-PROMPT-02): one of the room
languages or `mul` for a mixed-language room (R-PROMPT-13, #1182),
`CHECK ck_room_presets_prompt_language`, `en` by default. It used to be read
back from the saved lists, and a preset of lists in no language (R-PROMPT-12) has none to
read, so since #821 it is stored. The two still cannot drift apart: saving a preset whose
lists are not in the declared language (or in none; for a mixed preset, not playable by a mixed room) is refused rather than stored, and
reading one pins its lists against that language the way a room does, so a disagreement
makes the preset visibly unavailable.

### `planned_shutdown_abandonments`
The privacy-safe fact that a planned drain expired with a game still live.

`id` · `game_id` (unique) · `room_instance_id` · `contract_version` (`= 1`) ·
`reason` (`drain_timeout`) · `phase` · `round_number` · `completed_turn_count` ·
`seated_player_count` · `connected_player_count` · `spectator_count` ·
`canvas_action_count` · `game_started_at` · `observed_at`.

**It never stores room codes, room or player names, prompts, chat, or canvas contents.**
Retained 90 days, purged at startup. A hard crash cannot run this hook — failed
finished-history writes and crash-safe retry are a separate concern.

---

## 4. Accounts

### `users`
One row per player identity, guest or registered.

**What one page load costs** (#556): `GET /api/auth/me` sends two statements in the steady state — the session (with its suspension check) and the account, whose canonical id is resolved inside the same query through a `coalesce` over the alias table — and a third, one conditional `UPDATE … RETURNING`, only when the login touch is due; the route decides that from the row it already read, and the update repeats the check so two page loads landing together write once. Writers of `users` never `refresh`: the mapper fetches server-generated defaults in the statement's own `RETURNING` (`eager_defaults`). Before #556 the same request sent five selects. A registered account's answer carries its settings (#983), one more primary-key read of `user_settings`: the page used to fetch them in a request of its own before it could paint, which cost a session lookup and two selects. `tests/test_me_query_shape.py` pins the counts.

| Column | Notes |
| --- | --- |
| `id` | UUIDv7 |
| `username` VARCHAR(32) | Null for guests; case-insensitively unique via `ix_users_username_lower` |
| `password_hash` VARCHAR(255) | Argon2id encoded hash, carrying its own algorithm and cost parameters |
| `display_name` VARCHAR(32) | |
| `name_color`, `avatar_key` | `avatar_key` is the content address of the uploaded picture (`<sha256>.webp`, `.png` or `.jpg`, R-AVA-03), `doodle:<name>` for one of the deployment's own doodles (nothing else is stored for one; a claim assigns a random one, R-AVA-09), or null for the initial |
| `avatar_upload_blocked_until` | Set when a moderator removed the picture: no upload until then (R-AVA-04) |
| `state` | `anonymous \| registered \| merged \| deleted` |
| `role` | `user \| moderator \| admin` |
| `pending_role`, `pending_role_at` | Nullable pair, both or neither (`ck_users_pending_role_dated`), the role checked against `moderator` alone (`ck_users_pending_role`) — narrower than the grantable roles in both directions, since `user` is not a staff role to be left waiting for and `admin` is not granted over the network at all. A staff role that has been **offered** and is waiting on this account's second factor (R-AUTH-20). Not a role: nothing authorizes anything from it, and the account is an ordinary player until enrolment moves the value into `role`. `pending_role_at` is what the offer lapses against — thirty days, checked where it is used rather than swept |
| `email`, `email_verified_at` | Nullable; normalized by trim + lowercase, enforced by `ck_users_email_normalized`; case-insensitively unique via `ix_users_email_lower` |
| `created_at`, `updated_at`, `last_login_at`, `last_active_at` | |
| `last_seen_at` | Nullable. Stamped when the account's last socket closes and when its first one opens (so a process that dies with the player online still leaves a time). What a profile shows as *last seen* (#469). Not `last_login_at` (a page load) and not `last_active_at` (retention); the three mean different things on purpose |

`ck_users_verified_email_present` forbids a verification timestamp with no address.

Notable design points:

- **The legacy guest boolean is gone.** "Is a guest" is derived from `state`, so it
  cannot drift.
- **An address is recorded only once confirmed.** Until then it lives in the
  confirmation token and nowhere else, so a typo cannot hand the account to whoever owns
  the typed address, and nobody can reserve a mailbox they do not control.
- **Argon2 cost upgrades are lazy.** Every successful login compares the encoded hash to
  the current cost parameters and replaces stale hashes atomically. No bulk migration,
  and no redundant schema-version column.
- `last_active_at` changes **only** when a player takes or reconnects to a non-spectator
  room seat and when a game is persisted — deliberately not on page load, login, or an
  ordinary profile write, because it drives retention. The game-persist stamp rides that
  write; the seat's is one `UPDATE`, on a task of its own that the join does not wait
  for (#980): nothing about the seat depends on it, so it may reach the database before
  or after the acknowledgement, but never in front of it. A stamp that fails is logged and dropped, so `last_active_at` keeps
  its previous value until the account's next seat or its next persisted game, whichever
  comes first — which for a player who seldom plays can be weeks, bringing the retention
  sweep that much closer.

### `auth_sessions`
One revocable signed-in device.

`id` · `user_id` (CASCADE) · `token_hash` VARCHAR(64) **unique** · `device_label` ·
`last_device_label` · `rotated_from_id` (self-FK, unique, `SET NULL`) · `ip_hash` · `last_ip_hash` ·
`anomaly_at` · `anomaly_count` · `anomaly_audited_at` · `stepped_up_at` · `created_at` · `last_used_at` ·
`expires_at` · `revoked_at`, with `ck_auth_sessions_anomaly_count` and
`ck_auth_sessions_anomaly_pair` (a session that never looked wrong has no time at
which it did).

Expired rows are purged 30 days past `expires_at`, at startup and hourly. The
condition is **expiry, not revocation**: a revoked but unexpired row still keeps a
ban-time token recognisable rather than looking like a new cookieless guest, and
rotation leaves a revoked predecessor behind deliberately. Sessions of an account
under an **active suspension are never purged** — it cannot sign in to make another,
so that row is its only route to the export and deletion R-BAN-04 keeps available.

Cookies carry opaque 256-bit random tokens; **only SHA-256 hashes are stored**, so the
database never contains a credential that can be replayed. Socket.IO handshakes resolve
the same record as HTTP requests, so revocation applies on the next connection without a
shared signing secret.

**Both lifetimes are columns** (R-AUTH-03, #468): `expires_at` (365 days for a player,
7 for staff) and `idle_expires_at` (90 days, 24 hours for staff), the latter moving
forward with `last_used_at` by the whole window the lifetime allows, which was already maintained and throttled to one write
per five minutes. `idle_expires_at` is deliberately **not indexed** (#890): nothing
filters by it first, and because it moves on every touch an index on it made every
touch a non-heap-only update through all six indexes of the table. `ck_auth_sessions_idle_within_expiry` keeps silence able to end a
session early but never late. The span between `created_at` and `expires_at` is also
what says *which* rule the row lives under — seven days for staff, a year for a player
— and so what its rotation cadence is; nothing on the read path asks the account.

Deriving either from the account's role instead would mean joining `users` on the
single hottest read this server has — once per HTTP request and once per socket
handshake — to learn something that cannot have changed: a **role change revokes every
session the account holds** (R-AUTH-20), so a live session is always one issued under
the role its owner has now. That revocation is also why a staff role cannot be granted
to an account with no second factor: it would sign them out of the page they would
enrol from.

`ip_hash` is the address the session was **issued** to and `last_ip_hash` the one it was
last used from, both HMAC-SHA-256 under the same `IP_HASH_SECRET` the rate limiter uses
— raw addresses are never stored, so these answer "same network?" without knowing which
network. The address hashed is R-RATE-02's key, so an IPv6 address counts as its /64 and a
privacy address rotating inside it is not a different network. `anomaly_at`/`anomaly_count` record a session used from a browser other than
the one it was last seen from, or for staff from a different address. Every switch updates the row; the `session.anomaly` ledger entry is written at most once per five minutes per session, with `anomaly_count` in its `details` — the five minutes measured from the last entry written (`anomaly_audited_at`), not the last switch, which every switch moves, and claimed by one conditional `UPDATE` so two requests in flight cannot both write (#1299 review), so a client flipping between two browsers writes one permanent row an interval rather than one per request (#1242). `device_label` is
the browser the session was issued to; `last_device_label` the one it was last used from
(NULL until the session is first seen from another browser), and the comparison is against it, so a label
that changed for good is one anomaly rather than one per request (#1016); a player's address change is
deliberately *not* an anomaly, because a phone crossing between mobile data and wi-fi
does it several times an hour. An anomaly clears `stepped_up_at`, which is otherwise the
last time this device proved its second factor (R-AUTH-21) — held here rather than in
memory so revoking the device revokes its step-up with it.

`rotated_from_id` is what makes theft **detectable** (R-AUTH-22): rotation revokes the
predecessor and points the successor at it, so a predecessor presented after its
successor exists is a second copy rather than an unknown cookie. Every session descended
from it is revoked and a `session.token_replayed` audit event is written. A 60-second
grace lets a just-rotated predecessor still resolve, because a browser with requests in
flight can lose that race, and signing somebody out for using their browser normally is
not a security outcome — and only while the successor is unrevoked, so a sign-out or
password change inside the window ends the predecessor with it; a sign-out sent with
the predecessor revokes forward along `rotated_from_id` (#1075).

### `auth_tokens`
One-shot credentials for flows that leave the app and come back.

`token_hash` **PK** · `purpose` (`password_reset \| email_verify`) · `user_id`
(CASCADE) · `email` · `expires_at` · `consumed_at` · `requested_ip_hash` ·
`created_at`. `ck_auth_tokens_verify_address` requires an address on an
`email_verify` token.

A reset link is **checked when the page opens, not when the form is sent**, so nobody
chooses a password only to be told the link was spent. Checking deliberately does not
consume it, and is throttled separately from requesting a reset because it costs a
lookup rather than somebody else's inbox.

Spending a token is one conditional `DELETE … RETURNING` on `token_hash` and
`purpose` ([`auth/tokens.py`](../backend/app/auth/tokens.py) `consume_token`), so the
database decides who gets it: two submissions of one link in two transactions both
find the row, but only the first delete returns it, and the second, having waited on
the row lock, deletes nothing. A select followed by an ORM delete told both callers
yes (#607). An expired token presented is deleted on the way out and still refused;
a token presented under the wrong purpose is neither.

The reset, the signed-in change, and the operator reset all commit the new password,
the revocation of every live `auth_sessions` row, the audit event, and the queued
mail in **one transaction**, with the account row locked (`FOR UPDATE`) so a reset
and a change racing for one account apply in turn. A crash between the password and
the revocation therefore leaves both undone and the link unspent, never a new
password with every old device still signed in (R-AUTH-10, R-AUTH-17).

### `auth_rate_limit_buckets`
`scope` + `key_hash` composite **PK** · `attempt_count` · `window_started_at` ·
`window_expires_at` · `updated_at`.

`key_hash` is an HMAC-SHA-256 digest under `IP_HASH_SECRET` (or an auto-generated
`app_config` secret) of whatever the scope counts — **raw IP addresses are never
stored.** Most scopes count a client address (keyed as R-RATE-02 says). A per-account
scope hashes the **account** instead — `room_create`, the prompt-list and audited-route
budgets, `report-account`, `password_reset_account` and `_day`, `email_verify_account`
— because that is the key a caller cannot change by moving address; and
`email_verify_recipient` hashes the **normalized address being verified**, so one inbox
has one bucket whoever asks for it (#1240). Buckets
are shared, so limits survive restarts and apply once across every replica. Expired
buckets are cleaned in bounded batches. Rotating the secret starts fresh buckets without
exposing or re-identifying old keys.

### `auth_login_lockouts`
`key_hash` **PK** · `consecutive_failures` · `locked_until` · `updated_at`, with
`ck_auth_login_lockouts_failures`, `ix_auth_login_lockouts_locked_until` (the operator
view's count of accounts held back now) and `ix_auth_login_lockouts_updated_at`
(`updated_at, key_hash`: the sweep's walk, oldest first).

Separate from `auth_rate_limit_buckets` because it is a different shape (R-RATE-12,
#468). A bucket is a count inside a fixed window that forgets everything when the window
rolls, which is what a rate limit should do; a lockout has to remember **across**
windows, since the point of backing off is that the tenth failure costs more than the
second, and it is cleared by a success rather than by time. Rows untouched for a day are
dropped by the hourly retention sweep (§10), so a finished attack does not follow an
account for a week. That sweep matters more than the sentence suggests: a failure is
counted for usernames that do not exist - deliberately, so the answer does not reveal
which do (R-AUTH-09) - so every distinct name anybody tries leaves a row, and until #891
nothing removed them. The table is now bounded by one day of attempts, which the login
throttle bounds in turn.

`key_hash` is an HMAC of the **lowercased username**, never the username: this table
would otherwise be a list of which accounts exist and which are under attack, readable
by anything that can read the database.

### `user_second_factors`
`user_id` **PK** (CASCADE) · `secret` · `confirmed_at` · `password_proved_at` ·
`created_at` · `last_step` · `failed_attempts` · `locked_until`, with `ck_user_second_factors_failed_attempts` and
`ck_user_second_factors_last_step`.

`password_proved_at` records that somebody proved both the account's password and a
code from this very factor. Setting one up deliberately asks for neither the password
nor anything else — it is optional, and it does not gate a player's sign-in — so the
column is what a **staff role** requires instead: promotion checks that the factor is
the owner's rather than merely that a row exists, which is the difference between a
second factor and one somebody planted with a stolen cookie. Both proofs are needed
because they answer different halves of that question: the password says the account's
owner is asking, the code says the authenticator enrolled is the one they hold. It is
written by enrolment when a password came with it (the code is proved in that same
request) or by `POST /api/auth/second-factor/confirm-owner` afterwards, and it is never
backfilled — a null here means unproved, which fails closed.

One row per account, written **only once enrolment is confirmed** by a code the account
actually produced (R-AUTH-20): an unconfirmed secret lives in the enrolment response and
nowhere else, so a secret generated and then abandoned never becomes a credential and
can lock nobody out.

The secret is stored as it must be. TOTP is symmetric — the server has to hold what the
authenticator holds in order to check a code — and no hashing scheme changes that. This
is the honest cost of choosing TOTP over WebAuthn (N-15), and it is why a database read
is not the only thing between a leak and a staff account: the password is still required
first, and R-AUTH-21's step-up is required again per action.

`last_step` is the 30-second interval whose code was last spent, which is what makes a
code single-use **inside its own step** — a relayed code finds it already gone.
`failed_attempts` and `locked_until` stop a machine grinding six digits behind a password
it already has, which the login throttle in front does not cover. All three are written by
conditional `UPDATE`s that carry the decision — `last_step < :step` to spend a code,
`failed_attempts + 1` to count a miss — never a value read and written back, so two
requests with one code cannot both be accepted and parallel misses add up to the lock
(#1019).

### `user_passkeys`
`credential_id` **PK** · `id` (opaque, unique) · `user_id` (CASCADE, indexed) · `public_key` ·
`sign_count` · `label` · `backed_up` · `created_at` · `last_used_at`, with
`ck_user_passkeys_sign_count`.

The opposite of `user_second_factors` in the way that matters: what is stored is a
**public** key. TOTP is symmetric, so that table holds what the authenticator holds and a
database read hands over a working credential; this one holds a verifier and nothing that
can produce a signature (R-AUTH-23). The credential id is the primary key because that is
what a sign-in arrives holding — the browser names the credential and the account is read
from the row, rather than claimed by the caller. `id` exists so a page can name one for
deletion without putting the credential id in a URL.

Several rows per account on purpose: a laptop and a phone are two, and losing one device
must not be losing the role. `sign_count` is the authenticator's own counter, stored to be
compared — a decrease is the one signal WebAuthn gives that a credential has been cloned,
and authenticators that keep no counter report zero throughout. `backed_up` says whether
the platform syncs a copy, which is what lets the page tell somebody their only passkey
lives on one device.

Deleted with the account rather than by cascade: erasure anonymises the `users` row instead of removing it,
so `ON DELETE CASCADE` never fires and `account_data.py` clears these tables by hand (R-AUTH-23).

There is no `password_proved_at` here, unlike `user_second_factors`: registering a passkey demands
the account's password, so every row is one somebody proved was theirs. A promotion reads it that
way (R-AUTH-20).

### `webauthn_challenges`
`challenge` **PK** · `purpose` (`register`/`authenticate`, checked) · `user_id` (CASCADE,
indexed, nullable) · `created_at` · `expires_at`, with
`ix_webauthn_challenges_expires_at`.

Both ceremonies rest on a challenge that the server chose and that can be spent once: one
the client could pick is a signature an attacker could have collected in advance, and one
that outlives its use is a signature they could replay. So it is stored rather than carried
in the page, deleted as it is read, and lives five minutes. `purpose` keeps the ceremonies
apart — a challenge minted to add a credential must not be spendable as a sign-in.
`user_id` is null for a sign-in, which is asked for before anybody has said who they are.

Nothing sweeps this table on a timer: each new ceremony deletes what has expired, which
bounds it by how many are in flight rather than by how many were ever started.

### `user_recovery_codes`
`id` **PK** · `user_id` (CASCADE) · `code_hash` · `created_at` · `used_at`, with
`uq_user_recovery_codes_code` and `ix_user_recovery_codes_user`.

Ten single-use codes issued at enrolment, shown exactly once, hashed with SHA-256 for the
same reason session tokens are (R-AUTH-02): these are high-entropy values this server
generated, so a slow hash buys nothing, and the database must not contain a replayable
credential. **Spent rather than deleted**, so somebody can be told how many they have
left without the count being a guess. Re-enrolling deletes every code issued against the
old secret — a recovery code that still opened an account after its authenticator had
been replaced would be the hole this closes.

### `friendships`
`user_low_id` + `user_high_id` composite **PK** (both CASCADE) ·
`requested_by_id` (CASCADE, NOT NULL) · `status` ∈
`pending | accepted | declined` · `created_at` · `responded_at`, with
`ck_friendships_ordered` (`user_low_id < user_high_id`) and
`ck_friendships_requester_is_a_member`.

What either account is told about the pair is not kept here: a request is an entry in
the asked account's inbox and an acceptance one in the asker's, written in the same
transaction as the row (`inbox_entries` below, R-FRIEND-14). The row had carried
`acceptance_announced_at` for the second until #1436, which the inbox replaced.

**One row per pair, in a canonical order** rather than one row per direction.
Two directional rows can disagree — one accepted, one not — and no constraint
could forbid it; here the pair is the identity, the way it is for
`user_blocks`. The ordering also settles the case #529 was really asking
about: a crossing request, where A asks B while B has already asked A,
collides on the primary key instead of creating a second row, so the handler
sees a request from the other party and accepts it. `x < x` being false
forbids a self-friendship for free.

**The ceilings are counted under both accounts' row locks** (#898). The friends,
pending-sent and pending-received limits are each a count followed by a write, and
nothing about the rows counted stops a second request from counting the same rows a
moment later. So a request and an accept first take `FOR UPDATE` on both `users` rows
in one ascending statement (`lock_pair_for_ceilings`) — the order the erasure barrier
uses, so no cycle is possible with a game write, a merge or a deletion — and only
then read the pair and count. `tests/test_account_ceilings.py` holds a writer after
its count and proves the second one waits.

Canonicalisation lives in exactly one place,
[`services/friends.py`](../backend/app/services/friends.py)`.friendship_key`;
a site that inlines it and gets it backwards writes a row the CHECK rejects,
which is the failure worth having. PostgreSQL compares `uuid` as sixteen bytes
while SQLite compares the hex string, and this table rests on those orders
agreeing — `tests/test_db_models.py` runs against both engines in CI for that
reason.

Registered accounts only. A guest is purged after 30 inactive days, so a
friendship with one would outlive the account and disappear unexplained.

A **declined** row is kept rather than deleted, so a refusal cannot simply be
re-sent into; the person who declined may still ask in their own right later,
which rewrites it. Cancelling or unfriending deletes instead — neither is a
refusal. The tombstone durably records that one account asked and the other
refused: it is in both parties' data export and goes with either account's
deletion.

Blocking deletes any row for the pair **in the same transaction as the block**
([`api/user_blocks.py`](../backend/app/api/user_blocks.py)): a surviving
friendship is a room-join capability the blocker has just tried to revoke.
Deleted rather than tombstoned, so unblocking does not silently restore it.

---

### `identity_aliases`
`source_user_id` **PK** (FK RESTRICT) · `target_user_id` (FK RESTRICT) ·
`created_at`, with `ck_identity_alias_distinct` — the merged guest is the row's
identity, so the column that was unique anyway is the key.

The immutable mapping from a merged guest identity to its account. **Chains are a
load-bearing application invariant**: a merge target is never itself a source, so
resolution never depends on traversal order — the schema cannot express this without a
trigger, so the merge path enforces it. Historical
participant and drawer rows keep their original IDs and presentation, so a game
containing both identities keeps **two factual seats** rather than violating a
uniqueness rule or losing a player. Account history and statistics resolve the account
plus all of its aliases; the guest's sessions are revoked during the merge.

### `user_settings`
Cross-device Player settings for a registered account. `user_id` **PK** (CASCADE) ·
`theme` · `sound_effects` · `confetti_effects` · `sound_effects_volume` (0.0–1.0) ·
`brush_cursor` (`crosshair \| circle`) · `default_brush_size` (one of the slider's stops, `2 \| 4 \| 6 \| 8 \| 12 \| 16 \| 24 \| 32`, 6 by default, R-DRAW-18) · `pen_pressure` (on by default; the client acts on it only for a pressure-sensitive pen, R-DRAW-17) · `time_format` (`system \| 12h \| 24h`) ·
`key_bindings` (JSON) ·
`colorblind_safe_colors` · `prompt_language` (the supported set, `en` by default) ·
`extra_prompt_languages` (JSON list, `[]` by default: the other languages the player
plays in, in their order — never the default, never twice, at most seven; #1209) ·
`locale` (the interface locales, `en` by default) ·
`email_reminder_last_shown_at` · timestamps.

Bounded at both the API and database layers: key bindings must describe the complete
supported action set.

`email_reminder_last_shown_at` is the no-email reminder's clock (R-AUTH-15): the
reminder is due once it is a week old, and closing the reminder resets it. It is
also stamped when the row is seeded at registration — a claimed guest included — so
the first reminder comes a week after signing up rather than on the next page;
`NULL` means an account that has never been told, and is due at once. The seed
writes the browser's values and the stamp together, and a row that already has a
stamp is never re-seeded — which is how a registration that finds a defaults row
made by another tab still carries the browser's settings over (R-SET-03).

**Two languages, and they are not the same one.** `prompt_language` is the language
this player *plays* in by default (R-PROMPT-11) — what the lobby leads with, the seat
a mixed room gives them, and where Quick play opens a room.
`extra_prompt_languages` are the others they play in, ranked: a list on the row
rather than a table of its own, so `/api/auth/me` still reads settings in one
statement (R-PLAT-17). The settings routes check the pair in one write under the
row's lock — only the eight, each once, the default never among them — and promoting
one of them to the default swaps the old default into its place (#1209). Two CHECKs
hold what a JSON column can be held to on both engines, read as its text: a list
(`ck_user_settings_extra_prompt_languages_list`, at most 48 characters, which seven
languages fit), and never naming the default (`ck_user_settings_default_not_extra`).
The second is what stops two devices' PATCHes, each checked against the same row,
from storing the default twice where the lock is not one (SQLite); the loser gets the
same `422` as a PATCH that named it. An account that never chose any has `[]`, which
is exactly the one-language behaviour it had before.

`locale` is the language they *read* in (R-I18N-06): the interface, the
refusals, the room's own announcements. A Dutch speaker playing an English room is
ordinary, and one column could not describe them; it is the same line `prompt_lists`
draws between its content language and its localized catalogue copy.

The registries behind them are separate too, and bound by different things: a prompt
language needs matching semantics before it can exist at all (N-09, R-PROMPT-09),
while an interface locale needs only somebody to have written the words. They hold
the same eight values today and are free to diverge.

Both are stored rather than resolved from the browser every time, because a browser
describes the device, and a player who chose a language on their laptop should not
have to choose it again on their phone. Registration seeds each from whatever the
new account's browser resolved — it sends its settings with the registration — and
they are settings from then on. `Accept-Language` is the server's own fallback, for
the one reader with no browser attached: the mail it sends (R-I18N-08).

`auto_clear_chat_on_guess` and `custom_brush_presets` were removed rather than kept:
the first is now the only behaviour (a guess you got right is not a draft worth
keeping), and nothing in the interface could ever create a brush preset. Both were
synced, bounded and present in the data export, which is what made them worth
deleting rather than leaving (R-SET-07).

**Guests keep these in browser local storage only.** Creating an account copies that
browser's current settings to the account exactly once; logging in later makes the
account copy authoritative on the new device.

### `user_stats_daily`
A **rebuildable, disposable** per-account/per-UTC-day projection of immutable game facts.

`user_id` + `stat_date` composite **PK** · `games_played` · `games_won` ·
`total_score` · `turns_played` · `prompts_guessed` · `drawings_made` ·
`reactions_received` · `updated_at`, with a non-negative `CHECK` that also enforces
`games_won <= games_played`.

**Flow.** A finished-game transaction atomically adds one day's counts for each
canonical account. Same-day saves use database upserts, so concurrent games cannot
overwrite one another and an idempotent retry does not increment twice. Guest-to-account
merges rebuild the target's rows **for the guest's days only** and deduplicate games
shared by its factual identities. Ratios and averages are derived on read, never stored.

**Synchronization.** Every writer of an account's rows locks that account's `users`
row first, in ascending id order: the finished-game write holds every seat's account
`FOR UPDATE` (it also writes `last_active_at`), a merge holds source and target, a
rebuild holds every identity of the accounts it replaces, and a reaction holds the
drawer's identity (the guest and the account it merged into) shared, before the drawing
row. So a game or a reaction that commits while a rebuild runs either committed before
the rebuild read its facts, or waits and increments the rows the rebuild wrote — never
the lost increment a read-then-replace allowed (#609; the reaction writer took no
account lock until a +1 landing between the rebuild's read and its replacement was
reproduced on PostgreSQL). Shared, so reactions to one drawer's drawings do not wait on
each other; before the drawing row, because erasure and the pin write take the account
first too, and one order is what keeps them out of a cycle.
The incremental upsert lists its rows in ascending account id for the same reason: two
games sharing accounts in opposite seat order take the projection rows in one order.

A merge's rebuild is **bounded by the guest's history**, not the account's, because it
runs inside a sign-in: on the `web` role's `statement_timeout` of seconds, where a full
rebuild has the `maintenance` role's minutes. A merge cannot change what the account's
row says for a day the guest has nothing on, so `fold_identity_into_account` reads and
replaces only the days the guest has a finished game or a projection row on — the row as
well as the game, so a row whose facts are gone is not left keyed to a merged identity.
Whole days, never one identity's share of a day, because a day's row counts games and a
game both identities sat in is one game (#709, R-HIST-27). A guest that played on more
than `MERGE_REBUILD_DAY_LIMIT` (92) distinct days is not the case this exists for and
rebuilds the account whole.

A full rebuild is **bounded per batch of accounts**, not per deployment: it walks
canonical accounts by keyset in batches of `REBUILD_BATCH_ACCOUNTS` (100), each batch its
own transaction that locks only its identities, reads facts keyed by those identity ids
(the games they played are a subquery, never a bind list, so an account with more games
than asyncpg can bind still rebuilds) and streams them 1,000 rows at a time. That last
property is asserted as itself, by counting what each statement binds across two
histories of different sizes
([`test_no_statement_of_a_rebuild_widens_with_the_history`](../backend/tests/test_user_stats_projection.py)),
rather than by seeding one history large enough to break a driver. An
interrupted full rebuild leaves every finished batch correct and is simply run again; a
batch that loses to a deadlock or serialization failure is retried whole. On a 40,000-game
account the rebuild's peak allocation went from 63 MiB to 19 MiB (`benchmarks/user_stats.py`).

`reactions_received` is the one counter that keeps moving after a game is written: a
reaction given from the recap or from history adjusts the drawer's row for the **game's**
day by a delta (`adjust_reactions_received`), so a rebuild — which only knows the game —
reproduces the same totals. A decrement is guarded (`WHERE reactions_received >= n`)
rather than trusted, because the row may have been erased since the reaction it undoes
was counted, and the `CHECK` would otherwise turn a stale row into a failed write.

It is **never the source of truth**. A missing or deliberately erased row reads as zero
rather than silently falling back to an unbounded history scan. Operators repair drift
explicitly:

```bash
cd backend
.venv/bin/python -m app.services.user_stats_projection
.venv/bin/python -m app.services.user_stats_projection --user <account-uuid>
```

The structural invariant is tested: **profile reads must not query the participant,
turn, or guess fact tables.**

### `data_exports`
`id` · `user_id` (CASCADE) · `status` (`pending \| processing \| ready \| failed`) ·
`schema_version` · `artifact` (compressed bytes) · `artifact_encoding` (`gzip+json`) ·
`failure_code` · `created_at` · `started_at` · `completed_at` · `expires_at`.

Status, cooldown and listing reads defer `artifact` with `raiseload`; `export_status_payload` reads readiness from `artifact_encoding`, which the CHECK keeps present exactly when the bytes are. Only the download and the worker's completing write touch the artifact (#611).

The document is stored **compressed** — around 3× smaller on a representative
export, and it is the largest single non-blob value in the schema. The encoding is
recorded beside it rather than assumed, so a later format is a new discriminator
rather than a migration, the same rule `canvas_storage` applies to drawings.
`ck_data_exports_artifact_encoding_present` keeps the pair honest: a stored document
says how to read itself, and a row with no document claims no encoding.

A document is written, not assembled: the builder reads each section a page at a time
and hands every row to the compressor as it comes, counting the JSON bytes against
`EXPORT_MAX_BYTES` (64 MiB before compression by default, R-PRIV-13). Past it the job is
failed as `too_large` with no document stored; `generation_failed` is anything else.
Prompt lists are written one list at a time (`_write_prompt_lists`): each list's working
copy is read whole - never more than `MAX_PROMPTS_PER_OWNED_LIST` prompts - with its
aliases joined in the database to one row per prompt, written 100 prompts at a time, and
the loop is given back between lists. Until #1359 every save was a revision and the export
wrote them all; 801 saves of a 500-prompt list stalled the loop ~3 s and took ~1 GB before
failing `too_large` (#1250). A working copy does not grow with saves: an export after 300
saves of a 500-prompt list went from 26.6 MB / 2,693 ms to 0.1 MB / 57 ms. A list is read
whole rather than through a server-side cursor because on PostgreSQL each cursor stayed open
as a portal until the build's transaction ended. The document is compressed at gzip level 6:
level 9 cost ~9× the CPU for 0.6% less, in 128 KB steps that held the loop ~40 ms on
repetitive aliases.
The download hands a client that accepts gzip the stored bytes untouched, and one that
does not the same bytes decompressed a chunk at a time with the length the gzip trailer
records — never parsed, never held whole, never compressed twice (R-PRIV-14).

`uq_data_exports_one_live_per_user` is a partial unique index on `user_id` where the
status is `pending` or `processing`: one live job per account (R-PRIV-12), held by the
database because two requests arriving together can each read "nothing live" and only
a constraint sees them at once. The writer also locks the account row, which serialises
the pair on PostgreSQL; SQLite ignores row locks, so the index is what holds the line
there. The weekly interval is checked in the writer against the newest non-failed job.

Expired jobs are purged at startup and hourly. Before that sweep existed, an expired
row was removed only when its owner requested another export or a worker re-processed
the job — so a document that was generated and never collected outlived its seven-day
window indefinitely.

Jobs are stored **before** work begins, so a crash leaves a retryable row, and the
table is the queue: the export worker
([`app/services/data_export_worker.py`](../backend/app/services/data_export_worker.py))
builds `pending` rows one at a time, woken by the request and sweeping every
`EXPORT_SWEEP_SECONDS`. The sweep also reclaims a row left `processing` for more than
15 minutes by a process that died, and a planned shutdown hands a claimed row back to
`pending`. The same batch can be run by hand when the server is not up:

```bash
cd backend && .venv/bin/python -m app.auth.account_data --limit 25
```

Format v1 exports expire after seven days. The document contains the owner's account
fields, linked guest identities, session metadata, game seats, drawn turns, correct
guesses, prompt lists with their working copies and live and pending editions (schema 16,
#1362), the lists it starred, unexpired authored retained
messages, submitted evidence, blocks, presets, account-event metadata, and its inbox as
kinds and values (`inbox`, schema 17, #1436).
It **never** contains password or session hashes, other players' profile fields, or any
message body the requester did not explicitly receive and pin — nor what other people
did to the requester (schema 13, #1238): a friend request of theirs that was declined
is left out (the decliner's export keeps it), account events that name them only as
the **target** are limited to the ones they are told about as they happen (warnings,
bans and revocations, a moderator removing their picture, role changes, and `session.*`,
`account.*` and `identity.*`) so a block, a report or a staff look-up aimed at them is
not in it, and a report they filed carries `decided` and no status or review time. The field surface is
pinned by [`fixtures/account_data_export_v17_fields.json`](../fixtures/account_data_export_v17_fields.json).

### `email_outbox`
`id` · `to_address` · `user_id` (`SET NULL`) · `template` · `payload` (JSON) ·
`state` (`pending \| sent \| failed`) · `attempts` · `last_error` · `next_attempt_at` ·
`locale` (the interface locales, `en` by default) · `created_at` · `sent_at`.
`ck_email_outbox_sent_at` enforces `(state='sent') = (sent_at IS NOT NULL)`.

`locale` is **frozen when the row is written**, not read when the sweep sends
(R-I18N-08). Mail is the one place the server writes prose for a player, because
there is no client at the other end to write it — and the outbox is a durable
queue, so a send can happen hours after the queue. Resolving the language late
would mean a preference changed in between re-languages a message that was
already composed, including the one about the security event that prompted the
change. `en` for an account with no settings row of its own. `last_error` holds the relay's answer **redacted before it is truncated** to the column's 256 characters: `SMTPRecipientsRefused` stringifies with the refused address in it, and a cut taken first can land inside one and leave the local part standing (R-AUTH-12).

**Claimed reset first, but not only resets.** A sweep takes due `reset_password` rows
before anything else, oldest first (#1240): a reset link lives an hour and is somebody
locked out, a verification link lives a day, and oldest-first alone let a queue flooded
with verification mail age every reset behind it past its expiry at 50 messages a
sweep. A fifth of every batch (10 of 50) is kept for everything else, oldest first,
and filled with resets only when nothing else is due: without it a sustained flood of
resets held every verification until its link had expired (#1302 review). Any batch of two
or more keeps at least one slot for it; a batch of one goes to whichever kind has
waited longer, so a one-message drain starves neither.

`ix_email_outbox_sent_at_sent`, a partial `(sent_at, id) WHERE state = 'sent'`, serves the retention sweep's sent branch (#550, #554): sent rows are most of the outbox and age by `sent_at`. The failed branch ages by `created_at` and is served by `ix_email_outbox_ready`'s state prefix; the sweep runs the two as separate bounded branches with the state inlined as a literal.

Templates: `verify_email`, `reset_password`, `password_changed`, `account_banned`,
`content_hidden`. **Nothing else is ever sent to a player's address.**

**Flow.** Mail is queued in the **same transaction** as the action that causes it, and
delivered by a sweeper woken by that transaction's commit, which sweeps again at once
after a full batch and otherwise every `EMAIL_SWEEP_SECONDS` (default 30) for retries
coming due (#1255). A suspension is therefore
never undone by an unreachable relay, and a reset message is retried with backoff and
then recorded as failed rather than disappearing. With no `SMTP_HOST` the messages are
**logged instead of sent**, which is the only way the confirmation and reset flows can
be completed on a deployment without mail — outside production, where startup refuses a
missing `SMTP_HOST` outright and the console transport refuses to write a body at all,
so a live reset link never reaches a log store (#466).

A verification or reset payload carries the **raw link token** only while the row is
`pending` — a retry has to rebuild the link, and the token is unrecoverable from the
hash `auth_tokens` keeps. The same update that makes a row `sent` or `failed` scrubs
it, so a terminal row is a delivery record, never a credential. Terminal rows are kept
**30 days** (`OUTBOX_RETENTION`) and then purged, at startup and hourly by the sweeper.

```bash
cd backend && .venv/bin/python -m app.services.mail_delivery   # flush by hand
```

### `uploaded_avatar_assets`
One account's uploaded picture (#573): `id` · `user_id` (CASCADE, **unique**: one
picture per account) · `object_key` (indexed, **not** unique: the content address
`<sha256>.webp`, `.png` or `.jpg`, which two accounts uploading the same bytes share, each on
their own row; also denormalised onto `users.avatar_key` so identity payloads need no
join) ·
`content_type` · `byte_size` · `width` · `height` · `checksum_sha256` · `payload`
(the bytes) · `created_at`.

The bytes live here rather than in object storage because they are small by
construction — a 256×256 WebP (JPEG, or PNG for a transparent crop, where the browser cannot encode WebP) under 128 KiB,
framed and re-encoded by the browser and checked from its header by the server
(R-AVA-01) — so a whole player base is megabytes: a photograph is ~22 KiB as WebP, 13–43 KiB as JPEG.
Replacing a picture replaces the row; the moderator's removal (R-AVA-04) deletes it and
stamps `users.avatar_upload_blocked_until`; account deletion deletes it in the same
transaction (R-AVA-05). The export carries the bytes.

### `external_identities`
**Reserved, unused in v1.** Schema for a future authenticated identity provider. No
provider-login API is enabled until identity-linking flows ship.

### `inbox_entries`
`id` · `user_id` (→ `users`, **CASCADE**, NOT NULL) · `kind` · `subject_id` (nullable, no
foreign key) · `params` (JSON / `JSONB`) · `created_at` · `read_at`, with
`ck_inbox_entries_kind` (`warning`, `drawing_shared`, `friend_request`,
`friend_accepted`, `game_invite`, `reports_reviewed`, `role`),
`ix_inbox_entries_user_created` on (`user_id`, `created_at`) for the newest-first page,
`ix_inbox_entries_created_at` for the sweep, the partial `ix_inbox_entries_user_unread`
on `user_id` `WHERE read_at IS NULL` for the bell's count, and the partial unique
`uq_inbox_entries_subject` on (`user_id`, `kind`, `subject_id`)
`WHERE subject_id IS NOT NULL`.

Everything the app tells a player about their own account, behind the header's bell
(#1436, R-INBOX-01). It replaced three stores that each did part of this with different
rules — `role_change_notices`, `drawing_share_notices`, and the "told yet?" columns
`player_reports.reporter_notified_at` and `friendships.acceptance_announced_at` — which
disagreed on order, on what an acknowledgement settled and on whether a reconnect caught
up, and none of which another tab heard being read.

**An entry is the message, not the fact.** The warning, the share, the friendship and the
role keep their own rows and their own retention; the entry only says the account was
told. So `params` holds **values and never a sentence** (R-INBOX-05) — `{role, change}`
with `change` ∈ `offered | granted | removed` for a role, `{count}` for reviewed reports,
`{expiresAt}` for an invitation, nothing for the rest — and what an entry shows is read
from the fact **when it is shown**: who shared a drawing (the earliest share still
standing by somebody other than its drawer) and whether it is still in the Gallery,
whether a friend request is still waiting, whether an offer still stands
(`users.pending_role`). A fact that has gone leaves its entry saying so rather than a
stale line offering to act on it.

`subject_id` names the fact where there is one row or account to name: the warning, the
turn of a shared drawing, or the **other account** for `friend_request`,
`friend_accepted` and `game_invite`. No foreign key, because the kinds name different
tables; a fact that goes is noticed when the entry is read. The unique index makes it
**one entry per fact** — a second share of the drawing says nothing the first did not —
and the kinds that are asked again **renew** the one entry instead (`ON CONFLICT DO
UPDATE`: back to the top, unread): a request asked again after it was cancelled, a
second invitation from the same friend. `reports_reviewed` and `role` have no subject.

**Writes**, each in the transaction of the fact it is about
([`services/inbox.py`](../backend/app/services/inbox.py)), so there is no fact nobody was
told about and no entry about a fact that rolled back; the account's sockets are sent
`inbox_changed` once it commits:

- `warning` — a moderator's warning (`POST /api/moderation/warnings`) and a picture's
  removal (`services/avatars.py`), its subject the `user_warnings` row. Answering the
  warning marks it read.
- `drawing_shared` — the first share of a drawing by somebody other than its drawer, in
  the share's write; a live share's in the finished-game write (`save_game`); a pin, since
  a pin is a share (R-PIN-03). One per drawing, ever (R-SHARE-09). The drawer's withdrawal
  marks it read — they have just acted on it — and the entry stays, naming nobody once no
  share stands.
- `friend_request` — in the asked account's inbox, renewed if asked before. An acceptance
  marks it read and writes `friend_accepted` in the **asker's** inbox (R-FRIEND-14).
  Cancelling, unfriending and blocking delete both accounts' friend entries about the
  pair. A decline writes nothing and deletes nothing: the decliner's own entry is left,
  reading as answered, and the asker is never told (R-FRIEND-04, R-FRIEND-05).
- `game_invite` — a friend's invitation (`invite_friend`), renewed per inviter, with
  `expiresAt`. The token is **not** stored: it stays with the live card, and the entry
  offers Join only while that card's invitation from the same friend still stands. Best
  effort, in a transaction of its own, since the invitation was sent either way.
- `reports_reviewed` — a decision over an incident (a review, or a ban or warning issued
  from a report) counts its reports into each reporter's **unread** entry, or starts one, so a moderator working through a queue
  leaves one line rather than one per report. The count only (R-MOD-20).
- `role` — an offer (`offered`), a grant (`granted`) and a demotion (`removed`) by
  `PATCH /api/admin/players/{id}/role`. Withdrawing an offer writes nothing: the offer's
  entry stays as what happened and stops offering enrolment, its fact being gone. Taking
  an offer up marks the account's role entries read. No actor and no reason: who acted
  is in the ledger, and the reason is text one administrator wrote for another that can
  name a report or a second account, so it has no route to the person it is about
  (R-ROLE-02).

**Reads.** `GET /api/inbox` pages the entries of **every identity of the account**,
newest first, 20 at a time, and counts the unread; `POST /api/inbox/read` sets
`read_at` on named entries or all of them. Read state is the account's, so reading one
anywhere is read everywhere (R-INBOX-03).

**Retention.** Deleted **90 days after `created_at`, read or not** (R-INBOX-06), by the
`inbox_entries` sweep (§10). Ninety days is a player session's idle window (R-AUTH-03):
an absence longer than that is a fresh sign-in anyway, and nothing is lost with an entry
but the telling. The account's erasure deletes its entries, and deletes the entries in
**other** inboxes whose subject is the erased account (`friend_request`,
`friend_accepted`, `game_invite`), which would otherwise name an account that is gone;
a guest's purge removes its user row and CASCADE takes the entries (§11). Exported as
`inbox` (schema 17).

---

## 5. Moderation

### `audit_events`
Append-only record of every security- and moderation-sensitive action.

Nothing sweeps it, and the application role cannot delete from it, so every row a
player's request writes is permanent (#1241): the player routes that append one
are bounded per account — block/unblock and doodle/picture changes 30 an hour each,
withdrawing a list from the catalogue 30 — and a request that changes nothing writes
nothing (blocking somebody already blocked, the doodle already worn, removing a
picture that is not there, withdrawing a list that is not out).

`ix_audit_events_type_created_at` replaces the standalone `event_type` index (#554): the ledger filtered by one type, newest first, walks it in order instead of collecting every row of a rare type and sorting them, and the composite serves the plain equality the standalone did.

`id` · `event_type` · `actor_user_id` (`SET NULL`) · `target_user_id` (`SET NULL`) ·
`target_type` · `target_id` · `request_id` · `ip_hash` · `details` (JSON) · `created_at`.

The subject is named **twice, on purpose**:

- `target_user_id` is a real foreign key, so deleting an account leaves the entry
  standing with its subject blanked rather than taking it along.
- `target_type` + `target_id` names whatever row the action touched — a prompt list, a
  single prompt version, a room, a configuration key. `ck_audit_events_target_pair`
  requires both or neither, so an action on no single row (a bulk retention purge)
  records neither and **says so by leaving both empty rather than inventing a subject**.

The admin ledger reads newest-first on `created_at`, which is indexed for that read —
the UUIDv7 `id` is merely time-ordered, while `created_at` is the authoritative event
time.

**Names are never written into this table.** The admin view resolves them when the
ledger is read: the table is append-only, so a stored name would be personal data that
erasing an account could not reach. Resolving live gives the opposite — delete the
account and the entry reads *Deleted player* while standing exactly as it was.

### `player_reports`
`id` · `reporter_user_id` / `reported_user_id` (`SET NULL`) · `game_id` / `turn_id`
(`SET NULL`) · `reason` · `details` TEXT · `context_snapshot` (JSON) ·
`scope` (`room \| lobby \| profile \| unscoped`) · `room_instance_id` ·
`reported_avatar_key` · `decision_group_id` ·
`status` (`pending \| resolved \| dismissed`) · `reviewed_by_user_id` ·
`resolution_note` · timestamps.

Reasons: `harassment`, `offensive_drawing`, `inappropriate_name`, `cheating`, `spam`.
`ck_player_reports_not_self` forbids self-reports.

A decision tells each reporter only that their report was **reviewed**: it is counted into
their unread `reports_reviewed` inbox entry in the deciding transaction, and nothing is
stamped here — never what was decided, which is the reported player's business
(R-MOD-20). Until #1436 the telling was `reporter_notified_at`, read on every page load.

**Where the complaint happened**, so reports of one incident are read and decided
together (#620). `scope` and `room_instance_id` are one fact in two columns and
`ck_player_reports_scope_instance` keeps them from disagreeing: a room report names the
room instance it happened in, and nothing else names one. Both report paths already knew
this and threw it away — the socket handler holds the live room
(`Room.retention_scope_id`), and `POST /api/reports` has already proved that every cited
line came from one room instance or all from the lobby before it writes. Neither reads
it from a client. `room_instance_id` carries **no foreign key**, exactly as
`room_messages.room_instance_id` does not: rooms live in the process, have no row to
point at, and a report has to outlive the room it was filed in.

`unscoped` is a REST report that cited nothing and named nothing. It names no place to
look, so it stands alone rather than joining a bucket it merely resembles. Every lobby
report about one account shares the one bucket, because the lobby has no instance to
name.

`profile` is a complaint about the account itself rather than about anything it said —
today, its picture, which is reportable from the lobby's online list and from the profile
page (R-AVA-06). It belongs to no room and no line, so like the lobby it takes no
instance and every such report about one account meets in one bucket, whichever screen it
came from.

`reported_avatar_key` records **which** picture a complaint about a picture was about.
It is deliberately not a way to fetch that picture back: `uploaded_avatar_assets` deletes
the old row the moment a new one is uploaded, so this key can name something already
gone. That is what it is for — the queue compares it against the account's live
`avatar_key` and tells a reviewer the picture has **changed** since the report, rather
than showing a different one in its place and having a moderator judge, and remove,
something nobody reported (R-AVA-07). The key is never serialised to a client; it is
compared, not shown. Null on every report not about a picture.

**Which decision covered the report.** `decision_group_id` is minted once per moderator
action rather than once per report, so a decision over an incident leaves every report it
covered pointing at one value; `ck_player_reports_decision_group` says a decided report
carries one and a pending report does not, the same shape as
`ck_player_reports_reviewed_identity` beside it and for the same reason. The id is a
UUIDv7, which is what lets the closed-case stream page decisions from an ordered walk of
the partial index `ix_player_reports_decision_group` rather than aggregating every report
ever decided to find the newest ones.
`uq_player_reports_open_target (reporter_user_id, reported_user_id)` is a **partial
unique index**: one reporter holds **one open report per player**. Saying it again while
a moderator has yet to look adds no evidence and buries the queue; once decided, the
same reporter may raise a new one, because that is a new incident.

Submitted context is preserved as **versioned, reporter-supplied evidence** — it is not
treated as a server-verified fact merely because it was stored. Review is one-way: a
pending report receives one resolution and cannot later be silently rewritten.

### `room_messages`
Accepted player-authored chat, wrong guesses, and correct-guess text, kept **30 days**
in an audience-aware store — and, since #533, the lobby's chat too. A room line that
reached **nobody but its author** — said alone in a room, or with every other seat
blocking them — is not written (#1243): a report cites only a line its reporter
received, so such a row could never be evidence, and it was storage anybody could fill.

**Written in batches, never on the delivery path.** A queued writer inserts what
arrived within `WRITE_LINGER_SECONDS` (0.25 s) of a batch's first line, up to 100,
in one transaction that also runs the erasure barrier's two reads once for the batch
(#972). Taking only what was already queued wrote one transaction per line, because
rooms rarely say two lines in the same instant: under the load gate that was 2,885
inserts in 2,874 transactions, and with the barrier's reads half of every statement
the process ran. Batched, the same 60 s run wrote every line with 205 inserts, and
the process's statements fell 16,929 → 8,643 (SQLite, counted with an engine listener;
the shape is the same on PostgreSQL, the per-statement cost is not). A report reads its evidence from this table, so both report paths flush
the queue (bounded at 2 s) before that read and **outside any transaction of their own**:
waiting for the writer to get a connection while holding one is how concurrent reports
starve the very writer whose rows they are waiting for. A report that is going to be refused -
an erased account, an unknown player, game or turn, a duplicate, a picture that is not
there - never waits for the queue at all on either path (R-MOD-21): each decides its
refusals first, in a transaction it then closes.

The flush waits only for the
lines queued when it was called, not for what other rooms say meanwhile, and it cuts
the current linger short without cutting anybody else's.

The batching figures above are measured by the load gate (`benchmarks/run_load.sh`) with
an `Engine` statement counter attached; the flush's own rules are checked by

```bash
cd backend && .venv/bin/pytest tests/test_message_retention.py tests/handlers/test_moderation.py -q
```

**No index by game or turn** (#890): `game_id` and `turn_id` are correlation columns — no read filters on them and neither is a foreign key — and the `(game_id, turn_id, created_at)` index that used to cover them was the largest on the table. Dropping it, measured on 100,000 six-recipient lines (`benchmarks/index_write_cost.py`): index bytes per row 205 → 102, WAL per insert 918 → 773 B, heap plus indexes −16%.

**Indexes chosen from plans** (#554, `benchmarks/index_plans.py`): `ix_room_messages_lobby_newest` is a partial `(created_at, id) WHERE audience = 'lobby'` for the startup restore of the newest 50 lobby lines — one row in forty is a lobby line, and without it the restore sorted every retained message. The application inlines the literal `'lobby'` in that query: a generic plan for a prepared statement cannot prove a bound `audience = $1` implies the index's predicate, so the literal is what keeps the index in use once asyncpg stops planning per value.

| Column | Notes |
| --- | --- |
| `id` | UUIDv7 |
| `room_instance_id` | Durable correlation scope; the live room ID is never stored as a code. **Null for a lobby line**, which is the only kind without a room |
| `game_id`, `turn_id` | The same UUIDv7s eventual history will use — assigned before play, so a message from an unfinished game already correlates |
| `sender_user_id` (`SET NULL`), `sender_player_id`, `sender_seat_id` | `sender_player_id` is null for a lobby line, which has no seat |
| `sender_*_snapshot` | Frozen presentation |
| `is_spectator`, `message_kind`, `audience`, `near_miss_kind` | |
| `audience_user_ids` (JSON) | The recipients who **actually received** the line after Blocks and prompt-visibility rules. Empty for a lobby line: see below |
| `text`, `created_at`, `expires_at` | |

`message_kind` ∈ `chat \| wrong_guess \| correct_guess`; `audience` ∈
`room \| prompt_aware \| lobby`. `CHECK`s enforce that guesses carry a game and turn, that a
turn implies a game, that a near-miss kind only appears on a wrong guess, that
`expires_at > created_at`, and — `ck_room_messages_lobby_has_no_scope`,
`ck_room_messages_lobby_is_chat` — that a null room and seat *is* a lobby line and a
lobby line is chat: a null scope is a statement, never a room line that lost its room.

**Lobby lines.** Said to every lobby that was open, so the row has no room to scope
it to, no seat that said it, and **no recipient list**: recording every watcher per
line would make this table a directory of who was around, at lobby scale. The
audience value is what the moderation API reads instead of the list — a lobby line
is public by construction, so `POST /api/reports` accepts it as evidence without the
"did you receive it" check, still requires the reported account to have written it,
and refuses a report that mixes lobby and room lines, since the lobby is one
conversation and not any room's. An in-room `report_player` never selects lobby lines
automatically; `evidence_from_live_room` is scoped to that room by construction. The
`created_at` is the instant the line went out on the wire (`sentAt`), so the age a
watcher saw beside it is the time a moderator sees on it. Account deletion erases
them with the rest of the author's messages; the live backlog forgets them at the
same moment ([`services/lobby_chat.py`](../backend/app/services/lobby_chat.py)). A
guest's lines keep the guest's id after a merge, and resolve through
`identity_aliases` exactly as room chat does.

**Flow.** Ordinary chat and guesses use the Room audience; near misses, correct
guesses, spectator chat during play, and other restricted text use the Prompt-aware
audience. Retention is **best-effort and never delays live availability**: the row's id
is issued before the write lands, and a lobby line carries it as `retainedMessageId`; a
room `chat_message` does not, because nothing in a room cites a line (#869). Expired rows
are removed at startup and by bounded hourly cleanup during new writes.

**There is intentionally no transcript or profile-history endpoint.** After 30 days the
raw strings cannot be replayed through a new matcher; durable per-seat and per-turn
counts still support difficulty and attempt analysis, and that bounded loss is the
accepted privacy and storage-volume tradeoff.

### `player_report_message_evidence`
`report_id` + `position` composite **PK** · `role` (`cited \| context`) ·
`source_message_id` (`SET NULL`) ·
`source_message_snapshot_id` · `game_id_snapshot` · `turn_id_snapshot` ·
`sender_user_id` (`SET NULL`) · frozen sender presentation · `message_kind` ·
`audience` · `near_miss_kind` · `text_snapshot` · `message_created_at` · `copied_at`.

A report may pin up to **20** unexpired `messageIds`, but only when the reported player
authored them and the reporter was in each stored audience — which makes *"is this
message theirs"* and *"did you see it"* true by construction rather than by checking a
client's claims. A lobby line answers the second question differently: it was said to
everybody, so its `audience` value (`lobby`, carried across into the copy) stands in
for a list. The server copies those lines here before the ordinary rows expire.

Those are the `cited` rows. Around them the server also copies **`context`**: what
was said in the same room instance (or the lobby) up to **10 lines before and 5
after** the latest cited line, within **12 hours** of it, by anyone, but only lines the
reporter received — the stored audience for a room line, and for a lobby line (which
records no recipients) the reporter's `user_blocks` re-applied — by
[`context_around`](../backend/app/services/player_reports.py) rather than trusted. A
room report with nothing cited anchors on the report itself; a REST report with nothing
cited has no place to look and copies nothing. Rows are positioned in the order the
lines were said, so every reader gets one thread. The role matters to two readers: a
**Warning** and a **Suspension** show the reported player only the `cited` rows — their
own words, never what somebody else said around them.

Account deletion erases ordinary authored messages immediately and **tombstones the
presentation** on copied evidence, `context` rows included — a third party's line copied
into somebody else's report loses its name the same way; the evidence text continues
under the protected report retention policy.

### `player_report_drawing_evidence`
`report_id` **PK** (FK → `player_reports`, CASCADE) · `turn_id_snapshot` ·
`round_number` · `prompt_snapshot` · `action_count` · `format_magic` ·
`format_version` · `payload` BLOB · `byte_size` · `checksum_sha256` · `captured_at`.

The canvas as it stood when a report about the player drawing on it was filed
(R-MOD-14). One per report, and only when the reporter asked for it over
`report_player` with `includeDrawing` **and** the reported seat held the pen in a
phase where the canvas still showed the turn — the server decides both, so the
frame is the reported player's work by construction.

**Copied, never referenced.** The drawing on the canvas keeps changing after the
report: the drawer can add to it, undo the part complained about, or clear it. The
turn's own `turn_drawings` row is written only when the game ends, holds the
turn's *final* state, and is erased when the drawer's account is deleted. What a
moderator has to judge is what the reporter saw, so that is what is kept, for as
long as the report is — the same rule as message evidence. `turn_id_snapshot`
carries no foreign key for the reason `room_messages.turn_id` does not: the report
is filed while the game is still being played, and a game abandoned before it ends
never writes a `turn_records` row.

The bytes are stored the way `turn_drawings` stores them, under the same
[`canvas_storage`](../backend/app/canvas_storage.py) rules: validated on ingest,
the format named in the row so a decoder can be found without parsing, the checksum
verified on every read, and `byte_size` under the same 8 MiB structural bound. The
`payload` column is deferred in the model, so listing the queue and building an
export never drag the bytes along; only
`GET /api/moderation/reports/{report_id}/drawing` reads them.

`prompt_snapshot` is what the drawer was asked to draw — server-held, so unlike the
reporter's own words it may be read as fact, and it is what makes an "offensive
drawing" judgeable at all. No drawer name is snapshotted here: the report already
names the reported account, and a name would be one more thing deletion had to
reach. A reporter's data export records that a drawing was attached and of which
turn — never the bytes, and never the prompt, which a guesser who reported
mid-turn has not earned and must not be able to read out of their own export
(R-PRIV-02). The reported player sees it through a
**Warning** or **Suspension** decided from the report, beside their cited
words and for the same reason (R-MOD-12, R-BAN-08).

### `prompt_content_reports`
Player-authored prompt content has a separate, target-specific flow.

`id` · `reporter_user_id` / `reported_owner_user_id` · `prompt_list_id` (no foreign key,
#1362) · `prompt_version_id` (`SET NULL`) · `target_type` (`list \| prompt`) ·
`list_name_snapshot` · `prompt_snapshot` · `reason` · `details` ·
`decision_group_id` ·
`status` · `reviewed_by_user_id` · `resolution_note` ·
`resolution_moderation_state` · timestamps.

`decision_group_id` and `ck_prompt_content_reports_decision_group` are
`player_reports`' rule restated, for the same reason and paged from the same kind of
partial index. A content report needs no `scope` beside it: its target already names the
incident.

Reasons: `inappropriate`, `hateful_or_abusive`, `sexual_content`, `violence`, `spam`,
`other`. `ck_prompt_content_reports_target_snapshot` requires a prompt snapshot for a
`prompt` target and forbids one for a `list` target. Two partial unique indexes give one
open report per reporter **per list** and **per prompt version** — so a list and a
single prompt inside it stay separately reportable.

**Post-moderation:** submission preserves a bounded evidence snapshot but never hides
content automatically. One review may dismiss the report or set the exact target Active
or Hidden, with actor/time provenance and an append-only audit event. A dismissal
cannot mutate content. Snapshots survive list and account deletion. The list id is kept as
an opaque value with no foreign key (#1362): deleting a list writes nothing to its reports,
so an erasure holding the owner's account cannot wait on a report row a moderator's
decision holds while that decision waits on the account — the deadlock the `SET NULL`
produced once lists were deleted outright. The report keeps naming the list it was about.

### `prompt_takedowns`
`owner_user_id` (CASCADE) · `concept_id` (CASCADE) · `created_at`. Composite primary key
on `(owner_user_id, concept_id)`, plus `ix_prompt_takedowns_concept`.

**Which words an owner may not type back in** (R-MOD-11, #1357). A moderator hiding a
prompt writes one row for the owner the report names — whose list may have been deleted
since — and one for every owner whose lists hold the concept now. A save reads the rows for
its owner, joined to the hidden versions of those concepts in the languages that share
words with the list (#821), and a new entry matching one of their spellings is born hidden
with the decision's byline. That entry's concept is recorded too, so the word follows it
into a list only it shares words with, and a later decision on the original finds it by
its byline. A decision that leaves the word up deletes the rows naming it, and the
account's deletion deletes its rows explicitly — the CASCADE never fires, since deletion
tombstones the user row. A decision takes the owners it reaches through the erasure
barrier — shared, ascending — before it locks the list or writes a version: deletion
holds the account and then deletes its lists, so the other order deadlocked against it,
and an unlocked lifecycle read let a deletion commit in between and leave a record for an
erased account (#1375 review). Both writers live in
[`services/prompt_takedowns.py`](../backend/app/services/prompt_takedowns.py): the insert
ignores a row already there, since two decisions on one concept (two reports of different
versions are two incidents) can both find none, and removing a row offers its concept's
versions to the orphan collection at once — the sweeps only look at versions a deleted list
or a save left unlisted, and the unlisted sweep unstamps what a row kept, so a spelling kept
by a row is a candidate nowhere else, and the hidden text would outlive the account.
After the owners and the list, a decision locks every wording of the concept in id order,
the order every multi-row version writer takes; the unlisted sweep locks its batch the same
way and skips a row somebody holds, leaving it for its next pass (#1385 review).

The row names the concept, not a spelling: the decision is the concept's (#1020), and its
versions carry the text, the aliases and the byline the save compares against, so the
orphan collection keeps a concept a row names. Until this table the record was implicit:
the save searched every revision of every list the owner had ever held, so revisions had to
outlive their lists as long as a takedown did, and the reclaim carried holds for hidden
words and pending reports (#1091, #1354) that produced three review bugs in one epic.

No retention of its own: a row lives as long as the takedown and the account.

### `bug_reports`
A player's report that the app itself is broken. **Not a moderation row**: it is about
the software rather than a person, carries build and diagnostic data rather than safety
evidence, and is triaged by administrators. It lives in this section only because it
shares the `ReportStatus` review vocabulary.

`id` · `reporter_user_id` (`SET NULL`) · `area` · `severity` · `summary` ·
`details` · `build_sha` · `route` · `room_code` · `game_id` / `turn_id` ·
`client_context` · `server_context` · `screenshot_*` · `status` ·
`reviewed_by_user_id` · `resolution_note` · timestamps.

Areas: `drawing_and_canvas`, `guessing_and_chat`, `rounds_and_scoring`,
`rooms_and_lobby`, `prompt_lists`, `account_and_settings`, `connection_and_sync`,
`performance`, `accessibility`, `other`. Severities: `blocks_play`, `major`, `minor`.

`build_sha` and `route` are lifted out of the context blob so the queue can be grouped
by them without parsing JSON. `game_id` and `turn_id` are **not** foreign keys: a live
game is not written to `game_records` until it finishes, so at filing time they name
rows that may not exist yet.

**Two halves of context, never conflated.** `client_context` is what the reporter's
browser said about itself — build, viewport, browser, accessibility preferences,
connection telemetry, heap, and the last 20 client errors — and is reporter-supplied
evidence. `server_context` is what this server observed of their **live seat**, resolved
by walking the live rooms for that account rather than trusting the room code sent, plus
the clock skew between the two. Only the second half is fact. Neither ever carries the
prompt in play, chat text, or a query string.

**Screenshots** follow `turn_drawings` rather than inventing storage:
`screenshot_payload` with `screenshot_byte_size`, `screenshot_checksum_sha256`,
`screenshot_content_type`, dimensions, and a `screenshot_status` of
`none | ready | erased | expired`. The server sniffs the magic bytes, re-derives the size,
digest and dimensions (from the picture's header, not the sender's claim, and only up to
16384 a side — a claimed `10**12` once overflowed the column and lost the report on
PostgreSQL, #1017), and rejects anything that is not a real PNG or WebP under 2 MB.
`ck_bug_reports_screenshot_ready_identity` requires a `ready` row to hold the bytes and
their identity; `ck_bug_reports_screenshot_erased` and
`ck_bug_reports_screenshot_expired` make both erasures **structural** — neither a decided
nor an expired report can retain pixels, whatever a future code path does.

**`erased` and `expired` are different facts.** `erased` means a decision was made and
took the picture with it. `expired` means nobody decided anything and the 90-day ceiling
came first (R-BUG-13, #478): "erased when the report is decided" is a ceiling exactly as
long as somebody decides, and an unattended pending report used to hold up to 2 MiB of
somebody's screen indefinitely — the one retained thing in §10 with no maximum age at
all. Labelling that as `erased` would put a decision on the record that never happened,
and leave the reviewer opening the still-pending report no way to tell. The report row,
its status and every piece of screenshot metadata survive either way, so the record
still says a picture existed and what shape it was.
`ix_bug_reports_screenshot_expiry` — `created_at` over pending rows still holding a
picture — is what both the hourly sweep's candidate batch and its overdue probe read.

The admin queue and the account export read this table **without the screenshot column**: `screenshot_payload` is deferred with `raiseload`, so up to 200 rows of up to 2 MiB each are never transferred to serialise the shape of a picture nobody is looking at (#611, R-PLAT-14). Only the screenshot route selects the bytes.

**Deciding is one-way.** A pending report receives one resolution with a required note,
and the same transaction erases the screenshot. Submission and each decision append an
audit event naming the report; the ledger never records what the report said. Expiry
appends no per-report event — nobody did anything — only one aggregate row per sweep run
counting the pictures that went.

### `user_bans`
`id` · `user_id` (`SET NULL`) · `banned_by_user_id` (`SET NULL`) · `reason` ·
`source_report_id` (FK → `player_reports`, `SET NULL`) · `category` · `expires_at` · `is_active` ·
`created_at` · `revoked_at` · `revoked_by_user_id` · `revoke_reason` · `lift_requires_admin`.

`lift_requires_admin` records, when the suspension is placed, whether only an
administrator may lift it — an administrator placed it, or its subject was staff
(R-BAN-01). Revocation checks it beside the roles held today, so a demotion since —
of the administrator who placed it, or of the staff member under it — cannot bring
it within a moderator's reach (#1294 review). A suspension already in force when the
column arrived was backfilled `true`: nothing recorded the roles it was placed under,
and needing an administrator is the reading that cannot be wrong in a moderator's
favour.

**Active is one predicate everywhere** (#553): `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now)`, from `auth/bans.py` `active_ban_filter`. The `is_active` flag it replaced recorded only the first half, so an expired-but-unrevoked ban was active in one reader and not in another; such a ban now stays as history and counts as nothing. `ck_user_bans_revocation_identity` ties the revoking actor and reason to a revocation (the actor may still become NULL when that moderator's account is deleted). `ix_user_bans_user_expires` serves the account lookup and the foreign-key walk on deletion; `ix_user_bans_unrevoked_newest`, a partial `(created_at) WHERE revoked_at IS NULL`, serves the moderation queue's newest active bans (#554).

**Flow.** Creating a suspension revokes every signed-in device and removes any live room
seat immediately. Correct-password login, authenticated HTTP requests, and Socket.IO
handshakes all reject an active suspension. A token revoked at ban time stays
recognizable until expiry, so its next request cannot be mistaken for a new cookieless
guest. **Data export, account deletion, and logout remain available** through that
ban-time credential, so moderation cannot erase privacy rights. "Ban-time" is exact:
a session the ban itself revoked (`revoked_at` equal to the ban's `created_at`) and
issued before it. The owner's own later revocations — signing out on that device, a
password reset by mail or by an operator — restamp `revoked_at`, which ends that
session's hatch; before, they skipped the ban-revoked rows, and a copied cookie kept
exporting for the whole suspension (#1082). A staff action that revokes sessions (a role
change) leaves the hatch alone. Expired suspensions stop
applying automatically; revocation preserves the historic record and its reason.

`source_report_id` is what lets the suspension notice show the reported player their own
words as they were when the report was made. **A ban naming a report about somebody else
is refused**, so a suspension cannot be used to show one player another's messages. A ban
issued from a report also **resolves that report in the same transaction**, and a report
already decided refuses the ban - one complaint, one consequence.

### `user_warnings`
`id` · `user_id` (NOT NULL, `fk_user_warnings_user_id_users` → `users` **CASCADE**) ·
`issued_by_user_id` (`SET NULL`) · `reason` · `kind` (`warning \| avatar_removal`,
checked) · `source_report_id` (FK → `player_reports`, `SET NULL`) · `category` ·
`created_at` · `acknowledged_at`, with `ix_user_warnings_user_pending` on (`user_id`,
`acknowledged_at`).

`category` is the moderator's own finding about what rule a decision was about,
checked against the six report reasons and **nullable**: it is optional, so every
notice has to read correctly without it (R-MOD-19). It is never the reporters'
reason, which is their claim rather than a finding. `kind` says which notice the row
is: a moderator's removal of a picture travels as a warning (R-AVA-08) but is not
one, and its `reason` is **empty** — the client says the removal, and the date another
picture may go up (`users.avatar_upload_blocked_until`, served as `uploadAgainAt`), in
the reader's language, where a sentence built on the server was English on every screen.

**Flow.** The step between dismissing a report and suspending the account: nothing is
restricted but a new seat and publishing, until it is acknowledged (R-INBOX-04). Issuing
one writes a `warning` entry in the account's inbox in the same transaction, and the
account's sockets are sent `inbox_changed` once it commits. Every read of
`GET /api/inbox` carries the oldest unacknowledged warning (`mustAcknowledge`) together
with the pinned messages of its source reports — the same own-words rule as a
suspension, and a warning naming a report about somebody else is refused for the same
reason — which the client shows as a dialog that can only be acknowledged.
Acknowledging sets `acknowledged_at`, which is what stops it being shown again, records
that the notice actually landed and lifts the hold on room entry; it marks the entry
read too. Room entry and the prompt-list publish gate both ask this table for an
unacknowledged row, so the hold is the server's and no tab can skip it. Issuing one
writes a `warning.issued` audit event. A warning issued from a report **resolves that
report in the same transaction**, and a report already decided refuses the warning -
which is also what stops a retry from warning twice.

**Twelve months, then gone; and gone with the account.** A warning is moderation
history: a later suspension decision reads what the account was warned about before,
which is why it outlives its inbox entry. It is kept no longer than that reason needs —
swept 365 days after `created_at` (§10) — and **CASCADE** deletes it with the account,
where it used to be orphaned by `SET NULL` and kept for ever (#1436). An erased
account has no future decision for its history to inform.

### `user_blocks`
`blocker_user_id` + `blocked_user_id` composite **PK** (both CASCADE) · `created_at`,
with `chk_no_self_block` — the pair is the identity; nothing references a block by
anything else.

Directional, available to every account including a guest. A historical guest alias
resolves to its registered account, and login merges both incoming and outgoing blocks
without creating duplicates or a self-block.

**Blocking filters only ordinary player-authored chat, for the blocker.** Room state,
players, scores, turns, correct-guess events, votes, and room-authored announcements are
never hidden — so a Block never changes gameplay facts or creates a different game
state per player. Lookups use a bounded 1024-sender LRU invalidated immediately by the
REST mutation ([`backend/app/auth/blocks.py`](../backend/app/auth/blocks.py)), avoiding a
database query per chat line.

---

## 6. Game history

The finished-game write is **one transaction, keyed on the game's stable UUIDv7**,
implemented in [`backend/app/services/game_history.py`](../backend/app/services/game_history.py)
and [`backend/app/repositories/sqlalchemy.py`](../backend/app/repositories/sqlalchemy.py).
Since #541 it is not the write the room waits on: the room stages the whole game as one
envelope row first, and a supervised loop performs the history write from that row.

### `finished_game_envelopes`
The durable handoff (#541, R-HIST-26). One row per finished or abandoned game, written
by the room in a single small INSERT the moment the game ends, and deleted by the replay
loop once the game is in history — so a table with no rows is the healthy state, and a
row is a game that is on its way or that was lost.

`game_id` **PK** (the game's own UUIDv7, R-HIST-01) · `envelope_version` ·
`payload` (deflated JSON: the history rows, the drawings **already prepared** - each
one's stored `SKCD` blob as base64 with its checksum, format and the digest of the frame
it came from - and the prompt-usage batch; nullable, **null on a failed row**) ·
`byte_size` · `checksum_sha256` ·
`state` (`pending \| processing \| failed`) · `history_state`, `usage_state`
(`pending \| done \| none` — the two parts under one manifest, so a crash between them
resumes only the missing one; `none` is decided at staging when the game had no usage
to write, which is a fact, not a gap) · `attempts` · `next_attempt_at` · `claimed_at`,
`claim_token` (a claim is the pair; every later write is fenced by the token) ·
`failure_code` (`conflict \| exhausted \| unreadable \| invalid`) · `last_error` · `created_at` ·
`failed_at`. `ix_finished_game_envelopes_due` on `(state, next_attempt_at)` is the
loop's queue scan.

Since `envelope_version` 4 (#1430) an envelope carries the shares to the Gallery made
from the turn results (`shares`, each with its seat, account, moment and whether the
drawer should be told) and the turns whose drawer took theirs back out
(`withdrawn_turn_ids`); both are in the payload digest.
Since `envelope_version` 3 (#1358) an envelope's provenance names lists rather than
revisions, and its usage batch carries each version's source lists (`sources`).
Since `envelope_version` 2 (#1259) a drawing is prepared once, at staging on the
envelope's threads, and the replay writes that blob as it is after verifying its
checksum. Version 1 carried each wire frame as base64 and the replay prepared it again:
the row, written and deleted within seconds, was the larger part of the WAL a finished
game wrote. Measured on PostgreSQL 17 (`benchmarks/finish_game_stall.py`, 4 seats ×
8 turns, a distinct realistic drawing each turn): envelope 227.8 → 59.4 KB, whole-game
WAL 336.8 → 152.0 KB; a stroke-heavy game's WAL 3.68 → 2.73 MB. A frame that cannot be
prepared travels as it is, so the replay refuses it exactly where it always did. The
game's content hash names each frame's digest either way, so a game written directly and
the same game replayed from its envelope are one game.

The checks keep a row honest: a `failed` row has a code and a time and **no payload**;
any other row has a payload; a `processing` row has both halves of its claim.

**Flow.** The staging insert is bounded like the direct write was (10 s) and is the one
thing that can still lose a game: a database that is down at the moment a game ends. The
bound covers the insert only — the envelope is encoded before it, off the loop and
unbounded (#976), so a burst of endings queueing for an encode thread costs the room
latency rather than its game. The whole handoff runs on a task of its own rather than
inside the action that ended the game, so neither the result nor the waiting room waits
for it; a planned shutdown drains those tasks with a budget that covers an encode as
well as the write, and cancels and counts whatever is still running after it.
That loss is recorded exactly as before (`history.write_abandoned`, kind `handoff`) —
the issue is explicit that an outbox in the same unavailable database is not an outage
guarantee, and this table does not pretend to be one. Everything after the insert is
guaranteed: the loop
([`backend/app/services/game_handoff.py`](../backend/app/services/game_handoff.py))
claims one due row at a time (`FOR UPDATE SKIP LOCKED` on PostgreSQL, a compare-and-set
UPDATE on both engines), writes history through `save_game` and usage through
`record_prompt_usage`, marks each part done, and deletes the row. Both writes are
idempotent by content (R-HIST-02), so a commit whose acknowledgement was lost is simply
tried again. A transient failure hands the row back with backoff — 1 s, 5 s, 30 s,
2 min, 10 min, 30 min, 60 min, eight attempts in all — and then fails it as `exhausted`;
a conflict (the database already holds this game or this batch with different content)
fails on first sight; an envelope this build cannot read fails as `unreadable`; one the
writer refuses — a ledger that does not reconcile (R-HIST-12), a value the database will
not take — fails as `invalid` on first sight too, since the same bytes refuse the same way
on every attempt (#992). A failure
after the history half is written loses only the usage counters and is counted under
kind `prompt_usage`; the room's recap opens the moment the history is in. A claim
older than 15 minutes belongs to a process that died and is taken over with a new
token; a planned shutdown hands a claim back at once. Failed rows keep their metadata
**30 days** for the operations page (`sketchy_finished_games_failed`) and are purged by
the loop's own sweep; their payload is dropped the moment they fail, so nothing an
erased account authored (#606) sits here longer than the retry window — and the replay
itself runs through the same erasure barrier as every writer (R-PRIV-15), so content
erased while an envelope waited is tombstoned on the way in, never restored.

**Nothing is encoded on the event loop** (#976). Each drawing's stored form and the
envelope's JSON and deflate at staging, its checksum and decode at replay, and in
`save_game` the game's content digest and each staged drawing's checksum all run on
small thread pools of their own — not the default pool, which blocking SMTP can hold
while a staging waits for its insert. Each pool is `HISTORY_ENCODE_WORKERS` threads wide
(2 by default, 1-16, refused at startup if it is neither), which is how many endings
encode at once before the rest queue: one stroke-heavy envelope measures ~240 ms since it
prepares the drawings (#1259; ~143 ms before), so 50 rooms ending in the same instant is
~6 s of encode at the default, and the planned shutdown's drain allows
`ENVELOPE_ENCODE_SECONDS` (0.25 s) a room. `save_game` answers a replay of a game already
written with one read before checking anything, and checks each staged drawing — its
checksum, and its header against the format it travelled with — *before* the transaction
that holds every player's `users` row (a frame written directly is prepared there
instead); a drawing that fails fails the write only if it would be written, so an erased
drawer's is still a tombstone. The stored bytes are unchanged.
`benchmarks/finish_game_stall.py`, 8 turns, one idle 1 ms ticker on the loop: its
longest wait while a game is staged and replayed fell 16 → 1.5 ms for ordinary drawings
and ~200 → 12.7 ms for stroke-heavy ones. The encode still takes the same CPU and shares
the GIL with the loop while it runs, so the loop runs at reduced throughput for those
few hundred milliseconds rather than stopping for them. The encode's thread time is
recorded where the encode runs: at staging for a finished game's drawings, by `sizing`
for one written directly.

What the transaction writes scales with turns × seats, and the largest room is sixteen
seats and ten rounds: 160 turns, 2,400 guesser outcomes and up to 2,560 score events.
Those two go in as plain rows, one bulk insert each, after a flush of the turns and seats
they name — as ORM objects the unit of work tracked and flushed them one by one, on the
loop (#1260). The inserts render NULLs: left out, a right guesser's row (a time, an
award) and a wrong one's (neither) have different columns and the insert splits wherever
they alternate, ~1,600 statements for one game. Same benchmark, that game with a mix of
right, hinted, wrong and silent guessers (1,758 events): the loop's longest wait fell
67.5 → 14.8 ms, stage and replay 625 → 609 ms, row statements 5 → 2. Score events are
inserted in ledger order, so a correction's target is always a row already written. The
benchmark builds each game before its ticker starts; before #1260 it drew the ordinary
shape's eight drawings inside the measured window, which is where most of that shape's
21 ms came from (~1 ms now).

```bash
cd backend && .venv/bin/python -m app.services.game_handoff --limit 50   # replay by hand
```

### `game_records`
| Column | Notes |
| --- | --- |
| `id` | The live game's UUIDv7, reused for the history row and the prompt-usage batch |
| `payload_hash` | Canonical SHA-256 digest of the content. Retrying the same ID **and** content is idempotent even if collection order changed; a different payload under the same ID raises an operator-visible conflict |
| `room_name`, `player_count`, `total_rounds`, `drawing_seconds` | Bounds-checked: at least one player and round, a positive duration, and `started_at <= finished_at` |
| `scoring_mode`, `hint_mode` | Enum-checked |
| `scoring_version`, `score_ledger_version`, `rule_snapshot_version` | Legacy rows use `0` |
| `rule_snapshot` (JSON) | The frozen exact rules — see below |
| `prompt_source_mode` | `legacy_unknown \| curated \| custom \| mixed \| builtin_fallback` |
| `started_at`, `finished_at` | Gameplay times |
| `outcome` | `finished \| abandoned` (and shutdown-cut) |
| `visibility` | `public \| private`, CHECK-enforced. The room's public flag, frozen when the game is saved (#469): a public room's game is listed on a profile for anyone, a private room's only for the players who sat in it (R-HIST-25). Defaults to `private` at both layers, so a writer that does not say discloses nothing |
| `persisted_at` | The **database write time**, deliberately separate from `finished_at`, making delayed/retried-save lag measurable |

**The rule snapshot** ([`backend/app/game.py:548`](../backend/app/game.py)) freezes the
numeric default/pressure/hint parameters, the drawer-bonus algorithm, the drawing time,
the permitted tools and colors, prompt visibility and language, and the prompt lists the
game drew from (`sourceListIds`; the exact revisions until #1358). Historical points can therefore be interpreted under the rules that
produced them after defaults or algorithms change. Legacy rows use version `0` and an
**empty** snapshot rather than claiming parameters that cannot be reconstructed.
Participant-only game detail and private account export include the exact snapshot;
public history summaries expose only its versions and typed mode/time fields.

**Abandoned games are recorded.** Persistence used to run only for a game that reached
its end, so a room everyone walked out of left no trace — the games most worth looking
at were the only invisible ones. An abandoned game is an ordinary row with
`outcome = 'abandoned'`; `finished_at` keeps meaning *when the game stopped*, not that
it finished. Player history shows finished games unless `?includeAbandoned=true`. One
that is shown carries **no placing** — `final_rank` is **null** in the row, not merely
suppressed in presentation — because a rank is a claim about how a game ended, and this
one did not end. The scores stay,
since points earned in the turns that were played are a fact. An abandoned game
contributes those turns but **not** a game played, a game won, or a score.

### `game_participants`
`id` (the **participant seat**) · `game_id` (CASCADE) · `user_id` (`SET NULL`) ·
`display_name_snapshot` · `name_color_snapshot` · `is_anonymous_snapshot` ·
`final_score` · `final_rank` (nullable; null for abandoned games, `>= 1` otherwise) ·
`turns_played` · `created_at`, with `uq_game_participants_game_user`.

- At most **one participant seat per linked account** per game; multiple accountless
  seats remain distinct.
- Presentation is **frozen** at save time. Ordinary profile edits never rewrite it —
  history stays as other players saw it. Username and avatar are not rendered by
  finished-game history, so they are not copied in.
- A linked account ID may still support a live profile link while presentation comes
  from the frozen seat.
- Account deletion replaces identifying snapshots with the **Deleted player** tombstone.
- A live player receives their seat UUIDv7 when the game starts **even if no session
  cookie supplied an account**. Such a seat still counts toward the recorded player
  total and keeps every factual turn and correct guess.
- Foreign keys are `ON DELETE SET NULL`, so even a physical user-row removal cannot
  cascade away turns, guesses, or another player's game.
- **Read as a social graph, once.** `GET /api/users/me/recent-players` (R-FRIEND-11)
  self-joins this table on `game_id` to find who somebody has been playing with:
  the caller's seats give the games, the other seats give the accounts. Bounded by
  `game_records.finished_at` over a 30-day window rather than by a page of history,
  so the scan rides `ix_game_records_outcome_finished_at` and a returning player
  gets nothing rather than something a year old. The **live `users` row** supplies
  the name and picture, not the snapshot above: a snapshot is what somebody was
  called in that game, and this list offers a friendship with who they are now.
  That also means a deleted account drops out for free, since `user_id` is set
  null when it goes.

### `turn_records`
`id` · `game_id` (CASCADE) · `round_number` · `turn_number` · `drawer_user_id` /
`drawer_participant_id` (`CASCADE`, NOT NULL) · frozen drawer presentation · `prompt` ·
`prompt_version_id` (FK → `prompt_versions`, RESTRICT) · `prompt_source_kind` ·
`duration_seconds` · `guesser_count` · `prompt_auto_picked` · `stroke_count` ·
`end_reason` (`all_guessed \| timeout`) · `wrong_guess_count` · `near_miss_count` ·
`created_at`.

`uq_turn_records_game_round_turn` enforces one turn per game/round/turn number.
`ck_turn_records_prompt_identity` enforces that `curated` turns have a version ID and
non-curated turns do not — so curated turns are joinable **without text
normalization**, while custom and fallback turns retain only their factual text
snapshot. The `legacy_unknown` provenance sentinel was removed with the rest of the
pre-v1 accommodations; every turn names a real source kind, and the drawer's seat
(`drawer_participant_id`) is `NOT NULL` with `ON DELETE CASCADE` — a seat only ever
goes with its whole game.

### `turn_drawings`
`turn_id` **PK** (CASCADE) · `game_id` (CASCADE) · `status` · `format_magic` ·
`format_version` · `payload` BLOB · `byte_size` · `checksum_sha256` · `object_key` ·
`unavailable_reason` · `failure_code` · `reaction_count` · `hot_score` · `gallery_share_count` ·
`gallery_shared_at` · `gallery_withdrawn_at` · `gallery_hidden_at` · timestamps.

`status` ∈ `pending \| ready \| unavailable \| failed \| deleted`.
`ck_turn_drawings_ready_identity` requires a `ready` row to carry a complete format
identity, size, checksum, and either inline bytes or an object key.
`ck_turn_drawings_erased` requires a null payload once unavailable or deleted.
`byte_size` ≤ 8 MiB. `ck_turn_drawings_reaction_count` and
`ck_turn_drawings_gallery_share_count` keep both counts non-negative;
`ix_turn_drawings_gallery_top` `(reaction_count, gallery_shared_at)`,
`ix_turn_drawings_gallery_hot` `(hot_score)` and `ix_turn_drawings_gallery_new`
`(gallery_shared_at)` serve the **Gallery**'s Top, Hot and New orders (#524), each
**partial** on `gallery_share_count > 0`: only shared drawings are in the Gallery
(#1430), they are a small part of every drawing kept, and no order reads another row.

`reaction_count`, `gallery_share_count` and `hot_score` are the Gallery's
**projections** (R-GAL-05): how many rows `turn_drawing_reactions` and
`turn_drawing_shares` hold for the turn, and reddit's
`log10(max(n, 1)) + gallery_shared_at / 45 000 s` — zero while nobody shares it — kept
on the row so the Gallery filters and Top over the whole history orders by a column
rather than counting on read, and Hot orders by a score that never changes for one row
except when its count does — the decay is the newer rows' larger second term.
`gallery_shared_at` is the moment the drawing first entered the Gallery, and it keeps
it (R-SHARE-05): taking the last share back and sharing again is not a new entry, or a
drawing could be bumped to the top of New by pressing twice. It is a fact rather than
a projection — the rebuild fills it from the share rows only where it is missing, and
moves it only earlier — and only erasure clears it. `gallery_withdrawn_at` is the
drawer's taking it out of the Gallery (R-SHARE-04): every share and pin went with it,
and nobody else may share it again until the drawer does, which clears it. Every reaction write sets both from the rows **under the row's lock**
(`SELECT … FOR UPDATE`, taken after the drawer's account lock — *Synchronization* under
`user_stats_daily`), and so does every share write, so two writes landing together
cannot each count only their own — from one grouped count by code, hydrating only the seated rows the room names,
never a row per reaction: every other reaction to a popular drawing waits on that lock,
and loading 5,000 rows under it held it for 22 ms median, 44 ms p95, against 2.6 and
2.8 ms now, flat in the number of reactions (#897, `benchmarks/reaction_write.py`, PostgreSQL 17); the finished-game write sets them with the row; erasure zeroes them with the bytes.
They are never the source of truth: `app.services.gallery_ranking` rebuilds them from the
reaction and share rows, one transaction per batch of rows locked before they are counted, so a
reaction landing mid-rebuild waits for its batch and then sets the row itself; a rebuild
reproduces exactly what the writes left. The revision that added the first two columns
backfilled both, the score in Python, so a drawing written before it ranked where a later
one would; the sharing revision (`e7f8a9b0c1d4`) zeroed every score, since nothing was
shared yet and nothing is deployed.

```bash
cd backend
.venv/bin/python -m app.services.gallery_ranking
```

`gallery_hidden_at` is a moderator's judgement about the lobby (R-GAL-09), not an
erasure: set, the drawing is out of the Gallery, This week, the gallery bytes route,
the gallery reaction door and every pinned shelf in one act — all of them read the flag —
and it cannot be newly pinned or shared, while its
bytes stay and the players who were there keep seeing it in their history. Released
clears it. Audited as `gallery.review_hidden` / `gallery.review_released` with
`target_type = 'drawing'` and the drawer as the target account, in the same transaction as
the decision: a hidden drawing with no ledger entry would be a lie, so neither lands
without the other, and the cached This week shelf is recomputed only once both have.

Every drawing from a completed game is kept **for as long as that game, in the same
transaction that records it**. The stored bytes are the canvas frame itself — the
actions, not a picture of them — so a drawing can be replayed and redrawn at any size,
and a PNG stays something the browser produces on demand rather than something the
server keeps. Since #547 the frame is written delta-recoded and deflated (`SKCD`, v2 since
#828 so that a pen's width changes do not break the run of small deltas — v1 rows keep
their decoder; about 4.5× smaller on a realistic drawing; a frame too small to earn deflate's overhead
stays a verbatim `SKCH` v1), and `byte_size` and `checksum_sha256` describe those
stored bytes. On PostgreSQL the `payload` column (here and on
`player_report_drawing_evidence`) is `STORAGE EXTERNAL`: out of line past the TOAST
threshold like any large value, but never handed to TOAST's compressor, which could only
spend CPU on already-deflated bytes and keep them as they were (measured: same TOAST
bytes, WAL per game 107 KB → 88 KB). Alembic does not compare storage, so the migration
round trip pins it. The format rules, the read-side bounds and the frozen golden blobs
are in [wire-protocol.md](wire-protocol.md) under *Stored format*. A turn whose bytes the recap had to drop for budget is recorded as
`unavailable` rather than **omitted**. Deleting an account erases the drawings that
account made while leaving the row saying so.

`GET /api/games/{game_id}/turns/{turn_id}/drawing` returns one, and only to a player who
was in that game; **every refusal is a 404**, so the endpoint never reveals whether a
game exists.

#### Storing the drawings

The bytes stay in the primary database. That was a decision, not an omission, and #471
took it on measurements rather than on the general principle that blobs belong in an
object store. Measured on PostgreSQL 17 over 200 games seeded through the real writer
(`benchmarks/drawing_store_footprint.py`, 4 seats × 8 turns, the realistic frame):

| | |
| --- | --- |
| One stored drawing | 7,638 B (`SKCD` v2; 34.6 KB on the wire) |
| `turn_drawings` per finished game | 67.2 KB — heap 1.6, TOAST 64.8, index 0.8 |
| Every other history table per game | 13.2 KB |
| WAL per game, `turn_drawings` alone | 86.2 KB |
| WAL per finished game, whole (staging, replay, the envelope's deletion) | 152 KB (#1259; 337 KB before the envelope carried prepared drawings) |
| Reading one drawing back, checksum verified and decoded | 1.4 ms p95 |

So a drawing is about **five sixths of what a finished game adds to the database**, and
it is the only blob kept indefinitely: exports expire after seven days, envelopes are
deleted as they are unpacked, a bug screenshot goes when the report is decided, and a
picture belongs to an account that can be deleted. The retention table below is the
whole argument — there is one unbounded blob, not six.

What that costs at the documented scale target, and what it would cost to move:

- **Growth.** The recorded load gate plays 50 games per 300 s. Saturated day and night
  that is 14,400 games/day, about 1 GB a day; a tenth of that duty cycle is 36 GB a
  year. Restore of a drawing-shaped gigabyte measured 15 s, so the first figure is past
  any sane RTO inside a year and the second is not.
- **Moving the bytes does not reduce them.** It changes which system holds them, adds
  request and bandwidth costs, and adds a second store to restore to a *mutually*
  consistent point.
- **It would break the one write that must not break.** A finished game is written
  all-or-nothing (R-HIST-03, R-HIST-26). A remote object is not in that transaction, so
  a move means staged upload, manifest publication, idempotent retry, orphan
  reconciliation and deletion tombstones — and it still would not fix what N-12 names,
  since a database that is down at the moment a game ends loses the game either way.
- **The option costs nothing to keep.** `object_key` already sits beside `payload`, and
  `ck_turn_drawings_ready_identity` already accepts a key *or* inline bytes; avatars are
  already content-addressed by SHA-256 (R-AVA-03). The seam is built and untaken.

**When to reopen it.** Restore time is the binding constraint, so the trigger is a size:
`turn_drawings` past **50 GB** (about 750,000 drawings), or a restore that breaches
whatever RTO #458 fixes, whichever comes first. `sketchy_drawing_store_bytes` is that
number, and `SketchyDrawingStoreLarge` watches it (see [slo.md](slo.md)) — a trigger
nobody can see is not a trigger. The measurements above are laptop-class (Apple silicon,
local SSD); a cloud host with slower storage moves the threshold down, not the argument.

**One thing an operator must know before a restore drill.** Stored drawings are already
deflated, so a backup of them **cannot be compressed below the live byte count**.
Measured over 1 GB of distinct drawing-shaped blobs: the live data is 1045 MB,
`pg_dump -Fc` produces 1082 MB in 51 s, and `pg_dump -Fc -Z0` produces 1898 MB in 12 s.
Compression is not shrinking the data — it is only undoing pg_dump's own hex doubling
of `bytea`, at four times the wall clock. The real choice for #458 is dump size against
dump time, and `pg_dump -Fd -j N` is the option worth measuring, not `-Z6` by default.

Because a database column has no integrity check of its own, an operator command walks
the whole store (#610): a keyset over `(created_at, turn_id)` below a watermark taken at
the start, metadata first and payloads in groups whose declared sizes fit a byte budget,
checking each row's size and format metadata against the bytes, the checksum, the
decoder registry and the decoded frame's structure. It can stop after `--max-rows` and
resume from the cursor it printed. Before #610 it verified the oldest `batch_size` rows
and reported the whole store clean.

```bash
cd backend && .venv/bin/python -m app.services.drawing_storage --batch-size 2000
```

### `turn_drawing_reactions`
`id` · `game_id` (denormalized) · `turn_id` · `user_id` (the reactor's **account**, indexed,
FK to `users` CASCADE) · `participant_id` (the reactor's **participant seat** when they had
one, nullable, indexed) · `emoji` · `set_version` · `created_at` · `updated_at`, with
`uq_turn_drawing_reactions_turn_user` on `(turn_id, user_id)`,
`uq_turn_drawing_reactions_turn_participant` on `(turn_id, participant_id)`,
`fk_turn_drawing_reactions_turn_same_game` on `(game_id, turn_id)` and
`fk_turn_drawing_reactions_seat_same_game` on `(game_id, participant_id)`, both CASCADE.

`emoji` ∈ `heart \| laugh \| wow \| fire` — the **Reaction set**, version 1. Stored as a
code, never a glyph, and a code shipped is never removed from the `CHECK` or reused: the
stored-drawing rule (R-HIST-18) applied to an emoji, so retiring one changes what is
offered and nothing an old row means. `set_version >= 1` says which version of the set the
code was chosen from.

- One reaction per registered account per drawing is the `(turn, user)` unique constraint.
  The key became the account with the **Gallery** (#524): anyone signed in may react to a
  public-game drawing from outside the game, and most of them hold no seat in it. The
  writer resolves identity aliases before the write, so a person merged from two
  identities holds one row; guests cannot react, so a guest-to-account merge brings none.
- The seat rides beside the account when the reactor sat in the game — it carries the
  frozen presentation that names the reaction in the room and in history, and becomes
  the **Deleted player** tombstone with everything else — and is null for a reaction
  given from the Gallery or a pinned shelf, which only counts (R-REACT-05). A deleted
  account is a tombstoned `users` row, never a removed one, so the account key holds and
  the reaction keeps counting (R-REACT-10). The `game_id` denormalization is what lets the
  composite foreign keys say the turn and the seat belong to the same game.
- Reactions never touch `score_events` (R-HIST-11).

**Flow.** Reactions given while the game is live sit on the `Room` and ride in the
finished-game transaction, validated against the rows being written — a reaction on a turn
that did not survive, from a seat not in the game, from the drawer, from a guest seat, or
carrying an unknown code is a `ValueError`, not a row. They are part of the payload digest,
so a retry carrying different reactions is a conflict. Later writes — the recap, the
profile page — go through `set_drawing_reaction`, one transaction that resolves the
requester's seat by identity, refuses the drawer by seat and by account, refuses an erased
drawing, upserts or deletes the row, and moves the drawer's `reactions_received`.

Deleting an account deletes the reactions on the drawings it erases; the reactions that
account *gave* stay, attributed through the tombstoned seat.

### `turn_drawing_shares`
`turn_id` · `participant_id` — together the **PK** · `game_id` (denormalized) ·
`user_id` (the sharer's account, nullable, indexed, FK to `users` **SET NULL**) ·
`created_at`, with `fk_turn_drawing_shares_turn_same_game` on `(game_id, turn_id)` and
`fk_turn_drawing_shares_seat_same_game` on `(game_id, participant_id)`, both CASCADE, and
`ix_turn_drawing_shares_participant_id`.

A player who sat in the game putting its drawing in the **Gallery** (#1430). A drawing
is in the Gallery while it holds at least one (R-SHARE-01), counted on the drawing row
(`gallery_share_count`). One row per sharer's **seat**: every sharer sat in the game —
the drawer from any game, anybody else, guests included, from a public one
(R-SHARE-02) — and the seat carries the frozen presentation the Gallery credits the first
sharer with (R-SHARE-06). The account sits beside it, canonical when written, for the
writes that go by account: taking one's own share back, and erasure. SET NULL rather
than CASCADE: the retention purge of a guest removes the account row and not the
history it made, so the share stays, credited to the seat (R-SHARE-08).

**Flow.** Shares made from the turn results while the game is live sit on the `Room` and
ride in the finished-game transaction with their moments, validated against the rows
being written like the reactions — a share by somebody other than the drawer of a
private game's drawing, or of one its drawer took out, is a `ValueError`; a blank or
unkept drawing's is dropped. They are part of the payload digest and of the handoff
envelope (version 4). Later writes — the recap, history, the Gallery's door, and the
pin write, since a pin is a share (R-PIN-03) — go through `set_drawing_share` (or the pin
write's own copy of its rules), one transaction that locks the sharer's and the drawer's
accounts in one ascending statement and then the drawing row, checks who may share,
inserts or deletes, and sets the projections. The drawer's withdrawal deletes every
share and every pin of the drawing and sets `gallery_withdrawn_at`.

Deleting an account deletes the shares of the drawings it erases and every share it
made, and sets the projections again on the drawings that lose one (§11).

### `gallery_shelf_reviews`
`turn_id` **PK** (→ `turn_records`, CASCADE) · `decision` ∈ `released \| hidden` ·
`decided_by_user_id` (→ `users`, SET NULL, indexed) · `decided_at`.

A moderator's answer about one drawing's place on the Gallery's **This week** shelf
(#524, R-GAL-10), one row per turn — a later decision replaces the earlier one, so
*undecided* is the absence of a row. Read only while `app_config['gallery.shelf_review']`
is set: then the shelf takes released drawings only, and `GET /api/moderation/gallery`
lists the current Top-week candidates with no row. The switch holds the shelf and nothing
else; the Gallery page publishes after the fact for the reasons R-LIST-13 gives against
pre-approval, and the shelf is held because it is the one place a drawing is put in front
of everyone who opens the app, chosen by nobody. A hidden decision also sets
`turn_drawings.gallery_hidden_at`, so it holds whatever the switch says.

### `profile_drawing_pins`
`user_id` (CASCADE) · `turn_id` — together the **PK** · `game_id` (denormalized) ·
`position` · `created_at`, with `uq_profile_drawing_pins_user_position` on
`(user_id, position)`, `ck_profile_drawing_pins_position` holding `position` to `0..5`, and
`fk_profile_drawing_pins_turn_same_game` on `(game_id, turn_id)` → `turn_records`, CASCADE.

The drawings an account chose to show on its profile (#440): up to six, in the owner's
order. A pin is the **pinner's act**, not a fact about the drawing, which is why it hangs
off the account where a reaction hangs off a seat — it lasts as long as the account wants
it there, and a deleted account has no profile left to show a shelf on. The cap and the
order are in the schema, not only in the write path: a seventh pin has no slot to sit in,
whatever writes it. The `game_id` denormalization is the same-game edge the rest of the
history graph uses (#512), so a turn from another game can never be named by mistake.

What may be pinned is checked by the write, since neither rule is expressible here: a turn
with a `ready`, unhidden, non-blank drawing the pinner sat in the game of and may share
(R-SHARE-02) — their own from any game, another player's from a public one its drawer has
not taken out — credited through the turn's frozen drawer snapshot. A pin **is** a share
(R-PIN-03): the write shares every pinned drawing the pinner has not shared yet, in the
same transaction, with its inbox entry for the drawer. Only a `registered` account may pin, so a guest merge
never brings a shelf with it.

**Reads.** `get_profile_pins` lists the shelf, joined to the turn and the drawing so a pin
whose drawing has left the Gallery or is no longer ready is left out rather than shown as
a hole. `get_pinned_drawing` and its checksum twin are the
one other door beside `get_turn_drawing`'s participant check (R-HIST-16): a separate
query whose authorization is the join to this table, so the two can never loosen each
other by accident (R-PIN-06).

**Flow.** One write, `set_profile_pins`, replaces the whole shelf with the ordered list
given: pinning, unpinning and reordering are the same transaction, every turn is checked
before anything is deleted, and a refused list leaves the shelf as it was. Deleting the
game or the turn takes the pin through the cascade. Erasing a drawing does not — erasure
is a status on `turn_drawings`, and no cascade reaches a status — so the account-erasure
path deletes the pins on the drawings it erases, the way it deletes their reactions, and
the pins the erased account itself made. A drawer's withdrawal deletes every pin of the
drawing, and taking one's own share back deletes one's own pin of it (R-SHARE-04).

### `turn_participant_outcomes`
One row per current or late-arriving non-drawer seat, per turn.

`turn_id` · `participant_id` (**primary key**, and same-game composite FKs with
`game_id`, CASCADE) · `eligible` ·
`eligibility_reason` (`eligible \| afk \| disconnected \| joined_late`, the last written for one arrival only - an account that already knew the drawing's prompt when it joined as a player, having spectated it or guessed it with an earlier seat (#1317) - and by games finished before a mid-turn arrival became an ordinary guesser) ·
`outcome` (`correct \| incorrect \| no_attempt \| ineligible`) ·
`terminal_state` (`active \| afk \| disconnected \| left`) ·
`correct_guess_time_seconds` · `wrong_guess_count` · `near_miss_count` ·
`hints_used` · `points_spent_on_hints` · `points_awarded` · `created_at`.

One row per seat per turn is the identity: the pair is the primary key (#548). Paired
`CHECK`s keep the record coherent: eligibility and its reason must agree with the
outcome, a correct time exists **iff** the outcome is `correct`, and so does
`points_awarded` (`ck_turn_participant_outcomes_points`, never negative).

**The correct guess is the outcome, not a row beside it (#548).** Until #548 a correct
outcome had a scoring child in `turn_guesses`: a surrogate key, a link back to the
outcome, the seat's presentation copied from `game_participants`, the guess time copied
from the outcome, and the net award. Two records of one fact were two chances to
disagree, and the writer spent a proof keeping them equal; the row cost about 20 KB and
72 rows per game of 8 seats × 24 turns, with five index structures. The award now rides
on the outcome as `points_awarded`, NULL on every outcome but `correct`; the gross award
and the hint charge stay the ledger's (`score_events`), which the writer still proves
against these rows. Everything else the guess row held is on the outcome or the seat.

**When drawing begins, the server freezes the eligible guesser seats**
([`backend/app/services/game_flow.py`](../backend/app/services/game_flow.py)). Players who
were AFK or disconnected at that instant remain ineligible until the next turn; their text
is treated as restricted chat rather than a guess that could reveal the prompt. A player who
joins while the drawing is underway is *added* to the frozen population instead
([`backend/app/game.py`](../backend/app/game.py)) and is recorded as the eligible guesser
they were — unless its account already knew that drawing's prompt, having spectated it or
guessed it with an earlier seat, when it is recorded `joined_late` and ineligible (#1317). Ordinary history retains these
numeric facts but **not guess text** — text retention and evidence are governed separately
(§5).
No-scoring games record the same factual outcomes with zero awarded points and never
invent hypothetical score awards.

### `score_events`
The ordered, **append-only** point ledger for a scored game.

`game_id` (CASCADE) · `event_order` · `participant_id` (CASCADE) · `turn_id`
(CASCADE) · `event_type` · `points_delta` · `corrects_event_order` (same-game self-FK,
RESTRICT) · `created_at`. Primary key `(game_id, event_order)`.

**An event is identified by its place in its game's ledger (#552).** The writer proves
the order consecutive from one and every reader sorts by it, so a surrogate UUID beside
it bought two index structures - its own key and a `(game_id, id)` pair for the
same-game correction key - and a 16-byte correction reference, for an identity nothing
outside the row ever used. Rule versions (`scoring_version`, `rule_snapshot_version`)
are the game's: every event of a game was scored under them, so the export reads them
from `game_records` rather than from a copy on each row.

`event_type` ∈ `guess_award \| hint_charge \| drawer_bonus \| correction`, with
`CHECK`s that pin the sign of each: awards and bonuses positive, hint charges negative,
corrections either but never zero. A `correction` must name an earlier event by its
order (`ck_score_events_corrects_earlier`: strictly smaller, so never itself and never
one that has not happened yet); nothing else may. The self-FK's `RESTRICT` is about a
correction outliving its target, not the game's lifecycle: deleting the game cascades
both away in one statement. Corrections are rare, so the index that serves that
`RESTRICT` (`ix_score_events_correction`) is partial over the rows that carry a target.

**Corrections append; prior events are never rewritten.** The history writer proves the
gameplay events agree with the correct guesses and hint spend, then requires every
participant's ledger sum to equal the cached final score **in the same transaction**.

**Same-game coherence is structural.** Composite foreign keys pair cross-row
references with their `game_id` (or `turn_id`): an event cannot award to a seat, charge
a turn, or correct an entry belonging to another game; a turn's drawer seat must belong
to the turn's game; and an outcome's turn and seat must share a game
(`turn_participant_outcomes` carries a denormalized `game_id` precisely so that is
expressible). The writer's transactional proofs cover the arithmetic; these constraints
cover the addressing, so a second writer, a repair script, or a partial restore cannot
silently disagree.

Legacy games explicitly use ledger version `0`, because gross awards and drawer bonuses
cannot be reconstructed from their net totals. No-scoring games use the current version
with an **empty** event list.

### `game_prompt_sources`
`game_id` (CASCADE) + `prompt_list_id` (no foreign key) composite **PK**.

The lists that were actually present in the game's real pool **after custom-prompt
shadowing** — not merely the configured slugs. Until #1358 these rows named the exact
revision, `RESTRICT`, and that pin is what made a deleted list a tombstone and gave the
reclaim its holds. No reader needs it: each turn stores its prompt text and version.
Since #1362 `prompt_list_id` is an **opaque value with no foreign key**, here, in
`turn_prompt_offer_sources` and in `prompt_usage_facts`: a list is deleted outright, and a
cascade over every game that played it grew with how much it was played — about 300,000
rows for a list played in ten thousand games, a multi-second transaction inside the
owner's Delete or an account erasure. The row keeps naming the list that was played,
which a deleted list's id no longer resolves to; it is a random uuid, so it says nothing
about the owner. The writer writes the ids the game drew from as they are, checking and
locking nothing (until #1362 it named only lists that still existed, held `FOR KEY SHARE`).
Nothing reads a game's sources by list, so the list's side is not indexed.

---

## 7. Prompt provenance

### `turn_prompt_offers`
Every prompt option offered in a completed turn gets an ordered immutable row.

`id` · `turn_id` (CASCADE) · `position` · `prompt_version_id` (RESTRICT, nullable) ·
`prompt_snapshot` · `selected` · `source_kind` (`curated \| custom \| builtin_fallback`) ·
`created_at`. `uq_turn_prompt_offers_turn_position` orders them;
`uq_turn_prompt_offers_selected` is a partial unique index giving exactly one selected
offer per turn.

Custom and fallback options have explicit source kinds and **null curated identities**,
so a text collision cannot inflate curated statistics or make a bad prompt untraceable.
The turn row's selected offer, text, source kind, and version are kept identical by both
database checks and the history writer.

Exact offers are **private export data** - in the drawer's own export, for the turns
they drew - and are shown on no history page (#1254).

### `turn_prompt_offer_sources`
`offer_id` (CASCADE) + `prompt_list_id` (no foreign key, #1362) composite **PK**. Every list the draw
found an offered curated prompt version in — `game_prompt_sources`' rule, per offer (#1358).

---

## 8. Prompt content

Prompt content has a **stable identity independent of its spelling**.

### `prompt_concepts`
`id` · `created_at`. That is the whole table: a concept is pure identity. Equal text
never merges concepts implicitly.

### `prompt_versions`
An immutable, language-specific wording.

`id` · `concept_id` (CASCADE) · `language` · `version` · `canonical_answer` ·
`match_key` · `editorial_difficulty` (`unspecified \| easy \| medium \| hard`) ·
`content_rating` (`everyone \| teen \| mature`) ·
`moderation_state` (`active \| under_review \| hidden`) · `moderated_by_user_id` ·
`moderated_at` · `unlisted_at` (nullable, partial index) · `unlisted_from_list_id`
(nullable, `SET NULL`, partial index) · `created_at`, with
`uq_prompt_version_concept_language_version`. A save numbers a new wording above the highest
version its concept has stored, not above the working copy's: Discard changes puts an
edition's older wording back while the newer one stays (#1392 review).

**`unlisted_at`** is when a save, a Discard changes or a list's deletion last took the version out of a
working copy (#1359). A game that drew it before then holds it in memory and writes it into
its turns when it ends, so the hourly `unlisted_prompt_versions` sweep
(`reclaim_unlisted_versions`) collects it only `UNLISTED_GRACE` (a day) later, and only
if nothing names it — no list, turn, offer, usage fact, report or takedown record; one that
something does name is unstamped, kept by that reference from then on. A revision used to
keep a replaced wording that long; a save writes none now.

**`unlisted_from_list_id`** is the list it was taken out of, set and cleared with
`unlisted_at`. A reader who opened a catalogue page before the save can still report the
prompt they saw on that list during the grace window — membership is the working copy,
*or* any of its editions (what a catalogue reader sees, #1360), *or* a version unlisted
from that list — and a takedown decided then still reaches the
list's owner. Without it, an owner could edit a reported word out of the list and the
report would be refused as "not on this list" (#1385 review).

A moderator's decision is the concept's, not one wording's: resolving a report sets
`moderation_state`, `moderated_by_user_id` and `moderated_at` on every version of the
concept, an owner's edit that writes a new version (an alias added, an answer respelled)
carries them to it, and a new version whose answer or alias matches any prompt its owner has a
takedown record for (`prompt_takedowns`, §5), in the same language or in no language (`zxx`, which shares its words with every language, #821) — the same word when a room that plays both keys them as one word (its canonical key, not the spellings a guess is accepted under), so a hidden German **Bär** stops an agnostic **Bär** but not **Bar**, and between two agnostic lists, played in every room, any room's fold counts (#1091) — a word typed back in, into
this list or another, or another entry respelled into it — is
born with them — so a hidden word stays hidden (#1020). A concept born hidden that way is
recorded as the owner's takedown too, so the word reaches a list only it shares words with,
and a restore finds it. A concept belongs to
one list; copies mint their own. Bundled seed versions are the operator's own editions and
start `active`.

Supported languages: `en`, `de`, `es`, `fr`, `it`, `nl`, `pt`, `pl` — the Latin
registry (Polish joined it in #771), which case-folds, collapses whitespace, folds canonically decomposable
accents, and reads every apostrophe a keyboard writes as the plain one (#1011; the
bundled lists are written with the plain one, so no stored key changed)
([`backend/app/prompt_content.py`](../backend/app/prompt_content.py)). Other
BCP-47 tags are **rejected until their matching semantics are implemented.** Content may
also be `zxx`, BCP-47's "no linguistic content": a list in no language (R-PROMPT-12). The
four content tables that carry a language (`prompt_versions`, `prompt_aliases`,
`prompt_lists`, `prompt_list_editions`) admit it in their `CHECK`; `user_settings` and
`room_presets` do not, because a room needs a language to fold guesses under.

`match_key` is that fold for the row's own language, without spaces, hyphens, dots or
apostrophes and with `&` spelled as the language's "and" (#1396; a key written before
that keeps its separators, and the seed refuses such a database as "changed in place" -
it is recreated rather than migrated, as the Pre-v1 note says), with the language's
transliterations applied first (German **Mädchen** stores `maedchen`, not `madchen`).
A `zxx` row folds with the shared rule alone — **Müller** stores `muller` — because the
key must not depend on the room that plays it; a German room still accepts `mueller`,
since acceptance folds the answer's text under the room's language.
It is deliberately **one** string: it is the identity these unique constraints are
built on. A language where two spellings are both correct accepts them at match time
instead (R-GUESS-01) — the alternative would be an identity that is a set, and two
prompts could then be equal and unequal at once.

### `prompt_aliases` and `prompt_version_aliases`
`prompt_aliases`: `id` · `concept_id` (CASCADE) · `language` · `answer` · `match_key`,
unique on `(concept_id, language, match_key)`.

`prompt_version_aliases`: `prompt_version_id` + `alias_id` composite **PK**.

Aliases are unique within a concept and language, and are attached **separately to each
version**, so changing an alias later cannot rewrite how an older game matched guesses.

### `prompt_tags`, `prompt_version_tags`
Stable searchable categories (`slug` unique) and explicit per-version membership.
Deliberately relational rather than a JSON tag blob.

### `prompt_lists`
`id` · `owner_user_id` (`SET NULL`) · `slug` **unique** · `name` · `description` ·
`language` · `is_bundled` · `is_copy` · `copied_from_list_id` (`SET NULL`) ·
`copied_from_edition_id` (`SET NULL`, partial index) ·
`visibility` (`private \| public`) ·
`moderation_state` (`active \| hidden`; a hold is the edition's) · `moderated_by_user_id` ·
`moderated_at` · `version` · `letter_counts` · `letter_total` · `shelf` · `series` ·
`shelf_position` (all three nullable) · `edition_count` ·
`content_hash` · `published_at` (nullable) · timestamps.

`edition_count` numbers the list's next edition, so a number is never reused after the
edition that held it was replaced. `content_hash` is the working copy's digest, written by
every save beside the histogram (and copied from the live edition by Discard changes, #1363), in the form an edition's is: compared with the latest
edition's — the pending one while one waits, else the live one — it says whether the list
has **unpublished changes** without reading either one's prompts (#1360). It digests
version ids, so a prompt changed and changed back reads as changed until the next publish.
`copied_from_edition_id` is the edition a copy was taken from while it lasts; `copied_from_list_id` is what the credit reads.

`shelf`, `series` and `shelf_position` place an **official** list in the room picker's tree
(#1374, R-PROMPT-14): a shelf slug from `prompt_content.PROMPT_SHELVES`, an optional
series slug within it, and its position there. They are navigation, not content, so
`upsert_bundled` rewrites them - and the list's tags in `prompt_list_tags` - on every seed
without a new list version, as it does the name. `ck_prompt_lists_shelf_is_bundled` keeps
them off a player's list, `ck_prompt_lists_shelf_position` makes a shelf and a position
come together, and `ck_prompt_lists_series_on_shelf` keeps a series on a shelf. No CHECK
names the shelves: adding one is a code change to the registry, not a migration. Rows
migrated in start empty and the next start fills them.

`letter_counts` (JSON) and `letter_total` are the working copy's **letter histogram**
(#1359; it lived on each revision before): every save that changes content rewrites
them, and `upsert_bundled` writes them when seeding. Wheel pricing needs how common each
letter is among the prompts a game can draw (R-HINT-03), a distribution rather than the
words, which is what lets a room price letters without keeping its prompt pool in memory.
`letter_counts` tallies a–z, the only letters that can be bought; `letter_total` counts
*every* alphabetic character, including those outside a–z, because it is the divisor and
a list in such a language must keep the ratios it would have had. Membership is counted
rather than moderation state: a takedown does not rewrite the list, so a tally that
tracked moderation would be wrong from the first takedown and stay wrong through any
restore. The cost is that hidden content is priced without being drawable, which R-HINT-03
records among the histogram's approximations.

**Deleting a list deletes it** ([`services/prompt_reclaim.py`](../backend/app/services/prompt_reclaim.py),
#1362): the row goes in the owner's request, and its working copy, editions, tags and stars
go with it (`CASCADE`); a copy of it lets go of it (`SET NULL`), and a report about it keeps
its id, as the history does; the history its games wrote keeps its id as an opaque value (see
`game_prompt_sources`). So a delete costs what the list holds, never how much it was
played. The versions it held are stamped `unlisted_at` first, locked in id order, so a
room that drew from it before the delete still finds them when it writes its game, and
the unlisted sweep collects them a day later if nothing else names them.

Until #1362 a delete only **retired** the list: `deleted_at` was set and an hourly sweep
(`retired_prompt_lists`) collected the row a day later, after draining its play history
in budgeted batches, because that history held foreign keys to it (#1376 review). Before
#1358 a list a game pinned stayed a tombstone for ever (#478), and until #1357 holds for
hidden words and pending reports kept revisions alive (#1091, #1354) — three review bugs
between them. The takedown is its own record now (`prompt_takedowns`), a reported version
is kept by its report, and there is no tombstone left to hold anything.

Account erasure deletes the account's lists the same way (`delete_owned_lists`), its
authored name, description and prompts going with them.

`ck_prompt_lists_bundled_owner` forbids an owner on a bundled list;
`ck_prompt_lists_published_at` requires `published_at` on a public one.

**Publication is an act, and the act is what is gated.** `POST .../publish` is its
own route with its own trust gate (R-LIST-12), rate limit and audit event
(`prompt_list.published` / `prompt_list.unpublished`, on the `prompt_list` target type
the ledger already allowed). A `visibility` field on the save would be a way around all
three, so a save carries no visibility at all: `create_owned` writes every list private
and `update_owned` never changes it. Without that, fixing a typo could take a list out of
the catalogue, or a crafted save could put one in without the gate.

Unpublishing leaves a **`hidden`** state alone. Leaving the catalogue is the owner's act
and moderation is somebody else's; if withdrawal cleared a takedown, unpublishing would
be the way to launder one. It does release **`under_review`**, which is not a finding:
on a list, that state is written in exactly one place — a publish under the operator
switch — so it only ever means "waiting to be published". Once the owner withdraws there
is nothing left to publish, and keeping the hold left a private list in the moderators'
queue where it could still be decided on.

The gallery's shelf has a switch of the same shape, `app_config['gallery.shelf_review']`
([`services/gallery_shelf.py`](../backend/app/services/gallery_shelf.py)), written by
`POST /api/admin/gallery-shelf-review` and audited as `gallery.shelf_review_changed`; it
holds the Gallery's **This week** for a moderator's release and nothing else
(R-GAL-10, `gallery_shelf_reviews` in §6).

The operator switch is `app_config['prompt_lists.publication_review']`
([`services/publication_policy.py`](../backend/app/services/publication_policy.py)):
with it set, a publication — a first one or a Publish update — writes a **pending
edition** (`prompt_list_editions.state = under_review`) instead of a live one, and the live
edition, if any, keeps playing while it waits (#1360) — unless the list was withdrawn, whose live edition is dropped so nothing unreviewed returns with it. A list it holds waits in `GET /api/moderation/prompt-lists`, which is a queue of its own
rather than an entry in the report queue: nothing was complained about, so there is no
report to hang it on, and the owner cannot make one (a self-report is refused). Without
that queue the switch was a trapdoor — held lists were out of the catalogue, unplayable,
and reachable only by editing the database. "Held" is a pending edition of a public list
that is not hidden, one predicate the queue, the detail route and the decision share.

A reviewer reads the pending edition's prompts through
`GET /api/moderation/prompt-lists/{id}`, and the decision carries the edition `number`
they read as `expectedVersion`. Both are needed. Without the first, a release was made
from a name and a prompt count, so the switch could not keep out anything it was turned
on to keep out. Without the second, reading was not enough either: an owner can publish
again while an edition waits, which replaces it with the next number, and a moderator
could read one and release the other — the bait and the switch. A stale number is a 409,
and the audit event records which edition was decided on. A save the owner makes without
publishing changes only the working copy, so it cannot reach a release at all. A release
makes the pending edition live and deletes the one it replaces; a takedown hides the list
and drops the pending edition, as a takedown from a content report does (#1386 review).

It is read per publish rather than cached, because a cached posture is stale exactly
when it matters — just after an operator turned it on because something is going wrong —
and it is **not retroactive**, since sweeping already-published lists into a queue would
both punish people for a rule that did not exist when they acted and produce, in one
moment, the backlog this design exists to avoid.

**Three grounds admit a list into a room**, checked in the one `_pinned_lists` (and, for a mixed room,
`_pinned_mixed_lists`) helper that room creation and Start's re-authorization share: bundled, owned by the
requester, or **published** — played from its live edition when the room's host does not
own it (#1360), so the room carries that edition's id beside the list's. The sharing is the point — the
checks a room is admitted by stay the checks its prompts are drawn under (R-LIST-07), so
an unpublish or a takedown between the picker and Start refuses the room visibly rather
than shrinking its pool. A room preset needs nothing of its own: it stores slugs, which
are resolved through that same helper.

**The catalogue is one predicate, in one place.** Public, active, and with a live edition — served by `ix_prompt_lists_published`, which is partial on the first
three; a row shows the live edition's name, description, tags and prompts, never the
working copy's (#1360). A
takedown or a deletion therefore drops a list out of the catalogue without a second read
path having to agree, which is the property that made post-hoc moderation defensible in
the first place. Star counts are a correlated aggregate over `prompt_list_stars` rather
than a column, and tag filters are one `EXISTS` per tag against the live edition's tags
(`prompt_list_edition_tags`), bounded by `MAX_LIST_TAGS`. Paging is by offset with a ceiling
(`MAX_COMMUNITY_OFFSET`): nobody reaches page four hundred by reading, so a request that
deep is a scrape, and a filter is the better answer than a longer scroll.

**The star order is cached; the stars are not** (#901). Ranking by stars has to count
every published list's stars before it can return the first page — 35 ms a page at
5,000 lists and 120,000 stars, linear in both, and repeated by every scroll. The
repository keeps the **order** — the ranked list ids for each language and tag set, as
deep as `MAX_COMMUNITY_OFFSET` reaches — for `CATALOGUE_RANKING_TTL_SECONDS` (60 s),
the `GalleryShelfCache` pattern; one worker owns it, so it is exact to within the TTL.
A page then fetches its own rows by id with their live counts, 2.5 ms at the same size,
the same as `newest` (`benchmarks/catalogue_star_page.py`, PostgreSQL 17). The page read
re-applies the catalogue predicate and the language and tag filters, so a takedown,
retirement, unpublish or dropped tag leaves at once; a publish, or a save that changes
a published list's tags, through this process resets the ranking; a star moves a list within the
TTL while its count is right immediately. If even the minute's recompute starts to
hurt, a disposable `star_count` projection with a rebuild command is the next step (the
`reaction_count` precedent), not a counter.

**`published_at` is the record of an act, not a derived date.** Publishing is
gated, rate-limited and audited (R-LIST-11, R-LIST-12), so the schema refuses a
public row that carries no moment it became public — the hole worth closing here
rather than in a code path, because a `visibility` value on its own cannot say the
act happened. `updated_at` could not answer it either: that moves for every edit.
Unpublishing clears it, so a later publish is a new act with its own moment.
`ix_prompt_lists_published` is partial on published-active-present, which is the
community catalogue's whole question and the join the star counts hang off.
The bundled catalogue was backfilled to its own `created_at` rather than to the
migration's clock: it has been published since it was seeded.

**Governance is schema-first and deny-by-default.** A user-owned list is **Private** or
**Public**, and `ck_prompt_lists_visibility` allows nothing else. It starts Private, and
Public is reached only by publishing (R-LIST-02) — never by an ordinary save, which is
what keeps the gate in front of it from being optional. `ck_prompt_lists_public_is_bundled`
held the value for the official catalogue alone until #398 withdrew N-04.

**Unlisted is withdrawn** (R-LIST-03, migration `d8e9f0a1b2c3`). It was a third value
reachable by anyone holding a random `share_code`, and once publishing existed it was a
second way to let other people use a list with none of publishing's safeguards: a code
could be passed on without the trust gate, the audit event or the operator switch, and
could not be taken back short of making the list private. The migration turns every
Unlisted list Private — the one state its owner certainly agreed to — and drops the
column, its unique index and `ck_prompt_lists_unlisted_share_code`. Going back restores
the column but not the codes: they were capabilities, and minting new ones would grant
access nobody gave.
Ownership, fork provenance, revision tags, moderation actor/time, and moderation state
are relational fields — never JSON tags or a lossy `is_nsfw` flag. Difficulty and content
rating stay on the exact immutable prompt version where their meaning belongs.

Limits: an account may own at most **25** lists, and a saved list may contain at most
**500** prompts.

### `prompt_list_stars`
`user_id` (CASCADE) · `prompt_list_id` (CASCADE) · `created_at`. Composite primary key
on `(user_id, prompt_list_id)`, plus `ix_prompt_list_stars_list`.

**Facts, not a counter** (R-LIST-16). There is no `star_count` on `prompt_lists`, and
that is deliberate: a count derived from these rows cannot drift, cannot be
double-incremented by a retried request, and cannot be left too high by an account that
went away. The primary key already answers *did I star this* and *what have I starred*;
the index answers the other direction, *how many starred this*, which the catalogue asks
once per row and would otherwise scan for.

The composite key is also the idempotency: starring twice writes the same row, so the
endpoint needs no separate guard, and a retried request is safe without one either.
The count comes back from the write rather than as a delta the client applies, so two
browsers cannot disagree about it.

**Starring your own list is allowed.** It is a bookmark as much as a vote, and a rule
against it would be one nobody can enforce — a second account costs nothing, which is
what the trust gate on publication is for rather than this one.

Only a published list may be starred. A star is durable, and one on a private list would
be a lasting record that the starrer could see a list nobody but its owner can —
narrowing the target removes the problem instead of mitigating it. Unpublishing keeps the rows: the list stops being reachable,
and a later publish finds its stars where it left them.

**Account deletion removes them explicitly**, in `anonymize_account` — the `CASCADE` on
this table never fires, because deletion tombstones the user row rather than removing
it. Without the explicit delete a stranger's list would go on carrying the approval of
an account that no longer exists. They are also exported (`stars[]`, schema version 6),
naming the list and never its owner's account id.

**Revisions are gone** (#1362). Every save wrote one until #1359 — 500 item rows for a
one-word edit of a 500-prompt list — so storage and the owner's export grew with the
number of saves (#1250), bounded after the fact by a `superseded_list_revisions` sweep
with holds of its own (#1258). After #1359 only bundled seeding wrote them, for its
conflict check: a reseed of the same version with different content is a startup-failing
conflict. That check reads `prompt_lists.content_hash` now, the bundled digest the seed
writes on the list row; an empty one (a row nothing stamped) is written rather than
refused, and an older version seeded over a newer one - a rolled-back deploy - refreshes
only the metadata, as it did while revisions remembered every version. The migration that
dropped them stamped `unlisted_at` on every player wording a revision was the last to
name, so the unlisted sweep collects those a grace later like any other (#1394 review).

**A copy names the list it came from, on its own row** (`prompt_lists.copied_from_list_id`,
`SET NULL`, #1361). `fork_published` writes it and nothing else does, and a list's copy
count is read from it (R-LIST-20): the lists that point at it, not deleted — so the count is
a question asked of this column, served by the partial `ix_prompt_lists_copied_from`, and
there is no counter to keep in step. Until #1361 the pointer was `forked_from_revision_id`
on the copy's **first revision**, naming the exact revision it was taken from; editing the
copy superseded that revision, and a sweep that reclaimed it took the count, the credit and
the lineage with it (#1351). The credit reads the original as it is now (R-LIST-21), so the
list is all the pointer has to name; `copied_from_edition_id` says which content — a copy
is taken from the live edition, never the owner's unpublished changes (#1360). When the
source is **deleted**, the pointer goes: the reclaim deletes the list row and the `SET NULL`
clears it.

**`is_copy` is what survives it** (R-LIST-21). A copy credits the list it came from, and once the
pointer is cleared a copy looked exactly like a list nobody copied, so "copied from a list
that was deleted" could only be said for the day before the sweep. `is_copy` is set by
`fork_published`, never cleared, and deliberately a boolean: it says a list was copied and
nothing about what from — a name, an author or an id would be exactly what the deleted
list's author asked to take away. `ck_prompt_lists_copy_is_player_owned` keeps it off the
bundled catalogue, and `ck_prompt_lists_copied_from_is_copy` keeps the pointer off
anything that is not a copy.

That is deliberate, and it is why a copy's pointer holds nothing up. A copy is a live
list somebody else owns and edits; if its pointer kept the original alive, an author who
deletes their list could never actually remove it once a stranger had copied it. The copy keeps every prompt it took; it forgets only where they
came from, because the person they came from asked for the list to go. A fork gets **new prompt concepts and versions** rather than references
to the source's, so one owner's edit cannot rewrite what the other's list means, and
hidden versions are left out of the copy entirely.

An owner's tags come from a **curated vocabulary** (`prompt_content.LIST_TAG_VOCABULARY`,
R-LIST-18), seeded beside the bundled lists and idempotent: a missing slug is inserted
and a stale display name refreshed. A slug is never rewritten, because every list
tagged with it points at that row — a tag is renamed by changing its name. Free text was
refused: a tag is player-authored copy shown in a discovery surface, and a discovery
feature must not introduce a second kind of content to moderate.
`clean_prompt_tags` still takes any well-formed slug for **bundled** prompt content,
which is authored in the repository and reviewed as code; `clean_list_tags` is the one
that answers a request.

### `prompt_list_tags`
`prompt_list_id` (CASCADE) + `tag_id` (CASCADE) composite **PK**, indexed on `tag_id` for
the direction the community catalogue reads (*which lists carry this tag*). The working
copy's tags (#1359), rewritten in place by a save like the rest of it, a row added or
removed only for a tag that changed. They used to be copied onto every revision, so that a
filter agreed with the revision a game pinned; a game snapshots what it drew instead.
An official list's tags come from its seed file (`tags`) and are rewritten by every seed,
through the same helper a save uses (#1374).

### `prompt_list_editions`
`id` · `prompt_list_id` (CASCADE) · `number` (≥ 1, unique per list) · `state`
(`published \| under_review`) · `name` · `description` · `language` · `content_hash` ·
`letter_counts` · `letter_total` · `created_at` · `published_at` (null while pending), with
`uq_prompt_list_editions_one_per_state` on `(prompt_list_id, state)`.

An **edition** is an immutable snapshot of a published list's working copy (#1360),
written by `set_owned_publication` each time its owner publishes content that differs from
the edition already in that state: the live one (`published`) is what the catalogue shows
and what other players' rooms draw and copy; a pending one (`under_review`) waits for a
moderator under the operator switch (R-LIST-13) while the live one keeps playing — unless the list was withdrawn, whose live edition is dropped so nothing unreviewed returns with it. The
unique index is the "at most a live and a pending edition" rule: a Publish update or a
release deletes the edition it replaces (`drop_editions`), whose versions are stamped
`unlisted_at` / `unlisted_from_list_id` exactly as a save stamps what it drops, so a game
that drew one still writes its turns and a reader's open page can still report one for
the grace. A list that was public before editions got its working copy as edition 1 (live,
or pending if it was held) with an empty `content_hash`, which a first save then differs
from. Bundled lists have none: they play their working copy.

Why snapshot rather than publish the working copy: a save used to reach the catalogue and
every room at once, so nothing could be approved as it stood, and a moderator who read a
list could release a later save they never saw. An edition never changes, so approval
attaches to it and a decision names it by `number`.

### `prompt_list_edition_items`
`edition_id` (CASCADE) + `prompt_version_id` (`RESTRICT`, indexed) composite **PK** ·
`position`. An edition's prompts in order. `RESTRICT` because the orphan collection asks
first: a version an edition names is kept, and the unlisted sweep unstamps it.

### `prompt_list_edition_tags`
`edition_id` (CASCADE) + `tag_id` (CASCADE) composite **PK**, indexed on `tag_id`. The
catalogue's tag filter reads these: a retag reaches readers with the Publish update that
carries it, not with the save.

Editing a list uses **optimistic concurrency** on `prompt_lists.version` and overwrites the
working copy in place, writing only what changed (R-LIST-05, #1359). Setting or clearing
tags is such an edit and moves the version. The content language — a room language, or
`zxx` — cannot change after creation. A room resolves lists and draws at Start — the
game's snapshot (R-LIST-07) — from each list's working copy, or, in a room its owner does
not host, from its live edition (#1360); a finished game records the list (#1358).

### `prompt_list_localizations`
`id` · `prompt_list_id` (CASCADE) · `locale` · `name` · `description`, unique on
`(prompt_list_id, locale)`.

List `name` and `description` are **authored catalogue copy**; translated copy is stored
separately by *interface locale* and selected from `Accept-Language`, so translating the
UI never changes a list's **content language**.

### `prompts`
One prompt of a list's **working copy** (#1359): what its owner edits and what a room
drawing from it plays.

`id` · `prompt_list_id` (CASCADE) · `concept_id` (RESTRICT) · `prompt_version_id`
(RESTRICT) · `text` · `position` · `created_at`, unique on both
`(prompt_list_id, concept_id)` and `(prompt_list_id, text)`. `position` is the owner's
order; it is not unique, and a save rewrites only the rows that moved.

A save **overwrites** these rows in place rather than writing the list again: a reworded
prompt gets a new prompt version and its one row repointed, a removed prompt's row goes,
and the versions a save takes out of the working copy are stamped `unlisted_at`
(`prompt_versions`), collected a day later if nothing names them. Readers that must see one
save's prompts beside the same save's tags — the owner's editor, the moderators' held-list
read — hold the list row `FOR SHARE` while they read, so a save (which takes it
`FOR UPDATE`) waits for them rather than landing between the two reads (#1291 review).

**Prompt-list counts are derived from membership on read**, so adding or removing a
prompt cannot leave a cached total out of sync. An edit rewrites only the display rows
whose text or version actually changed; a row whose new text is another retained row's
current text (two answers swapped, or a new prompt reusing a changed one's old text) takes
a temporary text first, so the unique index never sees both. A save that restates the
working copy exactly — same concepts, answers, aliases and order, same name,
description and tags — writes nothing at all and keeps the list's version; a
metadata-only edit still moves the version, as R-LIST-05 requires (#613). Prompt
statistics are keyed by concept, so a row repointed at a new wording keeps them.

### `prompt_usage_facts`
Append-only per-game usage totals, **not** mutable counters on a display row.

`id` **PK** · `batch_id` · `prompt_list_id` (nullable, no foreign key) · `prompt_version_id`
(RESTRICT) · `occurred_at` · `scoring_mode` · `hint_mode` · `offer_count` · `pick_count` ·
`correct_guess_count` · `total_guesser_count` · `created_at`.

A fact names the **list** it was counted against, not the revision (#1358), and outlives
it: deleting the list sets the column null and keeps the fact, so a server-wide
observation is not silently decremented by an author tidying up. A nullable column cannot
sit in a key, so the fact takes a surrogate one; the triple used to be the key and the
retry's idempotency, and `prompt_usage_batches` (below) is what makes a retry a no-op.

A mixed-language turn (R-PROMPT-13) records the offer and the pick against the drawer's
language's version and each language's guessers against that language's version, so
a version can carry guessers with `pick_count = 0`: a language's statistics count the
players who met the prompt in it.

**Flow.** Each finished game appends one fact per used prompt version and list the draw
found it in, with the authoritative occurrence time plus scoring and hint modes
(`batch_id` is the game's UUIDv7, which is what makes a retry idempotent). Since #541
the batch is also a fact of its own: `prompt_usage_batches` (`batch_id` **PK** ·
`payload_hash` · `fact_count` · `recorded_at`) records that the batch was written and
with what content, so a retry can tell an identical batch (idempotent) from a different
one under the same id (`PromptUsageConflictError`), and a batch that touched no pinned
prompt (zero facts, still a row) from one never written at all. The batch carries each
version's source lists as the draw found them (`sources`), and the writer credits only
lists the game played, so a malformed call cannot credit one it did not; it reads no
membership at all. Until #1358 it asked the pinned revisions which versions they held
(#613), which a list's working copy could no longer answer once edited mid-game. A list
deleted while the game ran is credited all the same: `prompt_list_id` has no foreign key
(#1362), and a fact says which list was played. Stats are derived by **stable prompt concept**, so a later
wording revision keeps its history without matching on display text.

The indexes support time-window and rule filters; the Prompt stats page offers all-time,
30-day, and 90-day windows plus scoring/hint segmentation, and the minimum-guesser
ranking floor applies independently to the selected slice. `occurred_at`, `scoring_mode`, and `hint_mode` are
`NOT NULL`: every fact carries its authoritative occurrence time and rule dimensions,
so bounded and segmented reads never have to exclude unattributable rows.

**Runtime attribution observes the durable/live boundary.** Completed turns
snapshot nullable prompt-version source IDs, and usage writes credit those versions only
to the lists the game played. An ephemeral prompt has a **null source even when its
display text equals a curated prompt**, so neither its offers, picks, nor guess results
can inflate the curated list's statistics.

Facts contain **no user identifier**, so they remain reconcilable with retained,
anonymized game outcomes: deleting an account neither invents nor silently decrements a
server-wide gameplay observation.

### Seeding

Bundled lists live in
[`backend/data/prompt_lists/`](../backend/data/prompt_lists/) and are seeded at startup
by [`backend/app/db/seed.py`](../backend/app/db/seed.py), which then `ANALYZE`s the
prompt tables on PostgreSQL (skipping any a VACUUM holds, never failing startup): a
freshly seeded table has no planner statistics, and a thousand-prompt list's aliases
were then joined by walking all of them per prompt (#1367). The checked-in shape is
**identity-based, not text-keyed**:

```json
{"conceptId":"01a02b7b-b42d-7afc-a278-fc0ecc83b994","answer":"anchor","promptVersion":1}
```

- Equal text shares a concept **only** when the files deliberately repeat that ID.
- Changing capitalization, punctuation, wording, aliases, or editorial metadata requires
  the **same `conceptId` and a higher `promptVersion`** - one higher than the newest the
  database holds in that language. A database that holds none (a fresh install) seeds the
  file's version as it stands: it never saw the earlier wording, and refusing a version 2
  for want of a version 1 would stop every fresh install once one word was reworded
  (#1367).
- Adding, removing, or reordering membership requires a higher top-level list `version`.
- Optional `aliases`, `difficulty`, `contentRating`, and `tags` belong to the immutable
  prompt version.
- **Deploying different content under an already-seen list or prompt version is a
  startup-failing seed conflict**, not an in-place rewrite.

A **name list** (#1399) - the Pokémon generations, League of Legends, the video-game icons - is one file that
stands for a list per supported language, expanded before anything is seeded
([`app/db/name_lists.py`](../backend/app/db/name_lists.py)): a default spelling per concept,
and under `overrides` a language's own `answer` (with its `aliases` and `promptVersion`,
nothing else) where it names the concept differently. The rows it writes are exactly those
of one file per language, so the rules above apply per expanded list, and they move as
follows:

- The file's `version` is every expanded list's: raising it moves all of them.
- A language that inherits a concept takes the default's `promptVersion`, so raising the
  default moves every inheriting language; an override takes its own (1 when it gives
  none), so it does not follow the default. Moving a language from inheriting to
  overriding changes its spelling, so its override needs the version after the newest
  that language already holds - the default's, if it was following it - and the seed
  refuses a gap. Moving one back is the same in reverse: a language whose own version
  is behind the default's cannot simply drop its override, since it would jump to the
  default's version; keep an override that equals the default at the language's next
  version instead, which is what the Pokémon generator writes.
- Every supported language is expanded whether the file declares it or not; the
  declaration (`languages.inherit` / `languages.override`) is held to the registry by
  `tests/test_bundled_prompt_content.py`.
- Two files that define the same list, and a file that does not parse, fail startup
  naming the file.

---

## 9. Runtime analytics

### `runtime_events`
One raw observation. `id` (integer — the highest-churn table in the schema, purged
after 30 days, referenced by nothing; on SQLite an `INTEGER PRIMARY KEY` is the rowid
itself) · `event_type` · `occurred_at` · `room_id` · `user_id` (`SET NULL`) · `value` ·
`details` (JSON, SQL `NULL` when an observation carries none — not the JSON token
`null`, which is what the type stored before `PortableJSON` declared
`none_as_null`).

**Every observation is counted on `/metrics`** (`sketchy_events_total{event}`); only
those the database is for are written here (#965). Stored: `room.created`,
`room.closed`, `player.joined`, `player.left`, `player.disconnected`,
`player.reconnected`, `player.evicted`, `game.finished`, `game.abandoned` — keyed to an
account or a room, and what the Operations page's audited per-player activity view and
its room filter read, which Prometheus cannot and should not hold — and `timer.overran`
(`value` the milliseconds late, only past 250 ms) and `history.write_abandoned` (a
finished game's history or prompt-usage write the server gave up on; `details.kind` is
`game` or `prompt_usage`, `details.reason` is `timeout` or `error`, `value` is the
milliseconds spent before giving up — #482), each worth a durable row even if the
metrics stack was down when it happened (R-OBS-10). **Counted only**: `drawing.stored`
(the wire frame's bytes) and `drawing.encoded` (the same drawing's stored bytes, #895),
whose sizes are the `sketchy_drawing_*_bytes` histograms below; `command.throttled`,
which is `sketchy_socket_refusals_total{code="too_fast"}` per command (#882) and the one
type unbounded under abuse; and `recap.budget_dropped`. The `CHECK` on `event_type`
lists the stored set, so a counted-only type cannot be written by accident.
`game.started`, `turn.ended` and `canvas.payload_observed` were declared and never
written; #965 removed them.

Observations are **buffered and written in batches**, because a database round trip per
join would be felt as lag inside a drawing. The buffer is bounded and drops oldest when
full, **counting what it dropped**, so a gap is visible rather than silent. It is
flushed on the way out of a planned shutdown, so the observations describing a restart
are not the ones lost to it.

A flush takes the oldest 5,000 events but leaves them buffered until its transaction has
committed (#614): the rows go in as `executemany` chunks sized from the table's own
column count (about 4,300 rows under asyncpg's 32,767-parameter ceiling) with no ids
returned, and an observation naming an account that was erased or purged since is
detached from it (the erasure barrier, `app.auth.erasure`) rather than failing the
batch's foreign key. What can still be lost is counted apart, on the recorder and on
`/metrics`: overflow (`sketchy_events_dropped_total`), a transaction that failed before
its commit (`sketchy_event_flushes_failed_total`, the batch stays for the next flush), a
cancelled flush (`sketchy_event_flushes_interrupted_total`, kept too), and a commit whose
outcome the driver could not report (`sketchy_event_batches_ambiguous_total`,
`sketchy_events_lost_to_ambiguity_total`) — that batch is let go rather than retried,
because a raw row has no identity that would make a second write a no-op.

**The trend is Prometheus's.** Rows are kept `RUNTIME_EVENT_RETENTION_DAYS` (default 30)
and then deleted; nothing is rolled up first. A permanent daily roll-up,
`runtime_stats_daily` (a count, a sum and a maximum per metric per day, plus fixed
drawing-size buckets from #895), sat beside this table until #965: everything in it was
derivable from `sketchy_events_total` and the size histograms, and the one chart that
read it now reads Grafana. Keeping a trend past 30 days is therefore a Prometheus
retention setting (its default is 15 days; `--storage.tsdb.retention.time=1y` covers a
year), and `sketchy_phase_timer_lateness_seconds` carries every phase timer's lateness,
not only the overruns this table stores, so the loop drifting toward the threshold is
visible before it crosses it.

### Sizing facts on `/metrics`

What the storage reviews of #471, #545, #549 and #558 had to guess from seeded shapes is
recorded as it is written (#895), each after its write has committed and none carrying a
user identifier: `sketchy_drawing_raw_bytes`, `sketchy_drawing_stored_bytes`,
`sketchy_drawing_actions` and `sketchy_drawing_encode_seconds` (the encoding thread's own CPU time since #976, not wall time, which on a worker thread also counts the turns the event loop takes; observed when the envelope is staged, where a finished game's drawings are encoded since #1259), labelled by the format
stored (`SKCD` encoded, `SKCH` verbatim); `sketchy_history_rows_per_game{table}` for
every table a finished game writes; `sketchy_handoff_envelope_bytes`;
`sketchy_messages_retained_total{kind,audience}` with `sketchy_message_recipients{audience}`
— the recipient count #545 closed on a seeded distribution; and
`sketchy_export_artifact_bytes`. After two to four weeks of beta these answer whether the
drawing store reaches 50 GB in months or years, whether a second encoding (#899) is
worth a permanent decoder, and what a finished game really costs.

The live database's own footprint is one read-only command, safe to paste into an issue
(table and index names and numbers only):

```bash
cd backend && .venv/bin/python -m app.services.storage_report          # or --json
```

It prints heap, TOAST and index bytes, the planner's row estimate and bytes per row for
every table, bytes per finished game across all of them, and the ten largest indexes,
from the catalogue — no table is scanned but `game_records`, for the count of games.

Live counts of rooms, players, and running games are deliberately **not** in the
database: one worker owns all of it, so an in-process count is the true count, and it is
meant to vanish on restart because a live count is not a historical fact.

```bash
cd backend && .venv/bin/python -m app.services.runtime_metrics --purge
```

---

## 10. Retention summary

Two different numbers live in this section and they must not be confused. **Retention**
is how long the data is wanted. The **deletion SLA** is how long a row may still be here
*after* that window has passed — a lag allowance on the machinery, not on the policy.
"30 days" says when a message stops being wanted; "6 h" says that a sweep which has not
removed it six hours later is a fault somebody should hear about. What is measured
against the SLA is the age of the oldest row a sweep should already have removed,
counted only over rows the policy does not exempt (R-PRIV-17).

| Data | Retention | Deletion SLA | Exempt | Mechanism | Sweep |
| --- | --- | --- | --- | --- | --- |
| Friendships, including refusals | Indefinite | — | — | Deleted with either account (CASCADE), and on a block | — |
| Retained messages, room and lobby alike | 30 days | 6 h | Lines copied as report evidence, which are their own rows | `expires_at`; hourly retention sweep. The lobby's live backlog (50 lines) is memory, re-seeded from the unexpired rows at startup | `room_messages` |
| Delivered/failed outbox mail | 30 days (`OUTBOX_RETENTION`); tokens scrubbed at send/give-up | 6 h | Pending mail, still owed an attempt at any age | Hourly retention sweep (sent rows by `sent_at`, failed rows by `created_at`) | `email_outbox` |
| Expired one-shot tokens | Until expiry; consumed on presentation | 6 h | — | Hourly retention sweep (nothing scheduled it before #550) | `auth_tokens` |
| Pinned report evidence | Protected report policy (outlives the message) | — | Permanently kept: it is the evidence | Copied on report submission | — |
| Raw runtime events | `RUNTIME_EVENT_RETENTION_DAYS` (30) | 6 h | — | Swept hourly by the retention loop (the metrics loop's own purge before #478) | `runtime_events` |
| Daily runtime roll-ups | Permanent | — | Permanently kept | — | — |
| Shutdown abandonments | 90 days | 6 h | — | Hourly retention sweep (startup-only before #550) | `shutdown_abandonments` |
| Bug report rows | Indefinite | — | Permanently kept: a defect outlives its triage | — | — |
| Bug report screenshots | Until the report is decided, **and 90 days either way** | 6 h | The report row and every piece of screenshot metadata | Erased in the deciding transaction; expired unreviewed by the hourly sweep; `ck_bug_reports_screenshot_erased` and `ck_bug_reports_screenshot_expired` | `bug_report_screenshots` |
| Data exports | 7 days (format v1) | 6 h | — | `expires_at`; hourly retention sweep | `data_exports` |
| Inbox entries | 90 days after arrival, read or not (R-INBOX-06); deleted with the account | 6 h | — | Hourly retention sweep by `created_at` on `ix_inbox_entries_created_at` (#1436). The facts they name keep their own retention | `inbox_entries` |
| Moderator warnings, picture removals included | 12 months after issue (R-INBOX-06); deleted with the account (CASCADE) | 6 h | — | Hourly retention sweep by `created_at`. Kept that long because a later suspension decision reads them as history; kept for ever and orphaned on erasure before #1436 | `user_warnings` |
| Expired sessions | 30 days past `expires_at` | 6 h | Sessions of a suspended account, their only route to export and deletion (R-BAN-04) | Hourly retention sweep | `auth_sessions` |
| Expired rate-limit buckets | Their window | 6 h | — | One batch every 100 checks, and the hourly retention sweep | `auth_rate_limit_buckets` |
| Login lockouts | A day after the last failure (`LOCKOUT_FORGET_AFTER`); cleared at once by a correct password | 6 h | — | Hourly retention sweep, oldest first on `ix_auth_login_lockouts_updated_at`. Never ran before #891, though this row said a day: a failure is counted for usernames that do not exist, so every name anybody tried stayed for ever (R-RATE-12) | `auth_login_lockouts` |
| Ephemeral room codes | 30 days retirement, then reusable | 6 h | Codes of the removed persistent-room feature, which never re-enter the pool | `retired_until`; freed by the hourly retention sweep (collision-triggered only before #550) | `room_code_reservations` |
| Codes from the removed persistent-room feature | Permanent | — | Permanently kept | Never enter the reuse pool | — |
| Guests with no completed game | 30 inactive days (default) | 24 h | A guest another write holds this instant, left for the next pass | `app.auth.retention`, hourly | `anonymous_accounts` |
| Guests with history | 365 inactive days (default) | 24 h | As above; history survives via frozen snapshots | `app.auth.retention`, hourly | `anonymous_accounts` |
| Game history, turns, outcomes, ledger, drawings, reactions, pins, shares, usage facts | Indefinite | — | Permanently kept (R-PRIV-05); a share is the account's to take back, and goes with an erased account (R-SHARE-08) | — (drawings are the one blob with no expiry; *Storing the drawings* above records why they stay inline and the size that reopens it) | — |
| Prompt versions a save or a deletion took out of a working copy | A day after `unlisted_at` (`UNLISTED_GRACE`), for the game that drew one before; each hourly pass collects as many as the row budget allows | 24 h | A version still named by a list, a turn, an offer, a usage fact, a report or a takedown record, which is unstamped and kept by it | `services.prompt_reclaim.reclaim_unlisted_versions`; the overdue age is measured from `unlisted_at` (#1359) | `unlisted_prompt_versions` |

The SLAs are `STANDARD_SLA_SECONDS` and `HEAVY_SLA_SECONDS` in
[`auth/retention.py`](../backend/app/auth/retention.py), stated once beside each sweep
rather than restated here in prose that could drift from them. Six hours is six
scheduled passes of an hourly loop that also catches up in five seconds when it is
behind: reaching it means the loop missed its window six times over. A day is for the
two sweeps whose per-run ceiling is deliberately small — guests cascade across a dozen
tables, unlisted versions walk turns, offers, facts and concepts — so a backlog is worked off
over several passes by design.

The **Sweep** column names the registered sweep (`retention_sweeps()` in
[`auth/retention.py`](../backend/app/auth/retention.py)) and
`test_the_retention_summary_names_every_registered_sweep_and_its_sla` holds the two
together in both directions: a documented deletion SLA with no sweep behind it fails, as
does a sweep this table does not list or an SLA that differs. The login lockouts were
that gap until #891 — documented as dropped after a day, and never swept.

**Retention that runs is not retention that complies.** A sweep removing five thousand
rows an hour from a table growing by six thousand is healthy by every signal that
existed before #478: the loop is alive, no iteration failed, rows are going. So every
sweep also measures what it *left*, on every run and not only on a run cut short — the
age of the oldest non-exempt row still eligible, and how many there are, counted to
`BACKLOG_CAP` (10,000) because "more than ten thousand overdue" and "eight hundred
thousand" call for the same action and only one of them costs a sequential scan an hour.
Both are measured over the sweep's own eligibility predicate, so a suspended account's
sessions, a list still inside its grace, a persistent room code and pending mail are absent
from the backlog exactly as they are absent from the candidates. A table that owes
nothing reports **zero rather than nothing**: an absent Prometheus series does not
compare greater than its allowance, so a rule written on a metric that appears only
while a sweep is behind is silent for precisely as long as nobody is looking.

Per table, on `/metrics` and under `retention` on the operations page:
`sketchy_retention_overdue_seconds`, `sketchy_retention_sla_seconds` (identical labels,
so one rule holds every table to its own policy), `sketchy_retention_backlog_rows`,
`sketchy_retention_sweep_seconds`, `sketchy_retention_sweep_exhausted`,
`sketchy_retention_sweep_failed`, `sketchy_retention_rows_removed_total` and
`sketchy_retention_sweep_failures_total`. The alerts are `SketchyRetentionBehind`,
`SketchyRetentionSweepFailing` and `SketchyRetentionSweepStarved`, all naming the table
— because fault isolation means nothing else will: one sweep failing every hour leaves
the other fourteen succeeding and the loop looking merely intermittent
([`slo.md`](slo.md) SLO-10).

Deletion evidence in `audit_events` is deliberately **aggregate and sparse**: the guest
purge writes one row per applied run (R-PRIV-10), screenshot expiry writes one row per
run saying how many pictures went and never whose, and the sweeps over rows that hold no
personal content write none at all. A ledger row per purged session would be a second
copy of the retention log, at 24 permanent rows a day, saying nothing the metrics do not.

**Every sweep is bounded, scheduled, observable and fault-isolated** (#550,
[`services/sweeps.py`](../backend/app/services/sweeps.py)). The hourly retention loop
runs the sweeps above in a fixed order, each through `delete_in_batches`: an indexed,
deterministically ordered select of at most `RETENTION_SWEEP_BATCH_ROWS` (500) keys,
deleted in a transaction of their own, repeated until the table is clean or the run's
`RETENTION_SWEEP_ROW_BUDGET` (5,000 rows) or `RETENTION_SWEEP_SECONDS_BUDGET` (30 s) is
spent. A screenshot's expiry is the one sweep that takes `erase_in_batches` instead —
same batching, same budget, same probe, an `UPDATE` because the retention window is over
a column and the row must survive it. A sweep cut short reports so, and the loop comes
back after `CATCH_UP_SECONDS` (5) instead of an hour until nothing is behind; a sweep that raises is logged and counted on the loop's health and the sweeps
after it still run. Each sweep's rows, batches, duration, backlog and SLA
appear under the `retention_sweep` loop in `/api/health`. Startup runs no purge of its own: the loop's
first pass starts immediately, bounded, so a backlog left by a long outage cannot delay
serving. The chat writer only inserts; before #550 its first batch also ran the message
purge inside its own transaction.

A PostgreSQL churn run (`benchmarks/retention_churn.py`, 100,000 expired messages,
5,000-row budget, 500-row batches, local PostgreSQL 17) is the baseline for any table
storage decision: see the README benchmark notes for the numbers. The shape it shows is
the one to expect — each bounded run deletes its slice and leaves dead tuples behind, the
relation does not shrink until autovacuum has been round, and WAL is proportional to rows
deleted.

Anonymous retention is based on `last_active_at` and is bounded to 500 accounts per run
(each guest tier is offered half the batch and whatever the other cannot use, so a flood
of never-played guests cannot starve the tier with history). It **previews by default**
and records aggregate audit evidence when applied. A removal
selects its candidates `FOR UPDATE SKIP LOCKED` in ascending activity order — a guest a
claim, a merge, a seat or a finished-game write is holding is left for a later sweep, not
waited for — and the delete repeats every eligibility predicate and returns the ids it
removed, which are what the counts and the audit row report (#608). A preview takes no
lock. On SQLite the lock is not rendered and the repeated predicates are the whole
guarantee; the skip-locked behaviour is proven on PostgreSQL.

```bash
cd backend
.venv/bin/python -m app.auth.retention                  # preview
.venv/bin/python -m app.auth.retention --apply
```

`--unused-days`, `--player-days`, and `--batch-size` set an explicit deployment policy.
A stale guest's session is removed with the account, so an old cookie provisions a new
guest rather than resurrecting retained data.

---

## 11. Account deletion

`DELETE /api/auth/account` requires the current password for a registered account, and
an explicit `DELETE` confirmation in the UI. Guests may delete the automatically
provisioned account without a password, because possession of its HttpOnly session is
their only credential.

Deletion:

- revokes every linked session;
- removes export, provider, and avatar records, and clears login and profile identity;
- replaces frozen participant/drawer/guess names with the **Deleted player** tombstone;
- erases ordinary authored `room_messages` immediately, lobby lines included, and tombstones the presentation
  on copied evidence;
- removes every block owned by or targeting the anonymized identities;
- removes every friendship and pending or refused request involving them;
- deletes owned prompt lists outright, with their prompts and editions (see
  `prompt_lists` in §8) — and deletes the account's takedown
  records, with the spellings only they kept (`prompt_takedowns` in §5);
- erases the drawings that account made while leaving the row saying so, and deletes the
  reactions those drawings had; reactions the account gave elsewhere stay, under the
  tombstoned seat;
- deletes the pins on those erased drawings, and every pin the account itself made — a
  tombstoned account has no profile to show a shelf on (`profile_drawing_pins` in §6);
- deletes the shares of those erased drawings and every share the account made, setting
  the Gallery's projections again on the other players' drawings that lose one
  (`turn_drawing_shares` in §6). Every drawing row it writes - its own, and the others' it shared or pinned - is
  locked first, in one ascending statement, before any row that hangs off one is touched:
  a drawer's withdrawal holds its drawing and then deletes the shares and pins on it;
- deletes the account's inbox entries and its warnings, and the entries in other
  accounts' inboxes about it as a friend or an inviter, which would name an account that
  is gone; an entry about a drawing it shared names nobody now, since who a share entry
  names is read when it is shown (`inbox_entries` in §4, `user_warnings` in §5);
- erases any screenshot on a bug report that account filed, while leaving the report:
  a defect is not un-found by an erasure, and the reporter foreign key detaches;

The stable anonymized row, scores, prompts, and shared game structure **remain**, so
another player's history is never damaged. Prompt usage facts carry no user identifier
and are untouched.

### The erasure barrier

The deletion above erases what is in the database when it commits. What it cannot
reach is content composed before it and written after it: a message still in the
retention queue, a finished game still being written (or retried later, #541), an
avatar upload, list save or report whose request passed the session middleware
before the deletion committed. Each of those would write the erased name, text, or
pixels back (#606: reproduced with one queued lobby line).

So every writer of account-owned content re-reads the lifecycle of the accounts it
writes for **inside its own transaction, under a lock on their rows, in ascending id
order** ([`auth/erasure.py`](../backend/app/auth/erasure.py)) — a shared lock when it
only reads the account, `FOR UPDATE` when it goes on to write the row (the finished-game
write touches `last_active_at`, an avatar upload the avatar key), because two shared
holders that both update deadlock on the upgrade. The
deletion holds the account row `FOR UPDATE`; a writer that arrives while it is in
flight waits and then reads `deleted`, and a deletion that arrives while a writer
holds the shared lock waits for the commit and erases what was just written. Either
order ends erased, and the ascending order is what keeps two writers, or a writer and
two deletions, from waiting on each other in a cycle. A merged guest resolves to the
account it was merged into; a row retention has already purged counts as erased.

**The lock set is the whole identity, resolved before locking.** `erased_identity_ids`
reads the accounts its guests were merged into first, unlocked, and locks guests and
accounts in one ordered statement; a target found only under the lock (a merge that landed
in between) is locked in a second statement by a *shared* holder, the one case left — and
never by an exclusive one: the pin write abandons that transaction (`LockSetChangedError`)
and starts again from before the alias read, up to three times, so its set is always
taken whole. Locking the guests first
and reaching for their accounts gave two pin writes whose sets crossed a cycle (#811
review). A seat may still carry
a guest identity merged into an account mid-game. The finished-game write resolves such
seats to their accounts first and takes one `FOR UPDATE` over seats and accounts
together; the deletion reads the guests merged into the account first and takes one
`FOR UPDATE` over account and guests together, checking under the lock that no guest
joined in between (a merge needs the account row, so none can join after). Locking the
account and then reaching for its guests, or the guest and then its account, gave the two
transactions opposite orders and a cycle PostgreSQL had to break by aborting one.

A write that loses a lock wait to the web role's budget (§1, *Session budgets*), or is
chosen as a deadlock victim, is transient: the room's persist path tries it again, up to
three times with a short pause, before recording the game as unrecorded
([`services/game_flow.py`](../backend/app/services/game_flow.py)).

What each writer then does with an erased identity:

| Writer | With an erased identity |
| --- | --- |
| Message retention queue (`_write`) | Drops the line; the rest of the batch is written |
| Finished-game write (`save_game`) | Writes the game, the seats, the scores and the turns; the identity's snapshots carry the **Deleted player** tombstone, its drawings are written as `deleted` rows with no payload, reactions *on* those drawings are dropped and reactions it *gave* stay. The payload hash is taken from the input, so a retry of the same game is the same game, not a conflict |
| Avatar upload, owned-list create/update, bug, player and content reports | Refused (`AccountErasedError`, 401 over HTTP): authentication before the deletion is not authorization after it |
| Export request | Already locks the account row `FOR UPDATE` and refuses a deleted account |
| Reaction (`set_drawing_reaction`) | Locks the **drawer's** identity, shared, before the drawing row (for the stats rebuild, §`user_stats_daily` *Synchronization*). The turn and drawing are read before that lock, so a reaction that waited behind the drawer's deletion refuses on the erased identity the lock reports rather than on the drawing it loaded — the deletion took the drawing and its reactions (R-REACT-10) |
| Pin write (`set_profile_pins`) | Locks the pinner **and every drawer** named by the list, ascending, **`FOR UPDATE`** rather than shared — the one writer that must also serialize with its own kind, since two whole-shelf replacements for one account under shared locks both pass the barrier and collide on the shelf's unique positions. An erased pinner is refused (the uniform 404); an erased drawer's drawing reads `deleted` under the lock and refuses the list, so a pin can neither put a shelf back on a tombstoned profile nor outlive the drawing it names (#811 review) |

SQLite renders neither lock and has one writer at a time, so there the re-read alone
is the barrier; both lock orders are proven on PostgreSQL in
[`tests/test_erasure_barrier.py`](../backend/tests/test_erasure_barrier.py).

---

## 12. Recalculable competitive foundation

Finished-game **facts** — not profile counters — are the source for any future rating,
season, achievement, or competitive-standings work. The durable foundation is: game
event times and exact rule versions, factual participant seats with canonical identity
aliases, frozen eligibility and per-turn outcomes, prompt provenance, and the
append-only score-event ledger. Derived rows such as `user_stats_daily` may be deleted
and rebuilt without changing any of it.

**This is deliberately a foundation, not a feature.** Sketchy v1 has no rating
algorithm, season identity, achievement definitions, competitive-mode eligibility
policy, or server-wide standings. Those require a later product decision and a versioned
projection of the retained facts; they must not be introduced as mutable counters or
inferred by rewriting finished games. The version columns (`scoring_version`,
`score_ledger_version`, `rule_snapshot_version`) remain the mechanism by which a future
projection classifies facts by provenance; version `0` with an empty snapshot stays the
declared encoding for "rules unknown", though no current writer produces it.

---

## 13. Operating the database

### Local PostgreSQL checks

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/python -m app.db.migrate
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/pytest -q tests/test_migrations.py tests/test_repositories.py
```

> The shared persistence fixture is
> [`backend/tests/dbfixtures.py`](../backend/tests/dbfixtures.py), so `TEST_DATABASE_URL`
> moves its callers onto PostgreSQL. Tests specifically proving file-backed SQLite
> concurrency still use fresh temporary SQLite files. The fixture **deletes application rows** from its
> database - one `DELETE` per table, children first, sent as a single round trip - and
> refuses a name without `test` in it. Never point it at a development or production
> database.

Without `TEST_DATABASE_URL` the same fixture hands out fresh in-memory SQLite configured the
way [`db/__init__.py`](../backend/app/db/__init__.py) configures the application's own
connections, and checks `PRAGMA foreign_keys` on every connection it opens. The in-memory database is a **named** one in shared-cache mode with one keeper connection held for the engine's lifetime, not a plain `:memory:` — a plain one *is* its connection, and when SQLAlchemy discards that connection (a statement cancelled mid-flight does, and the chat path's block lookup gives up on a slow read by design) the replacement is an empty database, so every later statement in the test fails with "no such table" nowhere near the cause. Seen once on CI in the retention suite; `tests/test_dbfixtures.py` cancels a statement and reads again. A raw
`create_async_engine` leaves SQLite's enforcement off, and a suite built on one passes
deletion tests against constraints the database never applied — #612 found two
deletion paths that only failed once enforcement was real. The schema is the one
`create_all` would build - the same `CREATE` statements in the same order, so
`test_db_models.py` still proves models and migrations agree - compiled once per
process and run as one script, because several hundred tests build a database each and
compiling and sending 150-odd statements one at a time was most of what each cost
(#660). The engine remains local to the test's event loop.

For the full suite with CI's parallel scheduling, keep migration replay separate:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/pytest -q tests/test_migrations.py
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy_test \
  .venv/bin/pytest -q -n 4 --dist=loadgroup --database-backed-only \
    --deselect tests/test_migrations.py --durations=50
```

`--database-backed-only` is what CI passes, and leaves out the tests that would run
here exactly as they ran on SQLite. Drop it to run the whole suite against PostgreSQL -
which is the same thing, more slowly, and is worth doing when the selection itself is
what is in question.

[`tests/conftest.py`](../backend/tests/conftest.py) provisions an isolated migrated
database for each worker through
[`tests/parallel_databases.py`](../backend/tests/parallel_databases.py). The source's owner role needs
`CREATEDB` and access to the administrative `postgres` database. The migrated source
must have no other connections while it is cloned. The controller chooses unique
names, passes each URL before test modules import, and drops only its own clones
after the workers exit, including connections left by a crashed worker. It never
drops or resets the source. A killed controller can leave disposable
`sketchy_test_<uuid>` databases to remove manually; CI's service container is ephemeral.
Per-worker isolation retains real commits, native types, migration triggers, row
locks and READ COMMITTED interleavings; sharing an outer rollback transaction would
change what these tests prove.

CI upgrades a fresh PostgreSQL 17 database with Alembic, removes the baseline and
rebuilds it **down and up** on both PostgreSQL and SQLite, checks schema drift and the
hand-written expression indexes, then runs every database-backed test against the
migrated schema - `--database-backed-only`, which selects the modules whose imports
reach this fixture or which read `TEST_DATABASE_URL` themselves
([`tests/database_backed.py`](../backend/tests/database_backed.py), R-ENG-12). A SQLite
pass proves integrity, not concurrency: READ COMMITTED interleavings
and row locks are only ever exercised on that job.

### Budgets a PostgreSQL deployment enforces

The application's connections identify themselves as `sketchy-web` in
`pg_stat_activity` and are cut off by the server after 30 s of one statement, 5 s
waiting for a lock, or 60 s idle inside a transaction; `python -m app.db.migrate`
connects as `sketchy-migration` (600 s / 5 s / 60 s) and every operator command below
as `sketchy-maintenance` (600 s / 5 s / 120 s). A statement that hits its budget fails
with `canceling statement due to statement timeout` (or `lock timeout`) and the
connection stays usable; an idle transaction that hits its budget has its connection
terminated, and the next checkout finds its socket closed and replaces it (#973). Override with the
`DB_*_TIMEOUT_SECONDS` variables (README → Database & Configuration); raising one is
not a fix for unbounded work, which the sweeps' own budgets bound.

### Server configuration

The server side is tracked too (#889), in [`ops/postgres/`](../ops/postgres/): the
`initdb` flags ([`initdb.args`](../ops/postgres/initdb.args)), a `postgresql.conf`
include ([`sketchy.conf`](../ops/postgres/sketchy.conf)) and a one-time superuser
script ([`init.sql`](../ops/postgres/init.sql)) that creates `pg_stat_statements` and
the `sketchy_monitor` role the exporter connects as. Every setting carries its reason
in the file; `tests/test_postgres_config.py` refuses one without, and
[`check-config.sh`](../ops/postgres/check-config.sh) proves the three against a
throwaway cluster (checksums on, lz4 WAL and TOAST, a slow statement logged with its
duration and application name, `pg_stat_statements` readable by the monitor role).

- **Data checksums are an `initdb` decision.** `pg_checksums` can add them only to a
  stopped cluster, in time proportional to its size, so a cluster created without them
  stays without them in practice. With them, a damaged page is an error on read instead
  of data that is served, backed up and restored.
- **What is logged**: every statement over 250 ms with its duration and
  `application_name` (so it names `sketchy-web`, `-migration` or `-maintenance`), every
  lock wait over `deadlock_timeout`, every autovacuum run, every temporary file, every
  checkpoint. These lines are the evidence for everything below; the application's own
  statement histogram says *that* something is slow, not *what*.
- **Memory** is sized for a database container given 2 GB and SSD storage. None of
  those five settings is a correctness setting; re-derive them from the host (#408).
- `default_toast_compression = lz4` does not touch the two `STORAGE EXTERNAL` drawing
  payloads, which are never compressed by the server.

The Compose file of #405/#408 consumes these files; until it exists, a cluster built by
hand should be built with them.

### Reading the database from the inside

postgres_exporter (scrape job and collector flags in
[`scrape-example.yml`](../ops/prometheus/scrape-example.yml)) exports the statistics
views, and [`sketchy-postgres.yml`](../ops/prometheus/rules/sketchy-postgres.yml) holds
the rules over them: dead-tuple ratio and autovacuum age on the churn tables
(`room_messages`, `runtime_events`, `auth_rate_limit_buckets`,
`finished_game_envelopes`, `auth_sessions`, `auth_login_lockouts`), cache hit ratio,
transaction age, connections, wraparound, requested checkpoints, and weekly growth.
[`docs/slo.md`](slo.md) lists them. Everything here is readable as `sketchy_monitor`.

**Who is connected, doing what.** Each process names itself:

```sql
SELECT application_name, state, count(*),
       max(now() - xact_start) AS oldest_transaction,
       max(now() - query_start) FILTER (WHERE state = 'active') AS longest_statement
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY 1, 2 ORDER BY 1, 2;
```

`sketchy-web` never holds a statement past 30 s or an idle transaction past 60 s, so
anything older under that name is a bug; anything older under no name is an operator.

**Around a release**, snapshot and reset the statement statistics, so the next review
compares one release with the last instead of the sum of all of them:

```sql
CREATE TABLE IF NOT EXISTS stat_statements_snapshots AS
  SELECT now() AS taken_at, * FROM pg_stat_statements WITH NO DATA;  -- once, as owner
INSERT INTO stat_statements_snapshots SELECT now(), * FROM pg_stat_statements;
SELECT pg_stat_statements_reset();
```

The snapshot table belongs to the operator, not the schema: no migration creates it.

**The monthly review** reads four things and writes down what it found:

```sql
-- 1. Where the time goes, and where the WAL does.
SELECT calls, round(total_exec_time) AS ms, round(mean_exec_time::numeric, 2) AS mean_ms,
       rows, wal_bytes, left(query, 80)
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 15;   -- then BY wal_bytes

-- 2. Indexes nothing reads (since the statistics were last reset).
SELECT relname, indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes ui JOIN pg_index i USING (indexrelid)
WHERE idx_scan = 0 AND NOT i.indisunique ORDER BY pg_relation_size(indexrelid) DESC;

-- 3. Tables autovacuum is not holding, and whether updates are heap-only.
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, n_tup_upd, n_tup_hot_upd
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 15;

-- 4. Growth, per table, against last month's numbers.
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 15;
```

An index with `idx_scan = 0` after a month of beta is a candidate for removal only if
no statement in `backend/app` names its leading column (#890 applied that rule by
hand); a table whose dead tuples autovacuum is not holding gets its own
`autovacuum_vacuum_scale_factor`, set from these numbers rather than guessed.

### The integrity audit

The database holds three kinds of value nothing re-checked unless somebody thought to:
the stored drawings, the projections derived from facts, and the invariants only the
writers prove. A supervised loop checks all of them (#894,
[`services/integrity_audit.py`](../backend/app/services/integrity_audit.py)), a bounded
slice per pass, off the request path and off the event loop - a stored drawing's hash and
decodes run on the history encode pool, and the games check's comparisons are made by
the database, which returns only the rows that disagree (#1251) - and **reports without
repairing**:

| Check | What it compares | On a mismatch |
| --- | --- | --- |
| `drawings` | every ready drawing: declared size and format, checksum, decodability — the #610 walk | **pages** (`SketchyDrawingCorrupt`): the bytes are lost until a restore |
| `drawing_projections` | `reaction_count`, `gallery_share_count`, `gallery_shared_at` (set, and never later than the earliest share) and `hot_score` against the reaction and share rows | warns; `python -m app.services.gallery_ranking` rebuilds |
| `user_stats` | each account's `user_stats_daily` rows against a rebuild from facts, run in a transaction that is **rolled back** | warns; `python -m app.services.user_stats_projection` rebuilds |
| `games` | each seat's ledger sum against `final_score` (ledgered games), each turn's `guesser_count` against its eligible outcome rows | warns; a writer bug, investigate |
| `alias_chains` | no merged identity points at another merged identity | warns |

Every check walks its table by keyset and keeps its place in `app_config`
(`integrity_audit.<check>`, one JSON value with the cursor and the cycle's timings), so
a restart resumes and a **cycle is a whole pass over every row** — not a sample that may
never reach the bad one. Each pass gives every check an equal share of
`INTEGRITY_AUDIT_PASS_SECONDS` (10 s), and the drawing walk a byte budget
(`INTEGRITY_AUDIT_BYTE_BUDGET_MIB`, 16) on top; passes run every
`INTEGRITY_AUDIT_SECONDS` (300). At those defaults a day reads 4.5 GiB of drawings,
about 150,000 at the sizes measured so far — the **detection bound**: corruption or drift
exists for at most one cycle, which is kept shorter than backup retention so the restore
that repairs a drawing still exists when the audit finds the damage (#458). A check
fails alone: one that raises is marked failed and the others run.

Each slice reads both sides of its comparison from **one snapshot** (REPEATABLE READ).
Under the default READ COMMITTED a reaction committing between the read of
`reaction_count` and the count of the rows — both written by one transaction — would be
reported as drift that never existed. The `user_stats` rebuild writes before it rolls
back, so a writer that changed one of the batch's rows after the snapshot makes that
write fail with a serialization error; the slice then steps back, cursor unmoved, and
is retried next pass rather than reported.

A mismatch is logged, counted (`sketchy_integrity_mismatches_total{check}`) and written as
one `audit_events` row of type `integrity.mismatch` naming the check, the kind and the
row id — never the row's content. `sketchy_integrity_rows_verified_total`,
`sketchy_integrity_cycle_age_seconds` against `sketchy_integrity_cycle_target_seconds`
(`INTEGRITY_AUDIT_CYCLE_TARGET_SECONDS`, a day; `SketchyIntegrityCycleOverdue` at twice
it), `sketchy_integrity_last_cycle_seconds`,
`sketchy_integrity_last_completed_timestamp_seconds` and `sketchy_integrity_check_failed`
say how far along each check is. To run passes now, as the loop would:

```bash
cd backend && .venv/bin/python -m app.services.integrity_audit --passes 10
```

### Production deploy order

```bash
cd backend
export SKETCHY_ENV=production                # without it every production guard is off
export DATABASE_URL=postgresql+asyncpg://sketchy_app:password@localhost:5432/sketchy
export MIGRATION_DATABASE_URL=postgresql+asyncpg://sketchy_owner:password@localhost:5432/sketchy
.venv/bin/python -m app.db.migrate          # BEFORE starting or replacing any replica
HOST=0.0.0.0 PORT=8000 .venv/bin/python -m app.server
```

In a deployment the migration step is
[`ops/postgres/migrate-with-snapshot.sh`](../ops/postgres/migrate-with-snapshot.sh)
(#893): it takes a custom-format `pg_dump` named for the time and the revision it holds
into `SNAPSHOT_DIR` (mode 0600: it is the whole database), prints the `pg_restore`
command that puts it back, and only then migrates — a failed dump stops the deploy. The
owner's password reaches `psql` and `pg_dump` through a temporary 0600 passfile, never
their command lines, which any local user can read for as long as the dump runs. Recovery from a bad release is restore and
fix forward (#458); nothing trusts a migration to run backwards over live rows, and a
restore wants the state from immediately before the change rather than last night's
backup plus a day of games.

### Roles

Three roles, created once by a superuser with [`ops/postgres/init.sql`](../ops/postgres/init.sql)
(#896, R-PLAT-22), because one `DATABASE_URL` made the process that answers anonymous
traffic the owner of every table — able to drop and truncate them, disable
`trg_score_events_immutable_update`, and rewrite `audit_events`, whose append-only
property was only a convention of the code:

| Role | Used by | May |
| --- | --- | --- |
| `sketchy_owner` | `python -m app.db.migrate` (`MIGRATION_DATABASE_URL`) | own the schema and every table; DDL |
| `sketchy_app` | the web process and every operator command (`DATABASE_URL`) | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on rows — but only `INSERT` and `SELECT` on `audit_events` and `score_events`, only `SELECT` on `alembic_version`; `MAINTAIN` (PostgreSQL 17, which the migration therefore requires) on the prompt tables startup seeds a list into, so it can `ANALYZE` what it just wrote - a freshly seeded table has no planner statistics, and a thousand-prompt list's aliases were then joined by walking all of them per prompt (#1367); no `TRUNCATE`, `TRIGGER`, `REFERENCES` or DDL |
| `sketchy_monitor` | postgres_exporter | `pg_monitor`; no table |

The grants live in [`db/roles.py`](../backend/app/db/roles.py) and are applied by the
migration command after every upgrade, in the same transaction, when `sketchy_app`
exists — a table a revision creates is readable by the application the moment it
exists, and a grant changed by hand is put back by the next deploy. Default privileges
cover a table created by a hand-run migration too. Referential actions run with the
owner's rights, so deleting an account still clears its references in the ledgers.
Deleting a game remains an operator's act as the owner: the ORM removes its ledger rows
itself, in an order the self-referencing `RESTRICT` on corrections allows.

Production refuses to start when the web connection is a superuser, owns the schema's
tables or may create in the schema (one query beside the revision check), and the
migration command refuses to fall back to `DATABASE_URL`. CI runs the suite as
`sketchy_app` against a schema `sketchy_owner` migrated (`TEST_OWNER_DATABASE_URL`), and
`tests/test_database_roles.py` proves the application role cannot `TRUNCATE`, `ALTER`,
create a table, rewrite either ledger or disable the trigger.

### Adding a table or column

1. Edit [`backend/app/db/models.py`](../backend/app/db/models.py).
2. Generate a migration; make sure it is reversible and that SQLite batch mode is used
   where a table is rebuilt.
3. Add or extend the `CHECK` constraint if the column is an enum, and declare the enum in
   [`domain_values.py`](../backend/app/domain_values.py).
4. Run `pytest tests/test_migrations.py tests/test_db_models.py tests/test_online_ddl.py
   tests/test_populated_upgrade.py` — locally on SQLite and, for anything non-trivial,
   against PostgreSQL.
5. **Write it to run over live rows** (#893). The migration role's five-second lock
   budget turns an unsafe revision into a failed deploy rather than a stalled game, but
   it still fails, halfway, on the biggest tables. On the tables that grow with play
   (`LARGE_TABLES` in [`tests/test_online_ddl.py`](../backend/tests/test_online_ddl.py)),
   which refuses each of these in any revision after the lint's starting point:
   - an index is built `postgresql_concurrently=True` inside
     `op.get_context().autocommit_block()` — a plain build blocks every writer for as
     long as it takes, and `CONCURRENTLY` cannot run in a transaction (the lint refuses
     a concurrent build or drop outside the block on any table, since PostgreSQL would
     refuse it at deploy);
   - a check or foreign key is added `postgresql_not_valid=True` and validated in a
     separate `ALTER TABLE … VALIDATE CONSTRAINT` — adding it valid scans the table
     under a lock writers wait behind, and validating takes one they do not;
   - a type change or a `NOT NULL` is preceded by a validated
     `CHECK (column IS NOT NULL)` or done as add-copy-swap — both are a scan or a
     rewrite under an exclusive lock;
   - a new `NOT NULL` column has a `server_default` — without one it fails outright on a
     table with rows;
   - a backfill `UPDATE` or `DELETE` is batched, like the retention sweeps;
   - a `CHECK` is narrowed only in a revision later than the one whose code stopped
     writing the values it drops: the runbook migrates before the old replica is
     replaced, so that replica is still writing them while the migration runs, and a
     row it commits after the delete makes `VALIDATE` fail the deploy, then fails every
     flush it makes afterwards. Expand, deploy, then contract.

   **These rules do not yet do what they say.** `upgrade_database` runs every revision
   in one transaction — it holds a transaction-scoped advisory lock so two deploys
   cannot migrate at once, and applies the application role's grants in the same
   transaction (#896). Inside it a batched write does not commit between batches, the
   exclusive lock a `NOT VALID` constraint takes is held to the end so `VALIDATE` scans
   under it, and `autocommit_block()` — which the concurrent-index rule requires —
   cannot run at all, because the transaction is the runner's, not Alembic's. Until the
   runner changes, a revision written to these rules is only as safe as running it on a
   database nothing is writing to, which is true of every revision before launch. #969 tracks the runner change.

   A call that is safe for a reason the lint cannot see says so on its line or the one
   above: `# online-ddl: <why>`. Every revision then runs over rows in CI:
   [`fixtures/populated_upgrade.sql`](../fixtures/populated_upgrade.sql) holds a database
   seeded through the application's own writers at one revision
   ([`tests/populated_upgrade.py`](../backend/tests/populated_upgrade.py) wrote it), and
   `tests/test_populated_upgrade.py` builds the schema to that revision, loads the rows,
   upgrades to head, reads every history surface back and runs the integrity audit over
   the result. A pre-squash revision once ran an `UPDATE … SET NULL` before its column
   became nullable and passed the empty replay; this is the test that would have failed.
6. **Update this document**, plus [`architecture.md`](architecture.md) if the state
   ownership changed and [`requirements.md`](requirements.md) if a stated guarantee moved.

### Pre-v1 note

**Nothing is deployed, so no schema change owes anybody a migration path.**
Until this service runs somewhere with real data in it, a table may be
rewritten rather than converted, a column may change type in place, and a
format may be replaced rather than dual-read. Migrations still have to be
reversible and still have to replay cleanly in both directions on both engines
- that is what `tests/test_migrations.py` checks, and it is about the chain
being sound rather than about anybody's data surviving. The same freedom is
written down for the wire in `docs/wire-protocol.md` §11.

The same goes for seeded content. The bundled lists' rework for #1396
(#1404-#1407) raises some prompt versions by more than one between `main` and
its last PR, and a database seeded before it refuses them at startup
(`expected version N+1`): the seed only accepts the next version of a prompt it
already holds. **Recreate such a database** - delete a local `sketchy.db`, drop
and recreate a PostgreSQL one - rather than teaching the seed to skip.

Delete this paragraph at launch rather than leaving it to be read as still
true.

### The baseline

The 70 revisions written before launch were folded into one,
[`f0a1b2c3d4e5_baseline_schema.py`](../backend/alembic/versions/f0a1b2c3d4e5_baseline_schema.py),
under exactly that freedom (#557): no deployment held rows written under any of them,
so their backfills, refusals and legacy accommodations had nothing left to protect, and
an empty install now runs one revision instead of seventy. The file was generated from
the models and then finished by hand where autogenerate is blind — the two expression
indexes on `users` that SQLite cannot reflect, the append-only trigger on
`score_events`, and dialect-neutral defaults in place of the SQLite-compiled ones — and
it does not import the models: a historical revision stays what it was when it ran.

**A database built by the old chain cannot be upgraded**, and startup says so: a
revision this checkout does not know is refused with the instruction to rebuild
(`DatabaseRevisionError`, from both the SQLite auto-migrate and `python -m
app.db.migrate`) rather than handed to Alembic to trip over the first table that
already exists. Delete `sketchy.db`, or drop and recreate the PostgreSQL database, and
start again; it held development data only. What the fold saved on an empty database,
measured on 2026-09-06 through `python -m app.db.migrate` with interpreter start
included: SQLite 1.40 s → 0.34 s, PostgreSQL 17 0.64 s → 0.42 s.

Squashing is a pre-launch tool. Once anything is deployed, a revision that a database
has run is history that stays; the same paragraph above says when that starts.
