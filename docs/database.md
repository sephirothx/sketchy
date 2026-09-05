# Database

Every table Sketchy persists, what lives in it, and the flows that write and read it.

Companion documents: [`architecture.md`](architecture.md) ·
[`wire-protocol.md`](wire-protocol.md) · [`requirements.md`](requirements.md) ·
[`../GLOSSARY.md`](../GLOSSARY.md)

Schema source of truth: [`backend/app/db/models.py`](../backend/app/db/models.py).
Migrations: [`backend/alembic/versions/`](../backend/alembic/versions/) (61 revisions,
starting at `e7c9d4bc813e_initial_schema_…`).

To regenerate an authoritative dump of this schema:

```bash
cd backend && .venv/bin/python -c "from app.db.models import Base; [print(t) for t in Base.metadata.tables]"
```

---

## 1. Engines and conventions

| Concern | Rule | Source |
| --- | --- | --- |
| Default engine | Embedded SQLite at `./sketchy.db`, zero configuration — **development and test only** | [`db/__init__.py:23`](../backend/app/db/__init__.py) |
| Alternative | PostgreSQL via `DATABASE_URL` (`postgresql+asyncpg://…`) | [`db/__init__.py:47`](../backend/app/db/__init__.py) |
| Production | With `SKETCHY_ENV=production`, startup **refuses** a missing, blank, or SQLite `DATABASE_URL`. The zero-config default is a *relative* file, so a production deploy that forgot the variable would look healthy while writing accounts, moderation evidence, and history to storage the next container replacement discards. SQLite also serializes every writer, which caps such a server at one write at a time | [`deployment.py`](../backend/app/deployment.py) |
| Indexes | **No standalone index on the leading column of a composite** on the same table — the composite already serves every lookup and scan on its own prefix. A single-column index that is *unique or partial* is exempt: it enforces an invariant rather than accelerating a lookup. Asserted by `test_no_index_duplicates_the_leading_column_of_a_composite` | [`db/models.py`](../backend/app/db/models.py) · [`tests/test_db_models.py`](../backend/tests/test_db_models.py) |
| JSON columns | `jsonb` on PostgreSQL (parsed form, comparable, GIN-indexable), text on SQLite. A Python `None` stores as SQL `NULL`, never the JSON token `null` | [`db/models.py`](../backend/app/db/models.py) (`PortableJSON`) |
| SQLite pragmas | `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000` on **every** connection, test fixtures included | [`db/__init__.py:41`](../backend/app/db/__init__.py), [`tests/dbfixtures.py`](../backend/tests/dbfixtures.py) |
| SQLite migrations | Run automatically on startup | [`db/__init__.py`](../backend/app/db/__init__.py) |
| PostgreSQL migrations | An **explicit deploy step**, protected by an advisory lock (`POSTGRES_MIGRATION_LOCK_ID`). Startup only *verifies* the revision and fails with a direct instruction if the step was missed | [`db/migrate.py`](../backend/app/db/migrate.py) |
| Pool (PostgreSQL) | 5 persistent + 5 overflow, pre-ping, 10 s timeout, 30 min recycle; all four tunable | [`db/__init__.py:25`](../backend/app/db/__init__.py) |

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
  from each other by design, so session tokens, room codes, and prompt-list share codes
  stay independently random and are never derived from an entity ID.

### Timestamps

Every persisted timestamp uses `UTCDateTime`
([`backend/app/db/types.py`](../backend/app/db/types.py)): aware inputs are required and
raise on a naive value, and reads are normalized to aware UTC. SQLite and PostgreSQL
therefore behave identically and application code never infers a local timezone.

Write timestamps are `NOT NULL` everywhere: the schema was tightened before the
first deployment, so no row predates timestamp coverage (revision
`p8c3a6d9e147` refuses to upgrade a database that still holds one — see §13).

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

51 tables in eight domains.

```mermaid
erDiagram
    users ||--o{ auth_sessions : "has devices"
    users ||--o{ identity_aliases : "merges guests"
    users ||--o{ user_blocks : "blocks"
    users ||--o{ friendships : "befriends"
    users ||--o| user_settings : "prefers"
    users ||--o{ user_stats_daily : "projects to"
    users ||--o{ prompt_lists : "owns"
    users ||--o{ room_presets : "owns"
    users ||--o{ user_bans : "suspended by"
    users ||--o{ user_warnings : "warned by"
    users ||--o{ role_change_notices : "told about a role"

    game_records ||--o{ game_participants : "seats"
    game_records ||--o{ turn_records : "turns"
    game_records ||--o{ game_prompt_sources : "pinned revisions"
    game_records ||--o{ score_events : "ledger"
    turn_records ||--o| turn_drawings : "drawing"
    turn_records ||--o{ turn_participant_outcomes : "per seat"
    turn_records ||--o{ turn_prompt_offers : "options"
    turn_participant_outcomes ||--o| turn_guesses : "scoring child"
    game_participants ||--o{ turn_participant_outcomes : "seat"
    turn_records ||--o{ turn_drawing_reactions : "reactions"
    game_participants ||--o{ turn_drawing_reactions : "reactor seat"

    prompt_concepts ||--o{ prompt_versions : "wordings"
    prompt_concepts ||--o{ prompt_aliases : "accepted answers"
    prompt_versions ||--o{ prompt_version_aliases : "accepts"
    prompt_lists ||--o{ prompt_list_revisions : "versions"
    prompt_list_revisions ||--o{ prompt_list_revision_items : "membership"
    prompt_list_revisions ||--o{ prompt_usage_facts : "usage"
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
| **Accounts** | `users`, `auth_sessions`, `auth_tokens`, `auth_rate_limit_buckets`, `friendships`, `identity_aliases`, `user_settings`, `user_stats_daily`, `data_exports`, `external_identities`, `uploaded_avatar_assets`, `email_outbox` |
| **Moderation** | `audit_events`, `player_reports`, `player_report_message_evidence`, `player_report_drawing_evidence`, `prompt_content_reports`, `user_bans`, `user_warnings`, `role_change_notices`, `user_blocks` |
| **Messages** | `room_messages` |
| **Game history** | `game_records`, `game_participants`, `turn_records`, `turn_drawings`, `turn_drawing_reactions`, `turn_participant_outcomes`, `turn_guesses`, `score_events`, `game_prompt_sources` |
| **Prompt provenance** | `turn_prompt_offers`, `turn_prompt_offer_sources` |
| **Prompt content** | `prompt_concepts`, `prompt_versions`, `prompt_aliases`, `prompt_version_aliases`, `prompt_tags`, `prompt_version_tags`, `prompt_lists`, `prompt_list_revisions`, `prompt_list_revision_items`, `prompt_list_revision_tags`, `prompt_list_localizations`, `prompts`, `prompt_usage_facts` |
| **Runtime analytics** | `runtime_events`, `runtime_stats_daily` |
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
`users`.

A preset has **no room code, members, host identity, game, scores, timers, chat, or
canvas.** Applying one fills the create form but does not enable *Keep this room for
future games*. Borrowed Unlisted share codes and quick custom prompts are never stored;
that content must be saved as an owned list first. ≤ 20 per account.

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

| Column | Notes |
| --- | --- |
| `id` | UUIDv7 |
| `username` VARCHAR(32) | Null for guests; case-insensitively unique via `ix_users_username_lower` |
| `password_hash` VARCHAR(255) | Argon2id encoded hash, carrying its own algorithm and cost parameters |
| `display_name` VARCHAR(32) | |
| `name_color`, `avatar_key` | `avatar_key` is the content address of the uploaded picture (`<sha256>.webp` or `.png`), or null for the initial (R-AVA-03) |
| `avatar_upload_blocked_until` | Set when a moderator removed the picture: no upload until then (R-AVA-04) |
| `state` | `anonymous \| registered \| merged \| deleted` |
| `role` | `user \| moderator \| admin` |
| `email`, `email_verified_at` | Nullable; normalized by trim + lowercase, enforced by `ck_users_email_normalized`; case-insensitively unique via `ix_users_email_lower` |
| `created_at`, `updated_at`, `last_login_at`, `last_active_at` | |

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
  ordinary profile write, because it drives retention.

### `auth_sessions`
One revocable signed-in device.

`id` · `user_id` (CASCADE) · `token_hash` VARCHAR(64) **unique** · `device_label` ·
`rotated_from_id` (self-FK, unique, `SET NULL`) · `created_at` · `last_used_at` ·
`expires_at` · `revoked_at`.

Expired rows are purged 30 days past `expires_at`, at startup and hourly. The
condition is **expiry, not revocation**: a revoked but unexpired row still keeps a
ban-time token recognisable rather than looking like a new cookieless guest, and
rotation leaves a revoked predecessor behind deliberately. Sessions of an account
under an **active suspension are never purged** — it cannot sign in to make another,
so that row is its only route to the export and deletion R-BAN-04 keeps available.

Cookies carry opaque 256-bit random tokens; **only SHA-256 hashes are stored**, so the
database never contains a credential that can be replayed. Tokens rotate halfway
through their one-year maximum lifetime. Socket.IO handshakes resolve the same record as
HTTP requests, so revocation applies on the next connection without a shared signing
secret.

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

### `auth_rate_limit_buckets`
`scope` + `key_hash` composite **PK** · `attempt_count` · `window_started_at` ·
`window_expires_at` · `updated_at`.

`key_hash` is an HMAC-SHA-256 digest of the client address under `IP_HASH_SECRET` (or
an auto-generated `app_config` secret) — **raw IP addresses are never stored.** The
`room_create` scope is the one exception to "client address": it hashes the **account**
that opened the room, because a socket behind a reverse proxy presents the proxy and
the forwarded header is attacker-controlled. Buckets
are shared, so limits survive restarts and apply once across every replica. Expired
buckets are cleaned in bounded batches. Rotating the secret starts fresh buckets without
exposing or re-identifying old keys.

### `friendships`
`user_low_id` + `user_high_id` composite **PK** (both CASCADE) ·
`requested_by_id` (CASCADE, NOT NULL) · `status` ∈
`pending | accepted | declined` · `created_at` · `responded_at`, with
`ck_friendships_ordered` (`user_low_id < user_high_id`) and
`ck_friendships_requester_is_a_member`.

**One row per pair, in a canonical order** rather than one row per direction.
Two directional rows can disagree — one accepted, one not — and no constraint
could forbid it; here the pair is the identity, the way it is for
`user_blocks`. The ordering also settles the case #529 was really asking
about: a crossing request, where A asks B while B has already asked A,
collides on the primary key instead of creating a second row, so the handler
sees a request from the other party and accepts it. `x < x` being false
forbids a self-friendship for free.

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
participant, drawer, and guess rows keep their original IDs and presentation, so a game
containing both identities keeps **two factual seats** rather than violating a
uniqueness rule or losing a player. Account history and statistics resolve the account
plus all of its aliases; the guest's sessions are revoked during the merge.

### `user_settings`
Cross-device Player settings for a registered account. `user_id` **PK** (CASCADE) ·
`theme` · `sound_effects` · `confetti_effects` · `sound_effects_volume` (0.0–1.0) ·
`brush_cursor` (`crosshair \| circle`) · `time_format` (`system \| 12h \| 24h`) ·
`key_bindings` (JSON) ·
`colorblind_safe_colors` · `email_reminder_last_shown_at` · timestamps.

Bounded at both the API and database layers: key bindings must describe the complete
supported action set.

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
merges rebuild the target and deduplicate games shared by its factual identities. Ratios
and averages are derived on read, never stored.

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
guesses, prompt-list revision history, unexpired authored retained messages, submitted
evidence, blocks, presets, and account-event metadata.
It **never** contains password or session hashes, other players' profile fields, or any
message body the requester did not explicitly receive and pin. The field surface is
pinned by [`fixtures/account_data_export_v2_fields.json`](../fixtures/account_data_export_v2_fields.json).

### `email_outbox`
`id` · `to_address` · `user_id` (`SET NULL`) · `template` · `payload` (JSON) ·
`state` (`pending \| sent \| failed`) · `attempts` · `last_error` · `next_attempt_at` ·
`created_at` · `sent_at`. `ck_email_outbox_sent_at` enforces `(state='sent') = (sent_at IS NOT NULL)`.

Templates: `verify_email`, `reset_password`, `password_changed`, `account_banned`,
`content_hidden`. **Nothing else is ever sent to a player's address.**

**Flow.** Mail is queued in the **same transaction** as the action that causes it, and
delivered by a sweeper (`EMAIL_SWEEP_SECONDS`, default 30). A suspension is therefore
never undone by an unreachable relay, and a reset message is retried with backoff and
then recorded as failed rather than disappearing. With no `SMTP_HOST` the messages are
**logged instead of sent**, which is the only way the confirmation and reset flows can
be completed on a deployment without mail.

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
`<sha256>.webp` or `.png`, which two accounts uploading the same bytes share, each on
their own row; also denormalised onto `users.avatar_key` so identity payloads need no
join) ·
`content_type` · `byte_size` · `width` · `height` · `checksum_sha256` · `payload`
(the bytes) · `created_at`.

The bytes live here rather than in object storage because they are small by
construction — a 256×256 WebP (PNG where the browser cannot encode WebP) under 128 KiB,
framed and re-encoded by the browser and checked from its header by the server
(R-AVA-01) — so a whole player base is megabytes: a photograph is ~22 KiB as WebP.
Replacing a picture replaces the row; the moderator's removal (R-AVA-04) deletes it and
stamps `users.avatar_upload_blocked_until`; account deletion deletes it in the same
transaction (R-AVA-05). The export carries the bytes.

### `external_identities`
**Reserved, unused in v1.** Schema for a future authenticated identity provider. No
provider-login API is enabled until identity-linking flows ship.

---

## 5. Moderation

### `audit_events`
Append-only record of every security- and moderation-sensitive action.

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
`status` (`pending \| resolved \| dismissed`) · `reviewed_by_user_id` ·
`resolution_note` · timestamps.

Reasons: `harassment`, `offensive_drawing`, `inappropriate_name`, `cheating`, `spam`.
`ck_player_reports_not_self` forbids self-reports.
`uq_player_reports_open_target (reporter_user_id, reported_user_id)` is a **partial
unique index**: one reporter holds **one open report per player**. Saying it again while
a moderator has yet to look adds no evidence and buries the queue; once decided, the
same reporter may raise a new one, because that is a new incident.

Submitted context is preserved as **versioned, reporter-supplied evidence** — it is not
treated as a server-verified fact merely because it was stored. Review is one-way: a
pending report receives one resolution and cannot later be silently rewritten.

### `room_messages`
Accepted player-authored chat, wrong guesses, and correct-guess text, kept **30 days**
in an audience-aware store — and, since #533, the lobby's chat too.

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
audience. Retention is **best-effort and never delays live availability**: a successful
write adds `retainedMessageId` to the `chat_message` payload. Expired rows are removed
at startup and by bounded hourly cleanup during new writes.

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

The bytes are the same `SKCH` frame `turn_drawings` stores, under the same
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

`id` · `reporter_user_id` / `reported_owner_user_id` · `prompt_list_id` /
`prompt_version_id` (both `SET NULL`) · `target_type` (`list \| prompt`) ·
`list_name_snapshot` · `prompt_snapshot` · `reason` · `details` ·
`status` · `reviewed_by_user_id` · `resolution_note` ·
`resolution_moderation_state` · timestamps.

Reasons: `inappropriate`, `hateful_or_abusive`, `sexual_content`, `violence`, `spam`,
`other`. `ck_prompt_content_reports_target_snapshot` requires a prompt snapshot for a
`prompt` target and forbids one for a `list` target. Two partial unique indexes give one
open report per reporter **per list** and **per prompt version** — so a list and a
single prompt inside it stay separately reportable.

**Post-moderation:** submission preserves a bounded evidence snapshot but never hides
content automatically. One review may dismiss the report or set the exact target Active
or Hidden, with actor/time provenance and an append-only audit event. A dismissal
cannot mutate content. Snapshots survive list and account deletion even after the target
foreign keys are cleared.

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
`none | ready | erased`. The server sniffs the magic bytes, re-derives the size and
digest, and rejects anything that is not a real PNG or WebP under 2 MB.
`ck_bug_reports_screenshot_ready_identity` requires a `ready` row to hold the bytes and
their identity; `ck_bug_reports_screenshot_erased` makes erasure **structural** — a
decided report cannot retain pixels, whatever a future code path does.

**Deciding is one-way.** A pending report receives one resolution with a required note,
and the same transaction erases the screenshot. Submission and each decision append an
audit event naming the report; the ledger never records what the report said.

### `user_bans`
`id` · `user_id` (`SET NULL`) · `banned_by_user_id` (`SET NULL`) · `reason` ·
`source_report_id` (FK → `player_reports`, `SET NULL`) · `expires_at` · `is_active` ·
`created_at` · `revoked_at` · `revoked_by_user_id` · `revoke_reason`.

**Flow.** Creating a suspension revokes every signed-in device and removes any live room
seat immediately. Correct-password login, authenticated HTTP requests, and Socket.IO
handshakes all reject an active suspension. A token revoked at ban time stays
recognizable until expiry, so its next request cannot be mistaken for a new cookieless
guest. **Data export, account deletion, and logout remain available** through that
ban-time credential, so moderation cannot erase privacy rights. Expired suspensions stop
applying automatically; revocation preserves the historic record and its reason.

`source_report_id` is what lets the suspension notice show the reported player their own
words as they were when the report was made. **A ban naming a report about somebody else
is refused**, so a suspension cannot be used to show one player another's messages. A ban
issued from a report also **resolves that report in the same transaction**, and a report
already decided refuses the ban - one complaint, one consequence.

### `user_warnings`
`id` · `user_id` (`SET NULL`) · `issued_by_user_id` (`SET NULL`) · `reason` ·
`source_report_id` (FK → `player_reports`, `SET NULL`) · `created_at` · `acknowledged_at`.

**Flow.** The step between dismissing a report and suspending the account: nothing is
restricted. A connected player is told immediately over the socket (`moderator_warning`);
otherwise the client's `GET /api/warnings/pending` on their next visit
returns the oldest unacknowledged warning together with the pinned messages of its
source report — the same own-words rule as a suspension, and a warning naming a report
about somebody else is refused for the same reason. Acknowledging sets
`acknowledged_at`, which is what stops it being shown again and records that the notice
actually landed. Issuing one writes a `warning.issued` audit event. A warning issued
from a report **resolves that report in the same transaction**, and a report already
decided refuses the warning - which is also what stops a retry from warning twice.

### `role_change_notices`
`id` · `user_id` (`SET NULL`) · `role` (`user`/`moderator`, checked) · `created_at` ·
`acknowledged_at`, with `ix_role_change_notices_user_pending` on (`user_id`,
`acknowledged_at`). The check is the *grantable* roles rather than every role:
`admin` is never set over the network, so a notice about one could only arrive
by mistake, and the database is where that mistake should stop.

**Flow.** What an account still has to be told about its own role. Written by
`PATCH /api/admin/players/{id}/role` in the same transaction as the change and the
`admin.role_changed` audit event, so there can be no role nobody was told about and no
notice about a role that was never granted; a no-op change writes neither. A connected
player is told immediately over the socket (`role_changed`), and everybody else by
`GET /api/role-notices/pending` on their next visit — the same two-route shape a warning
uses, sharing one payload builder so they cannot drift.

**Newest, not oldest** — the one place this parts company with `user_warnings`. Two
warnings are two things a moderator said and both are worth reading; two role notices
are one fact recorded twice, and the older is simply wrong. So the pending query orders
by `created_at DESC`, and acknowledging one settles every older row with it: an account
promoted and then demoted while it was away is told once, correctly, rather than
congratulated and then contradicted.

**No actor column, and no reason.** Who acted is in the ledger, in the same transaction.
The reason is there too and stays there: it is text one administrator wrote for another
and can name a report or a second account, so it deliberately has no route to the person
it is about (R-ROLE-02).

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
| `persisted_at` | The **database write time**, deliberately separate from `finished_at`, making delayed/retried-save lag measurable |

**The rule snapshot** ([`backend/app/game.py:370`](../backend/app/game.py)) freezes the
numeric default/pressure/hint parameters, the drawer-bonus algorithm, the drawing time,
the permitted tools and colors, prompt visibility and language, and the pinned prompt-
source revision IDs. Historical points can therefore be interpreted under the rules that
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
`unavailable_reason` · `failure_code` · timestamps.

`status` ∈ `pending \| ready \| unavailable \| failed \| deleted`.
`ck_turn_drawings_ready_identity` requires a `ready` row to carry a complete format
identity, size, checksum, and either inline bytes or an object key.
`ck_turn_drawings_erased` requires a null payload once unavailable or deleted.
`byte_size` ≤ 8 MiB.

Every drawing from a completed game is kept **for as long as that game, in the same
transaction that records it**. The stored bytes are the canvas frame itself — the
actions, not a picture of them — so a drawing can be replayed and redrawn at any size,
and a PNG stays something the browser produces on demand rather than something the
server keeps. A turn whose bytes the recap had to drop for budget is recorded as
`unavailable` rather than **omitted**. Deleting an account erases the drawings that
account made while leaving the row saying so.

`GET /api/games/{game_id}/turns/{turn_id}/drawing` returns one, and only to a player who
was in that game; **every refusal is a 404**, so the endpoint never reveals whether a
game exists.

Because a database column has no integrity check of its own:

```bash
cd backend && .venv/bin/python -m app.services.drawing_storage --batch-size 2000
```

### `turn_drawing_reactions`
`id` · `game_id` (denormalized) · `turn_id` · `participant_id` (the reactor's **participant
seat**, indexed) · `emoji` · `set_version` · `created_at` · `updated_at`, with
`uq_turn_drawing_reactions_turn_participant` on `(turn_id, participant_id)`,
`fk_turn_drawing_reactions_turn_same_game` on `(game_id, turn_id)` and
`fk_turn_drawing_reactions_seat_same_game` on `(game_id, participant_id)`, both CASCADE.

`emoji` ∈ `heart \| laugh \| wow \| fire` — the **Reaction set**, version 1. Stored as a
code, never a glyph, and a code shipped is never removed from the `CHECK` or reused: the
stored-drawing rule (R-HIST-18) applied to an emoji, so retiring one changes what is
offered and nothing an old row means. `set_version >= 1` says which version of the set the
code was chosen from.

- One reaction per registered account per drawing is the unique constraint. A game holds
  at most one seat per linked account, so no alias resolution sits behind it; guests
  cannot react, so a guest-to-account merge brings none with it.
- The reactor is the **seat**, not an account column: the seat already carries the frozen
  presentation and becomes the **Deleted player** tombstone with everything else, so a
  deleted reactor's reaction keeps counting. The `game_id` denormalization is what lets
  both foreign keys say the turn and the seat belong to the same game.
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

### `turn_participant_outcomes`
One row per current or late-arriving non-drawer seat, per turn.

`id` · `game_id` · `turn_id` · `participant_id` (same-game composite FKs, CASCADE) ·
`eligible` ·
`eligibility_reason` (`eligible \| afk \| disconnected \| joined_late`, the last written only by games finished before a mid-turn arrival became an ordinary guesser) ·
`outcome` (`correct \| incorrect \| no_attempt \| ineligible`) ·
`terminal_state` (`active \| afk \| disconnected \| left`) ·
`correct_guess_time_seconds` · `wrong_guess_count` · `near_miss_count` ·
`hints_used` · `points_spent_on_hints` · `created_at`.

`uq_turn_participant_outcomes_turn_participant` gives exactly one row per seat per turn.
Paired `CHECK`s keep the record coherent: eligibility and its reason must agree with the
outcome, and a correct time exists **iff** the outcome is `correct`.

**When drawing begins, the server freezes the eligible guesser seats**
([`backend/app/services/game_flow.py`](../backend/app/services/game_flow.py)). Players who
were AFK or disconnected at that instant remain ineligible until the next turn; their text
is treated as restricted chat rather than a guess that could reveal the prompt. A player who
joins while the drawing is underway is *added* to the frozen population instead
([`backend/app/game.py`](../backend/app/game.py)) and is recorded as the eligible guesser
they were — which is why no new row carries `joined_late`. Ordinary history retains these
numeric facts but **not guess text** — text retention and evidence are governed separately
(§5).
No-scoring games record the same factual outcomes with zero awarded points and never
invent hypothetical score awards.

### `turn_guesses`
The **optional scoring child** of a correct outcome.

`id` · `turn_id` (CASCADE) · `user_id` / `participant_id` (`SET NULL`) ·
`outcome_id` (same-turn composite FK → `turn_participant_outcomes`, CASCADE,
**unique**) · frozen presentation · `points_awarded` · `guess_time_seconds` ·
`created_at`, with `uq_turn_guesses_turn_participant`. Attempt and hint facts live on
the parent outcome row alone — two records of one fact were two chances to disagree.

One correct guess per participant seat and turn, at the database layer. Finished-game
guesses reference the UUID of their turn **explicitly** — persistence never infers that
relationship from the positions of two independently ordered lists.

### `score_events`
The ordered, **append-only** point ledger for a scored game.

`id` · `game_id` (CASCADE) · `participant_id` (CASCADE) · `turn_id` (CASCADE) ·
`event_order` · `event_type` · `points_delta` · `scoring_version` ·
`rule_snapshot_version` · `corrects_event_id` (self-FK, RESTRICT) · `created_at`.

`event_type` ∈ `guess_award \| hint_charge \| drawer_bonus \| correction`, with
`CHECK`s that pin the sign of each: awards and bonuses positive, hint charges negative,
corrections either but never zero. A `correction` must name an earlier event; nothing
else may. `uq_score_events_game_order` keeps the order unique per game.

**Corrections append; prior events are never rewritten.** The history writer proves the
gameplay events agree with the correct guesses and hint spend, then requires every
participant's ledger sum to equal the cached final score **in the same transaction**.

**Same-game coherence is structural.** Composite foreign keys pair cross-row
references with their `game_id` (or `turn_id`): an event cannot award to a seat, charge
a turn, or correct an entry belonging to another game; a turn's drawer seat must belong
to the turn's game; an outcome's turn and seat must share a game
(`turn_participant_outcomes` carries a denormalized `game_id` precisely so that is
expressible); and a guess's outcome must belong to the guess's turn. The one reference
left single-column is `turn_guesses.participant_id`: its `ON DELETE SET NULL` in a
composite form would null the turn alongside the seat, and the guess's seat is already
same-turn-constrained transitively through its outcome. The writer's
transactional proofs cover the arithmetic; these constraints cover the addressing, so
a second writer, a repair script, or a partial restore cannot silently disagree.

Legacy games explicitly use ledger version `0`, because gross awards and drawer bonuses
cannot be reconstructed from their net totals. No-scoring games use the current version
with an **empty** event list.

### `game_prompt_sources`
`game_id` + `prompt_list_revision_id` composite **PK** (CASCADE / RESTRICT).

The exact immutable list revisions that were actually present in the game's real pool
**after custom-prompt shadowing** — not merely the configured slugs.

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

Exact offers are **participant-only** history and private export data. Share codes are
never stored with them.

### `turn_prompt_offer_sources`
`offer_id` + `prompt_list_revision_id` composite **PK**. Every list revision that
contained an offered curated prompt version.

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
`moderated_at` · `created_at`, with
`uq_prompt_version_concept_language_version`.

Supported languages: `en`, `de`, `es`, `fr`, `it`, `nl`, `pt` — the initial Latin
registry, which case-folds, collapses whitespace, and folds canonically decomposable
accents ([`backend/app/prompt_content.py`](../backend/app/prompt_content.py)). Other
BCP-47 tags are **rejected until their matching semantics are implemented.**

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
`language` · `is_bundled` · `visibility` (`private \| unlisted \| public`) ·
`share_code` VARCHAR(24) **unique** · `moderation_state` · `moderated_by_user_id` ·
`moderated_at` · `version` · timestamps.

`ck_prompt_lists_bundled_owner` forbids an owner on a bundled list;
`ck_prompt_lists_unlisted_share_code` requires a share code for an Unlisted list.

**Governance is schema-first and deny-by-default.** User-owned lists default to
**Private**; **Unlisted** requires a unique share code; **Public** is currently reserved
for official bundled lists and for a future moderation-approved discovery feature.
Ownership, fork provenance, revision tags, moderation actor/time, and moderation state
are relational fields — never JSON tags or a lossy `is_nsfw` flag. Difficulty and content
rating stay on the exact immutable prompt version where their meaning belongs.

**Share codes are bearer capabilities, not UUIDs.** They are cryptographically random,
retained only in private in-memory room state, and **never appear in shared room,
history, preset, or log payloads.**

Limits: an account may own at most **25** lists, and a saved list may contain at most
**500** prompts.

### `prompt_list_revisions` / `_items` / `_tags`
`prompt_list_revisions`: `id` · `prompt_list_id` (CASCADE) · `forked_from_revision_id`
(self-FK, `SET NULL`) · `version` · `language` · `content_hash` · `letter_counts` ·
`letter_total` · `created_at`, unique on `(prompt_list_id, version)`.

`letter_counts` (JSON) and `letter_total` are a **letter histogram** over every
answer the revision holds, computed and stored at the moment the revision row is
created — by `upsert_bundled` when seeding, and by `_write_owned_revision` when a
player creates or edits an owned list. Wheel pricing needs how
common each letter is among the prompts a game can draw (R-HINT-03), which is a
distribution rather than the words — storing it is what lets a room price letters
without keeping its prompt pool in memory. `letter_counts` tallies a–z, the only
letters that can be bought; `letter_total` counts *every* alphabetic character,
including those outside a–z, because it is the divisor and a list in such a language
must keep the ratios it would have had. Membership is counted rather than moderation
state: a revision's members never change, while their moderation state can, so a tally
that tracked the latter would be wrong from the first takedown and stay wrong through any
restore. The cost is that hidden content is priced without being drawable, which
R-HINT-03 records among the histogram's approximations.

`prompt_list_revision_items`: `revision_id` + `prompt_version_id` composite **PK** ·
`position`, unique on `(revision_id, position)`. The `RESTRICT` on `prompt_version_id`
is what stops a prompt version being deleted out from under a revision a game pinned.

Editing a list uses **optimistic concurrency** and creates a new immutable revision
instead of rewriting the revision a running or finished game pinned. The content
language cannot change after creation. Rooms resolve, and games pin, exact revision IDs.

### `prompt_list_localizations`
`id` · `prompt_list_id` (CASCADE) · `locale` · `name` · `description`, unique on
`(prompt_list_id, locale)`.

List `name` and `description` are **authored catalogue copy**; translated copy is stored
separately by *interface locale* and selected from `Accept-Language`, so translating the
UI never changes a list's **content language**.

### `prompts`
The current *display* row for one prompt concept in one list.

`id` · `prompt_list_id` (CASCADE) · `concept_id` (RESTRICT) · `prompt_version_id`
(RESTRICT) · `text` · `created_at`, unique on both `(prompt_list_id, concept_id)` and
`(prompt_list_id, text)`.

**Prompt-list counts are derived from membership on read**, so adding or removing a
prompt cannot leave a cached total out of sync. During the transition to rebuildable
projections, this legacy counter row is linked by concept and updated in place when a
new prompt version rewords it, preserving its existing statistics; old revisions keep
referencing the old wording.

### `prompt_usage_facts`
Append-only per-game usage totals, **not** mutable counters on a display row.

`batch_id` + `prompt_list_revision_id` (CASCADE) + `prompt_version_id` (RESTRICT)
composite **PK** · `occurred_at` · `scoring_mode` · `hint_mode` · `offer_count` ·
`pick_count` · `correct_guess_count` · `total_guesser_count` · `created_at` — the
idempotency triple is the identity, so it is the key.

**Flow.** Each finished game appends one idempotent fact per used prompt/version and
pinned list revision, with the authoritative occurrence time plus scoring and hint modes
(`batch_id` is the game's UUIDv7, which is what makes a retry idempotent). Stats are
derived by **stable prompt concept**, so a later wording revision keeps its history
without matching on display text.

The indexes support time-window and rule filters; the Prompt stats page offers all-time,
30-day, and 90-day windows plus scoring/hint segmentation, and the minimum-guesser
ranking floor applies independently to the selected slice. `occurred_at`, `scoring_mode`, and `hint_mode` are
`NOT NULL`: every fact carries its authoritative occurrence time and rule dimensions,
so bounded and segmented reads never have to exclude unattributable rows.

**Runtime attribution observes the durable/live boundary.** Completed turns
snapshot nullable prompt-version source IDs, and usage writes intersect those IDs with
the game's pinned list revisions. An ephemeral prompt has a **null source even when its
display text equals a curated prompt**, so neither its offers, picks, nor guess results
can inflate the curated list's statistics.

Facts contain **no user identifier**, so they remain reconcilable with retained,
anonymized game outcomes: deleting an account neither invents nor silently decrements a
server-wide gameplay observation.

### Seeding

Bundled lists live in
[`backend/data/prompt_lists/`](../backend/data/prompt_lists/) and are seeded at startup
by [`backend/app/db/seed.py`](../backend/app/db/seed.py). The checked-in shape is
**identity-based, not text-keyed**:

```json
{"conceptId":"01a02b7b-b42d-7afc-a278-fc0ecc83b994","answer":"anchor","promptVersion":1}
```

- Equal text shares a concept **only** when the files deliberately repeat that ID.
- Changing capitalization, punctuation, wording, aliases, or editorial metadata requires
  the **same `conceptId` and a higher `promptVersion`**.
- Adding, removing, or reordering membership requires a higher top-level list `version`.
- Optional `aliases`, `difficulty`, `contentRating`, and `tags` belong to the immutable
  prompt version.
- **Deploying different content under an already-seen list or prompt version is a
  startup-failing seed conflict**, not an in-place rewrite.

---

## 9. Runtime analytics

### `runtime_events`
One raw observation. `id` (integer — the highest-churn table in the schema, purged
after 30 days, referenced by nothing; on SQLite an `INTEGER PRIMARY KEY` is the rowid
itself) · `event_type` · `occurred_at` · `room_id` · `user_id` (`SET NULL`) · `value` ·
`details` (JSON, SQL `NULL` when an observation carries none — not the JSON token
`null`, which is what the type stored before `PortableJSON` declared
`none_as_null`).

Types: `room.created`, `room.closed`, `player.joined`, `player.left`,
`player.disconnected`, `player.reconnected`, `player.evicted`, `command.throttled`, `game.started`,
`game.finished`, `game.abandoned`, `turn.ended`, `timer.overran`,
`canvas.payload_observed`, `drawing.stored`, `recap.budget_dropped`,
`history.write_abandoned` (a finished game's history or prompt-usage write the server gave
up on; `details.kind` is `game` or `prompt_usage`, `details.reason` is `timeout` or `error`,
`value` is the milliseconds spent before giving up — #482).

Observations are **buffered and written in batches**, because a database round trip per
join would be felt as lag inside a drawing. The buffer is bounded and drops oldest when
full, **counting what it dropped**, so a gap is visible rather than silent. It is
flushed on the way out of a planned shutdown, so the observations describing a restart
are not the ones lost to it.

### `runtime_stats_daily`
`stat_date` + `metric` composite **PK** · `occurrences` · `value_sum` (BIGINT) ·
`value_max` · `updated_at`.

Raw events are kept `RUNTIME_EVENT_RETENTION_DAYS` (default 30) and **rolled into these
permanent daily totals first**. What retention costs is the ability to ask about one
particular minute last month; the shape of the month survives. Unbounded event rows on
embedded SQLite is a disk that fills up quietly.

Live counts of rooms, players, and running games are deliberately **not** in the
database: one worker owns all of it, so an in-process count is the true count, and it is
meant to vanish on restart because a live count is not a historical fact.

```bash
cd backend && .venv/bin/python -m app.services.runtime_metrics --purge
```

---

## 10. Retention summary

| Data | Retention | Mechanism |
| --- | --- | --- |
| Friendships, including refusals | Indefinite | Deleted with either account (CASCADE), and on a block |
| Retained messages, room and lobby alike | 30 days | `expires_at`; startup purge + bounded hourly cleanup. The lobby's live backlog (50 lines) is memory, re-seeded from these rows at startup |
| Delivered/failed outbox mail | 30 days (`OUTBOX_RETENTION`); tokens scrubbed at send/give-up | Startup purge + hourly purge in the delivery sweep |
| Pinned report evidence | Protected report policy (outlives the message) | Copied on report submission |
| Raw runtime events | `RUNTIME_EVENT_RETENTION_DAYS` (30) | Rolled up first, then purged |
| Daily runtime roll-ups | Permanent | — |
| Shutdown abandonments | 90 days | Purged at startup |
| Bug report rows | Indefinite | — |
| Bug report screenshots | Until the report is decided | Erased in the deciding transaction; `ck_bug_reports_screenshot_erased` |
| Data exports | 7 days (format v1) | `expires_at`; startup purge + hourly retention sweep |
| Expired sessions | 30 days past `expires_at` | Startup purge + hourly retention sweep; rows of a suspended account are kept |
| Ephemeral room codes | 30 days retirement, then reusable | `retired_until` |
| Codes from the removed persistent-room feature | Permanent | Never enter the reuse pool |
| Guests with no completed game | 30 inactive days (default) | `app.auth.retention` |
| Guests with history | 365 inactive days (default) | `app.auth.retention`; history survives via frozen snapshots |
| Game history, turns, outcomes, ledger, drawings, reactions, usage facts | Indefinite | — |

Anonymous retention is based on `last_active_at` and is bounded to 500 accounts per run.
It **previews by default** and records aggregate audit evidence when applied:

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
- deletes owned prompt lists and their owned prompt concepts, rather than leaving
  ownerless content;
- erases the drawings that account made while leaving the row saying so, and deletes the
  reactions those drawings had; reactions the account gave elsewhere stay, under the
  tombstoned seat;
- erases any screenshot on a bug report that account filed, while leaving the report:
  a defect is not un-found by an erasure, and the reporter foreign key detaches;

The stable anonymized row, scores, prompts, and shared game structure **remain**, so
another player's history is never damaged. Prompt usage facts carry no user identifier
and are untouched.

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

> Every persistence suite builds its database through
> [`backend/tests/dbfixtures.py`](../backend/tests/dbfixtures.py), so `TEST_DATABASE_URL`
> moves all of them onto PostgreSQL. The fixture **deletes application rows** from that
> database and refuses a name without `test` in it. Never point it at a development or
> production database.

Without `TEST_DATABASE_URL` the same fixture hands out in-memory SQLite configured the
way [`db/__init__.py`](../backend/app/db/__init__.py) configures the application's own
connections, and checks `PRAGMA foreign_keys` on every connection it opens. A raw
`create_async_engine` leaves SQLite's enforcement off, and a suite built on one passes
deletion tests against constraints the database never applied — #612 found two
deletion paths that only failed once enforcement was real.

CI upgrades a fresh PostgreSQL 17 database with Alembic, replays the complete migration
chain **down and up** on both PostgreSQL and SQLite, checks schema drift and the
hand-written username index, then runs the whole backend suite against the migrated
schema. A SQLite pass proves integrity, not concurrency: READ COMMITTED interleavings
and row locks are only ever exercised on that job.

### Production deploy order

```bash
cd backend
export SKETCHY_ENV=production                # without it every production guard is off
export DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy
.venv/bin/python -m app.db.migrate          # BEFORE starting or replacing any replica
HOST=0.0.0.0 PORT=8000 .venv/bin/python -m app.server
```

### Adding a table or column

1. Edit [`backend/app/db/models.py`](../backend/app/db/models.py).
2. Generate a migration; make sure it is reversible and that SQLite batch mode is used
   where a table is rebuilt.
3. Add or extend the `CHECK` constraint if the column is an enum, and declare the enum in
   [`domain_values.py`](../backend/app/domain_values.py).
4. Run `pytest tests/test_migrations.py tests/test_db_models.py` — locally on SQLite and,
   for anything non-trivial, against PostgreSQL.
5. **Update this document**, plus [`architecture.md`](architecture.md) if the state
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

Delete this paragraph at launch rather than leaving it to be read as still
true.


The UUID change **rewrote** the pre-v1 initial migration rather than converting old text
keys. Databases created before that baseline must be rebuilt; preserve no production
data on a preproduction schema.

Revision `p8c3a6d9e147` applied the same policy to the legacy-accommodation layer:
nullable-only-for-legacy columns became `NOT NULL`, the `legacy_unknown` enum members
were removed, and the migration **refuses** to upgrade a database still holding
pre-feature rows — filling a null write time or renaming a sentinel would fabricate
exactly the metadata those accommodations existed to avoid fabricating. Rebuild such a
database instead.
