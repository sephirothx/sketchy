# Sketchy

An online multiplayer drawing & guessing game, iSketch/Pictionary-style: one player is given a
prompt to draw while everyone else races to guess it in the chat. Join a public room from the
lobby, or create a private room and share its code — no mandatory accounts required to play.

Terminology is fixed in [GLOSSARY.md](GLOSSARY.md): one agreed name per concept, for UI
copy and docs alike. Read it before naming anything a player can see.

## Features

- Lobby with a live, polled list of open public rooms, or join a private room by code.
- Curated prompt lists (Standard and Extended English) selectable during room creation, combined with optional custom prompts. Pick rate and guess accuracy stats tracked per prompt.
- Turn-based rounds: each player draws once per round, choosing from 3 prompt options.
- Real-time synced canvas (freehand brush + rectangle/ellipse/triangle shape tools).
- Spectator mode — join any room as a spectator (even when full), with optional room creation setting to reveal the prompt, and private spectator chat restricted to the drawer, spectators, and correct guessers.
- AFK mode — toggle AFK status anytime so you are skipped for drawing turns and not waited for during rounds.
- Restart vote — active players can propose and vote to restart the current game by a strict majority without interrupting live gameplay.
- Kick vote and AFK vote — room players can vote to kick or mark another player AFK by a strict majority of connected, non-spectator players. AFK players and the vote target count toward that population; disconnected players and spectators do not. Spectators cannot cast votes or be selected as moderation targets.
- Save image — download the current drawn image directly as a PNG file at any time.
- Customization option to always hide the masked prompt's length and composition from guessers (forces hints off).
- Optional scoring, selected when the room is created.
- Reconnection grace period (30s) — refreshing mid-game rejoins you with your score intact.
- Score system designed to resist "sandbagging": drawers can't game an easy prompt by stalling,
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
        Repo["Repository Layer\nUserRepository\nGameHistoryRepository\nWordListRepository"]
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
- **Durable Persistence**: Accounts, game history records, and curated prompt lists are stored via abstract repository interfaces backed by SQLAlchemy.

## Tech stack

| Layer    | Technology |
|----------|------------|
| Backend  | Python 3.14, FastAPI, python-socketio (`AsyncServer`, ASGI), uvicorn, SQLAlchemy 2.0 (async), aiosqlite, Alembic |
| Frontend | React 19, TypeScript, Vite, react-router-dom, zustand, socket.io-client |
| Testing  | pytest + pytest-asyncio (backend unit tests), Playwright (multi-browser E2E testing) |

## Database & Configuration

Sketchy requires zero configuration by default, using an embedded SQLite database stored locally at `./sketchy.db`. Database migrations run automatically on server startup via Alembic.

To use an external PostgreSQL database instead, set the `DATABASE_URL` environment variable:

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sketchy ./scripts/serve.sh
```

### Accounts

Every visitor is given an account automatically on their first page load, and
it is remembered by an HttpOnly `sketchy_session` cookie. Guests play under a
name of their choosing; setting a username and password later claims that same
account, so stats collected as a guest carry over.

Sessions are signed with a key that is generated once and stored in the
database. Set `JWT_SECRET` to supply your own — required if you run more than
one server process, since they must all sign with the same key, and it also
keeps existing sessions valid if the database is ever rebuilt:

```bash
JWT_SECRET=$(openssl rand -base64 48) ./scripts/serve.sh
```

The authentication endpoints are rate limited per client address. The defaults
suit a normal deployment; raise them if many of your players share one address:

| Variable | Default | Applies to |
| --- | --- | --- |
| `AUTH_LOGIN_LIMIT` | 10 per 5 minutes | `POST /api/auth/login` |
| `AUTH_REGISTER_LIMIT` | 10 per hour | `POST /api/auth/register` |
| `AUTH_LOOKUP_LIMIT` | 60 per minute | name availability and display-name changes |

Limits are keyed on the connecting address. Behind a reverse proxy or tunnel
every request arrives from the proxy, so run uvicorn with `--proxy-headers` and
`--forwarded-allow-ips=<proxy address>` to have the real client address
recovered from `X-Forwarded-For`. Without that flag the header is ignored on
purpose: it is attacker-controlled, and trusting it blindly would let a
password-guesser sidestep the limit by varying it on every attempt.

## Project structure

```
backend/
  alembic/        Alembic migration environment and versioned migration scripts
  data/
    prompt_lists/ Bundled curated prompt list JSON definitions
  app/
    db/           SQLAlchemy models, engine setup, seeding, and migration runner
    repositories/ Abstract repository interfaces and SQLAlchemy implementations
    main.py       ASGI entrypoint - wires FastAPI + Socket.IO together, REST endpoints
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
      timers.py    Application-owned asynchronous timer lifecycle
    presenters.py Pure construction of room, turn, round, and session payloads
    game.py       Pure game state machine (turns, prompt choice, scoring) - no I/O, unit-testable
    rooms.py      In-memory Room/Player/RoomManager domain model
    state.py      Shared RoomManager singleton
    prompts.py    Prompt list + random choice helper
  tests/
    handlers/     Focused asyncio integration suites for each Socket.IO handler domain
    e2e/          Multi-browser Playwright scenarios
    test_*.py     Domain, protocol, payload, wire-contract, timer, DB, repository, and performance unit tests
frontend/
  src/
    components/   Canvas, Toolbar, PlayerList, PromptDisplay, Timer, GuessChat
    pages/        LobbyBrowserPage (home), GameRoomPage (room/gameplay)
    store/        zustand global game state store
    hooks/        useGameSocketListeners - registers all socket listeners once
    lib/socket.ts socket.io-client singleton + REST base URL
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

The canvas benchmark starts the built application on an isolated local port
(`8765` by default), creates a real two-player game, and reports
drawer-to-observer stroke latency, large-fill latency, Undo/replay latency,
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

`game.py` and `rooms.py` are pure logic (no sockets), covered by direct unit tests. Top-level Socket.IO handlers are grouped by domain under `app/handlers` and covered by focused asyncio integration suites in `backend/tests/handlers`. Cross-domain turn, round, timer, and player-removal workflows live in `services/game_flow.py`, while pure outgoing payload construction lives in `presenters.py`. Client JSON commands are validated as strict object payloads in `handlers/payloads.py`; values are not coerced, booleans are never accepted as integers, and bounded validation completes before authorization or mutation. The compact binary drawing and fixed-array undo commands have dedicated parsers for their documented wire formats. `tests/test_wire_contract.py` pins the names the two sides share - the events each direction sends, the camelCase keys the server puts in its payloads, and the aliases its command parsers accept - by reading both trees as text. It also rejects wire names built from vocabulary the glossary retired, because agreement alone cannot tell a current name from an old one both sides kept. Nothing else checks those: a payload key is a plain string here and a plain property there, so renaming one side alone compiles, lints, and passes every other test while the feature silently stops working. Playwright E2E tests in `backend/tests/e2e` cover real-time multi-browser room sessions, settings persistence, AFK status, and disconnection sync across Chromium and Firefox.

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
5. **Turn results** (5s): the prompt is revealed and scores update, then the next player's turn
   begins.
6. Repeat until every player has drawn once per configured round count, then **game over**
   shows final scores.

### Scoring

- Everyone starts a game on zero points, in every scoring mode.
- Room creators can choose **Default**, **Pressure**, or **No scoring**.
  No-scoring games still detect correct guesses and end turns normally, but everyone remains
  on zero points and no leaderboard is shown.
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
  nothing is charged when a hint is bought. Instead, the turn's total hint cost is subtracted from
  the points that turn's correct guess earns, floored at zero: `turn_score = max(0, guess_points -
  hint_spend)`. A turn can be wiped out, but a player's running total never goes down, and hints
  cost nothing at all to a player who never guesses the prompt. Spend is capped at 300 per turn — the
  most a single guess can ever be worth. In Pressure mode the 50-point floor guarantees the *gross*
  award only; the hint debt is settled after it.
- The drawer receives the sum of points earned by all correct guessers in that turn (`drawer_score = sum of guesser scores`, after each guesser's hint spend), balancing drawing and guessing potential across complete rotations.

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

- **Durable persistence with in-memory gameplay**: persistent domain data (users, game history records, prompt lists) is stored via SQLAlchemy with zero-config embedded SQLite by default and optional PostgreSQL support. Real-time game state (rooms, active games, strokes, timers) remains purely in memory for minimal latency.
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
