# Wire protocol

The complete contract between the Sketchy browser client and the Sketchy server:
transport, framing, every Socket.IO event in both directions, the binary drawing and
canvas-history formats, and the REST surface.

Companion documents: [`architecture.md`](architecture.md) ·
[`database.md`](database.md) · [`requirements.md`](requirements.md) ·
[`../GLOSSARY.md`](../GLOSSARY.md)

> **The rule that governs this document.** Nothing in either language checks that the
> two sides agree on a name. A payload key is a plain string in Python and a plain
> property in TypeScript, so a rename on one side compiles, lints, and passes every
> other test while the feature silently stops working.
> [`backend/tests/test_wire_contract.py`](../backend/tests/test_wire_contract.py) is the
> only thing that catches it. **Rename on both sides in one change, and update this
> document in the same change.**

---

## 1. Transport

| Concern | Value |
| --- | --- |
| Socket.IO path | `/socket.io` (mounted by `socketio.ASGIApp`, [`backend/app/main.py:266`](../backend/app/main.py)) |
| Client transports | `["websocket", "polling"]`, and polling **actually reached** ([`frontend/src/lib/socket.ts`](../frontend/src/lib/socket.ts), #601): `tryAllTransports` moves on when the WebSocket errors while opening, and a stall watchdog puts polling first when an attempt has produced no handshake after 6 s — a dropped upgrade neither errors nor closes, it hangs, and Engine.IO alone would retry WebSocket for ever. 6 s is under the 8 s an acknowledged command waits for the connection, so a join pressed during the stall still lands on the polling session. An application refusal at the handshake (a suspension, a version skew) opened a transport and changes nothing. A polling session is still probed for a WebSocket upgrade from there. The transport each handshake opened on, upgrades and fallbacks ride the bug report's connection telemetry; the server counts handshakes by transport (`sketchy_socket_backlog_closures_total{reason}` (sockets closed for an outbound backlog past the budget, §3 — `age` or `bytes`; anything but zero is a peer that could not keep up), `sketchy_socket_backlog_bytes_max` and `sketchy_socket_backlog_age_seconds_max` (the most any one socket has had queued, and the oldest a queued packet has been, since start), `sketchy_socket_handshake_transport_total{transport}`, §9) |
| Origin | Always same-origin: the backend serves the built SPA in production and E2E, and Vite proxies `/api` and `/socket.io` in dev |
| Authentication | The HttpOnly `sketchy_session` cookie, read from `HTTP_COOKIE` at handshake — named `__Host-sketchy_session` in production (#467), where it is `Secure` unconditionally and a browser will neither accept it over plain HTTP nor let another host set it |
| Scheme | Production is HTTPS only (#467): a handshake over plain `ws:` is closed before it is accepted (uvicorn answers 403), and a plain HTTP request is redirected with 308 to `PUBLIC_BASE_URL`; only `/api/health`, `/api/ready` and `/metrics` answer plain. A `Content-Security-Policy` on every response names `wss://` and `ws://` of the serving host beside `'self'` in `connect-src`, for browsers predating CSP 3 |
| REST base | `/api`, relative to whatever origin served the page |
| Default ack timeout | 8000 ms (`DEFAULT_ACK_TIMEOUT_MS`) |
| Engine.IO | Pinned in [`socket_server.py`](../backend/app/socket_server.py) rather than inherited (#887), the way #561 pinned the layer above it: `ping_interval` **25 s**, `ping_timeout` **20 s**, `http_compression` **on** above a `compression_threshold` of **1024 B**, `allow_upgrades` **on**. So a silent socket is closed **45 s after its last pong** — the ping is not a cycle of its own: Engine.IO schedules the next one when a pong arrives, sends it 25 s later, and closes 20 s after it goes unanswered, which is also what both read loops time out at. Measured from the moment the client actually went quiet that is **20–45 s**, floored by the *timeout*, since it may have died anywhere inside the interval it was waiting out. The 45 s is deliberately *longer* than the seat's 30 s reconnect grace (R-CONN-01): a phone that changes network is usually back in its seat before the server has noticed the old socket at all, so the seat is never released. A client that needs to know sooner has `session_ping` (R-CONN-12, every 5 s, forced every 15 s). The threshold is the polling transport's — a WebSocket has its own compression, above — and stays at 1024 B: measured over a captured gate stream, the responses are either tiny (median 97 B) or already past it, so lowering it to 256 B compresses nothing extra, and 128 B saves 149 B in three minutes while making one response bigger (`benchmarks/polling_compression.py`) |
| Drawing cadence by transport | `flushIntervalMs` **80 ms** on a WebSocket, `pollingFlushIntervalMs` **240 ms** on long-polling (`client_config` version 5, #887). Every flush on polling is an HTTP POST carrying 0.6–0.8 KB of headers and cookie around a base64'd frame: at 80 ms that is ~25 KB/s of header alone, and a third as many POSTs costs a viewer on that transport ink up to 240 ms behind the hand instead of 80 ms. A polling session upgraded to WebSocket mid-session picks the faster cadence up with it. Both are administrator-settable (`client.flush_interval_ms` 10–200 ms, `client.polling_flush_interval_ms` 10–1000 ms, R-CONF-01), and the drawing budget is checked against whichever of the two is shorter, since the budget is per caller rather than per transport (§ Command budgets). It is the **drawer's** transport that picks the cadence, never the viewer's: a batch is played out over the interval that produced it (§6), and since nothing on the wire says what the sender flushed at, the server names the drawing seat's **transport** — `drawerTransport`, on `turn_started` and on `sync_game`, read from that seat's own socket — and each viewer resolves it against the cadences it has been given. The transport rather than the resolved milliseconds, because the two move on different clocks: the cadences are tunables an administrator can change mid-turn, and every client is told the moment they do, so a viewer holding a number went on pacing at the old one until the next turn; which transport the drawer is on changes at most once a session. Either mismatch is visible: an 80 ms batch stretched over 240 ms passes the lag budget on the next frame and becomes a crawl and a snap, and a 240 ms batch paced at 80 ms leaves the canvas still for the other 160 — the stepping #559 removed. A drawer that upgrades from polling mid-turn leaves the value stale until the next turn, which is the forgiving direction rather than a free one: measured at a 16 ms frame rate, 80% of frames advance the ink against 97% matched, and 33% the other way round. Only `polling` is recognised; anything else, including a transport a build has never heard of, is the baseline |
| WebSocket implementation | **wsproto**, named by [`backend/app/server.py`](../backend/app/server.py) through [`backend/app/ws_transport.py`](../backend/app/ws_transport.py) and pinned in `requirements.txt` — never uvicorn's `auto`, which picked by what happened to be installed (#561) |
| Compression | **permessage-deflate with context takeover**, negotiated on every WebSocket: zlib level 6, memLevel 8, a **15-bit (32 KB) server window** the server states in its response whether or not the browser asked (`SERVER_MAX_WINDOW_BITS`); each accepted connection is counted under what it actually negotiated (`sketchy_socket_transport_total{compression}`) |

The client does **not** auto-connect. The handshake reads the session cookie exactly
once, so `App.tsx` connects only after `GET /api/auth/me` has answered — which on a
first visit is *nothing*: that route creates no account (a crawler or a link preview
must not cost a row), and the visitor becomes a guest when they choose a name
(`POST /api/auth/display-name`, R-ACCT-00). The socket then re-handshakes to pick the
new account up (`reconnectWithCurrentIdentity`).

### Compression, and what it means for every size in this document

The server answers a browser's `permessage-deflate; client_max_window_bits` with
`permessage-deflate; client_max_window_bits=15; server_max_window_bits=15`
([`backend/app/ws_transport.py`](../backend/app/ws_transport.py)), and a client that caps
the server window lower gets the smaller of the two. **Every byte count anywhere in this
document is therefore an input to the wire cost, not the wire cost.** Three consequences
worth stating, because each one has already reversed a plausible-looking optimization:

- **Repetition is nearly free.** With context takeover a socket's compressor keeps its
  window across messages, so a payload that resembles the previous one encodes largely
  as a back-reference — consecutive `room_state` broadcasts compress by ~98.7%. Anything
  that saves bytes by *not repeating* something is competing with that and will usually
  lose.
- **Every message costs a boundary.** Each message ends in a `Z_SYNC_FLUSH`, roughly
  five bytes that no payload change can remove. On high-frequency paths this is the
  dominant residue, and only *fewer messages* removes it.
- **A broadcast saves no bytes.** A deflate context is per **connection**, so a
  room-wide emit is compressed separately for every socket, exactly as N individual
  emits are. Replacing a per-socket loop with one broadcast is a server-CPU change and
  nothing more.

Measure compressed, through one context, over a plausible sequence — never a single
payload in isolation. Two more rules, each learned from a wrong number (#563):

- **Measure real, advancing traffic.** A model that repeats the same encoded batch is
  the best case deflate has — every byte already in the window — and it understated
  live drawing by about 3×. [`benchmarks/live_drawing.py`](../benchmarks/live_drawing.py)
  therefore measures recordings made through the production client
  ([`fixtures/live_strokes/`](../fixtures/live_strokes), made by
  [`benchmarks/record_stroke.sh`](../benchmarks/record_stroke.sh)): on the two hand
  drawings, context takeover saves **40–50%** of the drawing's packet bytes, not the 70%
  the repeated batch suggested (on the scripted 120 Hz pen only a third), and it saves
  *less* once the same context has also carried a `room_state` and some chat.
- **Strip the flush suffix.** Every message's deflate block ends in `00 00 ff ff` from
  the `Z_SYNC_FLUSH`, and permessage-deflate removes those four bytes before framing
  (RFC 7692 §7.2.1). A model that keeps them overstates every message by 4 B — a
  quarter of a compressed point frame.

**Why 15 bits and memLevel 8, and why they are constants.** The window is the
compressor's memory of what it already sent on that connection; the memLevel sizes the
hash table it finds matches with. [`benchmarks/deflate_windows.py`](../benchmarks/deflate_windows.py)
runs one viewer's session — join, late-join sync, two turns of recorded drawing with room
churn and chat between strokes — through each candidate, and measures the resident memory
of live zlib contexts rather than trusting a formula:

| window, memLevel | session bytes | of which `room_state` | deflate CPU | per connection | at 400 seats |
| --- | ---: | ---: | ---: | ---: | ---: |
| 12 bits (4 KB), 8 | 61.2 KB | 12.2 KB | 3.8 ms | 126 KB | 49 MB |
| 13 bits (8 KB), 8 | 52.2 KB | 4.5 KB | 3.8 ms | 142 KB | 56 MB |
| **15 bits (32 KB), 8** | **49.8 KB** | **2.7 KB** | **4.0 ms** | **159 KB** | **62 MB** |
| 15 bits, 5 | 50.2 KB | 2.7 KB | 5.3 ms | 78 KB | 30 MB |
| 15 bits, no context takeover | 84.1 KB | 14.1 KB | 6.3 ms | — | — |
| none | 140.6 KB | 60.5 KB | — | — | — |

A 4 KB window is smaller than a 16-seat `room_state` (4.6 KB), so every broadcast is
cold again and costs 4.5× the 32 KB figure; and the window is not where the memory
goes — the memLevel-8 hash table is 128 KB of the 159 — so shrinking it buys little. The
memLevel is the real memory lever, worth half the state for +1% bytes and +30% deflate
CPU; at 62 MB for a full server against a 1.5 GB resident-memory alert it is not a trade
worth making yet, and #461's load run is where to revisit it. Both are constants rather
than settings because a value nobody has measured is not one an operator can choose
well.

**Measured in the process (#875).** Every other byte figure in this document is an
Engine.IO packet before compression; `sketchy_ws_wire_bytes_{out,in}_total` count the
frames the WebSocket connection actually hands to TCP after permessage-deflate, headers
included, so the ratio of the two is the compression production traffic really gets. Under
the release gate's full population with every socket at `deflate-15`, the server wrote
**12.2%** of its packet bytes (7.1 of 58.3 MB over five minutes) and read 68.5% of what
it received — small commands gain little. The same run without deflate writes 104%
(frame headers). Two things the counter does not see: a TLS-terminating proxy in front
of the process can recompress or strip the extension (the transport counter above shows
the second), and a long-polling socket never reaches the WebSocket class, so the ratio
is over WebSocket traffic while the packet counters include polling. The counter also
found that the gate had been running **uncompressed** until then — aiohttp offers no
permessage-deflate unless asked — so its memory figure never held a zlib context. With
the browser's offer, a seat costs ~470 KB above idle against ~130 KB without, about
340 KB of compression state per connection (the model above says 159 KB for the server's
compressor alone; the decompressor for what the client sends, at the same window, and
wsproto's buffers are the rest): ~140 MB at 420 sockets, against the 1.5 GB alert.

**Measured, combined (#568, #869, #888).** One guest's whole inbound stream is captured
under the release load gate's full population (50 rooms, 400 seats,
`benchmarks/run_load.sh --duration 180 --slow-viewers 0 --capture-seat`) and replayed
through one context at the server's settings
([`benchmarks/room_state_deltas.py`](../benchmarks/room_state_deltas.py)). The current
capture is
[`fixtures/viewer_streams/gate-viewer-180s-888.jsonl`](../fixtures/viewer_streams/gate-viewer-180s-888.jsonl),
taken once epic #888 had landed. Its baseline,
[`gate-viewer-180s-888-baseline.jsonl`](../fixtures/viewer_streams/gate-viewer-180s-888-baseline.jsonl),
is the tree the epic started from (`337268e9`) under the **same workload**: that tree's
gate with #938's fix applied, because the gate's between-turn chat had been refused by
the server until then, and a baseline without it would have credited the epic with chat
it never sent. Each tree is driven the way its own browser behaved — the old server
pushed the canvas on join and rebind, today's is asked for it — and the replay
compresses both streams identically, so the comparison holds although the old gate never
negotiated compression. The captures #568 and #869 closed on are kept beside them
([`gate-viewer-180s.jsonl`](../fixtures/viewer_streams/gate-viewer-180s.jsonl),
[`gate-viewer-180s-869.jsonl`](../fixtures/viewer_streams/gate-viewer-180s-869.jsonl)).

| A guest's stream, 184 s | before #888 uncompressed | before #888 on the wire | after #888 uncompressed | after #888 on the wire |
| --- | ---: | ---: | ---: | ---: |
| whole stream | 106.1 KB (431) | 12.1 KB — 66 B/s per seat | 100.5 KB (415) | 7.1 KB — **39 B/s per seat** |
| `chat_message` | 34.7 KB (187) | 6.4 KB (53%) | 24.9 KB (192) | 1.4 KB (20%) |
| `draw` | 3.7 KB (127) | 2.2 KB (19%) | 3.7 KB (127) | 2.2 KB (32%) |
| `room_state` | 61.3 KB (26) | 1.7 KB (14%) | 67.3 KB (28) | 1.8 KB (26%) |
| presence events | 2.3 KB (25) | 0.2 KB (2%) | — | — |
| everything else | 4.1 KB (66) | 1.5 KB | 4.6 KB (68) | 1.6 KB |

**The epic's whole effect on a player's stream is −41% on the wire, and it is one
change.** Chat went from 6.4 to 1.4 KB, which is all but 4 B of the 5.0 KB saved: the
UUIDv7 each line carried (#869) was entropy deflate cannot remove, and nothing in a room
read it. Everything else nets out to about zero on this stream. #880 removed the 25
presence messages (−225 B) and `room_state` grew by what it now carries as `causes`
(+123 B); the first turn names its canvas in `turn_starting` (+45 B) instead of sending
`canvas_reset` and `game_started` (−69 B); and the canvas the browser asks for at game
start adds 52 B the seat never received before, because nothing pushed one into a
waiting room.

What one seat's 184 s does not contain is where most of the epic's other changes act.
Its room finished no game in the window (#871's recap), it is not one of the gate's
reconnecting seats (#872's spread, #877's tail), and it is neither a lobby watcher (#885)
nor a player with the lobby open in a waiting room (#873 changed what the *browser*
subscribes to there, which no gate seat ever did). The whole population sees more of
them: packet bytes out before compression, every socket, 180 s, went **43.1 → 37.9 MB
(−12%)**, about three quarters of it chat's raw saving (~10 KB a seat) and the rest the
reconnect canvas becoming a tail, the folded events and the lobby. The two runs'
server-side figures are not comparable — the old gate never negotiated compression, and
that is most of the difference in memory and timer lateness (#875 measured it).

**The gate asks for the canvas (#888).** Since #877 the server sends a canvas only when
asked, and the gate's seats never asked: the gate had carried none of the canvas-sync
load real players cause, and #882's tail-claim reading said `none` throughout. A seat now
asks when the browser would — once when a game starts, which is when the browser's
canvas mounts and stays mounted for the game, and again after every reconnect, claiming
the prefix it holds — and tracks that prefix the way the browser does. Nothing asks
periodically, in the gate or the browser: a heartbeat's soft rebind and a tab coming back
ask for nothing (#886), so in normal play a player asks about once a game and once per
real reconnect. On the recorded five-minute gate (requirements, *Scale target*) that is
910 requests, 500 of them claims, 456 answered with a tail — counts set by the gate's
reconnect schedule rather than by normal play: a quarter of the non-host seats drop every
30–60 s, 1.7 reconnects a second across 400 seats, which is a stress case for the grace.
The 410 unclaimed requests are the game-start ones, one per seat per game. Even so, canvas
syncs are **0.4% of the gate's bytes out** (0.23 MB of 58.1 MB, full syncs and tails
together): re-syncs were already rare, and the gate now carries them rather than
nothing. Both kinds of miss are the browser's own behaviour, modelled
rather than invented. 17 are claims whose turn ended during the gap (`generation`): the
browser's canvas resets only on `turn_starting`, never on `sync_game`, so it too comes
back holding the old generation. 27 were made mid-stroke (`hash`), which the gate counts
separately and which match the server's misses exactly: the browser's count includes the
open path while its hash covers only the finished actions, so a stroke that finishes
during the gap leaves nothing the server can verify, and a player who reconnects while
watching somebody draw takes a full sync — about 5% of reconnects, which is 5% of an
event that is already rare, at about a kilobyte each for a 20-stroke drawing. Left as it
is. As the browser does, a
seat drops its canvas when it comes back to a finished game (`last_game`), abandons a
request a new turn overtakes, and applies only the reply its outstanding request is
owed.

A **room-state delta protocol is still not worth building (#493).** Replacing every
`room_state` after the first with the patch the issue describes (changed top-level keys
and a version) saves 1.9% of the stream on the wire after #888 (7,095 → 6,960 B, 0.7 B/s
per seat) and 1.7% before it (1.1 B/s), against 14% of the uncompressed stream (the
long-polling bound), while building a snapshot costs 4 µs for a 16-seat room. The compressor already
does the delta: through this real mixed stream a `room_state` costs 66 B on the wire,
about what it costs through a context that saw nothing else (65 B). A smaller window
changes that (4 KB: 11.2 KB → 9.6 KB with deltas), which is one more reason the window is
32 KB (§above). Requirements N-14 records the decision.

The earlier measurements stand as they were taken. At #568, chat — not drawing — was the
largest share of a viewer's wire bytes once drawing was thinned and folded, and #869 found
the reason was the per-line id rather than the per-line message; drawing is the largest
share now. The #568 gate measured 64.6 MB of packet bytes out before compression over
five minutes for 420 sockets, 43% fewer draw messages and about half the draw bytes
against the state before that epic (#560, #559, #603).

The server's own counters (`sketchy_socket_bytes_{in,out}_total`, §9) sit **before** all
of this: they count Engine.IO packet bytes as the server handed them to the transport,
once per recipient, at `eio.send_packet` — the one boundary a room broadcast, an
acknowledgement and a direct emit all pass through. They are the denominator a
compression ratio needs, never the ratio itself, and nothing measured on the server can
say what a terminating proxy negotiated with the browser.

### Handshake

[`backend/app/handlers/connection.py:22`](../backend/app/handlers/connection.py) resolves
the cookie to a session record and stores `{"user_id": …}` on the Socket.IO session.

- No cookie → `user_id = None`. The visitor plays normally, without reconnect or
  history. **Opening a socket never creates a user row.**
- An active suspension → the handshake is refused with
  `ConnectionRefusedError("This account is suspended.")`, surfacing to the client as
  `connect_error`.
- A drain already in progress → the socket is immediately sent `server_shutdown`;
  a maintenance pause → `server_paused`.
- Every accepted socket is sent **`client_config`** before anything else it will
  need it for. There is no acknowledgement on a handshake to put these in, and
  `room_state` is per-room so it never reaches a client sitting in the lobby.

### A tab that goes away and comes back

What the client does when the page is hidden, shown again, or the network
returns ([`hooks/useLobbyChannel.ts`](../frontend/src/hooks/useLobbyChannel.ts),
[`hooks/useRoomSessionReconnect.ts`](../frontend/src/hooks/useRoomSessionReconnect.ts),
#886):

- **Hidden for 30 s: the lobby leaves the channel** (`unwatch_lobby`) and its
  presence list is dropped, the room list marked stale. Showing the tab again
  re-subscribes. Nothing re-subscribes while it is away, a reconnect included.
- **A seat re-binds on return only when it has something to reconcile**: away
  longer than the forced-probe interval (`MAX_GAP_MS`, 15 s), or nothing
  authoritative arrived while it was away. A hidden tab keeps its socket and
  keeps receiving, so a short alt-tab with a phase event in it costs nothing;
  it used to cost a `join_room` and a `sync_game` per seat per return.
- **`online`, and a `pageshow` from the back/forward cache, connect at once**,
  resetting the backoff: the delay it was waiting out describes a network that
  is no longer the one in front of it. Through a close and a fresh connect,
  never a bare one: `Socket.connect()` skips the manager's `open()` while it is
  reconnecting, and `open()` returns early while an attempt is in flight, which
  between them is every state a waiting client is in — so a bare call opens
  nothing and the handler never fires at all. Closing first cancels the pending
  retry and its backoff, and the connect that follows opens one attempt now.
  Not while an attempt is already under way, since that close would abort it
  and an interface that flaps would restart the handshake it keeps
  interrupting; and not during a planned restart, where the hold this client
  drew is the point (R-CONN-14) - a device waking mid-deploy must not turn the
  spread back into everybody at once.

### Reconnection

How a client comes back ([`lib/reconnectPolicy.ts`](../frontend/src/lib/reconnectPolicy.ts),
#872). Every (re)connect costs the server a session resolve, presence and block
warm-ups, a lobby baseline or a seat rebind, and two REST refetches; socket.io's
defaults put every client's first retry 0.5–1.5 s after the close, so a restart
used to be all of that from every client inside a second, against a pool of ten.

- **An ordinary drop** retries on the manager's backoff, written down rather
  than left to the library: 1 s, doubling, capped at 10 s, each ±50%.
- **After `server_shutdown`**, the first attempt waits a uniform random part of
  the notice's `reconnectSpreadMs`. A `connect()` asked for meanwhile (a room
  rebinding) waits on that pending attempt instead of opening its own. A room
  then waits up to 60 s for the server rather than 8 s twice, because a deploy
  is its drain plus a boot. Measured at 400 registered clients on PostgreSQL
  (`benchmarks/reconnect_herd.py`): summed pool wait over the herd 694–738 s →
  0.01–0.11 s, REST refetch p95 1.9–2.0 s → 17–19 ms, and every client back in
  9.9 s instead of 2.7–2.9 s — the spread, as intended.
- **The REST refetches** a reconnect triggers (friends, recovery address) run
  a random 0–3 s behind it, so they queue behind the seat rebind rather than
  beside it. A first connection does not wait.
- **Missed `session_ping`s** (three in a row) no longer tear the transport
  down by default. While Engine.IO's own pings keep arriving the connection is
  alive and the server is only slow, so the seat gets a soft `join_room`, which
  repairs the binding without a teardown or a canvas dump. Only a silent
  transport is restarted. Each escalation pushes the next one out, doubling
  from 5 s to a minute with ±50% jitter, and a successful probe resets it.
  Every seat misses together when the server is the slow one, so the old rule
  answered overload with the most expensive request a client can make.

### Origin

A browser sends `Origin` on every WebSocket handshake, and a WebSocket is not subject to
CORS: without a check, a page on any other site could connect here carrying the
visitor's session cookie and play as them (#465). Engine.IO therefore consults
[`backend/app/origin_policy.py`](../backend/app/origin_policy.py) for every handshake
that carries an `Origin` and refuses with **400** (`… is not an accepted origin`) unless
it is the origin this server serves the page at — the request's scheme and `Host`,
where the scheme is what uvicorn established (rewritten from `X-Forwarded-Proto` only
for a proxy in `FORWARDED_ALLOW_IPS`) — or one named in `ALLOWED_ORIGINS`. A handshake
with no `Origin` is a non-browser client (the probe, the load harness, a script) and is
not judged: it cannot carry a victim's cookie without the victim. The same rule guards
unsafe REST requests (§9).

### Protocol version

The client sends `auth: {protocol: PROTOCOL_VERSION}`
([`frontend/src/lib/protocol.ts`](../frontend/src/lib/protocol.ts)); the server compares it
against its own `PROTOCOL_VERSION` ([`backend/app/protocol.py`](../backend/app/protocol.py)).
Anything that is not a plain integer — absent, a string, a boolean — reads as **0**, because
every build from before this handshake existed sends no `auth` at all and *absent* means
older than version 1, never *trusted*.

A mismatch is **not** refused. The socket connects normally and is sent
`upgrade_required {reason, expected, received}`, which the client answers by reloading —
`index.html` is served `no-cache` precisely so that reload lands on the current bundle.
Refusing instead would hand a stale build nothing it could act on, and
`ConnectionRefusedError` is reserved for suspensions.

Told, then held to it (#476). Until the socket goes it is **quarantined**: every
command it sends is answered `protocol_mismatch {expected, received}` at the dispatch
door — before parsing, so nothing of a contract this server does not speak is acted on:
no room is created or joined, no frame recorded, no lobby watched — and `draw`, which has
no acknowledgement, is dropped in silence. After `STALE_SOCKET_CLOSE_SECONDS` (5) the
server closes it, so a tab that ignores the notice does not hold a socket and a presence
slot for the rest of its life. A reload takes a fraction of a second, so a client that
does act never notices either. The version is checked *after* admission: a stale build
turned away for capacity hears `server_full` (R-CONN-08) and a suspended one is refused,
with no notice and no quarantine — those outcomes stay their own.

> **Why this exists at all.** Frame layouts carry their own version bytes, but they are
> checked far too late to help. A `draw` frame refused by the codec is refused inside a
> handler that has **no acknowledgement** (§4), so the sender is never told: it keeps
> drawing into a canvas the server has stopped recording, and when it finally requests a
> resync it cannot decode the reply — so it requests another. Silent, permanent, and
> indistinguishable to the player from a frozen game. The handshake is the one place with
> somewhere to put the answer.

The client reloads **at most once per server version**, recording the version it reloaded
for in `sessionStorage`. A bundle that somehow does not update — a proxy ignoring
`no-cache`, a stale service worker — would otherwise reload forever, turning a recoverable
skew into an unusable page. When the same server version is seen again after that reload
the tab is **stuck**: the client turns reconnection off and puts the socket down (the
server was about to close it, and reconnecting would only be told the same thing again;
`socket.connect()` itself is a no-op from then on, whoever calls it),
and shows a banner saying the tab is out of date, with a Reload the player chooses. That
reload forgets the automatic one already spent, so a bundle that has been fixed since is
picked up the ordinary way. Nothing is invisible: a stale tab is either reloading, or
saying so.

**REST is held to the same number.** Every HTTP response carries
`X-Sketchy-Protocol: <PROTOCOL_VERSION>`, stamped in the one wrapper every response passes
through, and the client compares it against its own constant on every response it reads
— success or not — taking the same reload-once path, with the same marker, so the two
checks cannot between them reload twice for one server version. This is what catches a
tab that is not on a socket: offline and back, or one that has stopped reconnecting. A
header that is absent or not an integer is ignored rather than read as a skew — a proxy
stripping unknown headers, or a captive portal answering in the server's place, must not
reload the page. There is no `/api/v1`, no N/N−1 support and no per-route version: the
client and the server are one same-origin deployment and change together, and a mismatch
means reload, never a second code path (§11).

**Bump `PROTOCOL_VERSION` on both sides whenever any payload on the socket changes shape.**
It is cheap: both ends deploy together, so the only client that ever sees a mismatch is one
that was already open across the deploy. What "changes shape" means is not left to memory:
§11 describes the contract document CI compares against the base branch, and the policy
on when a difference must carry a bump.

---

## 2. Acknowledgement convention

Commands the client needs an answer to are emitted with an acknowledgement callback.
Every acknowledgement is a JSON object sharing these fields
([`frontend/src/types.ts` `AckResponse`](../frontend/src/types.ts)) — with one
exception, `session_ping`, whose answer is a compact positional tuple (below), because
it is sent every few seconds by every seat and carries no refusal a player could act on:

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | `boolean` | Whether the command was accepted |
| `errorCode` | `ErrorCode?` | **On every refusal.** Why, as one of the enumerated codes below. The only field a program reads |
| `error` | `string?` | English prose for a **log**, a bug report, and an operator reading a response by hand. **Never rendered**: the client writes the player's sentence from `errorCode`, in the reader's language (R-I18N-01), and [`frontend/tests/serverProse.test.mjs`](../frontend/tests/serverProse.test.mjs) fails on any screen that prints this instead |
| `field` | `string?` | The payload field that failed validation, for form binding |
| `params` | `object?` | The values that sentence needs - a count, a limit, a reason slug. **Values, never fragments**: a server-built noun phrase dropped into a client sentence breaks in the first language that inflects (R-I18N-02). Defined for both transports; today only HTTP refusals send one |
| `retryAfterMs` | `number?` | When the server knows trying again could work — a command budget's window, a restart-vote cooldown |

Command-specific **success** additions, all optional: `roomId`, `code` (the invite
code — which is why the refusal discriminator is `errorCode`, not `code`), `playerId`,
`isAnonymous`, `needsRebind`.

**Refusals are one shape** (#565): `{"ok": false, "errorCode": …, "error": …}` plus
`field` or `retryAfterMs` where they apply. Before #565 a refusal carried its reason as
prose, plus on four paths a boolean nobody else set (`roomFull`, `codeRetired`,
`serverDraining`, `serverPaused`); `useCanvasProtocol` compared the sentence "Drawing
actions are out of sequence" to decide whether to resync, so a copy edit could change
recovery. The codes are declared once, in
[`backend/app/refusals.py`](../backend/app/refusals.py) (`ErrorCode`) - top-level
rather than under `app/handlers`, because REST raises the same vocabulary through
[`app/api/errors.py`](../backend/app/api/errors.py) and a sibling package cannot own it
(#760). They are mirrored member for member by `ErrorCode` in `types.ts`, and both
facts are enforced by
[`backend/tests/test_wire_contract.py`](../backend/tests/test_wire_contract.py): the two
enums must match, every `"ok": False` literal on the server must carry a code, and no
client source may compare `.error` to a string. Codes are added, never renamed.

The table below lists the socket families. The REST-only codes - sessions, second
factors, exports, pictures, prompt lists, presets and the reporter's side of
moderation - are the rest of the same enum, and are listed at
[`app/refusals.py`](../backend/app/refusals.py) rather than duplicated here.

| Family | Codes |
| --- | --- |
| Payloads and arguments | `invalid_payload`, `invalid_nickname`, `invalid_name_color`, `invalid_hint`, `invalid_letter`, `invalid_prompt_lists`, `invalid_custom_prompts`, `max_players_below_seated`, `empty_message` |
| Rate and capacity | `too_fast`, `seat_changing_too_fast`, `joining_too_fast`, `room_quota`, `room_full`, `spectators_full`, `player_slots_full` |
| Server and account state | `server_draining`, `server_paused`, `server_busy`, `database_busy`, `account_ended`, `account_required`, `identity_unavailable` |
| Rooms | `not_in_room`, `room_not_found`, `room_ended`, `could_not_create_room`, `no_session_to_resume`, `host_only`, `players_only`, `waiting_room_only`, `already_a_player`, `registered_name_fixed`, `name_taken_by_account`, `name_in_use`, `guests_cannot_choose_color`, `suggestion_inactive`, `drawing_not_found`, `drawing_not_kept` |
| Games and turns | `not_in_game`, `game_in_progress`, `game_starting`, `need_two_players`, `room_not_startable`, `prompt_not_ready`, `prompt_unavailable`, `hints_disabled`, `hint_spend_limit`, `hint_unavailable` |
| Canvas | `drawer_only`, `canvas_stale_generation`, `canvas_sequence_committed`, `canvas_out_of_sequence`, `canvas_out_of_sync`, `nothing_to_undo` |
| Votes and restarts | `spectators_cannot_vote`, `spectators_cannot_be_targets`, `invalid_vote_target`, `not_eligible`, `restart_vote_active`, `restart_vote_cooldown`, `no_restart_vote`, `restart_vote_closed` |
| Reactions | `spectators_cannot_react`, `guests_cannot_react`, `reaction_not_visible`, `own_drawing`, `game_still_saving`, `game_not_recorded`, `reaction_not_accepted` |
| Friends | `friends_unavailable`, `friend_refused`, `friend_not_in_game`, `friend_in_several_games`, `not_friends`, `friends_only_uninvited`, `invite_expired` |
| Moderation | `reporting_unavailable`, `no_such_player`, `cannot_report`, `already_reported` |
| Lobby chat | `name_required`, `not_watching_lobby` |
| Versioning | `protocol_mismatch` — the socket was told to upgrade and has not reloaded yet (§1); carries `expected` and `received` |

Three distinctions worth knowing:
- `room_full` answers only a player-seat request when spectating is still open; a
  spectator refused for the same room gets `spectators_full`, because offering "you can
  still spectate" to somebody refused *as* a spectator is a loop.
- `server_draining` and `server_paused` are told apart on purpose: a drain means this
  server is going away and a reload will find another, while a pause means it is still
  here and will take the room shortly.
- `not_friends` answers both "we are not friends" and "there is no such account", so the
  command cannot be used to test whether somebody has unfriended you.
- `room_ended` also answers an entry — `join_room`, `quick_play`, `join_friend_room`, a
  `create_room` retry — whose room was torn down *while the entry was awaiting
  something*: the session read, the identity resolution, the release of a seat held
  elsewhere. The last seated player can leave through any of those gaps, and a seat
  added to the dead room afterwards answered `ok` to a player nothing would ever address
  again (#1000). The room is re-checked by identity before the seat is taken, on the
  new-seat path and the rebind path alike; a seat this socket already holds and is
  connected on needs no check, since its own presence keeps the room alive.

A payload that fails validation is refused by
`PayloadError.acknowledgement()` ([`backend/app/handlers/payloads.py`](../backend/app/handlers/payloads.py))
as `{"ok": false, "errorCode": "invalid_payload", "error": …, "field": …}` — before any
authorization or mutation runs. A parser may name a more specific code.

**Deliberate exceptions to the shape**, each for a reason the shape would spoil:
- `guess` answers with a receipt that is empty when there is nothing private to say: it is
  momentary *and* confirmed, and the acknowledgement's first job is "it arrived"
  (§ Client-side delivery guarantees). When the guess has a result only the guesser
  sees, it rides the receipt (#884): a correct guess `{correct: {prompt, points,
  basePoints, hintSpend}, line}` — what `you_guessed_correctly` and the guesser's own
  chat line used to say — and a near miss `{line, verdict}`, the guesser's own line and
  the room's announcement on it. A deduplicated retry is answered with the first
  attempt's body: the retry exists because that answer may be the one that was lost. A
  lost answer loses the result, which a correct guess recovers through `sync_game`
  (#870) and a near miss does not need to.
- `session_ping` answers with a compact tuple `[1, phaseCode, round, remaining, gen, seq]`
  or `[0]`: it runs on a timer on every seat and its size is the point. The timer is
  5 s, and a tick is **skipped** when an authoritative event — `turn_starting`,
  `turn_started`, `turn_ended`, `sync_game` or `room_state` — reached the seat inside
  the last interval and agrees with the phase and round it holds; nothing else counts
  (a draw frame, a chat line, a config notice or an Engine.IO pong proves the transport,
  not the seat), and a probe is forced at least every 15 s so a silent one-way failure
  is noticed before the transport would notice it at all (20–45 s, §1) (#564,
  [`frontend/src/lib/heartbeatSchedule.ts`](../frontend/src/lib/heartbeatSchedule.ts)).
  A reply is judged against the seat as it is when the reply lands, and only from the
  socket, room and seat the probe was sent on: an answer older than a turn change that
  landed meanwhile says nothing about the state it lands on.
- a throttled `draw` answers nothing at all (§ Command budgets).

**Earlier still, a command may be refused for its rate.** Every client command answers
to a per-caller budget ([§ Command budgets](#command-budgets)) checked before the
payload is even parsed, and answers `{"ok": false, "errorCode": "too_fast", "error": "You are doing that too
quickly. Slow down a moment.", "retryAfterMs": <the budget's window in ms>}`. The one exception is `draw`: a frame is fire-and-forget
at twenty-five a second, nobody awaits an answer to one, and an error surfacing
mid-stroke is worse than the frame it describes — so a refused `draw` answers nothing at
all. `undo_stroke` shares drawing's budget but **does** answer, because the client sends
it with an acknowledgement waiting on it.

### Command budgets

These are the **defaults**. Every limit is an administrator-settable runtime value
(§9 Operations, R-RATE-09 and R-CONF-01), bounded server-side and applied to the
next command. The windows are **sliding**: each hit is timestamped and a command is
refused when the window ending now already holds the budget's worth, so an allowance
never resets at a boundary a burst could straddle
([`handlers/budgets.py`](../backend/app/handlers/budgets.py)). The drawing budget is additionally bound to
the client's flush intervals, since the interval decides how many frames a
legitimate drawer produces and the budget decides how many are accepted — to
whichever of `client.flush_interval_ms` and `client.polling_flush_interval_ms` (§1) is
shorter, because one caller's budget has to admit either transport.

| Kind | Commands | Budget |
| --- | --- | --- |
| `drawing` | `draw`, `undo_stroke` | 100 per 2 s |
| `conversation` | `send_chat`, `guess` | 20 per 10 s |
| `lobby_chat` | `send_lobby_chat` | 6 per 10 s — its own kind, because a lobby line reaches every open lobby rather than one room's seats |
| `lobby_baseline` | `watch_lobby` | 3 per 10 s — the lobby's largest answer (#885). Covers opening the lobby, the re-handshake of a visitor who has just been named, and one resync; a client stuck resyncing is held to one every few seconds and waits out `retryAfterMs` |
| `client_health` | `client_health` | 2 per 60 s — the client's own report (#876), sent at most once a minute; its own kind so it can never spend an allowance a player's click needs, and two so a report that crossed a reconnect is not refused beside the next. Silent, like `draw` |
| `resync` | `request_sync_strokes` | 1 per 2 s |
| `heartbeat` | `session_ping` | 20 per 10 s |
| `action` | everything else, `react_to_drawing` included | 30 per 10 s |

Windows are per socket and per **kind**, not per command, so two commands of one kind
share the allowance that kind was given. The numbers follow the client's own cadence:
the drawer's flush timer fires every 80 ms (#559), so drawing is allowed four times the
12.5 frames a second that produces — room for an administrator moving the interval back
to 40 ms, and for the bunching a stall leaves behind — while a full canvas replay is
spaced rather than stockpiled.

### Client-side delivery guarantees

`emitWithAckOn` ([`frontend/src/lib/socket.ts:139`](../frontend/src/lib/socket.ts))
never hands a packet to a disconnected socket. Socket.IO would queue it and deliver it
on reconnect, and no `disconnect` event would arrive to reject against — so the timeout
would tell the player the action failed while the packet still lands seconds later. On
these paths that means a second room, or a game started twice. Instead:

- **Acknowledged actions** (create a room, join, start, vote to restart) wait for the
  connection and are sent exactly once, or they time out having never been sent.
- **Entries answer inside the wait, or create nothing (#879).** The client gives an
  acknowledgement 8 s; `create_room` used to make four database calls in a row, each
  bounded at 10 s on its own. Under a slow database the player was told it failed while
  the room was made anyway - a spent creation allowance, one of the account's three
  rooms, and after Quick play's fallback a public room nobody would start. Now
  `create_room`, `join_room` and `join_friend_room` have **6 s from arrival**, the wait
  for the seating gate included: each call gets what is left, and past the deadline the
  entry refuses with `database_busy` and nothing is made, checked at the last instant
  before the room or seat exists. The 2 s left over are for the answer to travel.
- **A creation is idempotent.** `create_room` carries a `requestId`, one per press and
  kept by the client across that press's retries. The server remembers each account's
  last one for 60 s and answers a repeat - an answer lost with the connection, the retry
  made from a new socket - by seating the socket back in that room, spending nothing,
  as long as the account's seat is still there. A copy that arrives while the first is
  still being made waits for it and takes the room its leader made - read from the
  leader, not from the account's memo, which another tab may have moved on. Sockets have
  separate seating gates, so without that both would make one. An entry also releases
  whatever seat its socket held **before** its last checks, and only the in-memory half
  of what that causes is waited on. Whether the old room empties or a spectator keeps it
  standing, the durable writes - the abandoned game's history, the retirement of a
  removed room's code - run as tasks of their own (drained at shutdown), because either
  could hold the entry past its deadline with the seating gate pinned, and neither is
  safe to cut short: a cancelled staging loses the game, a cancelled retirement leaves
  the code claimed until the next start.
- **A late answer is given back.** Should an entry's success arrive after the client
  gave up (`emitEntry`), the client sends `leave_room {roomId}`: the player was told it
  failed and may be somewhere else, so the seat is returned by name and the room they
  are in now is never the one left. Not for a room's own rebind, whose seat is the one
  the player is sitting in.
- **Momentary actions** (`guess`, `vote_player`, `toggle_afk`, `leave_room`) go through
  `emitTransient` ([`frontend/src/lib/socket.ts:220`](../frontend/src/lib/socket.ts)),
  which uses `socket.volatile.emit` so the packet is **dropped** rather than replayed
  into whatever the room has become — a vote cast in a turn that has ended, a guess
  against a prompt nobody is drawing any more, a `leave_room` that evicts the player
  from the room they just rejoined.
- **`guess` is momentary *and* confirmed.** Volatile delivery drops the packet whenever
  the transport is briefly unwritable, not only when the connection is gone, and a lost
  guess is the one silent failure in the game's core loop. So `guess` keeps volatile
  delivery and adds an acknowledgement: `createGuessSender`
  ([`frontend/src/lib/socket.ts:259`](../frontend/src/lib/socket.ts)) emits with a
  2-second ack timeout and **resends once** if nothing comes back, carrying the same
  `id`. A retry is abandoned rather than sent while disconnected — after a reconnect it
  would be exactly the replay volatile delivery exists to prevent. Two unacknowledged
  attempts are reported to the player instead of vanishing.

  The retry is sent only inside the **scope** the first attempt captured — the same
  connection (`socket.id`), the same room and the same turn — and abandoned otherwise
  (#599). `connected` being true at the timeout used to be the whole test, and a
  connection replaced before the timeout, a room switched on the same socket or a turn
  that ended all passed it, replaying the guess into whatever the seat was doing by then:
  the very thing volatile delivery exists to prevent (R-CONN-06). The guess also carries
  its `code` and `turnId`, and the server ignores — acknowledging, so the client stops —
  a guess whose room or turn its seat has left, **before** deduplication, the AFK reset,
  the chat line and the score, so a packet whose scope is gone has no effect at all
  (`sketchy_guesses_out_of_scope_total{scope}`). Like `id`, the scope is optional on the
  wire for the same reason: a client that sends none forgoes the protection, and a retry
  it never makes cannot be judged against it. Each delivery callback settles once,
  whatever arrives late.

  The `id` is what makes the retry safe. It is a per-page-load counter, and the server
  remembers a bounded window of ids **per connection**
  (`Player.accept_guess_id`, [`backend/app/rooms.py`](../backend/app/rooms.py)), so a
  retry of a guess that did arrive is acknowledged and dropped rather than echoed to the
  room a second time and counted twice in the turn's statistics. Ids are meaningless
  across connections: a new sid starts a fresh window, so a reconnected client's counter
  is never judged against the old one. A client that sends no `id` forgoes the
  deduplication and is always processed.

  The acknowledgement carries no body — the handler returns `None` and python-socketio
  sends an empty ACK. Its arrival *is* the message: the guess reached the server. Every
  path in the handler returns, including the ones that deliberately ignore the guess, so
  a client is never told to resend something the server chose not to act on.
- **Live drawing is deliberately not routed through either.** Its frames carry a
  generation and sequence the server checks, and it has an explicit resync path, so
  replay is already answered there (§7).

`SocketRequestError` carries `code: "disconnected" | "timeout"`.

---

## 3. Payload policy for inbound commands

Defined and enforced in
[`backend/app/handlers/payloads.py`](../backend/app/handlers/payloads.py):

- JSON commands accept **objects only**. Commands with no fields also accept `null`.
- **Values are never coerced.** Strings and booleans must have their JSON types;
  integers must be integers and must not be booleans.
- **Unknown fields are rejected** (`extra="forbid"`).
- All strings and integers are **bounded here**, before a handler authorizes or mutates.
- Camel-case wire names are declared as pydantic `Field(alias=…)`; the alias is what the
  client sends.

The drawing protocol is the deliberate exception to the JSON-object rule: `draw`
carries a binary frame (or a bare integer control) plus an optional two-integer action
identity, and `undo_stroke` carries a fixed four-integer array. Both have dedicated
parsers.

### Before dispatch: the envelope

Everything above runs inside a handler, after python-socketio has rebuilt the event.
A *binary* event is rebuilt from a text header that declares how many attachments
follow plus that many binary messages, and the library keeps every attachment until
the declared count is met — so a header declaring 1,000 attachments followed by three
1 KiB chunks left 3 KiB waiting for the other 997 with no handler run and no budget
spent (#596), and the header syntax allows ten billion. R-RATE-08's budgets cannot act
on what has not been dispatched yet, so
[`backend/app/socket_server.py`](../backend/app/socket_server.py) judges the envelope
at `_handle_eio_message`, the one door every inbound packet uses, before a byte is
kept:

| Rule | Bound | Why this value |
| --- | --- | --- |
| Binary events | `draw` only, `BINARY_EVENT` only | The one command that carries bytes; the server never asks a client for an acknowledgement, so a `BINARY_ACK` cannot be ours |
| Attachments per event | exactly 1 (`MAX_ATTACHMENTS`) | A frame is one attachment; the codec cannot spread it over two |
| Placeholder | `{"_placeholder": true, "num": 0}` in argument 1, then at most the action identity, never a second placeholder | The exact shape the client emits |
| Attachment size | `MAX_FRAME_BYTES` = 1 + 256 × (5 + 2) = 1,793 B | The largest frame the codec produces: a full relative frame in which every point escapes and every point changes the width (§6). Without width changes the largest is the absolute frame, 1,025 B |
| Assembly age | `ASSEMBLY_DEADLINE_SECONDS` = 5 s | The two messages leave the client back to back; seconds apart means the second is not coming |
| Text mid-assembly | dropped with the assembly, then judged on its own | A protocol violation, but the text may itself be a well-formed command |
| Packets per socket | `MAX_PACKETS_PER_WINDOW` = the drawing budget's tunable maximum + 100 (500 today) per second, counted before decoding; a frame's attachment does not count | An administrator may raise drawing to `DRAWING.maximum` frames per window and a client bunches frames after a stall, so the whole allowance can land in one second; the margin is the seat's other traffic. This stops a flood, the budgets are the limits |
| Packet size | `MAX_PACKET_BYTES` = 1 MiB, on both transports (engineio's per-packet ceiling, made explicit) | A **byte** ceiling on the encoded packet, not a character count. The largest legitimate command is `create_room` with every field at its bound and the 80 000-character custom-prompts blob (`MAX_RAW_INPUT_LENGTH`): a browser serialises astral characters as raw UTF-8, ~330 KB in all; a serialiser that escapes each as a `\uXXXX` pair produces ~960 KB. Both fit, which is why the ceiling stays at 1 MiB rather than the 512 KiB the REST body limit uses (#566); `test_socket_server.py` pins both sizes and pushes the command through the door on each transport |
| Arguments per command | one payload; `draw` may add its action identity | Checked in `HandlerContext.on` before the handler, refused as `invalid_payload` rather than raising `TypeError` inside the library |

A refused packet is **dropped, never answered** — an answer per malformed packet is the
amplification a flood wants — and counted once per reason
(`sketchy_socket_packets_rejected_total{reason}`, §9). A socket refused more than
`MAX_REJECTIONS` (20) times in a second is closed: it is not speaking this protocol.
What one socket can hold in assembly is therefore one frame, and the per-packet ceiling
bounds one text command; neither depends on what the client declares. Long-polling
delivers the same bytes to the same door — engineio decodes a polling POST's base64
attachment before handing it over — so the rules are one set, not two. No stored format
is involved.

Shared bounds:

| Constant | Value | Source |
| --- | --- | --- |
| `MAX_CHAT_MESSAGE_LENGTH` | 500 | [`message_limits.py`](../backend/app/message_limits.py) |
| `MAX_PROMPT_LENGTH` | 32 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_RAW_INPUT_LENGTH` (custom prompts blob) | 80 000 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_CUSTOM_PROMPTS` | 2 000 | [`prompts.py`](../backend/app/prompts.py) |
| `MAX_ROOM_NAME_LENGTH` | 40 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_NICKNAME_LENGTH` | 16 (`MAX_NAME_LENGTH`, shared with usernames) | [`auth/names.py`](../backend/app/auth/names.py) |
| `MAX_IDENTIFIER_LENGTH` | 128 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_PROMPT_LISTS` per room | 20 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_CANVAS_SEQUENCE` | 2³¹ − 1 | [`payloads.py`](../backend/app/handlers/payloads.py) |
| `MAX_GUESS_ID` | 2³¹ − 1 | [`payloads.py`](../backend/app/handlers/payloads.py) |

---

### After dispatch: the outbound budget

The other direction has a door too (#602). Engine.IO queues every packet for a socket
without a bound and drains the queue as fast as the peer reads; a peer that cannot keep
up holds the writer on the transport's slack and everything after that piles up — a
full canvas sync at a time — for as long as it takes the ping timeout (up to 45 s after the last pong, §1) to notice.
[`backend/app/socket_server.py`](../backend/app/socket_server.py) accounts for every
packet at `send_packet`, trimmed to what the socket's queue still holds, and closes the
socket past either bound:

| Bound | Value | Why this value |
| --- | --- | --- |
| Oldest queued packet | `BACKLOG_MAX_AGE_SECONDS` = 10 s | A healthy socket keeps this at milliseconds; a stalled one grows it at the rate of the stall. Re-read every second (`BACKLOG_SWEEP_SECONDS`), because age is time, not traffic: measured, a peer with nothing new sent to it sat at nine seconds until the ping timeout got there first |
| Queued bytes | `BACKLOG_MAX_BYTES` = 4 MiB | The hard cap a burst of syncs cannot pass inside the age window; ten seconds of anything a room sends is far below it |

The close **aborts**: no CLOSE packet, no waiting for the queue to drain (which a stalled
writer never does), the disconnect handlers run so the seat starts its grace, and the
socket leaves the server's table so the room's next fan-out finds nobody there. Nothing
partial is ever delivered and no draw packet is dropped mid-stream: the client
reconnects, rebinds its seat and takes a fresh sync (§7). What the budget cannot reach is
the slack *below* it — the peer's TCP window, the server's send buffer and the
transport's own 64 KiB — which on a loopback absorbed about 1.2 MB before the queue grew
at all (`benchmarks/slow_viewer.py`), and a stalled writer coroutine holding that slack
lives until TCP gives up on the peer. The gate reports the high-water of healthy play
(one packet, the largest being a sync) so the budget is known to sit far above it;
`sketchy_socket_backlog_closures_total{reason}` counts the closures and
`sketchy_socket_backlog_{bytes,age_seconds}_max` the high-water since start (§9).

## 4. Client → server events

Registered in each domain's `register(ctx)`. The **Ack** column says whether the
client uses the acknowledgement. `guess` is the one command whose acknowledgement is
empty: the client reads only its arrival, as proof the guess was delivered (§2).

| Event | Payload model | Ack | Handler |
| --- | --- | --- | --- |
| `create_room` | `CreateRoomPayload`, with an optional `requestId` a repeat is answered from (§2, #879) | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `join_room` | `JoinRoomPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `quick_play` | `QuickPlayPayload` — one press into a room; answers the join acknowledgement plus `created` (#931) | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `leave_room` | `LeaveRoomPayload` `{roomId?}` — with it, leaves only that room, and does nothing if the socket sits somewhere else (#879) | — | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_room_preview` | `RoomPreviewPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_room_settings` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `update_room_settings` | `UpdateRoomSettingsPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_custom_prompts` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `get_recap_drawing` | `RecapDrawingPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `react_to_drawing` | `ReactToDrawingPayload` | ✓ | [`reactions.py`](../backend/app/handlers/reactions.py) |
| `update_player_settings` | `PlayerSettingsPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) — `nameColor` must be a `#rrggbb` that reads at 1.8:1 on both themes' player-list panel (R-ACCT-08); anything else answers `{ ok: false, error: "Invalid player name color" }`, and a guest's colour is always refused |
| `rename_player` | `RenamePlayerPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `become_player` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `session_ping` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `accept_colorblind_suggestion` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `dismiss_colorblind_suggestion` | `EmptyPayload` | ✓ | [`rooms.py`](../backend/app/handlers/rooms.py) |
| `start_game` | `EmptyPayload` | ✓ | [`game.py`](../backend/app/handlers/game.py) |
| `select_prompt` | `SelectPromptPayload` | ✓ | [`game.py`](../backend/app/handlers/game.py) |
| `draw` | binary frame + optional `[generation, sequence]` | — | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `undo_stroke` | `[generation, sequence, revision, historyHash]` | ✓ | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `request_sync_strokes` | `[requestId]`, or `[requestId, generation, actionCount, historyHash]` | `{ok: true}` once the reply is on its way; `not_in_game` with `retryAfterMs` when there is no canvas; `too_fast` from the resync budget | [`drawing.py`](../backend/app/handlers/drawing.py) |
| `send_chat` | `TextPayload` | ✓ | [`chat.py`](../backend/app/handlers/chat.py) |
| `guess` | `GuessPayload` — `{text, id?, code?, turnId?}`: the id for the one retry, the room code and turn id for the scope it was made in (§2) | ✓ (a receipt; the private result when there is one, §2) | [`chat.py`](../backend/app/handlers/chat.py) |
| `buy_hint` | `HintPayload` | ✓ `{cost, hintSpend, maskedPrompt, hintCost}` — what it revealed (#884) | [`chat.py`](../backend/app/handlers/chat.py) |
| `buy_wheel_letter` | `WheelLetterPayload` | ✓ `{cost, found, hintSpend, maskedPrompt, letterPrices, line}` — what it revealed and the `hint_letter_found` / `hint_letter_missing` line (#884) | [`chat.py`](../backend/app/handlers/chat.py) |
| `toggle_afk` | `ToggleAfkPayload` | — | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `vote_player` | `VotePayload` | — | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `report_player` | `ReportPlayerPayload` | ✓ | [`moderation.py`](../backend/app/handlers/moderation.py) |
| `propose_restart_vote` | `EmptyPayload` | ✓ | [`restart.py`](../backend/app/handlers/restart.py) |
| `cast_restart_vote` | `RestartVotePayload` | ✓ | [`restart.py`](../backend/app/handlers/restart.py) |
| `client_health` | `ClientHealthPayload` `{tailRejected?, syncExhausted?, droppedEmits?, stallFallbacks?, playbackCompressions?, joinToDrawingMs?}` — what only the client can see about its connection, counted since its last report: each count 0–1000, and up to 8 join-to-drawing times of 0–60,000 ms. Sent **only when something happened** and at most once a minute, so a healthy session sends none — and not volatile, because socket.io discards a volatile packet whenever the transport is not writable, which on long-polling is every in-flight POST, and polling is the transport this most needs to hear from; no identifier, no content, no free text (R-OBS-20, #876) | — (fire-and-forget: a refusal answers nothing, and a malformed report is refused whole and counted by its code) | [`connection.py`](../backend/app/handlers/connection.py) |
| `watch_lobby` | `WatchLobbyPayload` `{chatSince?, chatEpoch?}` — the last chat line held and the process that numbered it, so only newer lines are sent (#885) | ✓ — joins the channel first, so a `send_lobby_chat` queued behind it is from a watcher; the acknowledgement carries every baseline (presence, rooms, chat), read after the handler's lookups with nothing yielding before the answer. Presence and rooms are the **last completed broadcast**, built once per tick and shared by every asker (#885), so the next delta follows them exactly; a delta already on its way when the answer is built reaches the socket first, and the client holds it and replays it (#600) | [`lobby.py`](../backend/app/handlers/lobby.py) |
| `unwatch_lobby` | `EmptyPayload` | ✓ — sent when the lobby is navigated away from, and when the tab has been hidden for 30 s (#886): a background tab was taking every tick, room change and chat line for as long as it stayed open. Coming back re-subscribes, which costs one baseline and only the chat the tab does not already hold | [`lobby.py`](../backend/app/handlers/lobby.py) |
| `send_lobby_chat` | `TextPayload` | ✓ | [`lobby.py`](../backend/app/handlers/lobby.py) |
| `add_friend` | `AddFriendPayload` | ✓ | [`friends.py`](../backend/app/handlers/friends.py) |
| `friends_in_room` | `EmptyPayload` | ✓ | [`friends.py`](../backend/app/handlers/friends.py) |
| `friends_online` | `EmptyPayload` | ✓ — from anywhere, seated or not | [`friends.py`](../backend/app/handlers/friends.py) |
| `invite_friend` | `FriendUserPayload` | ✓ | [`friends.py`](../backend/app/handlers/friends.py) |
| `join_friend_room` | `JoinFriendRoomPayload` | ✓ | [`friends.py`](../backend/app/handlers/friends.py) |

### `react_to_drawing`

One registered seat's reaction to one drawing, named by the turn's durable id
(#520). Addresses nothing by account: the reactor is the seat the socket holds,
the drawing is a turn id the room handed out, and the broadcast that follows
carries a seat token back (R-ROOM-07).

```jsonc
{ "turnId": "0192…", "emoji": "heart" }   // "emoji": null takes the reaction back
```

`emoji` ∈ `heart | laugh | wow | fire` — the offered **Reaction set**; a retired
code is refused on the way in and still rendered from history. Two kinds of
drawing accept one. The current turn's, while the phase is `drawing` or
`turn_results`: the reaction lives on the room until the game's history is
written. One in the recap, after the game ended: the row exists, so the handler
writes through the same repository method the REST route uses, and refuses with
`game_still_saving` inside the window between `game_ended` and the history write
landing - shown as *"That game is still being saved. Try again in a moment."*, so
the refusal itself must reach the control with its code - or `game_not_recorded`
when there is no row to write to. Guests are told to create an
account; spectators, the drawer (by seat **and** by account), and any turn not
on screen are refused. The acknowledgement carries `turnId`, `emoji` and the
new `tally`. Answers to the `action` budget like any other pressed control.

### Room settings fields

`RoomSettingsFields` is the shared base for `create_room`; `UpdateRoomSettingsPayload`
mirrors it with every field optional (absent means *unchanged*).

| Wire key | Type | Default | Bounds |
| --- | --- | --- | --- |
| `name` | string | `""` | ≤ 40, trimmed |
| `isPublic` | boolean | `true` | — |
| `maxPlayers` | integer | `8` | 2 – 16 |
| `rounds` | integer | `3` | 1 – 10 |
| `drawingSeconds` | integer | `90` | one of 15, 30, 60, 90, 120, 180, 240, 300 |
| `customPrompts` | string | `""` | ≤ 80 000 chars (`MAX_RAW_INPUT_LENGTH`), trimmed; newline/comma separated. Characters, not bytes: the byte ceiling is the packet's (§3) |
| `customPromptsOnly` | boolean | `false` | — |
| `hintMode` | string | `"checkpoints"` | `none \| checkpoints \| purchase \| wheel` |
| `scoringMode` | string | `"default"` | `none \| default \| pressure` |
| `spectatorsSeePrompt` | boolean | `false` | — |
| `hideMaskedPrompt` | boolean | `false` | forces hints off |
| `allowedTools` | string[] | `["brush","fill","shapes"]` | at least one of `brush`/`shapes` must remain |
| `colorMode` | string | `"all"` | `all \| palette \| colorblind_safe \| black_and_white` |
| `promptLanguage` | string | `"en"` | one of `en`, `de`, `es`, `fr`, `it`, `nl`, `pt`. **Create only** — see below |
| `promptListSlugs` | string[] | the declared language's Standard list | ≤ 20, trimmed/lowercased/deduped; empty ⇒ that language's own `<language>_standard` on create, refused on update. Every slug must resolve to a list in `promptLanguage` |

`create_room` adds `nickname`, `nameColor`
(`#rrggbb`), and `colorblindSafeColors`.

**`promptLanguage` is declared, not derived, and only at creation** (R-PROMPT-02).
The room says what language it is in and its lists answer to that; selecting a list
never changes it. `UpdateRoomSettingsPayload` therefore has no such field, and since
unknown fields are rejected (§ payload policy), sending one is refused with
`field: "promptLanguage"` rather than compared against what the room already holds.
A room's own quick custom prompts are matched under the declared language too, which
is what a room drawing on nothing but custom prompts gets out of the field.

### `get_room_preview`

Acknowledges with `{ ok, room, players }`. `room` is the same `RoomSummary`
`GET /api/rooms` returns; `players` is the room's seated players, each
`{ nickname, nameColor, isAnonymous, isHost }` — spectators excluded.

**The roster is answered here and nowhere else.** `to_public_summary()` carries
no player identities, so polling the lobby every four seconds cannot become a
live directory of who is playing where; this is one room, answered when a
visitor opens its card. The entries carry no seat id, no account id (room
payloads carry none anywhere — see the note under `report_player`), no score
and no connection or AFK state: none of that helps somebody decide whether to
join, and each one would say more about a stranger than the question needs.

`join_room` takes `roomId` **or** `code` (at least one required; `code` is upper-cased),
plus `nickname`, `nameColor`, `colorblindSafeColors`, `asSpectator`, `soft`,
`reconnectOnly` — used by the invite screen to ask *"do I already hold a seat
here?"* without seating a visitor who is still deciding whether to play or spectate. A
join admits a game in progress; Quick play, below, does not.

**`quick_play`** (R-UX-14, #931) is one command and one answer: `{nickname, nameColor,
colorblindSafeColors, promptLanguage}` in, a seat out — the ordinary join acknowledgement
plus `created`, which says whether the room was opened for it. The server picks the
fullest **public** room that is **waiting with no game running**, plays in that language
and has a seat free; failing that it opens one on its own defaults, public and in that
language. The choice used to be the client's, from the lobby's room list: a `join_room`
per candidate until one took the seat, so a press cost up to N+1 round trips, could not
run until a list had arrived (ten seconds after naming a first-time visitor, whose naming
reconnects the socket), and gave every presser in one moment a room of their own, because
each read the same list. Openness is re-checked at the instant the seat is added, with
nothing awaited in between; a room that filled or started meanwhile is the next
candidate's turn rather than a refusal, and the entry deadline (§2) is what ends the
picking. Callers who find nothing and open a room share the first one opened for their
language, so twenty presses on an empty server fill three rooms rather than opening
twenty.

Both `create_room` and `join_room` **release any seat the socket already holds**: the
room it came from sees an ordinary departure for it (a `left` cause on its `room_state`) and, if that was its last
player, ends. A client does not have to send `leave_room` first, and one that does
sees no difference.

> **Names and colors are resolved server-side, not taken from the payload.**
> A registered player always plays as their username and their account color
> ([`backend/app/handlers/identity.py:30`](../backend/app/handlers/identity.py)), so a
> name in the player list is either a claimed account or an unclaimed guest and never
> one impersonating the other. Guests are pinned to the guest grey `#888888`.

### `report_player`

Addresses the reported player **by room seat, never by account**. Room payloads
deliberately carry no account IDs, so a client could not name one even if it wanted to;
the server resolves the seat against the live room and selects the evidence itself.

```jsonc
{ "targetPlayerId": "…", "reason": "harassment", "details": "…", "includeDrawing": false }
```

`reason` ∈ `harassment | offensive_drawing | inappropriate_name | cheating | spam |
inappropriate_avatar`; `details` is optional and at most 1000 characters (stripped, so
blank is empty) — the server attaches the evidence itself, and from a room that is
usually the whole complaint; `includeDrawing` (optional, default `false`) asks for the
canvas to go with the report.

Acknowledgement: `{ ok, id, evidenceCount, drawingAttached }`.

> **The drawing is asked for, never sent.** `includeDrawing` is a request: the server
> copies the room's own canvas frame (the same `SKCH` bytes a `sync_strokes` carries)
> and only when the reported seat is the one drawing this turn and the canvas still
> shows it (drawing phase or turn results). A report about a guesser, or one filed once
> the next drawer is choosing, is accepted with `drawingAttached: false`, which the
> dialog tells the reporter — the turn can end between opening the dialog and sending.
> The client offers the box only where the server would copy (`canAttachDrawing` in
> [`lib/moderation.ts`](../frontend/src/lib/moderation.ts)); the server's rule is the
> one that holds. What was copied is read back by a moderator over
> `GET /api/moderation/reports/{report_id}/drawing` (R-MOD-14), which stays per report:
> an incident may carry several, one per reporter who attached the canvas as it stood
> when they sent.

> Note the deliberate asymmetry: the **socket** report bounds `details` at 1000, while
> the **REST** `POST /api/reports` bounds it at `MAX_REPORT_DETAILS` = 2000 and also
> accepts `contextSnapshot` (≤ 32 768 bytes) and `messageIds` (≤ 20, which must be
> unique). On both, `details` is optional and stripped: the evidence is the
> complaint, and the queue reads an empty one as *no details given* rather than as
> words the reporter never wrote. The socket path exists so a player can report from
> the room without leaving it, and the server selects the evidence itself. On both paths the server then copies
> the conversation around the cited lines as `context` (R-MOD-13); the acknowledgement's
> `evidenceCount` counts the cited lines only.

> **Two routes, by where the reporter is.** A room reports a *seat* over this event. A
> line of the lobby's chat has no seat, so the lobby reports over **REST** instead: the
> A **picture** is reported the same way and from the two places it is actually seen — the lobby's online list and the profile page: `POST /api/reports` with `reason: "inappropriate_avatar"` and **no** `messageIds`, which the server scopes `profile` and records the account's current avatar key against (R-AVA-06). An account with no picture is refused 422 rather than queued.
>
> client sends `POST /api/reports` with `reportedUserId` set to the `userId` the
> `LobbyChatMessage` (§5) carries (the lobby's exception to R-ROOM-07),
> `messageIds` naming that one line's `retainedMessageId`, and one of `harassment |
> spam | inappropriate_name`. A line delivered without a `retainedMessageId` cannot be
> cited and is offered no report action. The server checks the line the way R-LCHAT-05
> says: the author must be the reported account, no audience check, and never mixed with
> room lines. `report_player` never selects a lobby line. Client:
> [`ReportLobbyLineDialog.tsx`](../frontend/src/components/ReportLobbyLineDialog.tsx).

---

## 5. Server → client events

| Event | Payload | Scope |
| --- | --- | --- |
| `room_state` | `RoomStatePayload` — the whole state on every change, deliberately: a delta form was measured on a real viewer's stream under the full population and saves 1.5–2.6% on the wire (§1, *Measured, combined*; N-14). **At most one per room per action** (#880): a command, a connect or disconnect, or a timer firing marks the room and one snapshot goes out when the action is done, after the action's other events, as the room ended up. Two exceptions go at once, because the events after them depend on it: a socket taking a seat gets the room before its own `sync_game` / `last_game` (a client's first snapshot of a room resets what belonged to the one before), and a room turning to play is sent before its first `turn_starting` (that snapshot mounts the canvas the turn resets). **`causes`**, present when something needs saying, is why, in order: `{presence: "joined" \| "reconnected" \| "disconnected" \| "left", playerId, nickname}` for a seat that came or went — what `player_joined`, `player_reconnected`, `player_disconnected` and `player_left` used to be — and room-authored announcements (below) said to the whole room inside the action, which used to be `chat_message`s beside the snapshot. The client applies the snapshot first and then each cause, as a sound and a line (#880) | room |
| `turn_starting` | `{drawerId, drawerNickname, drawerNameColor, roundNumber, totalRounds, seconds, canvas: [revision, generation, sequence, historyHash], gameStarted?: true}` — the turn's new canvas identity, and on a game's first turn the fact that it started: one message where `canvas_reset` and `game_started` used to precede it (#880). A restart says so in its own announcement | room |
| `your_prompt_choices` | `{choices: string[], seconds}` | drawer only |
| `you_are_drawing` | `{prompt}` | drawer only |
| `turn_started` | `{turnId, drawerId, maskedPrompt, roundNumber, totalRounds, seconds, hintCost, letterPrices, hintSpend, maxHintSpend, drawerTransport}` — the last being `"polling"`, `"websocket"` or `null` for a seat between reconnects, which this socket resolves against the cadences in force to pace its playback of the drawer's batches (§1, R-DRAW-01) | **per socket** |
| `sync_game` | same shape as `turn_payload`, plus `turnId`, the turn's `reactions[]`, `drawerTransport` (§1), `correctGuessers: [[playerId, seconds]]` in guessing order, and `guessed` — this seat's correct-guess receipt (what a correct `guess` is answered with, §2), or `null` (R-CONN-13) | one socket |
| `turn_ended` | `TurnEndedPayload` | room |
| `game_ended` | `{scores, highlights, drawings}` — each drawing carrying `turnId` and its `reactions[]` | room |
| `last_game` | the same `{scores, highlights, drawings}`, for a socket that joined or rejoined the waiting room after `game_ended` (#871) — the recap without the end-of-game moment | one socket |
| `drawing_reaction` | `DrawingReaction` — one seat reacted to, or took its reaction back from, one drawing; on a finished game's recap also `highlight`, the refreshed most-reacted card or `null` (#871). No `room_state` follows it | room, the drawer included |
| `chat_message` | `ChatMessage` | room or a filtered recipient list |
| `correct_guess` | `{playerId, nickname, points}` | room |
| `hint_revealed` | `{maskedPrompt, turnId}` — a **timed** checkpoint hint, which answers no command; a bought hint answers in its own acknowledgement (#884) and names no turn, being an answer to something the player just did. `turnId` is the turn the hint belongs to: the loop emits one per seat and the turn can end between two of them, so a client drops a hint for a turn it has already ended rather than re-masking the prompt `turn_ended` revealed (#883) | **per socket**, each seat its own masked prompt |
| `draw` | the drawer's exact wire frame, rebroadcast verbatim — plus `[generation, sequence, revision, historyHash]` when that frame commits an action (§7) | room, `skip_sid` drawer |
| `canvas_commit` | `[generation, sequence, revision, historyHash]` | the drawer, or one socket replaying a duplicate |
| `canvas_undo` | `[generation, sequence, revisionBefore, revisionAfter, historyHash]` | room (or one socket) |
| `sync_strokes` | `(binaryHistory, revision, generation, sequence, historyHash, requestId)` — only ever the answer to a `request_sync_strokes`, whose id it echoes; a join or a rebind pushes none (#877) | one socket |
| `sync_strokes_tail` | `(binaryTail, baseActionCount, revision, generation, sequence, historyHash, requestId)` — only the actions after a verified prefix (§7); always answers a request, never unsolicited | one socket |
| `request_canvas_actions` | `[generation, expectedSequence, receivedSequence]` | one socket |
| `canvas_stale` | `[generation, sequence, reason, retryAfterMs]` — this socket's canvas needs recovering: `stale_generation`, `refused_tool`, `unknown_sequence`, `invalid_frame`, `dropped_frame` (a frame of this socket's was throttled at the door and the open path was closed where the server's copy ends, §6). At most one per socket per window; the client answers through its sync transaction (§7) | one socket |
| `afk_check` | `{seconds}` — this seat has sent nothing a person sent for the inactivity window, and is being asked whether anybody is there. Answered with `toggle_afk {afk: false}`, which is what the client sends by itself when it has seen a pointer or a key inside `afkInputWindowMs`, and otherwise what the **AFK check** dialog sends. Unanswered for `seconds`, the seat is marked AFK. Never sent to a spectator, a seat already AFK, or an unseated socket | one socket |
| `voted_afk` | `{message}` — English, for a log; the client says it from the event itself (R-I18N-01) | the player who was voted AFK |
| `kicked` | `{code, reason}` — `code` is `kicked_by_vote`, `room_closed` or `removed_by_admin`, and is what the client says; `reason` is English, for a log (R-I18N-01) | one socket |
| `colorblind_safe_suggestion` | `{active}` — sent only when the value changes or the host's socket does (#880), not beside every `room_state` | **host only**, unattributed |
| `session_superseded` | `{code, reason}` — `opened_elsewhere`, `account_deleted` or `account_suspended`, said by the client from the code; `reason` is English, for a log — then the socket is disconnected | the superseded socket |
| `upgrade_required` | `{reason, expected, received}` — the socket stays open; the client reloads (§1) | one socket, at handshake |
| `account_suspended` | `{detail, suspended, reason, expiresAt, …}` — the same body the HTTP refusal returns | every socket of the suspended account (each socket joins a `user:{id}` broadcast room at connect), which is then disconnected |
| `moderator_warning` | `{warning: {id, reason, createdAt, messages}}` — the same body `GET /api/warnings/pending` returns | every socket of the warned account |
| `role_changed` | `{notice: {id, role, pending, createdAt} | null, pendingRole}` — the same body `GET /api/role-notices/pending` returns. Emitted whether or not there is a notice: `pendingRole` says what is still outstanding on the account, and **withdrawing an offer** is the case with nothing to say and a change worth hearing — it settles the notice and ends the offer together, and a browser that missed it would go on offering an enrolment that would now grant nothing. The role and nothing else: the reason the administrator recorded is ledger text written for other administrators and can name a report or a second account. `pending` distinguishes a role the account **holds** from one it has been **offered** and takes up by enrolling a second factor (R-AUTH-20) — the second asks something of the reader, so it cannot be worded like the first, and it revokes nothing | every socket of the account whose role changed |
| `server_shutdown` | `ServerShutdownNotice` | every socket |
| `server_paused` | `ServerPausedNotice` — an administrator stopped, or resumed, admitting new rooms | every socket on each toggle; one socket at handshake while paused |
| `server_full` | `{reason}` — English, for a log; the client says it from the event itself (R-I18N-01). The socket is closed immediately afterwards | one socket, at handshake |
| `lobby_presence_changed` | `{revision, joined: LobbyPlayer[], left: userId[], changed: LobbyPlayer[], onlineCount}` — one fixed-tick delta, emitted only when the snapshot actually moved | the `lobby` channel: every socket that asked with `watch_lobby` |
| `lobby_rooms_changed` | `{revision, opened: RoomSummary[], closed: roomId[], changed: RoomSummary[]}` — the public room list moved, on the same fixed tick. Its own revision, because the two feeds move independently | the `lobby` channel: every socket that asked with `watch_lobby` |
| `lobby_chat_message` | `LobbyChatMessage` — one line, the moment it was said. Not a feed: no revision, no tick, and a gap in `seq` is never resynced | the `lobby` channel, minus the sockets of accounts that blocked the author |
| `friends_changed` | `{}` — this account's friend lists moved. Deliberately contentless: the list endpoint is the truth, and one event covers a request arriving and one being answered rather than two shapes to keep agreeing with it. The client still says **which** of those happened, by comparing the lists across the refetch this triggers (R-FRIEND-12) — so naming it costs no wire surface, and the event does not have to grow a second shape | every socket of **both** affected accounts, the one that acted included: its REST answer refreshes only the tab that called, and a second lobby has no other way to hear |
| `email_state_changed` | `{}` — this account's recovery address state moved: an address was offered, one was confirmed, or the weekly reminder was closed. Contentless for the reason `friends_changed` is: `GET /api/auth/email` is the truth, and the address itself is not something to put on a broadcast. The client re-reads it, and re-reads again on reconnecting, which is how a tab hears a change it was offline for | every socket of the account. The confirmation link is presented without a session, usually in a tab of its own, so this is the only way the tabs that were already showing the reminder hear that it is done |
| `friend_invite_received` | `{fromUserId, displayName, inviteToken, expiresIn}` — **no room code, name, or id** | every socket of the invited account |
| `client_config` | `ClientConfig` — cadences the client runs at, and since version 3 the drawing allowance its frames spend (`drawingFramesPerWindow`, `drawingWindowSeconds`), so a replay can pace itself under it (§7). Version 4 adds `afkInputWindowMs`: how recently the client must have seen a pointer or a key to answer an `afk_check` for the player. Version 5 adds `pollingFlushIntervalMs`, the flush cadence for a session on long-polling (§1). The full shape is under *Key payload shapes* | one socket at handshake; every socket when a cadence or the drawing budget changes |

Plus Socket.IO's own `connect`, `disconnect`, and `connect_error`.

### Ordering a client may rely on

Socket.IO delivers one socket's messages in the order they were emitted, so
what a client can be caught by is the order the server chooses. Three of those
were wrong (#883), and each showed up as the client holding two facts that
were never true together:

- **A seat that is removed leaves the room before the removal is broadcast.**
  An evicted socket used to stay in the room while the game moved on without
  it, so a kicked player was told they were out and then handed the next turn.
- **The roster goes before the turn its leaving caused.** Losing the drawer
  starts the next turn; the `room_state` without that seat is flushed first,
  so no client holds a turn whose player list still contains the player who
  left it. However the seat goes - given up, or evicted by a vote, an
  administrator or a ban - the ordering is the same.
- **A timed hint is checked per seat, not once per checkpoint.** Every emit
  awaits, and a turn that ends in one of those gaps stops the rest; the hint
  names its turn as well, and a client takes a named hint only while it is
  drawing that very turn: an abandoned turn goes straight to the next
  `turn_starting` or to `game_ended`, never through `turn_ended`, so "has this
  turn ended" is not a question the phase alone answers.

### Key payload shapes

`friends_in_room` answers `{playerIds}` — the **seats** in this socket's room
that belong to accepted friends of the caller, so the roster can mark them
(R-FRIEND-13). It is `add_friend` in reverse: that one takes a seat and finds
the account, this takes the account and finds the seats, and neither puts an
account id on the wire (R-ROOM-07). Asked for rather than broadcast, because
every reader's answer is different — which is also why it is not room state.
R-BLOCK-03 forbids a **block** creating a different game per player; this
changes no gameplay fact, exactly as the viewer's own avatar ring does not. A
caller with no account, or one in a room with no friends in it, gets an empty
list rather than a refusal, so the two cannot be told apart (R-FRIEND-04).

`friends_online` answers `{friends: [[userId, status], …]}` — this account's
accepted friends who are online, and `lobby` or `playing` for each (#873,
#878). Uncapped, and apart from the lobby's list for two reasons. The public
list is cut at a hundred and ordered by name for everyone, so a friend past the
cut was neither shown online nor invitable; and a waiting room had to join the
whole `lobby` channel — every row and every chat line — to read the few rows
its invite list needed. **Polled, not pushed**: a client asks on showing a
friends surface, on reconnecting, when its friend lists change, and every 15 s
while the tab is visible, and replaces its map with each answer. A push stream
was built first and dropped — merging pushes with answers needed ordering rules
to buy freshness that nothing here needs, since `invite_friend` is checked when
it is sent. After a connection's first ask the friend set is answered from
memory. A friend list that cannot be read is refused with `database_busy`
rather than answered empty, so the client keeps what it had. The status
is exactly what `LobbyPlayer.status` tells any stranger, and never the room
(R-ROOM-07). A guest, or an account with no friends online, gets an empty list;
the client does not ask for an account with no friends at all.

**Friend payloads** never carry a room. `friend_invite_received` holds a token
the server resolves against the sender's live seat, so an invitation is a
capability to *ask* rather than to enter: it cannot be forwarded to somebody it
was not addressed to, it stops working when the sender leaves their seat, and
it never puts a room code in the hands of somebody unseated (R-ROOM-02,
R-FRIEND-06). `add_friend` names a **seat**, not an account, so no account id
crosses the wire inside a room (R-ROOM-07).

**`LobbyPlayer`** — one row of the lobby's online list. The `watch_lobby`
**acknowledgement** carries every one of the channel's baselines at once:

```jsonc
{ "ok": true,
  "revision": 41, "players": [LobbyPlayer], "onlineCount": 412,
  "roomsRevision": 17, "rooms": [RoomSummary],
  "chatSeq": 1207, "chatEpoch": "3f9c…", "chat": [LobbyChatMessage] }
```

Baselines, not events, so there is no window in which a socket is in the
channel receiving deltas against a list it does not have yet — and one
acknowledgement rather than three, so that guarantee holds for every feed. The
revisions are separate on purpose: a room filling up must not look like
presence news, and somebody signing in must not re-send the rooms.

```jsonc
{ "userId": "…", "displayName": "Ada", "nameColor": "#4f9",
  "avatarUrl": "…" | null, "isAnonymous": false, "status": "lobby" | "playing" }
```

This and the friend payloads above are the ones that carry an account id,
and deliberately so: a friend request (#529) needs a stable target, and unlike a room payload
(R-ROOM-07) there is no seat to resolve for somebody idling in the lobby. What
it must never carry is the *room*: no id, no code, no name, and no state richer
than in-the-lobby or in-a-game. `Room.to_public_roster` refuses to make the
lobby a directory of who is playing where, and naming the room would
additionally disclose that a private one exists.
`test_presence_payloads_never_carry_a_room_identifier` pins it.

`revision` and `roomsRevision` are **sequence numbers, not contract
versions**. Each counts broadcasts on its own feed so a client can tell that it
missed one; a client that receives a delta which does not follow the revision
it holds discards that list and re-runs `watch_lobby` rather than patching
around the gap. Protocol compatibility is `PROTOCOL_VERSION` (§1) and nothing
else.

A **reconnect** ends both sequences, since the revisions were the old socket's.
The client empties its presence list and marks its room list *stale* — still
drawn, because those rooms are public and were true a moment ago, but patched
by nothing until a fresh acknowledgement replaces it. The rooms in
`lobby_rooms_changed` are the same `RoomSummary` shape `GET /api/rooms`
returns, from the same serializer. The chat is left exactly as it is: those
lines were said, and the next acknowledgement adds to them when it comes from
the same process, or replaces them when it does not.

**`LobbyChatMessage`** — one line of the lobby's chat, delivered by
`lobby_chat_message` the moment it is accepted and handed to an arrival in
the acknowledgement's `chat`, oldest first, at most the fifty the server
holds (re-read from the retained rows after a restart):

```jsonc
{ "seq": 1208, "userId": "…", "displayName": "Ada", "nameColor": "#4f9",
  "isAnonymous": false, "text": "anyone up for a round?",
  "sentAt": 1788361445,
  "retainedMessageId": "0192…" }   // present only when retention took the row
```

Chat rides the channel but is **not a third feed** of it. Presence and the
room list are state, rebuilt on the tick and numbered so a client can resync
across a gap; a line is an event with nothing to rebuild it from, and a gap
in `seq` is *expected* — a line is deliberately not delivered to somebody
who blocked its author. So `seq` is a per-process counter the client uses
for one thing: putting the backlog and the lines that beat the
acknowledgement into one order without a duplicate (a line numbered at or
below what it holds is one it has). `chatSeq` is the number of the last line
said, shown to this watcher or not, so the next line is never taken for an
old one. `chatEpoch` names the process that numbered them. A client holding
lines from this epoch, filtered for the same account, sends `chatSince` (the
last number it holds) and `chatEpoch` with `watch_lobby`, and is sent only
the lines after it (#885) — on a resync, on a reconnect to the same process,
and on the re-handshake of a visitor who has just been named, where the
backlog was most of what was resent. The answer is *merged* into what it
holds, so a lobby left open all evening keeps what it watched go by. From any
other epoch, or for another account (whose blocks differ), the whole backlog
is sent and *replaces* what the client holds, since the numbers mean nothing
here. It carries an account id for the reason `LobbyPlayer` does
— there is no seat to resolve, and a report needs a stable target — and never
a room. `sentAt` is the server's instant in whole seconds since the epoch, the same
one written to the retained row, and the client renders it as an age or a
clock rather than sorting by it. Seconds because the clock shows minutes: the
ISO string with microseconds it replaced was about a sixth of a line's weight
(#885).
`retainedMessageId` follows R-MOD-08a: issued before the row is written, absent
when retention withheld it, and absent means the line cannot be cited. Room chat
lines are retained under the same rule but never carry the id (#869).


**`room_state`** ([`backend/app/rooms.py:706`](../backend/app/rooms.py) →
`RoomStatePayload` in [`frontend/src/types.ts`](../frontend/src/types.ts)) carries the
room identity (`id`, `code`, `name`, `isPublic`), every setting listed
in §4, `state` (`waiting | playing`), `customPromptCount` (a count, never the prompts),
`promptLanguage`, `moderation` (`{eligibleVoterIds, requiredVotes}`), `restartVote`,
`restartVoteCooldownUntil` (epoch ms), and `players[]`:

```ts
{ playerId, nickname, nameColor?, isAnonymous?, score,
  connected, isHost, isSpectator, isAfk, kickVotes?[], afkVotes?[] }
```

**The finished game's recap is not in `room_state` (#871).** Scores, highlights and every
drawing's metadata with its reactions are immutable once a game ends, and a 16-seat recap
pushed each waiting-room snapshot past the 32 KB deflate window, so a broadcast that should
be a back-reference cost kilobytes per seat — the case N-14 names for reopening. The
snapshot stays whole; it stops carrying the recap. It travels in `game_ended`, and to a
socket arriving in the waiting room afterwards as **`last_game`** (the same shape, sent to
that socket on any join or rejoin, [`GameFlow.send_last_game`](../backend/app/services/game_flow.py));
a recap reaction's refreshed card rides `drawing_reaction.highlight`. Measured with
[`benchmarks/room_payloads.py`](../benchmarks/room_payloads.py), per seat on the wire:

| finished game | `room_state` raw | each waiting-room broadcast | each recap reaction |
| --- | ---: | ---: | ---: |
| 8 × 3 | 17.7 → 2.5 KB | 207 → 40 B | 269 B (2 messages) → 51 B (1) |
| 16 × 3 | 46.8 → 4.5 KB | 1,971 → 56 B | 2,050 B → 56 B |
| 16 × 10 | 138 → 4.5 KB | 4,268 → 56 B | 4,365 B → 57 B |

The two vote lists are **present only where somebody has voted**; absent means no
votes. Every seat receives every other seat's entry on every broadcast, so two empty
arrays per player is the payload paying an O(N²) price for the state almost every
player is in almost always.

**Room payloads deliberately carry no account IDs.** Reports, blocks, and profile links
all resolve seats server-side.

**`turn_started`** is emitted per socket because `maskedPrompt`, `hintCost`,
`letterPrices`, and `hintSpend` are private to that viewer. A spectator sees the masked
prompt unless the room enabled `spectatorsSeePrompt`; the drawer sees the answer.

At *turn start* those four are in fact identical for every guesser — nothing has been
bought yet — so only the drawer and any prompt-seeing spectators genuinely diverge, and
collapsing the loop into one broadcast plus a small private follow-up looks free.
[`benchmarks/turn_start.py`](../benchmarks/turn_start.py) measures what that would buy:
**zero bytes** (see §1 — a broadcast is compressed per connection either way) and
55–271 µs of server work, once per turn, which is three ten-thousandths of one percent
of a core. The loop stays. It has one payload shape rather than two, no second event
whose loss would leave a drawer looking at a masked prompt, and mid-turn
(`hint_revealed`, `sync_game`) the divergence is real anyway.

**`chat_message`** (`ChatMessage`) has `id`, `nickname`, `correct`, and the optional
`text`, `playerId`, `nameColor`, `isAnonymous`, `system`, `close`
(a near-miss hint), `restricted` (delivered only to the drawer, spectators, and correct
guessers), and `isSpectator`. It carries **no retained-message id**, though the line is
retained: nothing in a room cites a line (`report_player` selects its own evidence), and
the UUIDv7's random half, which deflate cannot remove, was 39% of a viewer's whole
stream on the wire (#869). A lobby line keeps its id because a lobby report cites it.

**A room-authored announcement carries no text.** Said to the whole room as part of an
action that changes it — a rename, a vote, a restart — it rides that action's
`room_state` in `causes`; said to one socket, or outside an action, it is a
`chat_message`. Either way it is `{system: true, code, params?}`
- built by `system_chat_message()`
([`backend/app/presenters.py`](../backend/app/presenters.py)) from the `Announcement`
vocabulary in [`app/announcements.py`](../backend/app/announcements.py), mirrored by
`AnnouncementCode` in
[`lib/announcements.ts`](../frontend/src/lib/announcements.ts) with
`tests/test_wire_contract.py` failing on drift. It is authorless by construction, so no
caller can attribute one to a player, and **wordless** by construction, so no caller can
write it in one language for a room that does not share one: one payload reaches every
seat and each client renders the sentence for its own reader (R-I18N-03). `params`
carry values, never fragments - `restart_cancelled` sends
`reason: "server_update"`, not the clause English puts after *because*, which most
languages do not build the same way. `text` remains for a line a **player** typed,
which is never translated: what somebody said is what everybody sees.

**Blocking is a presentation filter only.** When a sender is blocked, the recipient
list is narrowed for that one `chat_message`
([`backend/app/handlers/chat.py:27`](../backend/app/handlers/chat.py)); the sender still
sees their own line, and room state, players, scores, turns, correct-guess events,
votes, and announcements keep normal room-wide delivery. Blocking never creates a
different game state per player.

**`DrawingReaction`** — delivered by `drawing_reaction` the moment `react_to_drawing`
is accepted, to everyone in the room including the drawer:

```jsonc
{ "turnId": "0192…", "playerId": "seat-token", "nickname": "Ada", "nameColor": "#4f9",
  "isAnonymous": false, "emoji": "fire",          // null when taken back
  "tally": { "heart": 2, "fire": 1 } }            // the whole drawing, after this change
```

The reactor is a seat token with its presentation, like every other room payload;
the tally is the full count rather than a delta so a client that missed an earlier
event still converges. State payloads carry the **list** rather than the tally —
`reactions: [{playerId, emoji}]` on `turn_started`, `sync_game`, `turn_ended`, and on
every recap entry in `game_ended.drawings` and `last_game.drawings` — because a
reconnecting client has to find its own pick in it, and a list of seats is how the room
names anybody. The client reduces the list to a tally itself
([`lib/reactions.ts`](../frontend/src/lib/reactions.ts)). `emoji` is a stable code, never a
glyph; the glyph table is the client's, so a code the server adds later still arrives.

**`turn_ended`** carries `prompt`, `turnId`, `reactions[]`, `drawerId`, `drawerBonus`, `seconds`, the ordered
`guesses[]` (each with the guesser's `seconds`), and `scores[]` — each entry carrying
`score`, `delta`, `previousRank`, and `newRank` so the client can animate the standings
without recomputing ranks. Ranks use standard competition ranking (1, 2, 2, 4) via
`competition_ranks()` ([`backend/app/game.py:53`](../backend/app/game.py)), shared with
the recorded standings so the final screen and the history row can never disagree.

**`server_shutdown`**:

```ts
{ contractVersion: 1, reason: "deployment", drainSeconds: number, startedAt: string,
  reconnectSpreadMs: number }
```

`reconnectSpreadMs` (#872) is how widely clients should spread their return
once this process is gone: each holds its first attempt a uniform random part
of it (`SHUTDOWN_RECONNECT_SPREAD_SECONDS`, default 10 s, at most 120 s). See
[Reconnection](#reconnection).

`drainSeconds` is **exactly** what the server will wait, fractions included — it
used to be rounded up, which promised a client two seconds while the server
stopped waiting after 1.25 and left a countdown running past the socket closing.
Presenting it as whole seconds is the client's job
([`shutdownNotice.ts`](../frontend/src/lib/shutdownNotice.ts)), and it rounds up
as a countdown does — so a 1.25-second window reads 2, then 1, then 0. The
guarantee is not that the number never exceeds the time left, which rounding up
plainly breaks; it is that the countdown **reaches zero when the window closes
and not after**, so the banner never claims time the socket has already lost,
and that a skewed clock cannot show more than the announced window. The window is
fixed when the drain starts, so a change to the configured default cannot move it.

**`server_paused`**:

```ts
{ contractVersion: 1, paused: boolean, reason: "maintenance" }
```

**`client_config`** ([`backend/app/client_config.py`](../backend/app/client_config.py) →
[`frontend/src/lib/clientConfig.ts`](../frontend/src/lib/clientConfig.ts)):

```ts
{
  contractVersion: 5,
  flushIntervalMs: number,
  pollingFlushIntervalMs: number,
  drawingFramesPerWindow: number,
  drawingWindowSeconds: number,
  afkInputWindowMs: number,
}
```

Cadences the *client* runs at, decided by the server so a deployment can tune them
without shipping a bundle (R-CONF-01). `flushIntervalMs` is the motivating case:
it is the largest single lever on drawing bandwidth, and the drawer never feels it —
their own canvas is rasterized on every `pointermove`. A viewer used to draw each batch
as one polyline the moment it landed, so a value the byte curve liked arrived visibly
faceted and the default stayed at 40 ms; since #559 a viewer plays each batch out over
the interval that follows it (§6, *Playback on the viewer*), and the default is
**80 ms**: half the point messages, a viewer up to 80 ms behind the drawer's hand
instead of 40. It still ships rather than compiles, so it can be moved while somebody
watches.

The version is checked **as a whole** before any field is read, the way the shutdown
and pause notices are: a later server could give a field a different meaning rather
than a different name, and a client that took the fields it recognised would apply half
a contract it does not understand. An unknown version leaves every compiled default in
place, which is the same direction each field-level fallback takes.

Version 2 dropped `lobbyPollIntervalMs` — the lobby is told about rooms over its
channel now (#462) and has no cadence of its own to be given. Version 3 added the
drawing allowance a `draw` frame spends (#597), so a client replaying a stroke after a
stall can pace itself under it instead of bursting into a refusal that drops the frame
nobody is waiting on. Version 4 added `afkInputWindowMs` (#677), how recently this
client must have seen a pointer or a key to answer an AFK check on the player's behalf.
Version 5 added `pollingFlushIntervalMs` (#887), the flush cadence for a session on
long-polling, where every flush is an HTTP POST carrying more header than frame (§1).

The client keeps its compiled defaults for any field that is missing or outside
what it can run, because a server that cannot say is not a reason to stop drawing.
The values are latched where the socket lives and handed to subscribers on
subscription ([`onClientConfig`](../frontend/src/lib/clientConfig.ts)), since the
notice arrives at the handshake — usually long before anything that depends on it
has mounted. A change re-arms the affected timers rather than waiting for the next
turn: the flush interval is a dependency of the effect that owns the drawer's
`setInterval`, so it is torn down and re-armed mid-stroke.

---

## 6. The live drawing protocol

Source: [`backend/app/live_drawing.py`](../backend/app/live_drawing.py).
Golden fixtures: [`fixtures/canvas_protocol_v1.json`](../fixtures/canvas_protocol_v1.json),
exercised from both sides by
[`backend/tests/test_live_drawing.py`](../backend/tests/test_live_drawing.py) and
[`frontend/tests/canvasProtocolFixtures.test.mjs`](../frontend/tests/canvasProtocolFixtures.test.mjs).

All live drawing rides on **one** Socket.IO event, `draw`. This is a *hybrid* protocol,
and the shape a frame travels in is chosen by size rather than fixed:

- **Control actions** (path end, clear) send their single header byte as a bare
  **integer** — already the cheapest thing Socket.IO can carry.
- **Small data-bearing frames** (≤ `MAX_BASE64_FRAME_BYTES`, 85 B) travel as **base64
  inside an ordinary text event**.
- **Larger frames** travel as **binary attachments**.

> **Why base64 is cheaper for small frames.** Socket.IO cannot put binary inside an event
> without its placeholder envelope: `51-["draw",{"_placeholder":true,"num":0}]` is 41 bytes
> whose only job is to announce that a blob follows, and the blob is then a *second*
> WebSocket frame with its own header. On a 13-byte frame that is 76% overhead. Base64
> expands the payload by a third and deletes both, which wins until the expansion
> overtakes the envelope it saved — measured at about 85 bytes. A 5-point frame goes from
> 59 B to 33 B on the wire.
>
> Only the **sender** consults the threshold. The server accepts either shape and
> rebroadcasts whatever it was handed, so the value can move without a protocol change.
> `sync_strokes` is untouched and stays binary: histories run to kilobytes, far past the
> crossover.

### Header byte

```
bit  7 6 5 4 | 3 2 1 0
     version | tag
```

`LIVE_DRAWING_VERSION = 1`, so every current frame starts with `0x1_`.

| Tag | Value | Event | Frame |
| --- | --- | --- | --- |
| `PATH_START` | 0 | `draw_start` | binary, 9 bytes |
| `PATH_POINTS` | 1 | `draw_move` | binary, 1 + 4·n bytes |
| `PATH_END` | 2 | `draw_end` | integer `0x12` |
| `SHAPE` | 3 | `draw_shape` | binary, 14 bytes |
| `FILL` | 4 | `draw_fill` | binary, 8 bytes |
| `CLEAR` | 5 | `clear_canvas` | integer `0x15` |
| `PATH_POINTS_DELTA` | 6 | `draw_move` | binary, 5 + 2·(n−1) bytes without escapes |
| `PATH_POINTS_RELATIVE` | 7 | `draw_move` | binary, 1 + 2·n bytes without escapes (#559) |
| `PATH_POINTS_END` | 8 | `draw_move` that also ends the path | binary, the relative layout; carries the commit (#603) |

### Frame layouts

All multi-byte integers are **little-endian** except colors, which are big-endian RGB.

| Frame | `struct` | Fields |
| --- | --- | --- |
| `draw_start` | `<B3sBhh` | header, color (3 B, RGB), width (1 B), x, y (int16) |
| `draw_move` | `B` + `<hh` × n | header, then n points; 1 ≤ n ≤ 256 (`MAX_POINTS_PER_FRAME`) |
| `draw_move` (delta, tag 6) | `B` + `<hh` + records | header, the first point absolute, then one record per further point: `<bb` (a signed-byte offset from the previous point, each −126 … 127) or the escape byte `0x80` followed by `<hh` absolute. Any record may be preceded by a **width change**, `0x81` + width (see below) |
| `draw_move` (relative, tag 7) | `B` + records | header, then one record per point in the same two shapes — the first relative to the **open path's last point**, which the frame does not carry (#559). Decodes to offsets; the receiver resolves them against the path it holds: the server against `canvas_session`, a viewer against its own history. A relative frame with no open path is dropped, as an absolute `draw_move` with no open path is. The encoder takes it whenever the first step fits a byte, since it is then the smallest of the three: a one-point frame is 3 bytes instead of 5 |
| `draw_move` (final batch, tag 8) | `B` + records | The relative layout, and the frame **also closes the path** (#603): the points the drawer had buffered when the pen lifted and its `draw_end` used to be two events sent in the same call, only the second carrying the commit. One frame extends the path and ends it atomically — refused whole if the points do not fit the budget, so a refused ending never leaves a committed prefix — and carries the commit the way `draw_end` does. Always relative (an ending has an open path), escaping where a step is too far. The one-byte `draw_end` stays for a path with nothing buffered, and for a final batch that was refused: the stroke then ends where the budget ran out. Both forms produce byte-identical history and hash |
| `draw_end` | `B` | header only |
| `draw_shape` | `<BB3sBhhhh` | header, shape id (1 B), color, width, x₀, y₀, x₁, y₁ |
| `draw_fill` | `<B3sHH` | header, color, x, y as **absolute uint16 pixels** |
| `clear_canvas` | `B` | header only |

Shape IDs: `rectangle = 0`, `ellipse = 1`, `triangle = 2` (`SHAPE_IDS`,
[`backend/app/canvas_history.py:48`](../backend/app/canvas_history.py)).

x₀, y₀ is where the drag started and x₁, y₁ where it ended, and the order is kept
end to end. A rectangle or ellipse fills the box between them either way; a triangle
does not — the two points are one of its base corners and its apex, and its third
corner is the start mirrored through the apex's column, so swapping them gives a
different triangle (#787). Every client derives that third corner from the two, so it
is never sent; it can fall outside the canvas, where the rasterizer clips it.

### A width keyframe inside a path

A path's width can change along it (#828, R-DRAW-16): a pen's pressure. In a record
stream — tags 6, 7 and 8 — the byte `0x81` where a record would start is not an offset
but a **width keyframe**: **one more byte follows, the width (1 – 64), and then the
record of the point the path has that width at**.

```
17 0018 81 05 100c 100c      relative: a point, then "5 px wide at the next point"
```

**Between two keyframes the width is a straight line from the one to the other along
the length of the path**; the path's start is a keyframe at the width in its
`draw_start`, and after the last keyframe the width holds. No painter paints anything
else, and none is sent how: each derives the ramp from the points and keyframes it
holds ([`lib/pathWidths.ts`](../frontend/src/lib/pathWidths.ts)) — the stretch cut into
pieces a pixel of width apart, equal shares of its length, the cuts snapped to the
quarter-pixel grid the coordinates sit on — so the drawer, a viewer and a replay still
rasterize one picture and a fill sees the same edges everywhere. Every *piece* has one
constant radius, which is what keeps a segment painted in parts exact (below): a ramp is
only more capsules. A keyframe at the width the path already has is legal and means
something: it is where a later ramp starts.

> **Why keyframes, and not the width itself.** The first version sent the width as one
> of six levels per brush, when the level changed, and painted it as sent: a line that
> held 11 px and then held 18 px, with a shoulder between, however the levels were
> chosen. A hand's pressure is a smooth curve, and a smooth curve is a few points with
> straight lines between them: a sample becomes a keyframe only when a straight ramp
> past it would miss some sample's width by more than 15% of it (a pixel at least, and
> widening to 25% on a line 16 px and fatter, where a wobble is more pixels and the error
> hardest to see, and exact where the width is the brush's own or its floor), the same
> whole-stroke bound the point thinner holds for position
> ([`lib/widthKeyframes.ts`](../frontend/src/lib/widthKeyframes.ts)). A swell from 2 px
> to 32 that was five visible steps is one ramp and usually two keyframes.
>
> **Why in-band.** A message is what live drawing costs, not a byte (§1). A frame of
> its own per keyframe would be a second Socket.IO event — an envelope, a WebSocket
> header and a unit of the drawing budget — to carry one byte, and it would split the
> batch it fell inside; a width byte on every point would tax the strokes that never
> change width, which is every stroke from a mouse. In-band, a keyframe is two bytes in a
> frame that was being sent anyway and a path with none is byte for byte what it was.
> Measured over the recorded traces with a pressure curve laid on them
> (`benchmarks/path_widths.py`, deflated and framed, against the same strokes at one
> width): **+1 – 4% on a 6 px brush, +5 – 7% on a 12, +8 – 10% on a 32, and no message
> added**; a byte per point is +2 – 20% (on the short hand trace the two are level, and
> a mouse still pays nothing), a frame per keyframe +35 – 96% with about twice the
> messages, and the six stepped levels were +6 – 15%. Two things got the largest
> brush there from +13 – 19%, where its keyframes were being spent on a sensor's jitter:
> the pressure is smoothed before it is mapped
> ([`lib/penPressure.ts`](../frontend/src/lib/penPressure.ts)), and the tolerance widens
> with the line — everywhere but at the ends of the brush's range, where it is exact,
> because full pressure is promised to draw the selected size (R-DRAW-17) and a quarter
> of 32 px would have let a stroke held there be drawn at 26; it tightens toward the ends
> gradually, since a drop from 8 px to half of one between two samples is itself a
> shoulder. A frame that goes out while the width has drifted less than *half* the
> tolerance from the last keyframe says nothing about it; a whole tolerance of drift,
> painted flat and then made up, showed as a kink at the frame boundary. Together they
> took a pen from half again as fast through the turn's drawing limit (R-DRAW-07 charges
> a keyframe as a point) to a quarter.

**What a viewer may assume, and what the drawer's client therefore promises.** A viewer
paints a frame when it arrives, before the next keyframe exists, so it paints whatever
follows a frame's last keyframe at that keyframe's width. A later keyframe of another
width would ramp back across ink already painted flat, so the client never sends one
unless the keyframe it ramps from is **in the same frame or on the last point of the
frame before** ([`lib/penStroke.ts`](../frontend/src/lib/penStroke.ts)): a frame that
goes out part way through a change carries a keyframe on its last point saying how far
the width got, and a change that begins after frames with nothing to say gets a **hold**
— a keyframe at the old width — on the first point of its own frame. The server does
not check this; a client that broke it would show its viewers a line that a resync
redraws, and nothing else. It is what lets a live batch be ramped from the point it
joins and come out as the whole path will
(`frontend/tests/pathWidths.test.mjs` holds the drawer's ink, a viewer's frames and the
whole path to one raster).

The price is one value of the delta range: `0x81` was an offset of −127 quarter-pixels
and is now the marker, so that step escapes. The width is absolute, not a step from the
last, so a frame still validates on its own the way its points do. Decoded, the
keyframes are `widths: [[index, width], …]` beside `points`, ascending by index into that
batch.

The encoder never sends a frame with a keyframe as the absolute form, which has no
records: it is relative when the open path's last point is known — escaping if the first
step is too far, as a final batch does — and otherwise the delta form, whose first point
is not a record, so a keyframe there is refused. A keyframe with no point after it in the
same frame, two on one point, or a width outside 1 – 64 refuses the frame.

### Coordinates

Path and shape coordinates are **normalized** (0.0 – 1.0 across the canvas, and
allowed to overshoot) and packed to signed 16-bit **quarter-pixels**:

```
packed = round(normalized × canvasSize × COORDINATE_SCALE)
```

with `CANVAS_WIDTH = 800`, `CANVAS_HEIGHT = 600`, `COORDINATE_SCALE = 4`, and the
packed value bounded to `[-32767, 32767]`. That gives quarter-pixel precision and
about ±10 canvases of overshoot headroom before a coordinate is refused. int16's floor,
−32768, is not a coordinate: as a path entry's x it is the history's width marker (§8),
so every decoder refuses it in any frame rather than let a point be recorded as one.

Fill coordinates are different on purpose: they are sent as **absolute pixel indices**
(`uint16`), because a fill's seed point must land on an exact pixel. The encoder
requires `0 ≤ x < 1` and `0 ≤ y < 1` normalized and clamps to
`CANVAS_WIDTH − 1` / `CANVAS_HEIGHT − 1`.

**The decoder returns the centre of that pixel, not its corner** — `(x + 0.5) / CANVAS_WIDTH`.
The seed crosses the wire as an integer and is re-quantized twice more (by
`CanvasSession.record_stroke` and again by the client's renderer), and `x / CANVAS_WIDTH`
does not survive that round trip: `(x / w) * w` can fall just below `x` in binary floating
point, and truncation then takes it down a pixel. **37 of the 800 columns and 26 of the 600
rows were affected**, in both runtimes identically. Half a pixel of offset puts every value
clear of the boundary. For a flood fill this is not a rounding nicety — one pixel can be
the far side of an outline, so the wrong region is painted entirely.

Colors are `#rrggbb` strings on the payload side and three raw bytes on the wire.
`width` is 1 – `MAX_BRUSH_WIDTH` (64).

### Worked examples (from the fixture)

| Event | Payload | Wire (hex) |
| --- | --- | --- |
| `draw_start` | `{x: 0.25, y: 0.75, color: "#aabbcc", width: 4}` | `10 aabbcc 04 2003 0807` |
| `draw_move` | `{points: [{0.1,0.2}, {1.2,-0.1}]}` | `11 4001 e001 000f 10ff` |
| `draw_move` | three points from (0.5, 0.5), a keyframe `widths: [[1, 5]]` | `17 0018 81 05 100c 100c` |
| `draw_end` | — | `12` |
| `draw_shape` | ellipse `#123456`, width 64, (0.1,0.2)→(0.8,0.9) | `13 01 123456 40 4001 e001 000a 7008` |
| `draw_fill` | `{x: 0.25, y: 0.75, color: "#fedcba"}` | `14 fedcba c800 c201` |
| `clear_canvas` | — | `15` |

### Thinning at the source

The client does not send every pointer sample (#560). A pointer reports up to 120 a
second, and at a quarter-pixel quantization most of a hand stroke is exact duplicates
and runs along one straight segment. [`frontend/src/lib/pointThinning.ts`](../frontend/src/lib/pointThinning.ts)
keeps only the samples that move the drawn line by more than **0.25 canvas pixels**
(`THINNING_TOLERANCE_PX`, one quantization step), with a bound that holds for the whole
stroke: a sample is dropped only if it — and every sample dropped before it since the
last kept one — lies within the tolerance of the segment that will replace them, so
dropping cannot accumulate error. The first and last sample, corners, reversals and dots
are kept because they fail that test. The sample still pending when the flush timer fires
is sent with that flush, so a viewer watches a straight stroke advance every flush rather
than only when it bends or ends.

A pen's width keyframe (#828, above) says how wide the path is *at a point*, so the point
has to be one the path keeps: when a sample becomes a keyframe the thinner gives up its
pending sample, which is that one, and the keyframe is sent in front of it. Samples from
a mouse have no keyframes and thin exactly as before.

The kept samples are the stroke, on both sides: the drawer's own canvas is painted from
them, not from the raw pointer (the raw segment under the pen is shown on the preview
layer until it is kept or dropped), so the drawer, every viewer and every replay
rasterize the same polyline. The frames carry fewer points; no stored format moves.

### Playback on the viewer, and what a dropped frame does

A viewer does not paint a batch the moment it lands (#559). Each `draw_move` is
scheduled to be painted over the flush interval that follows its arrival — the time
the next batch takes to come — and every animation frame paints the part that has come
due, down to a fraction of a segment ([`frontend/src/lib/strokePlayback.ts`](../frontend/src/lib/strokePlayback.ts)).
Painting a segment in parts is exact: each part is painted as a *span* of its original
segment, a pixel belonging to the span its nearest point on the whole segment falls in
and decided exactly as the whole segment decides it, so the spans paint the whole
segment's pixels and no others. (Splitting at an interpolated point and painting each
half as its own capsule was exact only in exact arithmetic: a split point a float's
width off a diagonal moved an edge pixel in about one segment in five hundred, #940.)
The history and the commit on the frame are still applied synchronously, before
anything is queued; only presentation is delayed. Everything that is not a run of points
— a path start or end, a shape, a fill, a clear — is a barrier in the same queue, so a
fill always sees the complete raster before it. Past `MAX_LAG_MS` (250) of unplayed
ink the schedule is compressed so the viewer catches up; a hidden tab drains at once;
a replay or a clear discards the queue, since what follows repaints from history.

This is what let the default flush interval move from 40 ms to **80 ms**
(`client_config`, §5): a batch every 80 ms painted all at once read as steps, painted
over the next 80 ms it reads as a line. A viewer sees ink up to one interval behind
the drawer's hand, and the drawer sends half the point messages.

A `draw` frame the door drops (throttled, §2) is dropped in silence — nobody awaits a
`draw` — and the drawer painted it. Since a later relative frame would be resolved
against a point the server never recorded, the handler acts on the *next* frame from
that socket: the open path is closed where the server's copy ends (the room is sent a
`draw_end` carrying the commit), the drawer is sent `canvas_stale … dropped_frame`, and
the rest of that path is discarded as it trickles in; a frame that opens a new action
is taken as usual.

Measured on the recorded traces (`benchmarks/point_thinning.py`; the traces were
recorded before thinning, so they are the raw input): on a long hand drawing 57% of the
points and 75% of the deflated bytes remain, on a slow short one 33% and 65%, on a
scripted 120 Hz pen 82% and 89%; the maximum error measured equals the tolerance, no
pixel of a stroke edge moves by more than it, and the number of blank regions a fill
could be aimed at was unchanged on every trace. Holding the pending sample past the
flush would save about ten points in a hundred more; it was not taken, because a
ruler-straight line would then appear on viewers' screens all at once.

### Server-side refusals

`decode_live_drawing` ([`backend/app/live_drawing.py:469`](../backend/app/live_drawing.py))
rejects, before anything is recorded or rebroadcast:

- A non-integer, non-bytes payload, or an empty frame.
- An integer control outside 0 – 255, or an integer carrying a **data-bearing** tag —
  "data-bearing drawing actions must be binary".
- A version other than 1.
- Any frame whose length does not exactly match its tag's layout.
- A brush width outside 1 – 64, an unknown shape id, a fill point outside the canvas.
- A width keyframe that is misplaced (above), and any coordinate packed to −32768.

On top of the codec, [`drawing.py`](../backend/app/handlers/drawing.py) refuses:

- A sender who is not the current drawer, or a phase other than `drawing`.
- A tool or color the room's **drawing rules** disallow
  (`packet_allowed`, [`backend/app/drawing_rules.py`](../backend/app/drawing_rules.py)).
  Nothing is recorded and nothing is rebroadcast — but the sender already drew it
  locally, so the server replies with a canvas sync onto server truth. Only the frame
  that *opens* an action is answered; points and the end frame trailing a refused path
  are dropped in silence, so one refusal costs one sync however many frames follow.

### Drawing rules

Two room settings, deliberately shaped differently
([`backend/app/drawing_rules.py`](../backend/app/drawing_rules.py)):

- **Allowed tools** are independent flags (`brush`, `fill`, `shapes`), so they are a
  set. At least one of `brush`/`shapes` must stay on, since fill alone can only flood a
  blank canvas.
- **Color mode** picks one of four mutually exclusive alternatives: `all`, `palette`
  (13 light/dark pairs, mirroring `COLOR_PAIRS` in `Toolbar.tsx`), `colorblind_safe`
  (Okabe-Ito plus white), `black_and_white`.

**Erasing is a white brush stroke on the wire.** It is indistinguishable from drawing
in white, so the server can ban the brush and the eraser together or admit both, but
never one alone — which is also why **every color mode permits white**, and why the
mode is called *black and white* rather than *black only*.

---

## 7. The canvas sequencing protocol

Source: [`backend/app/canvas_session.py`](../backend/app/canvas_session.py) (server) and
[`frontend/src/hooks/useCanvasProtocol.ts`](../frontend/src/hooks/useCanvasProtocol.ts)
(client).

The drawer's canvas is optimistic: strokes appear locally before the server confirms
them. Four numbers keep the two canvases reconcilable.

| Name | Meaning |
| --- | --- |
| **generation** | Which turn's canvas this is. Allocated by `Room.allocate_canvas_generation()` at each turn start. A frame naming a stale generation is discarded and answered with a sync. |
| **sequence** | A monotonically increasing per-turn number identifying one *semantic* mutation (one whole path, one shape, one fill, one clear, one undo). Strictly `previous + 1`. |
| **revision** | How many actions the authoritative history contains. Undo *increments* the revision while shrinking the history. |
| **historyHash** | A CRC32 over the length-delimited canonical records of every action, so both sides can compare whole histories in one integer. |

### The exchange

```
drawer                                     server                       everyone else
  │  draw(frame, [generation, sequence])      │
  │──────────────────────────────────────────▶│  validate rules, generation, sequence
  │                                           │  CanvasSession.record_stroke(...)
  │                                           │  commit_sequence(...) if it closes one
  │                                           │─ draw(frame verbatim, [gen, seq, rev, hash]) ▶
  │◀──── canvas_commit [gen, seq, rev, hash] ─│
```

- Only the frame that **starts** an action carries `[generation, sequence]`. Path
  points and the path-end frame carry none — the parser refuses an identity on those
  and requires one on the others.
- A path is committed on `draw_end`, using the sequence its `draw_start` carried. A
  shape or fill commits immediately. A clear commits immediately.
- The rebroadcast to other clients is the drawer's **exact wire bytes**, never a
  re-encoded frame — plus, on the frame that *commits* an action, the commit itself as
  a trailing `[generation, sequence, revision, historyHash]`. Point frames commit
  nothing and carry nothing.
- **The drawer still receives `canvas_commit` as its own event**, because `skip_sid`
  excludes them from the rebroadcast and their pending-mutation window is what the
  commit resolves. Everyone else reads the commit off the frame that caused it, which
  costs the room one event per action instead of two and makes it impossible to observe
  a commit for a frame that has not arrived.
- `canvas_undo` is unaffected: an undo has no frame of its own to ride on, so it stays a
  room-wide event.
- **A viewer refuses a frame that disagrees with its commit.** A committing frame
  without one, or a commit on a frame that committed nothing, is a protocol break, and
  the viewer takes a resync rather than continuing. `ClientCanvasHistory.apply` returns
  whether a `draw_end` really closed an open path — the same condition the server
  commits on — so the check is exact rather than a guess about server state. Without it
  a viewer that stopped reading commits would drift silently: identical pixels, stale
  sequence, and nothing to notice until something validated against that sequence
  arrived.

### Recovery paths

| Situation | Server response |
| --- | --- |
| `generation` is stale | `canvas_stale … stale_generation` |
| `sequence` ≤ committed | replay the stored `canvas_commit` to that socket if the recorded mutation matches, else `canvas_stale … unknown_sequence` |
| `sequence` > expected (a gap) | `request_canvas_actions [generation, expected, received]` |
| A new action arrives while a path is still open | `request_canvas_actions`, unless it is a `draw_start` repeating the open sequence, which restarts that path |
| A refused tool or color | `canvas_stale … refused_tool` |
| A frame that does not decode | `canvas_stale … invalid_frame` (the acknowledgement body never leaves the server: nobody awaits a `draw`) |
| A final batch (tag 8) past the point budget | dropped whole, nothing committed, the path stays open; the drawer's one-byte `draw_end` that follows closes it, and its completion watch covers the case where nothing does |
| The socket's outbound backlog passed the budget (§3) | the socket is closed, its queue discarded whole; the client reconnects, rebinds its seat inside the grace and asks for a sync — a tail when the prefix it holds verifies, a full one otherwise — so recovery is a verified canvas rather than a partial stream |
| A frame throttled at the door (§2), noticed at the next frame | the open path is closed for the room with a `draw_end` carrying its commit; `canvas_stale … dropped_frame` to the drawer; the rest of that path discarded (§6) |
| `undo_stroke` whose generation, revision or `historyHash` disagree | the acknowledgement alone: `canvas_stale_generation` or `canvas_out_of_sync` — the client resyncs through its transaction |

**Why a notice and not the history (#562).** Every one of these used to push the whole
canvas to that socket, and nothing but the drawing budget bounded it: a hundred refused
openings in a window were a hundred full dumps, each up to 460 KB on a full canvas —
50 per second from one socket, and the client had no say in it. Now the server says
*that* the canvas needs recovering, once per socket per resync window (further refusals
inside the window are counted but not repeated), and the client asks through its
transaction — which is budgeted, carries a verified prefix when it can, and knows when
to ask again. The floor is **one requested** full reply per socket per window, through
its budget. A join used to push a snapshot as well, on its own window: on a fresh join
it left before the acknowledgement — before the canvas had mounted to receive it — so
the mount's own request loaded the drawing a second time, and on a rebind it was a full
dump to a client holding a verified prefix. Neither is sent any more (#877): the canvas
asks when it mounts, and again once a new socket has rebound its seat, claiming what it
holds (below). From up to 100 dumps
per window to 1: a 100× bound on the abusive draw path, and no path around it.
`sketchy_canvas_recovery_notices_total{reason}` (§9) counts every occurrence, not only
the notices sent.


`sync_strokes` is emitted as a **tuple**:
`(binaryHistory, revision, generation, sequence, historyHash, requestId)`.

### The sync transaction

A resync is one transaction at a time on the client
([`frontend/src/lib/canvasSyncRequests.ts`](../frontend/src/lib/canvasSyncRequests.ts)),
scoped to what it was asked for (#598). Before it, a reply was applied whatever it
answered: a tail asked for while nothing was pending could arrive after the drawer had
drawn again, and replacing history then cleared those strokes as if they had never
happened; a full reply to a request abandoned by a reset landed on the new turn; and a
request the server never answered released the latch after ten seconds and retried
only if something else had asked meanwhile — a lost or refused request on a quiet
canvas had no next trigger.

- **Identity.** `request_sync_strokes` carries an id, and the reply echoes it last. A
  reply whose id is not the outstanding request's is **stale** and ignored. The server
  sends no sync it was not asked for (#877), so every reply names a request. A tail must additionally be cut for the prefix the
  request *claimed* — the claim is captured when the request goes out, not when the
  reply arrives — so strokes drawn in between are pending mutations, reconciled like
  after a full reply, not history to be overwritten.
- **One reconciliation.** A full reply and a tail go through the same adoption: replace
  the history, drop pending actions the server has committed and paths still open,
  replay the rest through the paced sender (above) with a deadline each, or fall back to
  server truth if they do not fit.
- **Acknowledged, and retried.** The request is acknowledged: `{ok: true}` when the
  reply is on its way, `not_in_game` with `retryAfterMs` (2 s) between turns, `too_fast`
  with the resync budget's window. A refused request is retried after exactly the
  `retryAfterMs` it was given — that is how long the server's window has left; a lost
  one (no reply inside 10 s) after 2 s, then 4 s, then 8 s. When those are gone the
  client does not poll on: it hands the session to the reconnect hook, which restarts
  the transport — the player sees the existing reconnecting state, the server pushes a
  fresh snapshot on rejoin, and every counter resets. Unanswered syncs usually mean the
  seat binding itself is suspect.
- **Coalesced.** Triggers that arrive while a transaction is outstanding are satisfied by
  its reply when the reply converges; only a reply that failed to converge issues the
  follow-up. A burst of duplicate triggers costs one request and one reply.

### Replaying what the server did not get

Every frame a drawer sends is saved with its pending action until the server confirms
it, and a recovery — a `request_canvas_actions` for a gap, or a `sync_strokes` that
leaves some actions still unconfirmed — resends those actions. Before #597 the client
resent every saved frame in one synchronous loop, and those frames spend the same
drawing budget as live drawing (R-RATE-08), with the refusal silent because nobody
awaits a `draw`: a six-second stroke replayed as 152 frames had exactly 100 accepted,
the end dropped, and the path left open on the server with nothing to ever close it.
A larger allowance is not a fix, since a longer stroke exceeds any live allowance.

Recovery now lives in [`frontend/src/lib/canvasRecovery.ts`](../frontend/src/lib/canvasRecovery.ts),
pure and tested, wired by `useCanvasProtocol`:

- **Repacked.** Both histories store a path as one point list, so the flush batch
  boundaries were never part of the record. A saved relative frame (§6) is resolved
  against the one before it and re-encoded self-contained, and a path that ended on a
  final batch is resent with that batch's points and a plain end, so a replayed path
  decodes on the server without an open path to be relative to. A saved path is resent as its opener, one
  frame per 256 points, and its end — the same points in the same order, so the
  canonical action and the history hash are identical. The reproduced stroke becomes 3
  frames; 750 points become 5.
- **Paced.** Frames leave under the allowance `client_config` advertises, after a burst
  of 8, at `(framesPerWindow × 0.75) / windowSeconds` with the rest of the window's
  share reserved for controls a person may press meanwhile. Repeated requests for one
  sequence are coalesced; a replay is dropped in favour of a full sync past 5,000
  points; a reset, a new authority, a generation mismatch or a lost connection cancels
  it. Sending starts on the next tick so a run of sequences leaves in order.
- **Never into a dead socket.** A `draw` is emitted only while the socket is connected.
  Socket.IO would otherwise buffer it and flush that buffer on reconnect before the seat
  is rebound, into whatever the canvas has become; a frame dropped this way is recovered
  by the sync that follows the rebind.
- **A deadline for a finished action.** A completed path, a shape, a fill, a clear or an
  undo the server has not confirmed is resent after 2 s, again after 4 s, again after
  8 s, then the client requests authoritative state. One resend resolves both a lost end
  frame and a lost commit: the server replays the stored `canvas_commit` for an action
  it has (`sequence` ≤ committed, above) and accepts one it never saw. The heartbeat's
  `[generation, sequence]` fires the resend early when the server already reports the
  action committed. The terminal step is silent by decision: the canvas simply shows
  what the room has.

Ordinary live drawing is unchanged; the client_config bytes grow by two fields.

### Incremental resync

`request_sync_strokes` may carry a claim about the prefix the client already holds:

```jsonc
[generation, actionCount, historyHash]
```

The server checks it in **O(1)** against `CanvasSession.hashes`, the per-action prefix
array it already maintains, and answers a verified claim with `sync_strokes_tail` —
the same `SKCH` frame containing only the actions from `actionCount` on, plus the
`baseActionCount` they splice onto.

**The claim is an optimization, never a trust boundary.** Every one of these falls back
to the full `sync_strokes` dump:

| Situation | Why |
| --- | --- |
| `generation` is not current | The turn's canvas has been replaced |
| the hash disagrees | The client's prefix is not the server's |
| `actionCount` exceeds what is finalized | Includes the client being *ahead*, which undo can cause |
| `actionCount` lands inside an open path | `hashes` holds one entry per finalized action; the record under the pen is a moving target |
| no claim at all (`null`) | A canvas that holds nothing yet (a mount), or pending strokes the server has not confirmed |

**When a client asks (#877).** Once when its canvas mounts - which on a mid-turn entry
is what loads the drawing - and once each time a **new socket** has rebound its seat,
claiming its prefix, so a reconnect is answered with a tail: 90 B instead of 1 KB for a
20-stroke drawing, and up to hundreds of kilobytes for a full canvas
(`benchmarks/join_to_drawing.py`). A soft rebind (a heartbeat, a tab returning) keeps
its socket and asks for nothing. The server used to push a full history on every join
and rebind as well; a mid-turn entry received the canvas twice.

A client only claims a prefix when it has **nothing pending**. Unacknowledged mutations
mean it has optimistically applied actions the server may never have accepted, so its
history is a guess rather than a prefix of server truth — and a resync is precisely the
moment that guess is being abandoned. Viewers never hold pending mutations, so they
always qualify; the drawer qualifies between strokes.

On the client, `replace()` recomputes the prefix hashes over the spliced history and
rejects one that does not hash to what the server said, so a bad splice costs one full
sync rather than a wrong canvas.

`MAX_CANVAS_COMMITS = 512` bounds the acknowledgement window — twice the 256
unacknowledged mutations the browser retains — so ordinary duplicate deliveries are
answerable without per-turn state growing with the sequence number forever.

### `undo_stroke`

A fixed four-integer array, not an object:

```jsonc
[generation, sequence, revision, historyHash]
```

`generation` and `sequence` are 1 – 2³¹−1, `revision` is 0 – 2³¹−1, `historyHash` is
0 – 0xFFFFFFFF. Only the drawer may undo. Undo emits `canvas_undo` with **five**
elements — `[generation, sequence, revisionBefore, revisionAfter, historyHash]` — so a
client that missed the commit can tell an undo from an ordinary action.

### Replay-work budget

Every client that joins or resynchronizes replays the whole turn, so an unbounded turn
is a way to grief a room rather than merely a way to waste a server.

| Constant | Value | Meaning |
| --- | --- | --- |
| `MAX_CANVAS_ACTIONS` | 20 000 | Actions per turn |
| `MAX_CANVAS_POINTS` | 25 000 | Path points per turn. A width change inside a path is charged, and refunded, as one (R-DRAW-07): it is stored as an entry the size of a point |
| `MAX_TURN_REPLAY_WORK` | 20 000 | Weighted replay cost per turn |
| `REPLAY_WORK_BY_TAG` | path 1, shape 1, **fill 200**, clear 0 | Measured in Chromium: a worst-case fill repaints all 480 000 pixels (~6.1 ms) against ~0.02 ms for a path |

In practice this is a **fill budget**: cheap actions hit `MAX_CANVAS_ACTIONS` first.
Undo refunds what the removed action was charged. The client greys the fill tool out
before the budget runs down (`canvasBudgetStore.ts`), so a drawer meets this as a
disabled button; the server value is the authoritative backstop for a client that does
not, and the client is deliberately the stricter of the two.

---

## 8. Canvas history formats

Source: [`backend/app/canvas_history.py`](../backend/app/canvas_history.py).

### Binary replay envelope (`SKCH`) — the format on the wire

```
┌────────┬─────────┬───────────────┬──────────────────────────┬───────────────┐
│ "SKCH" │ version │ actionCount   │ offsetTable              │ packed records│
│  4 B   │  1 B    │  uint16 (2 B) │ (actionCount+1) × uint32 │   variable    │
└────────┴─────────┴───────────────┴──────────────────────────┴───────────────┘
```

Header is `<4sBH`; the offset table is `(n+1)` little-endian `uint32`s, the last being
the total data length, which makes every record self-delimiting. `CANVAS_HISTORY_VERSION = 1`.

Packed record layouts (tags are **history** tags, distinct from the live-drawing tags):

| Tag | Value | `struct` | Fields |
| --- | --- | --- | --- |
| `PATH` | 0 | `<B3sB` + `<hh` × n | tag, color, the width the path starts at, then entries: points, and width markers between them (below) |
| `SHAPE` | 1 | `<BB3sBhhhh` | tag, shape id, color, width, x₀, y₀, x₁, y₁ |
| `FILL` | 2 | `<B3sHH` | tag, color, x, y (absolute pixels) |
| `CLEAR` | 3 | `<B` | tag |

**A width marker** is a path entry whose x is `−32768` (`WIDTH_MARKER_X`), which no
coordinate packs to; its y is a width, and it is a keyframe (§6): the path is that wide
at the next point (#828). It is shaped like a point on purpose. The record stays a header
and a run of four-byte entries, so a path is still extended by appending, its last four
bytes are still its last point — what a relative frame is resolved against — and the
length check and the size bound below are unchanged. A marker is never a path's first
entry, its last, or beside another, and a decoder refuses a record where one is. Most
paths hold none, and the server only walks a record's entries when its x column holds
the value.

`MAX_BINARY_CANVAS_HISTORY_BYTES` is derived from the layout as an invariant, not a
target: all 20 000 action slots, all 25 000 points in one path, and the remaining slots
filled with the larger fixed-size shape record. Markers do not move it, because they are
charged against the same 25 000.

### The retired JSON form

Until #566 the server could also describe a history as `{"v": 1, "a": [...]}`, each
action a positional array, and the client decoded either. Nothing had sent the JSON
form since the binary envelope shipped — `sync_strokes`, `sync_strokes_tail` and every
drawing download carry `SKCH` — so the server encoder, the client decoder and the JSON
half of the cross-language fixture were removed rather than kept as a fallback nobody
could reach. This is the *wire* form only: every **stored** format keeps its decoder
(R-HIST-18), and those answer in `SKCH`.

### History hash

`extend_history_hash(previous, record)` CRC32s a `uint32` length prefix followed by the
record bytes, chained across every action from `HISTORY_HASH_INITIAL = 0`. The length
prefix is what makes it unambiguous: two different action sequences cannot produce the
same byte stream. `CanvasSession` keeps the prefix array so the common case (a path
still being drawn) extends the stored prefix instead of rescanning the whole history.

### Stored format — a different commitment

[`backend/app/canvas_storage.py`](../backend/app/canvas_storage.py) is the boundary
between two promises:

> A drawing **on the wire** only has to be understood by the client on the other end of a
> connection that is open right now, so both ends deploy together and a version bump is
> coordinated by definition. A drawing **in the database** has to be readable by every
> future decoder, forever.

Two rules, and only two:

1. **Every format ever written keeps its entry in `_STORED_DECODERS`.** An entry is
   added when a format starts being written and is **never removed**.
2. **A decoder returns bytes in the current wire format.** Clients therefore never
   learn that a stored format exists, and the wire format stays free to change without
   migrating a single row.

Three formats exist. `SKCH` v1 is the wire frame stored byte for byte, the only format
written before #547 and still what a frame too small to be worth encoding is stored as;
its decoder is the identity function. `SKCD` v1 is the same frame with every path's
points recoded as deltas from the previous point, then deflated, behind a header that
declares the frame's inflated length. `SKCD` v2 is what a finished drawing is written as
now (#828): v1 reads and restores a width marker exactly, since it treats every entry
alike, but it chains the marker into the differences — two large deltas, one to reach
it and one to leave — so a pen drawing stored **48% larger** than the same strokes at
one width where v2 stores it **12% larger** (`benchmarks/path_widths.py`, the long hand
trace at brush 12). v2 copies a marker through and differences the points either side
against each other. For a recoded marker to be tellable from a recoded point, x is
differenced modulo **65 535** rather than 2¹⁶ — a path's x has exactly that many values,
the floor being the marker — which leaves `0xFFFF` free to mean "marker"; modulo 2¹⁶
every value is some pair of points' difference, and a step of exactly 32 768 would read
as one. Small steps are the same small numbers either way. A stroke is a
run of small movements, so the deltas are the small repeated numbers deflate is good at;
the realistic benchmark frame stores 4.5× smaller (34.6 KB → 7.6 KB), where deflate
over the raw frame reaches 1.4×. The `(magic, version)` pair at offset 0 is the
discriminator, which is why no envelope is needed to tell formats apart.

Reading a compressed blob is bounded by what it claims, before any of it is trusted: a
declared length above the largest frame the wire format can express is refused before
allocation; the stream is inflated to at most that length and must end there exactly, with
nothing trailing; and the frame is walked under the wire format's own action and point
caps while the deltas are undone. A blob that lies about any of it is reported corrupt.
The row's checksum and `byte_size` describe the **stored** bytes, so a read verifies what
the database holds before decoding; the drawing route's `ETag` is that checksum, which is
a valid validator because a stored blob decodes to one frame. For the same reason the decoded bytes
are shared across the four drawing routes — participant, pin, gallery and moderator — by
that checksum and the wire version (#979): the first fetch decodes the blob and gzips the
frame once, on a worker thread, into a byte-bounded in-process LRU (32 MiB,
`sketchy_drawing_cache_bytes`), and concurrent misses for one drawing share that decode;
a later fetch asks the route's own access query — the same one the `ETag` is answered
from — and is then served the held bytes, `Content-Encoding: gzip` with `Vary:
Accept-Encoding` when the client accepts gzip (`q=0` refuses) and the frame is 500 bytes
or more. A smaller frame is handed over as it is - the held copy is not worth the
header. Whether it reaches the client compressed anyway is the response middleware's
business: its own 500-byte minimum applies to a body it is handed whole, and not to one
that reaches it in pieces. Only the bytes are shared, never the answer to who may have them. The decode-only golden
blobs live in [`fixtures/stored_drawings_v1.json`](../fixtures/stored_drawings_v1.json)
and [`fixtures/stored_drawings_v2.json`](../fixtures/stored_drawings_v2.json), one file a
format: entries may be added, never removed or changed. On PostgreSQL the payload columns are
`STORAGE EXTERNAL`, so TOAST never tries to compress what is already deflated. Because a
database column has no integrity check of its own, an operator command decodes stored
drawings in bounded batches:

```bash
cd backend && .venv/bin/python -m app.services.drawing_storage
```

---

## 9. REST API

Base path `/api` unless noted. `SessionAuthMiddleware`
([`backend/app/auth/middleware.py`](../backend/app/auth/middleware.py)) resolves the
hashed session cookie for every request under `/api/`; any other path (the application
shell, its assets, `/metrics`) is answered as a caller with no session, without a
database read (#974). The prefix is matched on the routed path, after any `root_path` a
proxy prefix puts in front, so the gate and the routes always agree on what is the API. Role-gated endpoints answer **404**, not 403,
to anyone without the role — the account menu decides what is *shown* and nothing more.

Every response carries an `X-Request-ID`: the UUID the caller sent in the request
header of that name, if it sent one, else one the server minted. It is the id the
server's own log lines for that request are stamped with, and the one written into
`audit_events.request_id` when the request produced a ledger entry - so a client, a
proxy and the operator can quote the same id. A supplied value that is not a UUID is
replaced, not echoed.

**A refusal names its reason.** A player-facing route answers

    {"errorCode": "sign_in_required", "detail": "...", "field"?: ..., "params"?: {...}, "retryAfterMs"?: ...}

built by `Refusal` ([`backend/app/api/errors.py`](../backend/app/api/errors.py)) from
the same `ErrorCode` vocabulary the socket uses (§2). `detail` is English and is not
rendered — the client writes the player's sentence from the code (R-I18N-01) — and
`params` carries values, never fragments (R-I18N-02). **Staff-only routes** keep a
plain `{"detail": "..."}`: the moderation queue and the operations pages are read by
operators in one language, and the split is written down as an allowlist in
[`backend/tests/test_rest_refusals.py`](../backend/tests/test_rest_refusals.py), which
fails on a player-facing route that refuses with prose and on a stale exemption.
FastAPI's own validation failures keep their `{"detail": [...]}` shape; a client that
provoked one sent a payload no screen can produce.

**Unsafe requests are held to the origin policy** (#465, [`backend/app/origin_policy.py`](../backend/app/origin_policy.py)):
a POST, PUT, PATCH or DELETE whose `Origin` — or `Referer`, when a browser sent only
that — is not this server's own origin or one in `ALLOWED_ORIGINS` is answered **403**
`{"detail": "This request did not come from Sketchy."}` before its cookie is resolved.
A request with neither header is a non-browser client and passes. CORS is granted only to
`ALLOWED_ORIGINS`, never to a wildcard and never with credentials. With the session cookie
`SameSite=Strict`, that is the whole CSRF policy: there is no token.

**Every response carries the browser hardening headers** (#467,
[`backend/app/security_headers.py`](../backend/app/security_headers.py)), the Socket.IO
mount's and static files' included: `Content-Security-Policy` (same-origin, the built
shell's inline script by hash, `data:`/`blob:` images and `data:` fonts, no frames or
objects), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
same-origin`, a `Permissions-Policy` declining device APIs, `Cross-Origin-Opener-Policy:
same-origin` and `Cross-Origin-Resource-Policy: same-origin` (`cross-origin` when
`ALLOWED_ORIGINS` is set). In production `Strict-Transport-Security: max-age=31536000;
includeSubDomains` joins them, the session cookie is `__Host-sketchy_session`, and a
request over plain HTTP is answered **308** to the same path on `PUBLIC_BASE_URL` — its
method kept — unless it is one of the three probe paths. A response the application gave
its own value for one of these headers keeps it.

Every response also carries `X-Sketchy-Protocol`, the `PROTOCOL_VERSION` this build
speaks, which the client compares against its own on every response it reads (§1, *REST
is held to the same number*). The REST surface has no version of its own: it is served
by the same deployment as the bundle that calls it, evolves additively where that is
free and otherwise changes shape under a `PROTOCOL_VERSION` bump, and a stale tab is
reloaded rather than served an older contract.

### Health, discovery, metrics

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, process-only — never fails on a dependency, because a restart cannot fix an outage the replacement comes back into. `{"status":"ok","readiness":…,"paused":…,"loops":{…}}`, where each supervised background loop reports `running`, `consecutive_failures`, `total_failures`, `seconds_since_success`, `seconds_since_failure`, and `detail` when it has something to say in its own terms — the retention loop puts each table's rows, batches, duration, backlog, overdue age and SLA under `detail.sweeps`, which is where the `sketchy_retention_*` series are read from |
| `GET` | `/api/ready` | 200 only when startup finished, no drain has begun, no supervised loop has stopped, and the database answers `SELECT 1` inside 1 s (result cached ~5 s). 503 otherwise, with `detail.reason` naming which of the three it was. A loop that is merely *erroring* stays ready — see `docs/architecture.md` §Health and readiness |
| `GET` | `/api/rooms` | Public room summaries (`RoomSummary[]`). No longer polled by anything — the lobby is pushed this list on its channel (#462) — but kept as a plain public read for operators and tests. Sends an `ETag` and answers a matching `If-None-Match` with an empty **304**; `Cache-Control: no-cache` so it is revalidated, never served stale. The validator is a hash of the serialized list, not a change counter — a counter must be bumped at every site touching any of the 22 fields in `to_public_summary()`, and a missed bump is a lobby that stays stale |
| `GET` | `/metrics` | Prometheus text, bearer token. **Disabled entirely until `METRICS_TOKEN` is set.** The nine recorder series (`sketchy_rooms_live` … `sketchy_events_total{event}` — every runtime observation is counted here, including those the database does not store, so the trend over days is this counter's, #965; every kind is present at zero from the first scrape, so `increase()` counts its first occurrence, #968) plus `sketchy_phase_timer_lateness_seconds` (how late each phase timer fired, every firing — the distribution the stored `timer.overran` rows only sample past 250 ms, #965) and the process signals: `sketchy_http_requests_total{method,route,status_class}` and `sketchy_http_request_duration_seconds{route}` (a histogram; probes are not timed), `sketchy_http_requests_in_flight`, `sketchy_socket_events_total{event,outcome}`, `sketchy_socket_event_duration_seconds{event}`, `sketchy_socket_connections_total{outcome}`, `sketchy_canvas_recovery_notices_total{reason}` (every time a socket's canvas needed recovering, by reason — §7; one notice per window is sent, every occurrence counts), `sketchy_socket_packets_rejected_total{reason}` (inbound packets dropped at the envelope check, §3 — `flood`, `attachment_count`, `attachment_size`, `envelope`, `binary_event`, `binary_ack`, `text_in_assembly`, `stale_assembly`, `unexpected_binary`; anything but zero on a healthy deployment is a client that is not ours), `sketchy_socket_handshake_transport_total{transport}` (handshakes accepted by the transport they opened on — `polling` or `websocket`; a rising polling share is a network dropping upgrades, or a proxy), `sketchy_socket_disconnects_total{reason}` (`server_disconnect`, `client_disconnect`, `ping_timeout`, `transport_close`, `transport_error`, or `other` for a reason a later library adds), `sketchy_socket_session_seconds` (how long an accepted socket stayed open, 1 s to 4 h), `sketchy_seat_rebind_seconds` (how long a seat inside its reconnect grace waited for its account to come back, dense below the 30 s grace), `sketchy_socket_ping_rtt_seconds` (Engine.IO ping to pong on every connection — the network round trip plus both event loops, no client report needed), `sketchy_sockets_by_transport{transport}` (open sockets by the transport they are on *now*, read at scrape) and `sketchy_socket_upgrades_total` (sockets whose handshake opened on polling and later upgraded — the handshake transport is read from the Engine.IO handshake request itself, because a client can upgrade before its Socket.IO CONNECT is handled), `sketchy_stale_clients_total{received,outcome}` (sockets told to upgrade, by `older`/`newer`/`absent` and `reloaded`/`closed` — the raw version a client claims is never a label) — all #881, R-OBS-18, `sketchy_socket_transport_total{compression}` (WebSocket upgrades accepted, by the permessage-deflate window they negotiated — `deflate-15` — or `none`; a proxy stripping the extension shows up here first), `sketchy_sockets_connected`, `sketchy_ws_wire_bytes_out_total` and `sketchy_ws_wire_bytes_in_total` (WebSocket frame bytes after permessage-deflate, headers included, from the open connection through both halves of its closing handshake — never the upgrade or a refused handshake's HTTP response; WebSocket sockets only — the real compression ratio against the packet counters, §1, #875), `sketchy_socket_bytes_in_total` and `sketchy_socket_bytes_out_total` (Engine.IO packet bytes before compression or framing; out counted once per recipient at `eio.send_packet`, which broadcasts, acknowledgements and direct emits all pass through — the earlier `eio.send` hook missed every ordinary broadcast, #563), `sketchy_socket_bytes_out_by_event_total{event}` (the same bytes by what they carried, read off each packet's prefix: an event name, `<ack>`, or `<control>` for connect/disconnect and Engine.IO's own packets, with a binary event's attachments charged to it; it sums to `sketchy_socket_bytes_out_total` and is the series to rank events by — #874), `sketchy_socket_refusals_total{event,code}` (every refused command by its `errorCode`, including those refused at the door before any handler runs — `invalid_payload` for arity, `protocol_mismatch` for a stale tab, `too_fast` for a throttled one — `other` for anything outside the enum), `sketchy_canvas_tail_claims_total{result}` (each canvas sync by what the client's prefix claim came to: `none`, `hit`, or why it missed — `generation`, `empty`, `open_path`, `ahead`, `hash`; §7), `sketchy_draw_frames_total{kind,shape,result}` (every `draw` frame by tag — `start`, `points`, `points_delta`, `points_relative`, `points_end`, `end`, `shape`, `fill`, `clear` — wire shape — `binary`, `base64`, `int` — and what became of it — `accepted`, `refused`, `out_of_order`, `duplicate`, `discarded`, `not_drawing`, `invalid`, or `throttled` when the command budget turned it away before the handler ran), `sketchy_draw_frame_points` and `sketchy_draw_frame_width_keyframes` (per accepted point frame; the zero bucket of the second is a mouse or a steady pen, #903), `sketchy_drawing_cache_bytes` (decoded drawings held for re-serving, both encodings) and `sketchy_drawing_cache_requests_total{result}` (`hit`/`miss` per fetch that got past the validator — #979), `sketchy_lobby_watchers` (sockets on the lobby channel now), `sketchy_lobby_ticks_total{feed,result}` (`rooms`/`presence`, `emitted`/`skipped`), `sketchy_lobby_baseline_bytes` (one `watch_lobby` acknowledgement), `sketchy_socket_backlog_bytes` and `sketchy_socket_backlog_age_seconds` (every open backlog sampled on the 1 s sweep, beside the high-water marks) — all #882, each the input to a pending protocol decision, R-OBS-19; `sketchy_client_health_reports_total{transport}`, `sketchy_client_health_events_total{event,transport}` (`tail_rejected`, `sync_exhausted`, `dropped_emit`, `stall_fallback`, `playback_compression`) and `sketchy_client_join_to_drawing_seconds{transport}` (a player entering mid-turn waiting for the drawing, 0.1 s to a minute) — all #876, R-OBS-20, the client's half: what only it can see, reported only when something happened, labelled by the transport the server reads off the socket and never by anything the client sent; `sketchy_socket_command_bytes{event}` and `sketchy_socket_emit_bytes{event}` (payload-size histograms, once per command received and once per emit — the size distribution, not what an event cost: a broadcast is one observation however many seats hear it; bytes inside a list, as the canvas events carry them, count as their length), `sketchy_event_loop_lag_seconds` (+ `_last_seconds`), `sketchy_db_queries_total`, `sketchy_db_query_errors_total{cause}` (by SQLSTATE class: `timeout`, `lock_timeout`, `deadlock`, `serialization`, `integrity`, `connection`, `other`), `sketchy_db_query_duration_seconds{operation}` and `sketchy_db_transaction_seconds{operation}` (histograms to 30 s; the operations are named at their call sites, everything else is `other`), `sketchy_db_pool_wait_seconds` and `sketchy_db_pool_timeouts_total` (PostgreSQL's pool only), `sketchy_db_retries_total{operation,outcome}`, `sketchy_history_write_seconds` and `sketchy_history_persist_lag_seconds` (#892), `sketchy_db_pool_{size,checked_out,checked_in,overflow,capacity}` (absent for a pool that keeps no count), `sketchy_db_ready` (the readiness probe's result, refreshed by the scrape itself - cached a few seconds, bounded to one - so it is present on a worker nothing has asked `/api/ready`), `sketchy_history_writes_abandoned_total{kind,reason}`, `sketchy_mail_outbox_{pending,oldest_seconds}` and `sketchy_data_exports_{pending,oldest_seconds}` (the one family that costs a query; omitted, not failed, when the database does not answer within 2 s, so a scrape survives the outage it is describing), `sketchy_loop_{running,consecutive_failures,failures_total,seconds_since_success}{loop}`, `sketchy_retention_{overdue_seconds,sla_seconds,backlog_rows,sweep_seconds,sweep_exhausted,sweep_failed}{table}` and `sketchy_retention_{rows_removed_total,sweep_failures_total}{table}` (per retained table, read off the retention loop's own health record, so they cost the database nothing at scrape time; a table that owes nothing reports zero rather than being absent, because an absent series compares greater than no allowance — R-PRIV-17, SLO-10), `sketchy_process_{cpu_seconds_total,resident_memory_bytes,start_time_seconds,uptime_seconds}`, `sketchy_data_disk_{free,total}_bytes` |

### Accounts and sessions — [`backend/app/auth/routes.py`](../backend/app/auth/routes.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/auth/me` | The caller's account, or `null` — it creates nothing, so a crawler or a link preview costs no row. `POST /api/auth/display-name` is the one path that provisions a guest (R-ACCT-00). Carries `pendingRole`: a staff role offered and waiting on this account's second factor, or `null`. It authorizes nothing — it is what makes the two-factor entry appear for the one account it means anything to (R-AUTH-20), and a lapsed offer reads as `null`. A guest's account also carries `nameInUse`: `true` when a guest who came online earlier is using the same name, so this one is asked for another before playing (R-ACCT-09). A registered account's carries `settings`, the same object `GET /api/users/me/settings` returns: the first paint waits for this answer (R-I18N-06), and asking for them separately put a second round trip in front of it (#983). The page requests it from an inline script in `index.html` before any bundle has loaded, so it is in flight while the bundle downloads |
| `GET` | `/api/auth/nickname-available` | Rate limited (`AUTH_LOOKUP_LIMIT`). Unavailable for a registered player's username, and for a name a guest online is using (R-ACCT-09) |
| `POST` / `DELETE` | `/api/users/me/avatar` | Set or remove the caller's picture (R-AVA-01). `POST` takes `{ image }`, base64 of a 256×256 WebP or PNG under 128 KiB; refused `400` for anything else, `403` for a guest or while a moderator's block stands (the message names the date), `429` past 10 an hour. Answers `{ avatarKey, avatarUrl }` |
| `PUT` | `/api/users/me/avatar/doodle` | Wear one of the deployment's doodles instead of a picture (R-AVA-09). Takes `{ name }`, a name from the sprite's list; refused `400` (`invalid_payload`) for any other, `403` for a guest. No rate limit and no moderator's block: nothing is stored but the name. Deletes an uploaded picture. Answers `{ avatarKey, avatarUrl }`, the URL a fragment of `/avatars/doodles.svg` — a static file from the frontend build, not an API route |
| `GET` | `/api/avatars/{key}` | The picture behind a content address, for anybody: `image/webp` or `image/png` as the key's extension says, `nosniff`, `Cache-Control: public, max-age=31536000, immutable`. `404` for a key that is not a content address or not stored |
| `POST` | `/api/moderation/reports/{report_id}/remove-avatar` | Moderator. Takes down the reported account's picture, audits it, tells its owner, and blocks re-upload for a while that grows with how many a moderator has taken down from this account — none, 7, 30, then 90 days (R-AVA-08); `{ ok, removed, blockedUntil }`, the last null when this one cost no wait (R-AVA-04) |
| `POST` | `/api/auth/display-name`, `/api/auth/name-color` | Profile edits — and `display-name` is what **provisions a guest** on a first visit (R-ACCT-00): choosing a name is the first act only a person about to play performs. A name colour that does not read on both themes' player list is refused with 400 (R-ACCT-08); the same rule the seat applies. A display name another online guest is using is refused with 409 `name_in_use` (R-ACCT-09), including keeping your own when a guest who came online first holds it |
| `POST` | `/api/auth/register` | Claims the current account (`AUTH_REGISTER_LIMIT`) |
| `POST` | `/api/auth/login` | `{ username, password, code? }`. Argon2id; rehashes stale-cost hashes on success. Throttled on three keys at once — account, address, deployment — all counting **failures only**, plus a per-account backoff (R-RATE-12). A staff account must also produce its second factor (R-AUTH-20): with no `code` it answers `401` carrying `X-Sketchy-Second-Factor: required` — or `X-Sketchy-Second-Factor: passkey` when the account holds a passkey and no authenticator app, where the password route cannot finish at all and the form has to offer the passkey rather than a field (R-AUTH-23), which is how the client knows to ask rather than to report a wrong password; a staff account that has not enrolled is `403`. A recovery code is accepted in the same field. Every route that hashes **or verifies** a password — this one, register, password change, reset, account deletion, and every proof of a password (turning a second factor off, replacing recovery codes, stepping up) — answers **503** `server_busy` with `Retry-After` once `PASSWORD_HASH_WORKERS` × 16 hashes are already running or waiting, so a burst is refused rather than queued behind the loop (#975); the rehash after a successful login is skipped instead, never refused |
| `POST` | `/api/auth/logout`, `/api/auth/logout-all` | |
| `GET` | `/api/auth/sessions` | Signed-in device list: `id`, `deviceLabel`, `createdAt`, `lastUsedAt`, `expiresAt`, `idleExpiresAt` (when silence alone ends it — usually far sooner than `expiresAt`), `anomalyAt` (last used from a browser it was not issued to, or `null`), `current` (R-AUTH-03, R-AUTH-22) |
| `DELETE` | `/api/auth/sessions/{session_id}` | Revoke one device |
| `GET`/`PUT` | `/api/auth/email` | `PUT` is rate limited (`AUTH_VERIFY_LIMIT`) |
| `POST` | `/api/auth/email/verify`, `/api/auth/email/reminder-seen` | |
| `POST` | `/api/auth/password/forgot` | **Answers identically whether or not the account exists** (`AUTH_RESET_LIMIT`) |
| `POST` | `/api/auth/password/reset/check` | Checks without consuming the token (`AUTH_RESET_CHECK_LIMIT`) |
| `POST` | `/api/auth/password/reset` | Revokes every session, then signs the user in (`AUTH_RESET_PERFORM_LIMIT`) |
| `POST` | `/api/auth/password/change` | Signed in, and knows the current password. Revokes every session, then signs the caller back in (`AUTH_PASSWORD_CHANGE_LIMIT`) |
| `POST`/`GET` | `/api/auth/data-exports` | Request a job / list the caller's jobs. One per account per 7 days and never two live at once (R-PRIV-12): a request too soon answers `429` with the date in `detail` and a `Retry-After`; the listing carries `nextRequestAt` (ISO 8601, or `null` when one may be requested now) |
| `GET` | `/api/auth/data-exports/{export_id}` | Job status. On a `failed` job `failureCode` is `too_large` (the deployment's ceiling, R-PRIV-13) or `generation_failed`; otherwise `null` |
| `GET` | `/api/auth/data-exports/{export_id}/download` | The document: the stored gzip bytes as `Content-Encoding: gzip` when the request accepts it, else decompressed as it streams; `Content-Length` either way. Owner-only through the session, never a bearer URL (R-PRIV-14); v1 exports expire after 7 days |
| `GET` | `/api/auth/second-factor` | `{ enrolled, confirmedAt, recoveryCodesRemaining, passwordProved, required, stepUpWindowSeconds }`. `required` is true when the account's role demands one |
| `POST` | `/api/auth/second-factor/enrol` | Offers `{ secret, uri }` and **stores nothing** — the secret becomes a credential only when a code proves it arrived (R-AUTH-20), so an abandoned enrolment can lock nobody out (`AUTH_SECOND_FACTOR_LIMIT`) |
| `POST` | `/api/auth/second-factor/confirm` | `{ secret, code, password? }` → `{ ok, recoveryCodes, roleGranted }`. The password is **optional** only for an account that holds no credential at all; it is **required** when one is already in place — an authenticator app being replaced, or a passkey, since binding a second factor beside a passkey is otherwise something a stolen cookie can do unaided (R-AUTH-20). The ten codes appear **here and nowhere else**: only their SHA-256 hashes are kept. Re-enrolling replaces the secret and every code issued against the old one. `roleGranted` names a role that was waiting on this enrolment and has just taken effect — every **other** session on the account is revoked with it, and this response carries a fresh cookie for the role, so the codes above stay readable |
| `POST` | `/api/auth/second-factor/confirm-owner` | `{ password, code }` → `{ ok, roleGranted }`. Records that the factor already in place is the account owner's — what a staff role requires and enrolling through the API need not carry. Both proofs: the password says the owner is asking, the code says the enrolled authenticator is theirs. The code is spent like any other, so one just used to enrol is refused until the next step. Takes up a waiting offer exactly as `confirm` does, cookie and all |
| `POST` | `/api/auth/passkeys/options` | Staff, or an account with a role waiting on it → `{ options }`, WebAuthn's own creation JSON as a string. Asks for a **discoverable** credential with `userVerification: required`, and excludes what the account already holds so an authenticator already registered says so instead of silently making a second credential (R-AUTH-23) |
| `POST` | `/api/auth/passkeys` | `{ credential, password, label? }` → `{ passkey, roleGranted }`. The password is what says this credential is being added by the account's owner rather than by a stolen cookie, exactly as R-AUTH-20 asks of an authenticator app — and it takes up a waiting offer the same way, cookie and all |
| `GET` | `/api/auth/passkeys` | `{ passkeys, canHold }`. `canHold` is false for an account that is neither staff nor holding an offer, which is also what makes the control invisible to every other player |
| `DELETE` | `/api/auth/passkeys/{id}` | `{ password }`. Refused when it is a staff account's **last** way in, the way removing the last second factor is: giving up the role is what removes the requirement |
| `POST` | `/api/auth/passkeys/challenge` | `{ options }`, WebAuthn's request JSON. Answered to anybody: signing in happens before anybody has said who they are, and the challenge is a random number this server will remember for five minutes. Names no credentials, so it tells an unauthenticated caller nothing about which accounts hold what |
| `POST` | `/api/auth/passkeys/verify` | `{ credential }` → `{ ok, user, steppedUp }`. One act, two uses: a caller already holding a session on the account that signed is **stepped up** (R-AUTH-21); anybody else is **signed in**, which does everything `POST /api/auth/login` does after the password check — the guest is merged (R-ACCT-04), its sessions revoked, the login stamped — plus the step-up recorded, since the assertion is that proof and it is one request old |
| `POST` | `/api/auth/second-factor/recovery-codes` | `{ password }` → a fresh set, invalidating every previous code |
| `DELETE` | `/api/auth/second-factor` | `{ password }`. Refused `409` when the account's role requires one: giving up the role is what removes the requirement |
| `POST` | `/api/auth/step-up` | `{ code }` → `{ ok, expiresInSeconds }`. Opens the 15-minute window every destructive staff action needs (R-AUTH-21). Recorded on the session, so revoking the device revokes the proof. An authenticator app whose owner was never proved is refused here with **403**, though it may still sign in beside a password: a step-up costs an attacker only the session they stole (R-AUTH-21) |
| `DELETE` | `/api/auth/account` | Password required for a registered account |

### Profiles and history — [`backend/app/api/profiles.py`](../backend/app/api/profiles.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/users/{user_id}/stats` | Served from the daily projection, never four history scans. The `user` beside the numbers is the **public profile** (#469): `id`, `displayName`, `nameColor`, `avatarUrl`, `isAnonymous`, `createdAt`, plus `isOnline` (the presence registry's answer now) and `lastSeenAt` (when the account's last socket closed; `null` for one that never connected). Never `role`, `lastLoginAt` or `username`; those are the caller's own account on `/api/auth/me` |
| `GET` | `/api/users/{user_id}/games` | `?includeAbandoned=true` to include games that stopped. Which games are on the page depends on who asks (R-HIST-25): a game from a public room is listed for anyone, a game from a private room only for a caller who sat in it. Each summary carries `visibility` (`public \| private`), frozen from the room when the game was saved; `hasMore` is answered from the games the caller may see |
| `GET` | `/api/games/{game_id}` | Participant-only detail: exact rule snapshot, offers, outcomes, ledger |
| `GET` | `/api/games/{game_id}/turns/{turn_id}/drawing` | Participants only. **Every refusal is a 404**, so it never reveals whether a game exists. The bytes in the current wire format (`application/octet-stream`), `Cache-Control: private, no-cache` and a weak `ETag` of the form `W/"<stored sha256>-w<CANVAS_HISTORY_VERSION>"` — the stored checksum *and* the wire version the decoders answer in, because a new wire version changes the bytes served without changing the bytes stored (R-HIST-18), and weak because the same bytes go out gzipped or not. A matching `If-None-Match` (weak comparison; a list, the strong form, or `*`) is answered **304** with no body, from the metadata alone — the blob is neither read nor decoded — and only after the same participant and availability query as the drawing itself: a remembered tag from a stranger, or for an erased drawing, is a 404 like any other refusal (#604). `no-cache` rather than a lifetime so an erased drawing stops being shown at the next open, not when an hour runs out |
| `PUT` | `/api/games/{game_id}/turns/{turn_id}/reaction` | `{"emoji": "heart"}` — leave or change the signed-in player's reaction to a stored drawing (#520), the **participant door** (R-REACT-08). Same 404 rule as the drawing route: stranger, guest, drawer, erased drawing, unknown code and unknown game are all `No such drawing.` Answers `{turnId, seatId, emoji, myReaction, reactions: [{seatId, emoji}], reactionCounts: {code: n}}` — the seat rows as a list, every row as a count, and the caller's pick (R-REACT-05) |
| `DELETE` | `/api/games/{game_id}/turns/{turn_id}/reaction` | Take the reaction back; same answer shape with `emoji: null`. Both share `set_drawing_reaction` with the socket's recap path and with the gallery door below, so the rules live once |
| `PUT` | `/api/me/pins` | `{"turnIds": [...]}` — replace the signed-in player's **Pinned drawings** with the list given, in that order (#440). Pinning, unpinning and reordering are all this one request: the body is the whole shelf. Any turn with a `ready` drawing from a **public** game the caller sat in may be on it, their own or another player's (R-PIN-01, R-PIN-03). More than six answers `409 pinned_drawings_full` with `params.slots`; a repeated id or a body past twice the cap is `422`; every other refusal — signed out, guest, stranger to the game, private game, erased or never-kept drawing, unknown turn — is the drawing route's `404` and writes nothing (R-PIN-04). Answers `{pins: [{turnId}]}` in shelf order |
| `GET` | `/api/users/{user_id}/pins` | The player's **Pinned drawings** for anyone signed in, a guest included (R-PIN-06); no session and no such player are the same `404`. Each entry is `{turnId, roundNumber, turnNumber, drawerDisplayName, drawerNameColor, drawerIsAnonymous, prompt, strokeCount, reactions: [{seatId, emoji}], reactionCounts: {code: n}, myReaction, drawnByMe}` — the game-detail turn's shape where the two overlap, credited through the frozen drawer snapshot, and **no `gameId`** (R-PIN-07); `myReaction` and `drawnByMe` are the viewer's own facts, so the shelf can offer the picker of R-PIN-08 without an account id. A pin whose drawing is no longer ready is left out, not shown as a hole |
| `GET` | `/api/users/{user_id}/pins/{turn_id}/drawing` | The pinned drawing's bytes for anyone signed in: the one other door beside the participant route, with its own query — this account pinned this turn, the game is public, the drawing is ready. Same bytes, `Cache-Control`, `ETag` and `304` handling as that route (R-HIST-24), and the same `404` for every refusal: signed out, unpinned since, erased, or a player that does not exist |

`GET /api/games/{game_id}` carries each turn's `reactions: [{seatId, emoji}]`, its
`reactionCounts: {code: n}` and the requester's own `mySeatId`, because the client cannot
work its seat out from `participants`: a seat kept by a merged guest identity carries that
identity's id, not the account the requester is signed in as. Names for reactors come
from `participants`, whose frozen snapshots are already tombstoned on deletion. The list
and the counts differ on purpose (R-REACT-05): a reaction given from outside the room
through the gallery door has no seat, so it is counted and named nowhere.

### Gallery — [`backend/app/api/gallery.py`](../backend/app/api/gallery.py)

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/gallery` | One page of the **Gallery** (R-GAL-01..04): every `ready` drawing from a **public** game. `sort` = `hot` \| `new` \| `top` (default `hot`), `window` = `all` \| `month` \| `week` (default `all`, read by `top` only), `limit` ≤ 24, opaque `cursor`. Paging **stops 480 rows deep** with an empty page, the community catalogue's rule. Hot looks back fourteen days. Any session, a guest's included; **no session is `403 account_required`** with `params.action` = `gallery` (R-GAL-02) — refused, not an empty page, so the client can say why. An unknown sort or window is `422 unknown_sort` naming the field. Each entry is `{turnId, roundNumber, turnNumber, drawerDisplayName, drawerNameColor, drawerIsAnonymous, prompt, strokeCount, finishedAt, reactionCounts: {code: n}, myReaction, drawnByMe}` — the pin's shape plus the finish time and the viewer's own facts, and **no `gameId`**, room name or reactor's name (R-GAL-03). Answers `{entries, nextCursor}` |
| `GET` | `/api/gallery/week` | **This week** (R-GAL-07), the Gallery rail's six: Top over the last seven days, the first six, as `{entries}` in the listing's entry shape. Served from one process-wide snapshot recomputed at most once a minute and shared by every reader, with the viewer's own `myReaction` and `drawnByMe` added per request; `Cache-Control: private, no-cache` and a weak `ETag` naming the snapshot and those facts, answered `304` on a matching `If-None-Match`, so a page opened twice costs one read and one revalidation, never a poll (#462). No session is `403 account_required` like the listing |
| `GET` | `/api/gallery/{turn_id}` | One entry in the listing's shape, under the listing's predicate, for the drawing's own page (`/gallery/{turn_id}`, R-GAL-03): a drawing worth a reaction is worth a link. Its 404 for everything else — signed out included, so a stranger holding a link learns nothing from it |
| `GET` | `/api/gallery/{turn_id}/drawing` | The bytes through the **third door** (R-GAL-06): its own query over the gallery predicate — public game, ready drawing — never the participant check or the pin join. Same bytes, `Cache-Control: private, no-cache`, `ETag` and `304` handling as the participant route (R-HIST-24), and the same `404` for every refusal: signed out, a private game, a drawing never kept or erased, an unknown turn. Its own budget (600 a minute, against the listing's 120): a page replays up to 24 thumbnails and a scroll adds 24 more, and most of these are `304`s |
| `POST` | `/api/gallery/{turn_id}/report` | `{details?}` → `201 {id, status, createdAt}` — report a drawing from the Gallery (R-GAL-08). The reporter names the **turn** and nothing else: the reason is always `offensive_drawing`, the server resolves the drawer (R-MOD-02, no account id is learnt) and copies the turn's stored drawing in as the report's evidence (R-MOD-14's shape), so a moderator sees exactly what was reported even after the drawer erases it. `401` signed out, `422` for one's own drawing, `409 already_reported` while an earlier report of that player is open, and the Gallery's `404` for a drawing it does not show — a private game, an erased or hidden drawing, an unknown turn |
| `PUT` | `/api/gallery/{turn_id}/reaction` | `{"emoji": "heart"}` — leave or change the signed-in player's reaction to a drawing the **Gallery** shows, the **gallery door** (R-GAL-06, #524): any registered account that is not the drawer, whether or not they sat in the game; a caller who did is written with their seat, so history keeps naming them. No game is named — the turn id is enough, and a game id would be one more thing to disclose. Every refusal is the same `404`: signed out, a guest, the drawer, a private game, an erased or never-kept drawing, an unknown turn, an unknown code. Answers the participant route's shape, with `seatId: null` for a caller who was not there |
| `DELETE` | `/api/gallery/{turn_id}/reaction` | Take the reaction back; same answer shape with `emoji: null` |

Its `scoreEvents` are identified by `eventOrder` within the game (#552): there is no
per-event id on the wire, and a `correction` names its target as `correctsEventOrder`.
Each turn's `participantOutcomes[]` carries the seat's `pointsAwarded` (null unless the
outcome is `correct`); there is no separate `guesses[]` list (#548).
The private export's `scoreEvents` (schema version 5) use the same identity.

### Prompt lists — [`backend/app/api/prompt_lists.py`](../backend/app/api/prompt_lists.py)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/prompt-lists` | Official catalogue; localized copy selected from `Accept-Language` |
| `GET` | `/api/prompt-lists/community` | `{lists, nextCursor}` — published lists (R-LIST-14). Filters: `language`, `starred` (this account's shortlist; **403** `account_required` with `params.action` = `stars` when nobody is signed in), repeated `tag` (a list must carry **every** tag given, not any of them), `sort` = `stars` \| `newest`, `limit` ≤ 48, opaque `cursor`. Each row carries `starCount` and `copyCount` (R-LIST-20), both derived from rows. Paging **stops 480 rows deep** (an empty page, no cursor): nobody reaches that far by reading, so a deeper page is a scrape and a filter is the better answer. `starred` is **exempt** and is read whole — every row in it is a list the caller chose, so reading it to the end collects nothing they did not pick, and the room picker's shortlist does read it to the end. Open to a signed-out caller, whose rows carry `starredByMe: null` and `isMine: null` — a different answer from `false`. `isMine` says whether the caller owns the list, so the catalogue offers no copy of it (R-LIST-17); each caller learns it only about themselves. A row names its owner's **display name and no account id**: a stable third-party identifier in a public listing is a join key for anybody who collects the pages |
| `GET` | `/api/prompt-lists/community/{prompt_list_id}` | One published list with its `prompts` (R-LIST-19) and its `copiedFrom`, which is the list a copy was taken from (R-LIST-21), or `null` for an original: `{status, listId, name, ownerDisplayName}` with `status` `published` (named, `listId` set), `withdrawn` (unpublished or hidden — named, `listId` null) or `deleted` (all three null). Prompts are each `{promptVersionId, prompt}`: the version id is what lets a reader report one exact prompt rather than the whole list. Aliases and concept ids stay out. Hidden prompt versions are left out. **404** unless the list is published, active and present — the same predicate the listing uses, so a takedown closes both doors at once. Open signed out, rate-limited apart from the listing since it returns a list whole |
| `GET` | `/api/prompt-tags` | `{tags: [{slug, name}], maxPerList}` — the curated vocabulary a list owner chooses from (R-LIST-18). Unauthenticated and served rather than duplicated in the client, because a client guessing at the set would offer a tag a save then refuses |
| `GET` | `/api/prompt-lists/mine` | The caller's own lists, each with the `tags` its current revision carries, the `starCount` it has been given and the `copyCount` of copies of it that still exist (R-LIST-20) — **numbers only**: who starred or copied a list is disclosed to nobody, its owner included. Each list also carries `copiedFrom` is the list a copy was taken from (R-LIST-21), or `null` for an original: `{status, listId, name, ownerDisplayName}` with `status` `published` (named, `listId` set), `withdrawn` (unpublished or hidden — named, `listId` null) or `deleted` (all three null). |
| `GET`/`PUT` | `/api/prompt-lists/mine/{prompt_list_id}` | Owner only; `PUT` uses optimistic concurrency and creates a new immutable revision. `tags` are part of the saved content: setting them earns a revision the way a name change does (R-LIST-05), and an unknown tag is **refused by name** rather than dropped — `unknown_prompt_tag`, with the slug in `params.tag` so the client can say which, in the reader's language. Neither this nor `POST /api/prompt-lists/mine` takes a `visibility`, and one sent is a **422** like any unknown field: a list is created private and only `publish`/`unpublish` change that (R-LIST-02), so a save can neither take a list out of the catalogue nor put one in |
| `POST` | `/api/prompt-lists/mine/{prompt_list_id}/publish` | Put an owned list in the community catalogue (R-LIST-11). Its own route rather than a `visibility` on the save, because the trust gate, the rate limit and the audit event all belong to the act. **403** `email_verification_required` or `warning_unread`, each with `params.action` = `publish` (R-LIST-12); **422** `prompt_list_hidden` for a list a moderator hid; **429** `too_many_attempts` past the limit |
| `POST` | `/api/prompt-lists/mine/{prompt_list_id}/unpublish` | Take it back out. Stars survive as rows (R-LIST-16). A `hidden` finding survives too — leaving the catalogue is not a moderator's ruling, and clearing one would launder a takedown — but a review-switch hold (`under_review`) is released to `active`: it only ever meant "waiting to be published", and a withdrawn list is no longer waiting |
| `POST` | `/api/prompt-lists/{prompt_list_id}/fork` | **201** with the new list. Copies a published list's current revision into a new **private** list of the caller's, recording `forked_from_revision_id` — a revision rather than a list, because both go on being edited and a pointer at the list would stop meaning anything after the first edit. Counts against R-LIST-04's 25 and **refuses visibly at the cap, having written nothing**. Hidden prompt versions are left out: a moderator took them out of play, and a copy must not put them back under a new owner. **422** `cannot_copy_own_prompt_list` for the caller's own list — the owner duplicates it instead |
| `POST` | `/api/prompt-lists/mine/{prompt_list_id}/duplicate` | `{name}` (1–64; the client writes it, since "(duplicate)" is a word in the reader's language) → **201** with a new **private** list of the owner's holding the list's current revision: no `forked_from_revision_id`, no `is_copy`, no credit, no copy count (R-LIST-17). Only active prompt versions are carried - the owner's editor shows hidden ones, and a create from those would make them active again. **422** `cannot_duplicate_prompt_list` with `params.reason` = `moderation` (the list is under review or hidden) or `copy` (the list is a copy of somebody else's, whose credit a duplicate would drop); **422** `prompt_list_allowance_reached` at R-LIST-04's 25; **404** for anything the caller does not own |
| `PUT`/`DELETE` | `/api/prompt-lists/{prompt_list_id}/star` | Star or unstar a **published** list → `{starCount, starredByMe}` (R-LIST-16). Idempotent both ways — the composite primary key is the idempotency, so a retry is safe. Verified account only (R-LIST-12), rate-limited. **404** for anything not published, active and present: a star on a private list would be durable evidence the starrer could see it |
| `GET` | `/api/prompt-lists/{slug}/prompt-stats` | Window (all-time / 30 d / 90 d) and scoring/hint segmentation |

### Settings, blocks, friends, presets

| Method | Path | Notes |
| --- | --- | --- |
| `GET`/`PATCH` | `/api/users/me/settings` | Cross-device Player settings; bounded at API and database layers. Carries **two** languages, and they are not the same one: `promptLanguage`, the language the player *plays* in (R-PROMPT-11), and `locale`, the language they *read* in (R-I18N-06). Both are seeded at registration from what the new account's browser resolved, and are settings afterwards; both are stored because a browser describes a device rather than a person |
| `GET`/`POST` | `/api/users/me/blocks` | Directional; self-blocks rejected |
| `GET` | `/api/users/me/friends` | `{friends, incoming, outgoing, announce}`. Refusals are in none of them. A guest is refused **403 with `X-Sketchy-Account-Required`** — the header names the reason, because a status cannot: the middleware answers 403 for a suspended account before this route runs, and a client that reads any 403 as *this caller is a guest* shows an empty friends list for a real account. Same pattern as `X-Sketchy-Step-Up`. The client does not ask for a guest at all — a guest provably has no list (R-FRIEND-03), so asking only logs a refusal on every anonymous load; the refusal still answers a session that lapses mid-read. Also `announce`: the requests this account **sent** that were accepted and that nobody has told them about yet — a fact on the row rather than a difference between two reads, so a client that was reloading when the answer came still learns it (R-FRIEND-14) |
| `POST` | `/api/users/me/friends/announced` | `{ userIds }` → `{ ok, announced }`. Records that the asker was told, for exactly the friendships the message named, re-checking on the write that each is their own request, accepted, and still unannounced. Sent **after** the message is shown: recording first loses the news whenever the render does not happen |
| `POST` | `/api/users/me/friends` | `{userId}`. **Answers the same whether it landed, hit a block, hit an earlier refusal, or named nobody** (R-FRIEND-04); 409 only for a ceiling the caller reached (`FRIEND_REQUEST_LIMIT`) |
| `POST` | `/api/users/me/friends/{user_id}/accept` | Re-checks blocks: one placed since the request has to win. Answers `accepted`, `declined` or `unchanged` — the caller is answering a request on their own list, so unlike `POST /` there is no third party to be vague about |
| `DELETE` | `/api/users/me/friends/{user_id}` | Decline, cancel, or unfriend — the server decides which the row is asking for |
| `GET` | `/api/users/me/recent-players` | `{players}` — registered accounts the caller **finished a game with** in the last 30 days, most recent first, capped at 20. Not a search and not a directory (N-06): it answers only about games the caller sat in, so it can never name a stranger. Deliberately **unfiltered by friendship or block** — an absence from it would be readable, and "absent because they declined you" is the fact R-FRIEND-04 refuses to disclose, so the client drops the rows it can already see for itself and leaves a refusal in place |
| `DELETE` | `/api/users/me/blocks/{user_id}` | Idempotent |
| `GET`/`POST` | `/api/room-presets` | ≤ 20 per account. `settings` is `RoomSettingsFields`, so it carries `promptLanguage`; a preset whose lists are not in it is refused **422** |
| `GET`/`PUT`/`DELETE` | `/api/room-presets/{preset_id}` | `PUT` uses an optimistic version check. The `promptLanguage` read back is **derived from the saved lists**, so a preset and its lists can never disagree; applying a preset sets the new room's language and its lists together |

### Reports and moderation — [`backend/app/api/moderation.py`](../backend/app/api/moderation.py)

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/reports` | any signed-in | ≤ 2000 chars of optional detail, ≤ 32 768 bytes context, ≤ 20 **unique** `messageIds`. One open report per reporter/target |
| `POST` | `/api/prompt-content-reports` | any signed-in | Targets a **published** list or an exact `promptVersionId` in one; anything else is **404** `no_reportable_prompt_list`, since nobody but its owner can see a private list. Official content and self-reports rejected |
| `GET` | `/api/moderation/reports` | moderator+ | The queue as **incidents**, oldest first: `{ incidents, total, hasMore }`, where `limit` and `offset` page incidents rather than reports (R-MOD-16). Each incident carries `id` (its oldest report's, which every decision route accepts), `reportedPlayer` standing (name, registered, age, prior reports/warnings, active suspension), `scope` (`room`, `lobby`, `profile`, `unscoped`), `reporterCount`, the distinct `reasons` in the order first given, `openedAt`/`latestReportedAt`, `reports` — each complaint's own `reason`, `details`, reporter and `drawing`, and no evidence of its own — `evidence`, every report's lines merged into one thread in the order they were said, each line once, with a `role` of `cited` or `context` (R-MOD-13) and `citedBy`, the reports that complained about it, `drawings`, every attached canvas by its metadata (`reportId`, `turnId`, `roundNumber`, `prompt`, `actionCount`, `byteSize`, `capturedAt`), and how it was closed: `outcome` (`pending`, `dismissed`, `resolved`, `warned`, `suspended`; a content report closes as `dismissed`, `hidden`, `left_up` or `resolved`) read from the warning or suspension that names the report rather than from its status, `reviewedBy`, the reviewer's name resolved when read (R-MOD-15), and `decisionGroupId`, the moderator action that decided it. Two more facts a moderator needs before deciding: `picture` says what became of the picture the incident is about (null when it is about none): `status` of `same`, `replaced` or `removed`, and for a removal `removedByModerator`, `removedAt` and `removedFromThisIncident` — because a picture a moderator has already taken down must not read as merely a different one, and the reviewer seeing it is often the one who removed it from that case; each report carries its own `pictureStatus` beside this (R-AVA-07); and `priorDecision`, null on a first complaint, carries `outcome`, `decidedAt`, `decidedBy`, `note` and `priorDecisions` for the last decision taken about this same incident key, so a repeat of something already dealt with does not arrive looking untouched (R-MOD-18) |
| `GET` | `/api/moderation/reports/{report_id}/drawing` | moderator+ | The attached drawing's bytes in the **current wire format** (`application/octet-stream`, `Cache-Control: private, no-store`), checksum verified on every read; `404` when the report has none |
| `GET` | `/api/moderation/closed-cases` | moderator+ | Decided **incidents**, player and content as one stream, **newest decision first**, under `limit` (≤ 100) and `offset` (≤ 1000): `{ players, content, hasMore }`, each list already in that order and carrying what its open queue does. The page counts **decisions**, so an incident five people reported takes one slot rather than five; grouping keys on `decisionGroupId`, never on the open incident key, since two incidents in one room instance decided a week apart are two entries. `hasMore` is `false` at the offset cap even when older rows exist, so the client is never pointed at a page it would be refused (R-MOD-15) |
| `PATCH` | `/api/moderation/reports/{report_id}` | moderator+ | Decides the **whole incident** the named report belongs to and answers with it: one note, one step-up, one action, every report of it resolved with its own reviewer, moment and audit entry (R-MOD-17). Any report of the incident reaches it. Review is one-way, so a report another moderator already decided answers `409` and nothing is written |
| `GET` | `/api/moderation/prompt-lists` | `{lists, waiting}` — publications the review switch is holding (R-LIST-13): under review **and public**, oldest first. **Not a report queue**: nothing was complained about, so a row carries the list, its owner, its `version` and how long it has waited, and no reporter, reason or evidence |
| `GET` | `/api/moderation/prompt-lists/{prompt_list_id}` | Every prompt in a held list — text, aliases, and each version's own `moderationState` — at the `version` being decided on. The queue carries a name and a count, and no other route can show a held list's words: the owner's route is the owner's, and the catalogue and room resolution exclude anything not active. **404** for a list that is not held, so this stays a reading surface for the queue rather than a staff window into private lists |
| `PATCH` | `/api/moderation/prompt-lists/{prompt_list_id}` | `{state: active \| hidden, note, expectedVersion}`. Releases a held list into the catalogue or takes it down. **409** for a list nobody held (or one its owner withdrew), and **409** when the list's version is no longer `expectedVersion`: an owner can edit a held list, every save is a new revision (R-LIST-05), and without the check a moderator could read one revision and release the next. Hiding tells the owner, as a takedown from a report does. Writes `prompt_list.review_active` / `prompt_list.review_hidden`, with the version decided on |
| `GET` | `/api/moderation/gallery` | moderator+ | `{review, waiting, candidates}` — This week's review queue (R-GAL-10): whether `gallery.shelf_review` is set, and while it is, the current Top-week drawings nobody has decided (the six This week would take and six behind them), each in the Gallery entry's shape. With the switch off nothing waits: the shelf is Top-week directly |
| `PATCH` | `/api/moderation/gallery/{turn_id}` | moderator+, step-up | `{decision: released \| hidden, note}` → `{turnId, decision, hidden}`. **Hidden** takes the drawing out of the Gallery, the shelf, its bytes route and its reaction door in one act and leaves the players' own history alone (R-GAL-09); **released** puts it back, and onto the shelf under the switch. One row per turn in `gallery_shelf_reviews`; audited as `gallery.review_{decision}` against the drawing with the drawer as the target account. The cached This week shelf is recomputed at once. Any kept drawing may be decided, held or not; `404` otherwise |
| `GET` | `/api/moderation/gallery/{turn_id}/drawing` | moderator+ | A **public** game's kept drawing, hidden from the Gallery or not, with the participant route's conditional handling: the queue has to show what it asks a decision about. Never a private game's — those are the players' own (R-HIST-16), the queue lists none, and a turn id is not a permission; `404` like every other refusal |
| `GET` | `/api/moderation/prompt-content-reports` | moderator+ | The queue as **incidents** keyed on the target, which already names one: `{ incidents, total, hasMore }`, `limit`/`offset` paging incidents. Each carries the target once (`targetType`, `listName`, `prompt`, `promptListId`, `promptVersionId`), `reporterCount`, the distinct `reasons`, `openedAt`/`latestReportedAt`, `reports` — each complaint's own reason, words and reporter — and the decision (`outcome`, `reviewedBy`, `resolutionNote`, `moderationState`, `reviewedAt`, `decisionGroupId`) |
| `PATCH` | `/api/moderation/prompt-content-reports/{report_id}` | moderator+ | A resolution chooses Active or Hidden; a dismissal cannot mutate content. Decides the **whole incident** — every pending complaint about that target — and answers with it: the content is hidden or left up once, under one note (R-MOD-10, R-MOD-17). `409` if any of it was already decided |
| `GET`/`POST` | `/api/moderation/bans` | moderator+ | Moderators cannot suspend peers; administrators cannot be targeted. With `reportId`, resolves that report's **whole incident** in the same transaction (`409` if any of it was already decided). The ban records the named report as `source_report_id`; the notice is read from the whole decision (R-BAN-08) |
| `POST` | `/api/moderation/bans/{ban_id}/revoke` | moderator+ | Preserves the historic record and reason |
| `POST` | `/api/moderation/warnings` | moderator+ | Formal warning; same role boundaries as a suspension, restricts nothing. With `reportId`, resolves that report's **whole incident** in the same transaction (`409` if any of it was already decided) |
| `GET` | `/api/reports/reviewed` | any signed-in | Whether any of the **caller's own** reports have been decided since they were last told: `{ count, reportIds }`, capped at 100. Read-only, asked on every page load, so the usual answer costs no write. It carries no outcome, no target and no time — what was decided is the reported player's business (R-MOD-20). The ids are the caller's own reports and exist so the acknowledgement can name exactly what a message was about |
| `POST` | `/api/reports/reviewed/acknowledge` | any signed-in | `{ reportIds }` → `{ ok, acknowledged }`. Stamps only those, and only where they are still the caller's own, still decided and still unannounced: the list is a client's account of what it displayed, never authority over a row. Sent **after** the message is shown, so a render that never happens marks nothing as told (R-MOD-20) |
| `GET` | `/api/warnings/pending` | any signed-in | The caller's own oldest unacknowledged warning, with the reported messages behind it — the `cited` lines of **every report the decision covered**, deduplicated and in the order they were said, never the context around them (R-MOD-12) — and `drawings`, each attached canvas by its metadata beside the `reportId` whose bytes serve it |
| `GET` | `/api/warnings/{warning_id}/drawings/{report_id}` | any signed-in | The bytes of one drawing behind the caller's **own** warning, in the current wire format; `404` for anyone else's, as acknowledging is, and for a report the warning's decision did not cover |
| `GET` | `/api/suspension/drawings/{report_id}` | the suspended account | The bytes of one drawing behind the caller's own **active** suspension. The one path beside the privacy escape hatch that the ban-time credential may reach: the refusal names them (`drawings` beside `messages` on the 403 body and the `account_suspended` event), and this is how the notice gets them. `404` when not suspended, or for a report the suspension's decision did not cover |
| `POST` | `/api/warnings/{warning_id}/acknowledge` | any signed-in | Own warnings only (`404` otherwise); records that the notice landed |
| `GET` | `/api/role-notices/pending` | any signed-in | The caller's own **newest** unacknowledged role-change notice. Newest rather than oldest: a role is one current fact, so an account promoted and then demoted while it was away is told once, correctly. An **offer** notice is served only while the offer still stands (`users.pending_role`, unlapsed): the row is a message and the column is the fact, and telling somebody a role is waiting when enrolment would grant nothing sends them to do a thing for no reason. `pendingRole` beside it is that fact, so one payload answers both what the account has still to be told and what is still waiting on it |
| `POST` | `/api/role-notices/{notice_id}/acknowledge` | any signed-in | Own notices only (`404` otherwise); settles that notice and every older one, since the account has just been shown where it stands |

### Bug reports — [`backend/app/api/bug_reports.py`](../backend/app/api/bug_reports.py)

Not a moderation surface: the queue is administrator-only, and a moderator gets the
same `404` as anybody else.

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/bug-reports` | any identity, guests included | One of ten `area` values and three `severity` values, ≤ 200-char `summary`, ≤ 4000-char `details`, ≤ 32 768 bytes `clientContext`, optional base64 `screenshot`. 5 per hour per client. Room, game and turn are resolved from the reporter's **live seat**, never from the `roomCode` sent |
| `GET` | `/api/admin/bug-reports` | administrator | The queue, newest first, optionally filtered by `status`. Screenshot **metadata** only |
| `GET` | `/api/admin/bug-reports/{report_id}/screenshot` | administrator | The raw bytes, `Cache-Control: private, no-store`; `404` once erased |
| `PATCH` | `/api/admin/bug-reports/{report_id}` | administrator | Review is one-way (`409` if already decided) and requires a note. Erases the screenshot in the same transaction |

A screenshot is validated rather than believed: real PNG or WebP magic bytes, ≤ 2 MB,
with byte size and SHA-256 re-derived server-side. Anything else is `422` — never a
silently dropped attachment.

Request bodies are capped before they are read at all
([`app/request_limits.py`](../backend/app/request_limits.py)): 512 KiB by default — sized against the largest
body the API declares, a 500-prompt list with aliases — 4 MiB for
`POST /api/bug-reports`, which is the one route that legitimately carries a
screenshot, and 256 KiB for `POST /api/users/me/avatar`, a 128 KiB picture in base64. An over-length `Content-Length` is answered `413` without invoking the
application; a body with no length, or a false one, is cut off as it streams and fails
its own validation. The `screenshot` field is separately bounded at its base64 length,
so an oversized image is refused before it is decoded.

`clientContext.route` is cut back to its path before it is stored, in the blob as well
as in the column lifted out of it. The client already sends a bare `location.pathname`,
but a query string is where invite codes and identifiers live, so the rule holds against
a client that is buggy or lying rather than resting on its promise.

### Operations — [`backend/app/api/operations.py`](../backend/app/api/operations.py), [`admin_settings.py`](../backend/app/api/admin_settings.py)

Administrator role required for all of these, checked per request and answered **404** to
anyone else (R-ROLE-01) by the shared gate in
[`api/admin_auth.py`](../backend/app/api/admin_auth.py). On the routes that carry a
body the gate is a **dependency**, not a call inside the handler: FastAPI validates a
body before the handler runs, so a gate awaited inside one would answer `422` to an
ordinary player who sent nonsense — confirming there was something there to process,
which is the one thing the 404 exists to refuse.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/admin/metrics`, `/api/admin/metrics/events` | The first carries the live counts and recorder state, then the process signals: `windowMinutes`, `http`, `socket` (rates, outcomes, p95, bytes in and out per minute before compression, and the eight heaviest commands and emitted events with their payload-size p50/p95/p99 since start), `process`, `database` (pool, statement latency, `errorsByCause` by SQLSTATE class, `poolWaitP95Ms`, `poolTimeouts` and `poolTimeoutsInWindow`, `topOperations` — the labelled operations with the most statement time and their p95 — `retries` keyed `operation:outcome`, `historyWriteP95Ms` and `historyPersistLagP95Seconds` (#892), `historyWritesAbandoned` by reason — `timeout` and `error` are staging losses, `conflict`, `exhausted` and `unreadable` are replay losses — `historyHandoff` with games staged and replay outcomes since start, last readiness probe), `drawingStore` (`totalBytes` and `rows` — what the stored drawings occupy, and the planner's row estimate rather than a count, the whole relation including TOAST and indexes, and `null` off PostgreSQL rather than a zero that would read as an empty store; R-OBS-14), `queues` (`mailOutbox` with `sweepSeconds`, `dataExports`, `finishedGames` with `failed` and `sweepSeconds` — the staged finished games of #541), `loops`, `retention` (one row per retained table: `overdueSeconds` against the `slaSeconds` it is held to, `backlogRows`, `sweepSeconds`, `exhausted`, `failed`, `removedTotal`, `failuresTotal` and the server's own `breached` verdict — decided once, so the page and the alert rule cannot disagree; empty until the retention loop has finished a pass, R-PRIV-17), and `series` — eight sixty-point per-minute arrays, oldest first, `null` where a minute recorded nothing. Rates and percentiles are over the trailing window |
| `GET` | `/api/admin/players/{user_id}/activity` | **Writes an audit event on every use** |
| `GET` | `/api/admin/audit` | |
| `GET` | `/api/admin/tunables` | Every runtime tunable with its value, default, bounds, unit, whether its values are whole, origin and purpose |
| `PATCH` | `/api/admin/tunables` | `{values?, reset?}`. **Writes one `config.changed` audit event per setting moved** |
| `GET` | `/api/admin/maintenance` | Whether this process is paused, draining, and its readiness |
| `POST` | `/api/admin/maintenance` | `{paused, reason?}`. **Writes `maintenance.paused` / `maintenance.resumed`** |
| `GET` | `/api/admin/prompt-list-review` | `{review}` — whether a list published from now on waits for a moderator (R-LIST-13) |
| `POST` | `/api/admin/prompt-list-review` | `{review, reason?}`. **Writes `prompt_lists.publication_review_changed`.** The lever that makes post-hoc moderation reversible without a release. **Not retroactive**: lists already published were published under the posture in force at the time |
| `GET` | `/api/admin/gallery-shelf-review` | `{review}` — whether the Gallery's **This week** waits for a moderator's release (R-GAL-10) |
| `POST` | `/api/admin/gallery-shelf-review` | `{review, reason?}`. **Writes `gallery.shelf_review`** (`app_config`) and audits `gallery.shelf_review_changed`. On, the shelf shows only released drawings and `GET /api/moderation/gallery` lists the candidates; the Gallery page publishes after the fact either way. The cached shelf is recomputed at once |
| `POST` | `/api/admin/shutdown` | `{reason, drainSeconds?}`, 0–300. **Writes `server.shutdown_requested`** |
| `GET` | `/api/admin/rooms` | Live rooms: code, state, phase, counts, and seats by id and nickname. No prompts, chat or canvas |
| `DELETE` | `/api/admin/rooms/{id}` | Close a room. **Writes `room.closed_by_admin`** |
| `DELETE` | `/api/admin/rooms/{id}/players/{playerId}` | Remove one seat. **Writes `room.player_kicked`** |
| `POST` | `/api/admin/rooms/{id}/end-turn` | End the drawing phase as its timer would. **Writes `room.turn_ended_by_admin`** |
| `GET` | `/api/admin/players?q=` | Find a registered account by part of its display name, or by a full id; a blank `q` lists who holds a role now. At most ten rows of `{id, displayName, nameColor, role, pendingRole}`. `pendingRole` is an offer still standing, so a promotion waiting on somebody's second factor is visible as a promotion rather than as nothing. **Writes no audit event** |
| `PATCH` | `/api/admin/players/{id}/role` | `{role, reason}`, `role` ∈ `user`/`moderator` → `{id, role, pendingRole}`. Granting a staff role to an account with no owner-proved second factor — no passkey, and no authenticator app whose password was proved — **offers** it instead of granting it (R-AUTH-20): `role` is unchanged, `pendingRole` names the offer, **`admin.role_offered`** is written, and nothing is revoked. Otherwise it grants outright — **writes `admin.role_changed`**, revokes every session, and clears any offer. Either way a `role_change_notices` row is recorded in the same transaction and `role_changed` is pushed to the account. Setting an account with a standing offer back to `user` **withdraws the offer**: it clears `pending_role`, writes **`admin.role_offer_withdrawn`**, settles the pending notice, pushes `role_changed` so a connected browser stops offering the enrolment, and touches neither the role nor the sessions — nothing about the account changed, so nothing may be taken from it and nobody may be told they are no longer a moderator about a role they never held. Setting the role an account already holds is otherwise a no-op |

`GET /api/admin/players` is the one read among those commands, and it writes nothing
to the ledger while `GET /api/admin/players/{id}/activity` writes a row on every use.
The line is what each answers. The activity view answers *how has this account
behaved*, which is a surveillance surface on the game's own players (R-AUDIT-05). The
search answers *which account is called this*, and returns nothing a room does not
already show everybody seated in it — a display name and the colour its owner chose —
plus the role about to change. An event per keystroke would also bury
`admin.role_changed` under hundreds of rows in an append-only record that exists to
make it findable. Nothing else is returned for the same reason: two players who chose
the same name are both listed and told apart by an id fragment, and an operator who
genuinely cannot tell which is which has the activity view, where that cost is
recorded.

Pausing refuses new rooms, game starts and restart votes while leaving live games
to finish, and leaves readiness alone — `/api/ready` keeps answering 200, because a
readiness failure invites an orchestrator to replace a container that is
deliberately still running. It survives a restart, since a pause is usually taken
*because* one is coming. A shutdown drain still runs normally from a paused process.

`POST /api/admin/shutdown` asks the *process* to stop rather than draining inside
the request. `begin_shutdown` is one-way and ends with the coordinator `stopped`;
running it from a handler would leave that state inside a process still listening,
and the genuine shutdown afterwards would find the drain already spent and cut off
the games it was meant to protect. So the endpoint signals, and the drain runs where
it runs for any other deploy ([`app/server.py`](../backend/app/server.py)). A
`drainSeconds` in the body is a one-shot window for this shutdown, not a change to
the setting. A deployment served without that runner answers **503** rather than
pretending, and a second request before the drain begins answers **409** — the
right to stop is claimed once, because `draining` is false for the whole gap
between asking and starting. Nothing in the API starts a server again.

`PATCH /api/admin/players/{id}/role` cannot grant `admin`: the first administrator
is created by the guarded server-side command ([`auth/admin.py`](../backend/app/auth/admin.py)),
which refuses once one exists, and minting more over the network would mean one
compromised session could mint them — the reasoning R-AUTH-14 applies to a remote
password reset. An administrator also cannot change their own role, or another
administrator's.

`PATCH /api/admin/tunables` is validated as a set and applied as a set: every value is
bounded server-side before any of them is written, so a request carrying several settings
either takes effect entirely or not at all. A value equal to what the process booted at is
not stored (see [`docs/database.md`](database.md) on the `tunable.` namespace), and a
value submitted unchanged is neither stored nor audited — a panel posting its whole form
must not bury the one change an operator made.

### Static delivery

When `frontend/dist` exists it is mounted on the same FastAPI app
([`backend/app/main.py`](../backend/app/main.py)). Vite's fingerprinted `/assets/` are
served `immutable` with a one-year lifetime, and `index.html` (including client-route
fallbacks) `no-cache`, so browsers discover new deployments promptly. Every text file
the build emits above 1 KiB - by extension: `js`, `css`, `html`, `svg`, `json`, `webmanifest`,
`txt` and `map` - has a Brotli (`.br`) and a gzip (`.gz`) copy beside it, and
the server answers with the best one `Accept-Encoding` admits — a coding given `q=0` is refused —
setting `Content-Encoding` and `Vary: Accept-Encoding`. The copy has its own `ETag`, so
a conditional request is answered against the bytes the client would receive — the copy is chosen before the validators are compared, so a 304 carries that copy's `ETag` and `Vary: Accept-Encoding`, never the identity file's (#978). A copy is served only when it is a regular file: a symlink, a directory or a FIFO wearing the `.br` name is ignored, and a copy asked for under its own name is a 404 whatever case the suffix is written in. A hard link is a regular file and is served like any other, which is why this is a shape check and not containment — write access to the build output is the boundary that matters, and a deploy that hardlinks its files keeps its compressed copies. Three things this deliberately does not do: a copy is not checked against its file's modification time (the build writes both in one step, and a mismatched pair is a broken build, not a request-time question), `Accept-Encoding: *` is read as naming no coding rather than all of them, and `identity;q=0` is not honoured - a client that refuses the stored bytes and accepts no coding is still served the stored bytes. Nothing
static is compressed per request ([`backend/app/compression.py`](../backend/app/compression.py), #978): a text file small enough that the build wrote no copy is served as it is stored, which also leaves every static representation the `ETag` its bytes were stored with.
Dynamic responses are gzipped at level 4. Images, fonts, audio and video never are,
because they are compressed formats already. A reverse proxy may take over compression,
but must keep the cache distinction and `Vary: Accept-Encoding`.

---

## 10. Rate limits

Persistent, shared-database buckets keyed on an HMAC-SHA-256 digest of the client
address under `IP_HASH_SECRET` — **raw IP addresses are never stored**
([`backend/app/auth/rate_limit.py`](../backend/app/auth/rate_limit.py)). Login is the
exception to "keyed on the address": it is counted against three keys at once, and the
account key is an HMAC of the lowercased username rather than of an address
([`backend/app/auth/login_guard.py`](../backend/app/auth/login_guard.py), R-RATE-12).

| Variable | Default | Applies to |
| --- | --- | --- |
| `AUTH_LOGIN_LIMIT` | 10 / 5 min | `POST /api/auth/login`, keyed on the **address**; failures only |
| `AUTH_LOGIN_ACCOUNT_LIMIT` | 10 / 15 min | The same route keyed on the **account** — the key a distributed attack cannot dodge (R-RATE-12); failures only |
| `AUTH_LOGIN_GLOBAL_LIMIT` | 500 / 5 min | The same route for the whole deployment; failures only. `0` switches it off — it is the one bucket an attacker can saturate on purpose (N-17) |
| `AUTH_SECOND_FACTOR_LIMIT` | 20 / 15 min | The `/api/auth/second-factor/*` and `/api/auth/step-up` routes |
| `AUTH_REGISTER_LIMIT` | 10 / hour | `POST /api/auth/register` |
| `AUTH_LOOKUP_LIMIT` | 60 / min | Name availability and display-name changes |
| `AUTH_RESET_LIMIT` | 5 / hour | `POST /api/auth/password/forgot` |
| `AUTH_RESET_CHECK_LIMIT` | 30 / hour | `POST /api/auth/password/reset/check` |
| `AUTH_RESET_PERFORM_LIMIT` | 10 / hour | `POST /api/auth/password/reset` — the leg that hashes, so a stolen or guessed link cannot be used to keep the hashing pool busy (#975) |
| `AUTH_PASSWORD_CHANGE_LIMIT` | 10 / hour | `POST /api/auth/password/change` |
| `AUTH_VERIFY_LIMIT` | 10 / hour | `PUT /api/auth/email` |

Lower-risk profile and prompt-statistics throttles remain process-local.

Limits are keyed on the *connecting* address. Behind a reverse proxy or tunnel every
request arrives from the proxy, so production must run with `PROXY_HEADERS=1` and
`FORWARDED_ALLOW_IPS=<proxy address>`. Without that trusted-proxy configuration
`X-Forwarded-For` is **ignored on purpose**: it is attacker-controlled, and trusting it
blindly would let a password-guesser sidestep the limit by varying it per attempt.

---

## 11. Versioning and change rules

| Version constant | Governs | Bump when |
| --- | --- | --- |
| `PROTOCOL_VERSION` (41) | The socket handshake: which commands, events and payload keys both ends agree on (§1) | A command or event is added, removed or renamed, or a payload's shape changes. Both ends deploy together |
| `LIVE_DRAWING_VERSION` (1) | The live `draw` frame | An existing frame layout changes. A new tag under the same version is an addition (tags 6, 7 and 8 were), covered by the `PROTOCOL_VERSION` bump. Both ends deploy together |
| `CANVAS_HISTORY_VERSION` (1) | `SKCH` | The history layout changes |
| Stored `(magic, version)` | A durable drawing blob | **Add** a decoder; never remove one |
| `SCORING_RULES_VERSION` (1) | Any constant or algorithm that can change a score | Any such change; every completed game freezes its rule snapshot |
| `GAME_RULE_SNAPSHOT_VERSION` (1) | The stored rule-snapshot JSON contract | The snapshot's *shape* changes |
| `score_ledger_version` | The score-event ledger contract | The ledger's semantics change |
| `contractVersion` on `server_shutdown` (1) | The shutdown notice | The notice's shape changes |
| `contractVersion` on `server_paused` (1) | The maintenance-pause notice | The notice's shape changes |
| `contractVersion` on `client_config` (5) | The client-cadence notice | A cadence is added, removed or renamed |
| Data export `schema_version` (11) | The export document, pinned by [`fixtures/account_data_export_v11_fields.json`](../fixtures/account_data_export_v11_fields.json) | The export's field surface changes |

### The contract as a document

Names are not the contract. `tests/test_wire_contract.py` proves both ends use the same
event names and payload keys, and that is all it can prove: a key can move from one
event to another, a field can change type or stop being required, a tuple can swap two
positions, a binary layout can change under the same tag, and the union of names is
unchanged. So [`backend/app/wire_contract.py`](../backend/app/wire_contract.py) builds
the contract as **one document** and
[`fixtures/wire_contract.json`](../fixtures/wire_contract.json) is that document as last
committed (#567):

- every client command with the JSON Schema of its payload model — types, bounds,
  aliases, required fields — or, for the three hand-written parsers (`draw`,
  `request_sync_strokes`, `undo_stroke`), a declared positional layout; the rate class
  it spends; whether it answers;
- every server event, with a declared positional layout for the tuple-shaped ones
  (`draw`, `canvas_commit`, `canvas_undo`, `sync_strokes`,
  `sync_strokes_tail`, `request_canvas_actions`) and, for object payloads, the camelCase
  keys each payload-building function writes — attributed to the function, so a key
  moving between builders is a difference;
- the refusal codes (§2), every version constant above that travels on the socket, the
  live-drawing frame constants, and a SHA-256 of each cross-language fixture, so a
  byte-level layout example cannot change under the same tag unnoticed.

[`scripts/check-wire-contract.py`](../scripts/check-wire-contract.py) regenerates the
fixture (`--write`), refuses a stale one, and with `--base <ref>` diffs the tree's contract
against the fixture **at that revision** — CI passes the pull request's base. Comparing
against the base rather than the working tree is what makes regenerating the fixture
under the same number visible: the fixture can be rewritten, the base cannot.
[`backend/tests/test_wire_contract_baseline.py`](../backend/tests/test_wire_contract_baseline.py)
pins that a type change, a key relocation, a tuple reorder and a same-tag fixture change
each move the document, that a bump makes any change acceptable, and that the fixture
matches the tree and the §5 table lists exactly the events extracted.

**What the document cannot see, and review must:** a change of *meaning* under an
identical shape (a field that now holds something else), and privacy — a key that is
still named but now carries what it must not. The document is a floor for review, not a
proof of compatibility.

### Before the first deployment

**Nothing is deployed yet, so nothing needs a compatibility story.** Until this
service runs somewhere with users on it, every version constant above is free
to change without a migration path, a decoder for the old shape, or a bump at
all: there is no client in the wild speaking the old protocol, and no database
holding rows written by it. A schema may be rewritten rather than migrated; an
export format may be replaced rather than dual-read; a payload may change shape
under a version number that stays put.

For the socket contract this is made explicit rather than left as a contradiction
with §1's bump rule: **the development policy is regenerate and commit.** Every
wire change regenerates `fixtures/wire_contract.json` in the same commit, so the
change is a reviewable diff; CI fails a stale fixture and *warns* on a contract
that differs from the base branch under the same `PROTOCOL_VERSION`. Bumping is
still worth doing where it costs a line, because a stale tab open across a
rebuild is told to reload rather than left silently broken - and, since #476,
refused everything and closed if it does not - but it is a development
convenience for now, not a contract with anybody, and there is no N/N−1
support: a mismatch means reload, never a second code path. That last rule is
not a pre-launch exception; it is the deployment model (§1, §9): one
same-origin deployment, both ends change together, and a rollback is just a
deploy whose number is lower - the tab reloads onto it the same way.

What changes at launch: every rule below starts applying, the CI step gains
`--enforce` (an unbumped contract change fails), and `docs/database.md`'s
"Pre-v1 note" stops being an option. **In the same change, reset `PROTOCOL_VERSION`
to 1 on both sides** (and the other on-wire `contractVersion` constants likewise):
the numbers accumulated before launch counted development rebuilds, not deployed
protocols, and nothing in the wild speaks any of them. Regenerate the contract
fixture with the reset. Delete this section then, rather than leaving it to be read
as still true.

**Checklist for any wire change:**

1. Change the server (handler, payload model, presenter). A new command is added to
   `COMMAND_PAYLOADS` in `backend/app/wire_contract.py` with the model it parses; a new
   tuple-shaped event to `TUPLE_EVENTS`.
2. Change the client (`frontend/src/types.ts`, the listener, the emitter).
3. Update the fixture if the binary formats moved
   (`fixtures/canvas_protocol_v1.json`).
4. Regenerate the contract: `backend/.venv/bin/python scripts/check-wire-contract.py --write`,
   and read the diff of `fixtures/wire_contract.json` as the review of the change.
5. Run `backend/.venv/bin/pytest tests/test_wire_contract.py tests/test_wire_contract_baseline.py`.
6. Update **this document** — §5's table must list the event — and
   [`../GLOSSARY.md`](../GLOSSARY.md) if a player-visible name changed.
