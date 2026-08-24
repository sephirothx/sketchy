# Issue #393 implementation handoff

Durable checkpoint written on 2026-08-23 because the session execution
allowance reached the user-requested graceful-stop threshold. Resume from this
file and `ISSUE_393_IMPLEMENTATION_PLAN.md`; do not restart the epic from
scratch.

## Non-negotiable contracts

- Durable entity primary/foreign keys use RFC 9562 UUIDv7 through SQLAlchemy
  `Uuid(as_uuid=True, native_uuid=True)`. PostgreSQL therefore uses native
  16-byte UUID storage; `created_at` remains the authoritative business time.
- Preserve privacy-safe performance and incident evidence: exact rules and
  source facts with completed games, bounded metrics/anomaly facts without
  codes/names/content, and explicit retention. Never turn identifiers into
  credentials or high-cardinality metric labels.
- Keep `README.md`, `GLOSSARY.md`, and the status ledger in
  `ISSUE_393_IMPLEMENTATION_PLAN.md` current in every issue branch.
- Branch topology remains:
  `issue/<child>` -> `epic/338...epic/343` ->
  `epic/393-preproduction-baseline` -> `main`.

## Integrated work

- `epic/393-preproduction-baseline` already contains completed umbrellas
  #338, #339, #340, #342, and #341, plus standalone #388.
- `epic/343-live-rooms-deployment-formats` contains:
  - #382 single-worker topology (`a3a3027` on its issue branch),
  - #381 durable globally unique room codes (`b7f39d9`),
  - #383 persistent group rooms (`cbaf13f`),
  - #391 private room-setting presets (`dd92a97`), merged by umbrella commit
    `043ba5e`.
- #391 gate at merge: 702 backend tests (one skip), 159 frontend tests,
  lint/build, one Alembic head, and 48 browser scenarios.

## Current issue #380 state

Active branch: `issue/380-graceful-shutdown-drain`, based on umbrella commit
`043ba5e`. The implementation is complete in the working tree but is not yet
committed or merged.

Implemented:

- `ShutdownCoordinator` lifecycle: starting/ready/draining/stopped state,
  `/api/ready`, liveness/readiness reporting, versioned `server_shutdown`
  notice, bounded configurable drain (`SHUTDOWN_DRAIN_SECONDS`, 0-300,
  default 30), and bounded notice/diagnostic writes.
- A production `app.server.DrainingServer` wrapper closes listeners first,
  keeps established WebSockets alive during the application drain, then lets
  Uvicorn disconnect and run lifespan cleanup. `scripts/serve.sh` and the E2E
  runner use it. This wrapper is required; stock Uvicorn invokes ASGI lifespan
  shutdown only after closing WebSockets, which is too late for the notice.
- New room creation, persistent-room materialization, game starts, and restart
  votes/restarts reject once draining. In-flight create/start work rechecks
  after repository awaits before live mutation. Existing joins/reconnects are
  allowed so a game can finish.
- Games completed inside the window follow normal atomic finished-history and
  prompt-usage persistence. Partial games/canvases are never presented as
  completed history or restored after restart.
- `planned_shutdown_abandonments` stores one idempotent UUIDv7-correlated,
  privacy-safe fact for a game still active at the deadline: phase/round,
  completed-turn and canvas-action counts, coarse player/spectator counts, and
  timestamps. It stores no room code/name, player name, prompt/chat, or canvas
  content and purges after 90 days.
- Frontend shows a persistent deployment notice. README, glossary, deployment
  commands, proxy configuration, and plan status are current.

Verified after the final compatibility fix:

- Backend: `717 passed, 1 skipped`.
- Frontend: `159 passed`; ESLint and production build pass.
- `git diff --check` passes.
- Migration replay/model drift tests pass and Alembic has one head:
  `g6e0b3d7f261`.
- Focused shutdown/server/handler/lifecycle/wire tests pass.

Still required to close #380:

1. Run `env E2E_WORKERS=4 ./scripts/test-e2e.sh`. The attempt was rejected by
   the environment only because the session execution/approval allowance was
   exhausted; do not treat this as a product test failure. The last browser
   gate before #380 was 48/48 on #391.
2. If green, update the #380 ledger row from “browser gate/merge pending” to
   Complete with the 717/159/48 evidence.
3. Commit the current branch, suggested message:
   `Implement bounded graceful shutdown drain (#380)`.
4. Merge it with `--no-ff` into
   `epic/343-live-rooms-deployment-formats`.

## Remaining epic work after #380

- #384: completed-game drawing persistence and the versioned SKCH stored
  format/object-storage lifecycle. Inspect the authoritative issue body before
  implementation.
- #385: record its consolidation under standalone #323; do not build an
  independent competing retry design.
- Complete and merge the #343 umbrella into
  `epic/393-preproduction-baseline`.
- Standalone/cross-epic work still needs explicit implementation or disposition:
  #316, #317, #319 (deferred mobile/PWA), #320 (deferred OAuth), #321, #322,
  #323, #324, #336, #337, and #397. #330 and #318 are already complete under
  #342; #385 belongs to #323.
- Finish the v1 contract/deployment/load/security gates, then merge the long-
  lived #393 branch to `main` only after every issue has a durable disposition.
