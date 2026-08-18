import type { AckResponse, RoomPreviewResponse, RoomSummary } from "../types";

/** Keep in sync with backend/app/auth/names.py. Guest nicknames and account
 * usernames share one rule, so a guest name can be claimed as a username. */
export const MAX_NICKNAME_LENGTH = 16;
export const MIN_NICKNAME_LENGTH = 3;
export const NICKNAME_PATTERN = /^[a-zA-Z0-9_-]{3,16}$/;
export const NICKNAME_RULE_MESSAGE =
  "Use 3-16 characters: letters, numbers, hyphens or underscores. No spaces.";
const RESERVED_NICKNAMES = new Set(["guest", "system", "admin", "sketchy", "server", "you"]);

/** Mirrors the server rule so the form can object before a round trip. */
export function nicknameError(value: string): string | null {
  const trimmed = value.trim();
  if (!NICKNAME_PATTERN.test(trimmed)) return NICKNAME_RULE_MESSAGE;
  if (RESERVED_NICKNAMES.has(trimmed.toLowerCase())) {
    return "That name is reserved. Please choose another.";
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
  /** Rejoin an existing seat; the session cookie identifies the player. */
  reconnect: (args: { code: string; nickname: string }) => Promise<AckResponse>;
  preview: (code: string) => Promise<RoomPreviewResponse>;
  join: (args: {
    code: string;
    nickname: string;
    mode: RoomJoinMode;
  }) => Promise<AckResponse>;
  saveNickname: (nickname: string) => void;
  acceptSession: (session: RoomSession) => void;
  requestErrorMessage: (error: unknown, action: string) => string;
}

type Listener = (snapshot: RoomEntrySnapshot) => void;

function sessionFrom(response: AckResponse): RoomSession | null {
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
      // Always attempt a rejoin: the session cookie is sent automatically, so
      // the server can tell whether this account already holds a seat here.
      // Anyone without one simply falls through to the invite preview.
      const rejoin = await this.dependencies.reconnect({
        code: this.code,
        nickname: this.snapshot.nicknameInput,
      });
      if (!this.isCurrent(version)) return;
      const existing = sessionFrom(rejoin);
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
          state: { status: "error", message: response.error || "This room is no longer available" },
        });
      }
    } catch (error) {
      if (!this.isCurrent(version)) return;
      this.publish({
        ...this.snapshot,
        state: { status: "error", message: this.dependencies.requestErrorMessage(error, "load this room") },
      });
    }
  }

  async join(mode: RoomJoinMode): Promise<void> {
    const current = this.snapshot.state;
    if (current.status !== "preview") return;

    const nickname = this.snapshot.nicknameInput.trim();
    const invalid = nickname ? nicknameError(nickname) : "Enter a nickname to continue.";
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
        this.dependencies.saveNickname(nickname);
        this.dependencies.acceptSession(session);
        return;
      }

      const room = mode === "player" && response.error === "Room is full"
        ? { ...current.room, isFull: true }
        : current.room;
      const error = mode === "player" && response.error === "Room is full"
        ? "The player slots just filled up, but you can still spectate."
        : response.error || "Could not join this room";
      this.publish({
        ...this.snapshot,
        state: { status: "preview", room, notice: current.notice, error },
      });
    } catch (error) {
      if (!this.isCurrent(version)) return;
      const action = mode === "spectator" ? "join as a spectator" : "join this room";
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
