# Sketchy — repository instructions

Setup, test, and benchmark commands live in [README.md](README.md). Read
[GLOSSARY.md](GLOSSARY.md) before naming anything a player can see.

This file is the single source of truth for how to work in this repository.
[CLAUDE.md](CLAUDE.md) points here rather than restating any of it, so a rule
changes in one place.

## Read the reference docs before you implement

`docs/` holds four tracked reference documents. Read the relevant ones **before**
writing code, not after — they carry reasoning that is not recoverable from a diff.

- **[docs/architecture.md](docs/architecture.md)** — processes, layering, state
  ownership, lifecycle, data-flow walkthroughs, and a module index. Read this first for
  anything structural: a new module or service, where state should live, startup or
  shutdown, the single-worker boundary.
- **[docs/wire-protocol.md](docs/wire-protocol.md)** — every Socket.IO event in both
  directions, the acknowledgement convention, inbound payload policy, the binary
  live-drawing and `SKCH` history formats, the canvas sequencing protocol, and the whole
  REST surface. Read it before touching any event, payload key, or route.
- **[docs/database.md](docs/database.md)** — every table, column, and constraint, with
  the flows that write them, plus retention, deletion, and operator commands. Read it
  before touching `models.py`, a migration, or a persistence path.
- **[docs/requirements.md](docs/requirements.md)** — numbered `MUST`/`MUST NOT`
  requirements, the explicit non-goals, and a traceability table. Read it before
  changing anything a player, operator, or moderator can observe — and **always** before
  concluding something is missing. Check the non-goals first: it may be a decision.

Requirements are numbered (`R-SCORE-08`, `N-03`). Cite them when a change implements or
alters one.

## Check whether the docs went stale before you commit

Every change ships with the documentation it invalidates. Before committing, look at
what you touched and work out which of these it makes wrong:

- **docs/wire-protocol.md** — a Socket.IO event, a payload key, an ack field, a REST
  route, a binary format, or a wire version constant.
- **docs/database.md** — a table, column, `CHECK` enum, migration, retention window, or
  persistence flow.
- **docs/architecture.md** — module layout, a new service or handler domain, state
  ownership, startup/shutdown, or a versioning rule. The module index is generated from
  module docstrings, so a new module means a new row.
- **docs/requirements.md** — observable behaviour, a limit, a guarantee, a deliberate
  refusal, or a non-goal. Retire a requirement ID by marking it withdrawn; never reuse
  one.
- **GLOSSARY.md** — a player-visible concept with no name yet gets its entry in the
  same change. Renaming something means updating its entry and the Known drift list.
- **README → Features, Game flow, Scoring, Spectating, Reconnection & disconnection** —
  these describe how the game behaves. Any rule, timing, or new setting lands here.
- **README → Project structure** — a new module or directory.
- **README → Database & Configuration** — a new environment variable, rate limit, or
  default.
- **README → Running tests** — a new or renamed benchmark fixture, or one whose meaning
  changed. The fill fixtures are documented as a pair for a reason; keep that intact.
- **Module docstrings and the comments explaining *why*** — `game.py`, `rooms.py`, and
  `canvas_session.py` carry the reasoning behind their limits and formulas. A changed
  constant usually invalidates the paragraph sitting above it.

"No doc change needed" is a perfectly good answer. Reaching it deliberately, rather
than by not looking, is the point.

Two habits keep the `docs/` four worth reading. **State the reason, not only the rule**
— they are read to decide whether a change is allowed, and "MUST NOT store raw IPs" is
only useful next to *why*. And **keep references clickable and true** — paths are
repo-relative, and a `path:line` anchor has to be verified, because a wrong line number
is worse than none.

## Invariants worth not rediscovering

- **One application worker.** Live rooms, games, canvases, timers, and Socket.IO
  sessions are process-owned. Nothing may assume a second worker.
- **Wire names are unchecked by both compilers.** `backend/tests/test_wire_contract.py`
  is the only thing that catches a half-finished rename. Rename both sides in one change
  and run it.
- **Validation, then authorization, then mutation** — always, in
  `backend/app/handlers/payloads.py`.
- **Pure logic stays pure.** `game.py`, `rooms.py`, and `presenters.py` do no I/O.
- **Stored formats are forever.** A decoder in `canvas_storage.py` is added, never
  removed.
- **Facts, not counters.** Derived rows such as `user_stats_daily` are disposable;
  finished-game facts are not.
- **Mockup artboards are output.** `docs/ui-mockups/*.dc.html` and `canvas.json` are
  written by `tools/build.mjs`; edit `tools/` and commit the regenerated files.
  `scripts/check-mockups-regenerated.sh` fails on a hand-edited artboard.

## Branch naming

Branches are named for the change, never for the tool that made it. Prefixes such as
`codex/`, `cursor/`, `claude/`, and `agent/` are not used; a branch that starts life
with one is renamed before it gets a commit worth keeping.

Use `{prefix}/{short-kebab-description}`, with the prefix that fits the change:

- `feature/` — new functionality.
- `fix/` — bug fixes.
- `test/` — testing improvements.
- `docs/` — documentation.
- `chore/` — CI, tooling, and maintenance.
- `refactor/` — behaviour-preserving restructuring.

State the proposed name before creating the branch. For ambiguous changes, default to
`chore/`.

## GitHub CLI

Always consider `gh` to be correctly authenticated; do not use `gh auth status` as a
blocker.
