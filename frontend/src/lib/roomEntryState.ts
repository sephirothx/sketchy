import type { AckResponse, RoomPreviewResponse, RoomSummary } from "../types";
import { refusalText } from "./refusals.ts";
import { ui } from "../content/ui/index.ts";

/** Keep in sync with backend/app/auth/names.py. Guest nicknames and account
 * usernames share one rule, so a guest name can be claimed as a username. */
export const MAX_NICKNAME_LENGTH = 16;
export const MIN_NICKNAME_LENGTH = 3;
export const NICKNAME_PATTERN = /^[a-zA-Z0-9_-]{3,16}$/;
const RESERVED_NICKNAMES = new Set(["guest", "system", "admin", "sketchy", "server", "you"]);

/** One character a name may hold: the pattern above, a character at a time. */
const NICKNAME_CHARACTER = /^[a-zA-Z0-9_-]$/;

/**
 * What a name field holds after an edit: the characters the name rule allows,
 * in order, no more than `MAX_NICKNAME_LENGTH`, and where the caret belongs.
 *
 * Anything else is simply not entered, however it arrived - typed, pasted,
 * dropped or composed. A space too: "Jo Jo" pasted becomes "JoJo", the same
 * as typing it, where the space key does nothing. Turning it into "Jo_Jo"
 * would put a character in the name that nobody typed, and an underscore for
 * a space is a rule a player would have to know.
 *
 * `caret` is where the caret was in the raw value; it comes back counting only
 * the characters kept before it, so it stays after what was just typed rather
 * than jumping to the end. Past the length limit it is the characters just
 * inserted - those before the caret - that give way, as with `maxLength`,
 * rather than the end of a name that was already there.
 */
export function keepNameCharacters(raw: string, caret: number = raw.length): { value: string; caret: number } {
  let kept = "";
  let keptBeforeCaret = 0;
  for (let index = 0; index < raw.length; index += 1) {
    const character = raw[index];
    if (!NICKNAME_CHARACTER.test(character)) continue;
    kept += character;
    if (index < caret) keptBeforeCaret = kept.length;
  }
  const excess = kept.length - MAX_NICKNAME_LENGTH;
  if (excess <= 0) return { value: kept, caret: keptBeforeCaret };
  if (keptBeforeCaret < excess) {
    const value = kept.slice(0, MAX_NICKNAME_LENGTH);
    return { value, caret: Math.min(keptBeforeCaret, value.length) };
  }
  return {
    value: kept.slice(0, keptBeforeCaret - excess) + kept.slice(keptBeforeCaret),
    caret: keptBeforeCaret - excess,
  };
}

/**
 * What of an insertion - a key, a paste, a drop - may go into a name field:
 * its allowed characters, no more than the `room` the field has left.
 * `keepNameCharacters`' rule for one piece of text, used before the browser
 * inserts it, so a refused character is never entered at all and the field's
 * own undo history stays whole.
 */
export function nameCharactersToInsert(data: string, room: number): string {
  let kept = "";
  for (const character of data) {
    if (kept.length >= room) break;
    if (NICKNAME_CHARACTER.test(character)) kept += character;
  }
  return kept;
}

/** Mirrors the server rule so the form can object before a round trip. */
export function nicknameError(value: string): string | null {
  const trimmed = value.trim();
  if (!NICKNAME_PATTERN.test(trimmed)) return ui.roomEntryState.nicknameRule;
  if (RESERVED_NICKNAMES.has(trimmed.toLowerCase())) {
    return ui.roomEntryState.thatNameIsReservedPlease;
  }
  return null;
}

export type RoomJoinMode = "player" | "spectator";

export type RoomEntryState =
  | { status: "loading" }
  | { status: "preview"; room: RoomSummary; notice?: string; error?: string }
  | { status: "joining"; room: RoomSummary; mode: RoomJoinMode; notice?: string }
  | { status: "error"; message: string };

export interface RoomSession {
  roomId: string;
  code: string;
  playerId: string;
}

export interface RoomEntrySnapshot {
  state: RoomEntryState;
  nicknameInput: string;
}

export interface RoomEntryDependencies {
  /** Reconnect to an existing seat; the session cookie identifies the player. */
  reconnect: (args: { code: string; nickname: string }) => Promise<AckResponse>;
  preview: (code: string) => Promise<RoomPreviewResponse>;
  join: (args: {
    code: string;
    nickname: string;
    mode: RoomJoinMode;
  }) => Promise<AckResponse>;
  acceptSession: (session: RoomSession) => void;
  requestErrorMessage: (error: unknown, action: string) => string;
}

type Listener = (snapshot: RoomEntrySnapshot) => void;

/** The four fields that together make an ack a usable seat, checked once. */
export function sessionFrom(response: AckResponse): RoomSession | null {
  if (!response.ok || !response.roomId || !response.code || !response.playerId) {
    return null;
  }
  return {
    roomId: response.roomId,
    code: response.code,
    playerId: response.playerId,
  };
}

/** Framework-independent owner for invite preview, reconnect, and join transitions. */
export class RoomEntryMachine {
  private readonly code: string;
  private readonly dependencies: RoomEntryDependencies;
  private snapshot: RoomEntrySnapshot;
  private listener: Listener | null = null;
  private requestVersion = 0;
  private disposed = false;

  constructor(code: string, nickname: string, dependencies: RoomEntryDependencies) {
    this.code = code;
    this.dependencies = dependencies;
    this.snapshot = { state: { status: "loading" }, nicknameInput: nickname };
  }

  getSnapshot(): RoomEntrySnapshot {
    return this.snapshot;
  }

  subscribe(listener: Listener): () => void {
    this.listener = listener;
    listener(this.snapshot);
    return () => {
      if (this.listener === listener) this.listener = null;
    };
  }

  setNicknameInput(nicknameInput: string): void {
    const state = this.snapshot.state;
    this.publish({
      nicknameInput,
      state: state.status === "preview" ? { ...state, error: undefined } : state,
    });
  }

  async load(): Promise<void> {
    const version = ++this.requestVersion;
    this.publish({ ...this.snapshot, state: { status: "loading" } });

    try {
      // Always attempt a reconnect: the session cookie is sent automatically, so
      // the server can tell whether this account already holds a seat here.
      // Anyone without one simply falls through to the invite preview.
      const reconnectResponse = await this.dependencies.reconnect({
        code: this.code,
        nickname: this.snapshot.nicknameInput,
      });
      if (!this.isCurrent(version)) return;
      const existing = sessionFrom(reconnectResponse);
      if (existing) {
        this.dependencies.acceptSession(existing);
        return;
      }

      const response = await this.dependencies.preview(this.code);
      if (!this.isCurrent(version)) return;
      if (response.ok && response.room) {
        this.publish({ ...this.snapshot, state: { status: "preview", room: response.room } });
      } else {
        this.publish({
          ...this.snapshot,
          state: {
            status: "error",
            message: response.errorCode === "room_ended"
              ? ui.roomEntryState.thisRoomHasEndedAsk
              : refusalText(response, ui.roomEntryState.thisRoomNoLongerAvailable),
          },
        });
      }
    } catch (error) {
      if (!this.isCurrent(version)) return;
      this.publish({
        ...this.snapshot,
        state: { status: "error", message: this.dependencies.requestErrorMessage(error, ui.roomEntryState.loadThisRoom) },
      });
    }
  }

  async join(mode: RoomJoinMode): Promise<void> {
    const current = this.snapshot.state;
    if (current.status !== "preview") return;

    const nickname = this.snapshot.nicknameInput.trim();
    const invalid = nickname ? nicknameError(nickname) : ui.roomEntryState.enterANicknameToContinue;
    if (invalid) {
      this.publish({
        ...this.snapshot,
        state: { ...current, error: invalid },
      });
      return;
    }

    const version = ++this.requestVersion;
    this.publish({
      ...this.snapshot,
      state: { status: "joining", room: current.room, mode, notice: current.notice },
    });

    try {
      const response = await this.dependencies.join({ code: this.code, nickname, mode });
      if (!this.isCurrent(version)) return;
      const session = sessionFrom(response);
      if (session) {
        this.dependencies.acceptSession(session);
        return;
      }

      const justFilled = mode === "player" && response.errorCode === "room_full";
      const room = justFilled ? { ...current.room, isFull: true } : current.room;
      const error = justFilled
        ? ui.roomEntryState.theLastPlayerSeatWasTaken
        : refusalText(response, ui.roomEntryState.couldNotJoinThisRoom);
      this.publish({
        ...this.snapshot,
        state: { status: "preview", room, notice: current.notice, error },
      });
    } catch (error) {
      if (!this.isCurrent(version)) return;
      const action = mode === "spectator" ? ui.roomEntryState.joinAsASpectator : ui.roomEntryState.joinThisRoom;
      this.publish({
        ...this.snapshot,
        state: {
          status: "preview",
          room: current.room,
          notice: current.notice,
          error: this.dependencies.requestErrorMessage(error, action),
        },
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.requestVersion += 1;
    this.listener = null;
  }

  private isCurrent(version: number): boolean {
    return !this.disposed && version === this.requestVersion;
  }

  private publish(snapshot: RoomEntrySnapshot): void {
    if (this.disposed) return;
    this.snapshot = snapshot;
    this.listener?.(snapshot);
  }
}
