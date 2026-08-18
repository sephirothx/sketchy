import type { AckResponse, RoomPreviewResponse, RoomSummary } from "../types";

/** Keep in sync with backend/app/handlers/payloads.py MAX_NICKNAME_LENGTH. */
export const MAX_NICKNAME_LENGTH = 16;

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
  if (
    !response.ok
    || !response.roomId
    || !response.code
    || !response.playerId
  ) return null;
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
      const response = await this.dependencies.preview(this.code);
      if (!this.isCurrent(version)) return;
      if (response.ok && response.room) {
        this.publish({ ...this.snapshot, state: { status: "preview", room: response.room, notice: undefined } });
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
        state: {
          status: "error",
          message: this.dependencies.requestErrorMessage(error, "load room preview"),
        },
      });
    }
  }

  async join(mode: RoomJoinMode): Promise<void> {
    if (this.snapshot.state.status !== "preview") return;

    const trimmedNickname = this.snapshot.nicknameInput.trim();
    if (!trimmedNickname) {
      this.publish({
        ...this.snapshot,
        state: {
          ...this.snapshot.state,
          error: "Please enter a nickname before joining",
        },
      });
      return;
    }

    const version = ++this.requestVersion;
    const room = this.snapshot.state.room;
    const notice = this.snapshot.state.notice;
    this.publish({
      nicknameInput: trimmedNickname,
      state: { status: "joining", room, mode, notice },
    });

    try {
      const response = await this.dependencies.join({
        code: this.code,
        nickname: trimmedNickname,
        mode,
      });
      if (!this.isCurrent(version)) return;

      const session = sessionFrom(response);
      if (session) {
        this.dependencies.saveNickname(trimmedNickname);
        this.dependencies.acceptSession(session);
        return;
      }

      if (response.error === "Room is full" && mode === "player") {
        this.publish({
          nicknameInput: trimmedNickname,
          state: {
            status: "preview",
            room: { ...room, isFull: true },
            notice,
            error: "The player slots just filled up, but you can still spectate.",
          },
        });
        return;
      }

      this.publish({
        nicknameInput: trimmedNickname,
        state: {
          status: "preview",
          room,
          notice,
          error: response.error || "Could not join room",
        },
      });
    } catch (error) {
      if (!this.isCurrent(version)) return;
      this.publish({
        nicknameInput: trimmedNickname,
        state: {
          status: "preview",
          room,
          notice,
          error: this.dependencies.requestErrorMessage(error, "join room"),
        },
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.listener = null;
  }

  private isCurrent(version: number): boolean {
    return !this.disposed && version === this.requestVersion;
  }

  private publish(next: RoomEntrySnapshot): void {
    this.snapshot = next;
    this.listener?.(this.snapshot);
  }
}
