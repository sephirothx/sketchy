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
  /** Hidden by a moderator (#1435): shown as "This message was deleted",
      and the server sends no text for it. */
  hidden?: boolean;
  /** The server's visibility count when this line was last hidden or shown
      again; absent for one never touched. A change is applied only if it is
      newer, whichever order changes and backlogs arrive in. */
  visibility?: number;
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
  /** How many hides and show-agains this process announced that these lines
  reflect (#1435): a returning lobby sends it, and one behind is handed the
  whole backlog to replace them with. */
  visibility: number;
}

export const EMPTY_LOBBY_CHAT: LobbyChatState = {
  lastSeq: 0,
  lines: [],
  epoch: null,
  owner: null,
  visibility: 0,
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
  if (row.hidden === true) {
    line.hidden = true;
    line.text = "";
  }
  if (typeof row.visibility === "number" && Number.isSafeInteger(row.visibility) && row.visibility > 0) {
    line.visibility = row.visibility;
  }
  return line;
}

/** A moderator hid a line or showed it again (#1435): the line we hold is
    replaced where it stands, by the id that names it everywhere. Hidden, its
    words go even from memory; shown again, they come back with the event.
    The same state back when we do not hold it, or it already says so, so
    nothing re-renders for it. */
export function applyLineVisibility(state: LobbyChatState, payload: unknown): LobbyChatState {
  if (!payload || typeof payload !== "object") return state;
  const event = payload as Record<string, unknown>;
  if (typeof event.retainedMessageId !== "string" || typeof event.hidden !== "boolean") return state;
  const hidden = event.hidden;
  const at = typeof event.visibility === "number" ? event.visibility : 0;
  const text = typeof event.text === "string" ? event.text : null;
  // Shown again with no words: this viewer muted its author and holds no
  // line of theirs. Only the count moves, so a resync does not take the
  // change for one it missed.
  if (!hidden && text === null) {
    return at > state.visibility ? { ...state, visibility: at } : state;
  }
  let changed = false;
  const lines = state.lines.map((line) => {
    if (line.retainedMessageId !== event.retainedMessageId) return line;
    // Per line, not one count for all: an older change to this line arriving
    // late must not undo a newer one, and a late change to another line must
    // still land.
    if ((line.visibility ?? 0) >= at && at > 0) return line;
    changed = true;
    if (hidden) return { ...line, hidden: true, text: "", visibility: at };
    const shown: LobbyChatLine = { ...line, text: text as string, visibility: at };
    delete shown.hidden;
    return shown;
  });
  const visibility = Math.max(state.visibility, at);
  if (!changed) return visibility === state.visibility ? state : { ...state, visibility };
  return { ...state, lines, visibility };
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
  visibility: number;
  replace: boolean;
} {
  if (!payload || typeof payload !== "object") {
    return { lines: [], chatSeq: 0, epoch: null, visibility: 0, replace: false };
  }
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
  const visibility =
    typeof answer.chatVisibility === "number" && Number.isSafeInteger(answer.chatVisibility) && answer.chatVisibility >= 0
      ? answer.chatVisibility
      : 0;
  return { lines, chatSeq, epoch, visibility, replace: answer.chatReplace === true };
}

/** What a `watch_lobby` sends about the chat it already holds (#885).

The last number seen and the numbering it belongs to, so the server sends only
newer lines - on a resync, on a reconnect to the same process, and when a
visitor naming themselves re-handshakes the socket. Nothing when there is
nothing to resume, or when the lines were filtered for another account. */
export function chatResumeRequest(
  state: LobbyChatState,
  owner: string | null,
): { chatSince: number; chatEpoch: string; chatVisibility: number } | Record<string, never> {
  if (!state.epoch || state.lastSeq === 0 || state.owner !== owner) return {};
  return { chatSince: state.lastSeq, chatEpoch: state.epoch, chatVisibility: state.visibility };
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
  const { lines, chatSeq, epoch, visibility, replace } = parseBacklog(payload);
  // Replaced, too, when the server says a hide or show-again was missed
  // (#1435): the lines held may be showing words since hidden, or a
  // placeholder since lifted, and only the backlog is known to be right.
  if (replace || !epoch || epoch !== state.epoch || owner !== state.owner) {
    const last = lines.length ? lines[lines.length - 1].seq : 0;
    // A line held with a newer change than the backlog's keeps it: the
    // change reached this tab after the backlog was read (#1435).
    const newer = new Map(
      replace && epoch === state.epoch
        ? state.lines.filter((line) => line.retainedMessageId).map((line) => [line.retainedMessageId, line])
        : [],
    );
    const kept = lines.map((line) => {
      const held = line.retainedMessageId ? newer.get(line.retainedMessageId) : undefined;
      return held && (held.visibility ?? 0) > (line.visibility ?? 0)
        ? { ...line, hidden: held.hidden, text: held.text, visibility: held.visibility }
        : line;
    });
    return {
      lastSeq: Math.max(chatSeq, last),
      lines: capped(kept),
      epoch,
      owner,
      visibility: Math.max(visibility, replace && epoch === state.epoch ? state.visibility : 0),
    };
  }
  let next = state;
  for (const line of lines) next = append(next, line);
  if (chatSeq > next.lastSeq) next = { ...next, lastSeq: chatSeq };
  if (visibility > next.visibility) next = { ...next, visibility };
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
  // Already hidden by a moderator: there is nothing left to show them (#1435).
  if (line.hidden) return false;
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
