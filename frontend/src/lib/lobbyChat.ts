/** The lobby's chat: the lines the client holds, and the rules it applies.

Kept out of the component for the reason `lobbyPresence.ts` gives: the unit
tests run on bare `node:test`, so everything here is a pure function over
plain objects.

Chat rides the lobby channel but is not a feed of it. Presence and the room
list are *state*, rebuilt by the server on a tick and numbered with a revision
that a gap in means a resync. A chat line is an event: it goes out the moment
it is said, and a gap in its numbering is expected rather than a fault - a
line is deliberately not delivered to somebody who blocked its author. So
`seq` here is used for one thing only: putting the backlog an acknowledgement
hands over and the lines that beat it into one order without a duplicate. A
line numbered at or below what is held is one we have; nothing ever asks for a
resync because of it. */
import { formatClock, type TimeFormat } from "./clock.ts";


export interface LobbyChatLine {
  seq: number;
  userId: string;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  text: string;
  /** The server's instant, as epoch milliseconds. Rendered, never sorted by. */
  sentAt: number;
  /** Present only when retention took the row - the id a report can cite. */
  retainedMessageId?: string;
}

export interface LobbyChatState {
  /** The highest sequence number seen, held or not. Zero before any. */
  lastSeq: number;
  lines: LobbyChatLine[];
  /** Which server process numbered these lines (`chatEpoch`), so a later
  `watch_lobby` can ask only for newer ones - and only of the same process. */
  epoch: string | null;
  /** The account these lines were filtered for. Another account's blocks
  differ, so its lobby asks for everything and replaces them. */
  owner: string | null;
}

export const EMPTY_LOBBY_CHAT: LobbyChatState = {
  lastSeq: 0,
  lines: [],
  epoch: null,
  owner: null,
};

/** More than the server hands an arrival, so a long-open lobby keeps some of
what it watched go by; bounded so it never grows with the evening. */
export const MAX_HELD_LINES = 200;

/** One line, or null if the server sent something this build cannot read. */
export function parseLine(value: unknown): LobbyChatLine | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.seq !== "number" || !Number.isInteger(row.seq) || row.seq < 1) return null;
  if (typeof row.userId !== "string" || !row.userId) return null;
  if (typeof row.displayName !== "string") return null;
  if (typeof row.text !== "string") return null;
  // Whole seconds since the epoch (#885).
  if (typeof row.sentAt !== "number" || !Number.isFinite(row.sentAt)) return null;
  const sentAt = row.sentAt * 1000;
  const line: LobbyChatLine = {
    seq: row.seq,
    userId: row.userId,
    displayName: row.displayName,
    nameColor: typeof row.nameColor === "string" ? row.nameColor : null,
    isAnonymous: row.isAnonymous === true,
    text: row.text,
    sentAt,
  };
  if (typeof row.retainedMessageId === "string" && row.retainedMessageId) {
    line.retainedMessageId = row.retainedMessageId;
  }
  return line;
}

function capped(lines: LobbyChatLine[]): LobbyChatLine[] {
  return lines.length > MAX_HELD_LINES ? lines.slice(lines.length - MAX_HELD_LINES) : lines;
}

/** Append one line, unless it is one we hold or cannot read.

Returns the state it was given when there is nothing to do, so a store can
tell a no-op from a change by reference. */
export function applyChatLine(state: LobbyChatState, payload: unknown): LobbyChatState {
  return append(state, parseLine(payload));
}

function append(state: LobbyChatState, line: LobbyChatLine | null): LobbyChatState {
  if (!line || line.seq <= state.lastSeq) return state;
  return { ...state, lastSeq: line.seq, lines: capped([...state.lines, line]) };
}

function parseBacklog(payload: unknown): {
  lines: LobbyChatLine[];
  chatSeq: number;
  epoch: string | null;
} {
  if (!payload || typeof payload !== "object") return { lines: [], chatSeq: 0, epoch: null };
  const answer = payload as Record<string, unknown>;
  const lines = Array.isArray(answer.chat)
    ? answer.chat.map(parseLine).filter((line): line is LobbyChatLine => line !== null)
    : [];
  lines.sort((a, b) => a.seq - b.seq);
  const chatSeq =
    typeof answer.chatSeq === "number" && Number.isInteger(answer.chatSeq) && answer.chatSeq >= 0
      ? answer.chatSeq
      : 0;
  const epoch = typeof answer.chatEpoch === "string" && answer.chatEpoch ? answer.chatEpoch : null;
  return { lines, chatSeq, epoch };
}

/** What a `watch_lobby` sends about the chat it already holds (#885).

The last number seen and the numbering it belongs to, so the server sends only
newer lines - on a resync, on a reconnect to the same process, and when a
visitor naming themselves re-handshakes the socket. Nothing when there is
nothing to resume, or when the lines were filtered for another account. */
export function chatResumeRequest(
  state: LobbyChatState,
  owner: string | null,
): { chatSince: number; chatEpoch: string } | Record<string, never> {
  if (!state.epoch || state.lastSeq === 0 || state.owner !== owner) return {};
  return { chatSince: state.lastSeq, chatEpoch: state.epoch };
}

/** Take the backlog a `watch_lobby` acknowledgement carries, for *owner*.

Merged when it continues what is held - the same process, and lines filtered
for the same account - so a lobby left open all evening keeps what it watched
go by rather than being cut back to the fifty the server keeps, and a resumed
answer, which holds only the newer lines, adds to them. Replaced otherwise: the
numbers held belong to a sequence that no longer exists, or to somebody else's
blocks, and what the server hands over is all there is. */
export function applyChatBacklog(
  state: LobbyChatState,
  payload: unknown,
  owner: string | null,
): LobbyChatState {
  const { lines, chatSeq, epoch } = parseBacklog(payload);
  if (!epoch || epoch !== state.epoch || owner !== state.owner) {
    const last = lines.length ? lines[lines.length - 1].seq : 0;
    return { lastSeq: Math.max(chatSeq, last), lines: capped(lines), epoch, owner };
  }
  let next = state;
  for (const line of lines) next = append(next, line);
  if (chatSeq > next.lastSeq) next = { ...next, lastSeq: chatSeq };
  return next;
}

/** Whether this viewer may report this line from the lobby.

A line is reported over REST, citing its retained row, because the lobby has
no seat for the socket route to resolve. So there has to be a row to cite: a
line retention withheld is shown like any other and simply offers nothing,
rather than a dialog that would be refused on sending. The other two rules
are the room's: nobody reports themselves, and a guest is offered no control
because a report a moderator cannot follow up on helps nobody (R-MOD-06). */
export function reportableLine(
  line: LobbyChatLine,
  viewer: { id: string; isAnonymous: boolean } | null | undefined,
): boolean {
  if (!viewer || viewer.isAnonymous) return false;
  if (line.userId === viewer.id) return false;
  return Boolean(line.retainedMessageId);
}

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

function localMidnight(at: number): number {
  const date = new Date(at);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** The small label beside a line: how fresh it is, at a glance.

Fresh lines say how long ago, because that is the question - is anybody
still here? A line from earlier today says when, because "six hours ago"
is arithmetic the reader would do anyway. Older than that, the day is all
that matters. A clock behind the server's reads as "now" rather than as a
line from the future. */
export function chatTimeLabel(
  sentAt: number,
  now: number,
  timeFormat: TimeFormat = "system",
): string {
  const age = now - sentAt;
  if (age < MINUTE_MS) return "now";
  if (age < HOUR_MS) return `${Math.floor(age / MINUTE_MS)}m`;
  const today = localMidnight(now);
  const thatDay = localMidnight(sentAt);
  if (thatDay === today) {
    return formatClock(new Date(sentAt), timeFormat);
  }
  const days = Math.round((today - thatDay) / DAY_MS);
  return days <= 1 ? "yesterday" : `${days}d`;
}
