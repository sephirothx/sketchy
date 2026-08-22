# Issue #393 implementation plan

Status: approved planning baseline; implementation not started  
Tracker: https://github.com/sephirothx/sketchy/issues/393  
Last updated: 2026-08-22

This is the durable implementation specification for the pre-production schema
and breaking-change audit. Issue #393 remains the authoritative issue index;
this document preserves the architectural decisions, delivery order, branch
topology, contract boundaries, and release gates that individual issue bodies
cannot safely repeat.

Do not delete a decision after it is implemented. Mark it delivered or
superseded and link the PR or ADR that changed it. A PR that changes a decision,
public contract, schema boundary, retention rule, or branch assignment must
update this document in the same change.

## Completion definition

The production baseline is complete when the required foundations and contracts
are implemented, every linked optional feature has an explicit post-v1
disposition, and the final HTTP, Socket.IO, database, room-configuration,
persistence-spool, export, and SKCH contracts are declared v1.

| Disposition | Issues |
| --- | --- |
| Implement for v1 | #316, #318, #322, #323, #330, #336-#397, #399 |
| Already implemented | #23; its tool and color rules still need to be recorded in game history |
| Foundation only | #388 recalculable game facts; no ratings, seasons, achievements, or leaderboard product |
| Partial | #398 ownership, visibility, tags, difficulty, provenance, and moderation fields; public discovery, starring, and user-facing forking remain deferred |
| Explicitly deferred | #319 mobile/PWA distribution and #320 OAuth providers/UI; compatible identity and avatar storage is reserved |
| Decision closures | #380 and #382: active games are intentionally single-process and non-recoverable; draining, abandonment records, and client messaging mitigate that limit |

## Locked decisions

These are defaults for implementation. Changing one requires an ADR and an
update to this document and issue #393 before dependent work merges.

1. PostgreSQL is the sole supported production database. SQLite remains a
   supported zero-configuration development and test database.
2. Existing pre-v1 databases may be discarded once. The regenerated v1
   baseline is the last mutable/squashed migration; every later migration is
   immutable after it reaches the #393 integration branch.
3. Durable entity primary and foreign keys use RFC 9562 UUIDv7. SQLAlchemy uses
   `Uuid(as_uuid=True, native_uuid=True)`, producing native 16-byte PostgreSQL
   UUID storage and portable storage on SQLite. Python values are `uuid.UUID`;
   public contracts use canonical hyphenated strings.
4. UUIDv7 generation is centralized in a locked `generate_uuid7()` wrapper.
   While Python 3.12 is supported, use one pinned UUIDv7 backport on every
   Python version so generation semantics do not differ by runtime. When the
   minimum becomes Python 3.14, the wrapper may switch to `uuid.uuid7()` without
   a data migration. Tests cover version/variant bits, clock rollback,
   concurrent generation, monotonic process-local order, and uniqueness.
5. UUIDv7 is not a credential and not the authoritative business timestamp.
   Session tokens, recovery codes, room codes, and share codes remain
   cryptographically random. Queries that require chronological truth order by
   `created_at, id`; UUIDv7 improves index locality and approximate ordering but
   does not replace timestamps.
6. Active rooms, games, canvases, timers, and socket sessions remain in one
   application process. Persistent rooms and presets preserve configuration,
   not live state. The official production topology has exactly one app worker.
7. Account deletion anonymizes the stable user row and participant snapshots;
   it does not corrupt shared game results. Identity merges use alias records
   instead of rewriting historical seats.
8. Authentication uses revocable opaque per-device sessions plus one-time
   recovery codes. OAuth providers and email delivery are post-v1.
9. Never-played guests expire after 30 inactive days. Played guests are
   anonymized after one inactive year.
10. Chat and guess text has a 30-day retention window. Evidence pinned to a
    moderation report follows the report/audit retention policy.
11. Prompt lists are private or unlisted in v1. Public discovery, favorites,
    and user-facing forking remain disabled.
12. Prompt identity uses stable concepts, immutable language-specific versions
    and aliases, and separate immutable list revisions. Equal text does not
    automatically merge two concepts.
13. Every drawing from every turn of a completed game is retained as versioned
    SKCH in S3-compatible object storage, with filesystem storage for local
    development. Drawings from abandoned games are not persisted.
14. Active-game state is never snapshotted or restored. Planned shutdown drains
    briefly, records abandonment, and clearly tells clients the game will end.
15. The public launch is an explicit v1 break. HTTP routes live under
    `/api/v1`; Socket.IO requires `contractVersion: 1`; there are no unversioned
    compatibility aliases.
16. Observability includes structured logs, Prometheus metrics, durable anomaly
    records, daily server rollups, and anonymous sampled browser performance
    rollups. It must not become per-player behavioral tracking.

## Branch and PR topology

### Long-lived branches

Create the integration branch from `main`:

```text
epic/393-preproduction-baseline
```

Create these six long-lived umbrella branches from the #393 branch:

```text
epic/338-postgresql-migrations
epic/339-database-invariants
epic/340-accounts-identity-privacy
epic/341-game-history-statistics
epic/342-prompt-content-usage
epic/343-live-rooms-deployment-formats
```

The logical flow is:

```text
issue/<number>-<slug>
        |
        v
epic/<owning-epic>-<slug>
        |
        v
epic/393-preproduction-baseline
        |
        v
main
```

Branches are shared integration branches. Do not rebase or force-push them.
Regularly merge `main` into the #393 branch, then merge the #393 branch down
into umbrellas that need the latest integrated foundation. Do not merge one
umbrella directly into a sibling; shared dependencies must reach #393 first and
then flow down.

### Sub-issue routing

| Umbrella | Child issue branches and PR targets |
| --- | --- |
| #338 | #344-#351 |
| #339 | #352-#356 |
| #340 | #357-#366, #394-#396, #399 |
| #341 | #367-#374, #386, #387, #389, #390 |
| #342 | #375-#379, #392, #398 |
| #343 | #380-#385, #391 |

Standalone and adjacent issues (#316, #318-#323, #330, #336, #337, #388,
#397) use `issue/<number>-<slug>` branches and normally target
`epic/393-preproduction-baseline` directly. They may target an umbrella only
when the decision log assigns a single clear owner before work begins. #385 is
not implemented independently; it is consolidated into #323, with #390 owning
the idempotency prerequisite. #23 is already on `main`.

### Integration order

Umbrella development may proceed in parallel, but promotion into the #393
branch is serialized in dependency order:

1. #338 - production database and migration foundation.
2. #339 - database-enforced invariants.
3. #340 - accounts, identity, privacy, roles, settings, and safety primitives.
4. #342 - stable prompt identity and reusable prompt content.
5. #341 - history, ledgers, projections, messages, and drawing persistence.
6. #343 - persistent room configuration, shutdown behavior, and stored-format
   integration.

Standalone PRs merge when their dependencies are present. Cross-epic contract
or integration fixes target #393 rather than being hidden inside the next
umbrella.

Each umbrella stays open until its parent epic is complete. Sub-issue PRs may
be squash-merged into the umbrella. Umbrella-to-#393 and final #393-to-`main`
PRs use merge commits so the integration boundaries remain visible. Open a
draft #393-to-`main` PR early for visibility, but do not merge it until every
release gate passes.

### Migration serialization

Parallel schema work must not create permanent competing Alembic heads.

1. #338 owns the regenerated v1 baseline and lands first.
2. Only one umbrella at a time holds the schema-integration slot for promotion
   to #393.
3. Immediately before an umbrella integration PR is finalized, merge the
   current #393 branch into it and make its first unpublished migration descend
   from the current #393 Alembic head.
4. Migrations may be retargeted while they exist only on an unshipped umbrella.
   After a migration reaches #393, never rewrite or squash it.
5. The umbrella gate requires `alembic heads` to report exactly one head, a
   blank upgrade to head, stepwise downgrade/re-upgrade, and model/migration
   drift checks on PostgreSQL and SQLite.
6. If two already-reviewed migrations cannot safely be linearized, add an
   explicit Alembic merge revision during umbrella integration and document it
   in the PR; never leave multiple production heads.

Contract fixtures follow the same integration rule. Sub-issue PRs update their
contract surface, and the umbrella integration PR regenerates the complete v1
fixtures against the latest #393 branch.

### Information-preservation rules

Every sub-issue PR must include:

- the owning issue and umbrella;
- schema and public-contract impact;
- migration and downgrade behavior;
- privacy, retention, and observability impact;
- corresponding `README.md` updates whenever setup, configuration, deployment,
  operation, API behavior, player-visible behavior, limitations, or test
  instructions change;
- corresponding `GLOSSARY.md` updates whenever domain terminology, public copy,
  event names, payload fields, stored-format vocabulary, or canonical enum
  values are added, renamed, or retired;
- focused test evidence;
- an update to the status ledger below;
- an update to this decision log or a linked ADR when behavior differs from the
  locked plan.

Documentation updates land with the behavior they describe. Do not merge code
with a promise to repair `README.md` or `GLOSSARY.md` in a later cleanup PR. If
a change genuinely has no effect on either document, state that explicitly in
the PR description.

Every umbrella integration PR must include:

- the complete list of included and still-open child issues;
- its final schema/contract diff against #393;
- PostgreSQL, SQLite, backend, frontend, and relevant E2E evidence;
- migration-head and downgrade/replay evidence;
- a documentation review confirming that `README.md` describes the integrated
  behavior and deployment surface and that `GLOSSARY.md` matches every current
  domain, wire, and player-facing term;
- any operational runbook or retention-job changes;
- a summary comment on issue #393 linking the umbrella PR, child PRs, ADRs, and
  test results.

The final #393 PR must not rely on conversation history. Everything needed to
review and operate the release must be present in this document, checked-in
contracts, ADRs, migrations, tests, and runbooks.

## Implementation workstreams

### 1. Database and migration foundation (#338, #339)

- Regenerate the disposable baseline once and provide a clear manual rebuild
  path for existing development databases. Never delete a database on startup.
- Replace string UUIDs with SQLAlchemy `Uuid` and UUIDv7 defaults throughout.
- Use Python string enums plus database `CHECK` constraints rather than native
  PostgreSQL enums. Cover every role, status, mode, outcome, visibility,
  moderation state, and event type.
- Add database defaults for counters, booleans, versions, and timestamps; use
  `sa.false()` for Boolean defaults.
- Enforce natural keys after the history redesign: game/seat,
  game/round/turn, turn/participant, prompt revision membership, session token
  hash, provider identity, list and room codes, block pairs, and idempotency
  keys.
- Drop `prompt_lists.prompt_count` and mutable prompt usage counters. Compute
  counts from membership and serve statistics from rebuildable projections.
- Centralize aware UTC handling. Mutable tables get `created_at` and
  `updated_at`; append-only tables get `created_at`.
- Enable SQLite foreign keys on every connection plus WAL and a bounded busy
  timeout. Test actual database cascades and `SET NULL` behavior.
- Configure PostgreSQL `pool_pre_ping`, pool size, overflow, timeout, recycle,
  and graceful disposal.
- Remove production migration execution from application startup. Provide an
  advisory-lock-protected migration CLI; app startup only verifies head.
- Add PostgreSQL to CI and run repository/migration suites against both
  dialects. Most database tests must migrate rather than call
  `metadata.create_all`.

### 2. Accounts, identity, privacy, settings, and safety (#340)

- Model `anonymous`, `registered`, `merged`, and `deleted` user states plus
  `user`, `moderator`, and `admin` roles. Bootstrap the first administrator
  through an audited CLI command.
- Replace stateless JWT sessions with opaque 256-bit session tokens stored only
  as hashes. Track device label, creation, last use, expiry, and revocation.
- Implement hashed, single-use recovery codes shown/downloaded at registration
  and rotation. Recovery changes the password and revokes all sessions.
- Rehash Argon2 credentials after successful login when parameters are stale.
- Merge guests with an immutable identity-alias row, preserving distinct seats
  when both identities occurred in one historical game.
- Normalize email by trim/lowercase without provider-specific rules, enforce a
  nullable case-insensitive unique key, and record `email_verified_at`. Do not
  expose email recovery before a delivery/verification flow exists.
- Replace arbitrary avatar URLs with built-in hosted avatar keys. Reserve an
  empty uploaded-avatar asset table and external provider identity table for
  later features.
- Make history-to-user references nullable and preserve immutable participant
  presentation snapshots so cookie-less players and deleted users do not
  corrupt shared history.
- Account deletion anonymizes identity and snapshots, revokes sessions, removes
  owned settings/content/configuration and ordinary authored messages/drawings,
  and preserves scores and shared game structure. Pinned moderation evidence
  survives under audit policy.
- Build asynchronous versioned data exports containing the requester's data and
  authored content while excluding other players' private profile fields and
  message bodies.
- Persist security-sensitive auth rate-limit buckets. Low-risk display/stats
  throttles may remain process-local.
- Store registered-user theme, sound/confetti, volume, brush cursor,
  keybindings, and `colorblind_safe_colors` settings. Guests remain
  local-storage-only; registration seeds server settings once.
- Add generalized reports/evidence, bans, blocks, and append-only audit events.
  Bans revoke sessions and reject HTTP and socket authentication. Blocks filter
  ordinary chat and future direct invites without hiding game-critical state.
- Store audit request IDs and keyed IP hashes, not raw IP addresses.

### 3. Prompt identity and reusable content (#342, #318)

- Separate stable prompt concepts from immutable language-specific versions.
  A version contains BCP-47 language, canonical answer, normalized match key,
  aliases, editorial difficulty, content rating, and tags.
- Scope aliases to concept plus language. Accent folding and near-miss matching
  use the exact selected version.
- Bundled seed data carries stable concept IDs. Lists share a concept only by
  explicit reference; matching text never silently merges ownership or stats.
- Give prompt lists registered ownership, private/unlisted visibility,
  moderation state, stable share code, optional fork provenance, and immutable
  revisions. Games pin the exact revisions resolved at start.
- Owners control list content/editorial metadata; moderators control takedowns
  and visibility overrides. Public visibility exists only as reserved schema in
  v1 and cannot be selected by user APIs.
- Keep quick unsaved custom prompts for ephemeral rooms. Their history stores
  text snapshots with null concept/list references and they never affect
  curated statistics. Registered hosts can save them as a private list.
- Fail selected-list resolution visibly. Custom-prompts-only games may continue
  during a prompt-list store failure; no path silently substitutes defaults.

### 4. Finished-game history, statistics, messages, and drawings (#341)

- Allocate a UUIDv7 game ID at game start. Repeated persistence with the same ID
  and payload hash succeeds idempotently; a differing hash becomes an
  operator-visible conflict.
- Persist a typed rule summary and versioned exact rule snapshot: scoring/hint
  parameters, drawing time, allowed tools, color mode, and prompt-source
  revisions.
- Persist participant seats with nullable user reference, frozen presentation,
  final score/rank, and turns played.
- Key turns by explicit runtime UUIDv7, not positional list index. Store every
  offered prompt/source, selected flag, and text snapshot.
- Store one participant outcome per turn, including eligibility, terminal
  state, correct timing, wrong/near-miss counts, hints, and spend.
- Add an immutable score ledger for guess awards, hint charges, drawer bonuses,
  and later corrections. Cached final scores must reconcile exactly. Do not
  write hypothetical score events for no-scoring games.
- Persist audience-aware chat and guess messages for 30 days. Reports copy
  selected evidence before retention removes normal messages.
- Persist SKCH for completed games through transactional PostgreSQL staging and
  idempotent content-addressed object upload. Metadata stores format version,
  checksum, size, status, and object key. History reports `pending`, `ready`,
  `deleted`, or `failed`.
- Retain ordinary drawings with game history. Account deletion removes drawings
  authored by that user after protected report evidence is copied.
- Maintain decoder registries and golden fixtures for every stored SKCH version.
- Build rebuildable daily prompt-stat and user-stat projections from immutable
  facts. Ratings/seasons/achievements remain later projections, not v1 product.

### 5. Persistent configuration and live-state boundary (#343)

- Add owner-controlled persistent rooms with stable globally unique codes and
  typed settings. Anyone with the code may join; only the registered owner may
  edit/archive durable configuration.
- Restarting instantiates a fresh in-memory room from persistent configuration.
  No players, scores, timers, or canvases are restored.
- Add private named room presets containing configuration only.
- Persistent rooms and presets reference stable prompt-list IDs and resolve the
  latest authorized revision when applied. Games snapshot actual revisions.
  Missing/deleted access is a visible validation error.
- Raw quick custom prompts cannot live inside durable room configuration; save
  them as a private prompt list first.
- Retire ephemeral room codes for 30 days. Never reuse persistent codes.
- Archiving prevents new joins; an already-live instance becomes ephemeral
  until empty. Account deletion archives owned rooms and retires codes.
- On shutdown, fail readiness, reject new rooms/game starts, emit a versioned
  shutdown notice, allow a bounded drain, record narrow abandonment events,
  then close timers and storage clients. Do not persist partial games/drawings.
- Consolidate failed history writes under #323/#390. Atomically serialize
  versioned payloads to a required persistent filesystem spool and retry with
  the stable game ID and payload hash.
- Reject acknowledged socket commands immediately while disconnected. Use
  non-buffering/volatile acknowledgement timeouts and request UUIDs for
  state-changing controls; cache completed acknowledgements per session.
- Send the colorblind preference only as a host-only aggregate suggestion. It
  never appears in player, preview, room-list, or public state payloads;
  spectators do not count and dismissal lasts for that live room instance.

### 6. Contracts, operations, diagnostics, and deployment (#316, #323)

- Move product HTTP endpoints under `/api/v1` and require
  `contractVersion: 1` during Socket.IO connection.
- Standardize acknowledged commands as `{requestId, ...payload}` with typed
  success/error envelopes. UUIDs are canonical strings and timestamps are RFC
  3339 UTC.
- Generate deterministic OpenAPI, Socket.IO, room-configuration, spool/export,
  and canvas fixtures. Backend and frontend consume the same checked-in v1
  fixtures.
- Add account/recovery/session/export/delete, settings/blocks/reports,
  prompt-list/revision/share, persistent-room/preset, drawing retrieval, and
  role-gated administration APIs.
- Keep aggregate profile summaries available, but restrict detailed game
  records and stored drawings to participants and privileged reviewers.
- Emit structured JSON logs with request, room, game, turn, and persistence-job
  IDs. Never log credentials, codes, chat, prompts, display names, or raw IPs.
- Export Prometheus gauges/counters/histograms for concurrent rooms/players,
  event-loop lag, handler latency, disconnect/reconnect rate, timer overruns,
  canvas frames/points/bytes/syncs, DB pool/query latency, spool depth, and
  drawing-upload latency. Metrics have no user/room/code labels.
- Retain durable anomaly records for 90 days: abandonments, persistence
  timeouts/conflicts, phase failures, protocol mismatches, oversized payloads,
  upload failures, and exhausted retries.
- Retain privacy-safe daily server rollups for one year: peak concurrency,
  games started/completed/abandoned, reconnects, timer overruns, persistence
  failures, and bounded canvas-size histograms.
- Record server build, contract/drawing/SKCH versions, exact rules, prompt
  revisions, phase durations, action/point counts, drawing checksum, and size
  with completed games. Do not link browser/device diagnostics to a game or
  participant.
- Sample 10% of browser sessions by default for anonymous Web Vitals and canvas
  input/replay/sync latency. Accept only enumerated metric names, numeric values,
  app build, contract version, browser family/major, and coarse device class.
  Buffer and aggregate samples; never store raw samples. Retain daily aggregates
  for 30 days.
- Client telemetry includes no user, room, game, or turn IDs; no names, prompts,
  chat, codes, IPs, URLs, free text, or stack traces. Provide a player opt-out,
  an operator kill switch, strict payload limits, and transient abuse throttles.
- Provide liveness, readiness, and token-protected metrics endpoints. Readiness
  checks migration head, database, writable spool, and drawing storage.
- Add multi-stage Docker packaging and Compose services for PostgreSQL,
  S3-compatible object storage, a one-shot migrator, the single-worker app, and
  persistent spool/object volumes.
- Document proxy trust, pool sizing, admin bootstrap, telemetry controls,
  graceful shutdown, retention jobs, and the unsupported multi-worker topology.
- Provide coordinated PostgreSQL/object-store/spool backup and restore commands
  plus an object-reference manifest. Rollback restores a coordinated backup or
  uses a forward fix; it does not downgrade a populated production schema.

## Tests and release gates

Current planning baseline on `main`: 556 backend tests and 156 frontend tests
pass, and the frontend production build succeeds.

### Sub-issue PR gate

- Focused unit/integration tests for the changed behavior.
- Schema/contract/privacy/retention impact documented.
- `README.md` and `GLOSSARY.md` updated in the same PR, or an explicit
  no-documentation-impact statement included in the PR description.
- Relevant model-to-migration and contract fixtures updated.
- No decision drift from this document without an ADR.

### Umbrella PR gate

- Full backend and frontend unit suites.
- PostgreSQL and SQLite repository/migration coverage.
- One Alembic head; blank upgrade and stepwise downgrade/re-upgrade pass.
- Relevant multi-browser E2E and failure-path coverage.
- UUIDv7 generation/type/serialization and timestamp-order tests where schema is
  involved.
- `README.md` and `GLOSSARY.md` reviewed against the complete umbrella diff;
  stale setup, behavior, limitations, vocabulary, and examples block the merge.
- Status ledger and issue #393 summary updated.

### #393 release gate

- All required umbrella and standalone work integrated in dependency order.
- Contract fixtures are clean and explicitly reviewed as v1.
- `README.md` is the accurate production setup, deployment, operation,
  troubleshooting, API/contract, retention, and limitation guide, and
  `GLOSSARY.md` contains the final canonical v1 vocabulary with retired terms
  still protected by contract tests where applicable.
- PostgreSQL/MinIO Compose smoke: migrate, seed, play and persist, restart,
  reopen history/drawing/persistent room, export/delete, scrape metrics, and
  complete a backup/restore drill.
- Concurrent/idempotent persistence, committed-after-timeout retry, DB outage
  spool, object outage staging, conflict, and orphan cleanup are covered.
- Session revocation/recovery/rehash, identity merge conflicts, guest expiry,
  ban/block/report/export/delete paths are covered.
- Prompt revision, alias, language, unlisted authorization, takedown, bundled
  upgrade, and custom-prompt attribution paths are covered.
- Score reconciliation, participant outcomes, no-cookie identity, projection
  rebuild, SKCH compatibility/checksum/access/deletion, and evidence pinning are
  covered.
- Payload-absence tests prove the colorblind flag and telemetry identity fields
  cannot leak.
- Telemetry sampling, opt-out/kill switch, strict schema, retention cleanup,
  low-cardinality metrics, and poisoned-payload throttling are covered.
- Shutdown/drain, persistent-code restart, code retirement, prompt-store
  failure, and non-buffered socket timeout behavior are covered.
- Every required, partial, completed, and deferred issue has a recorded final
  disposition on issue #393.

## Status ledger

Update this table in every child and umbrella PR. Links should be GitHub PRs or
ADRs once they exist.

| Workstream | Branch | Status | Evidence |
| --- | --- | --- | --- |
| #338 PostgreSQL and migrations | `epic/338-postgresql-migrations` | Complete | #344-#351 integrated; 564 backend, 156 frontend, and 41 E2E tests pass locally; PostgreSQL CI gate configured; README updated and glossary reviewed (no new game terms) |
| #339 database invariants | `epic/339-database-invariants` | In progress | #355 explicit turn-to-guess identifiers implemented; README updated and glossary reviewed (existing Turn/Guess terms) |
| #340 accounts and privacy | `epic/340-accounts-identity-privacy` | Not started | - |
| #342 prompt content | `epic/342-prompt-content-usage` | Not started | - |
| #341 game history | `epic/341-game-history-statistics` | Not started | - |
| #343 live rooms and formats | `epic/343-live-rooms-deployment-formats` | Not started | - |
| Standalone/cross-epic integration | `epic/393-preproduction-baseline` | Not started | - |
| Final production baseline | `epic/393-preproduction-baseline` -> `main` | Not started | - |
