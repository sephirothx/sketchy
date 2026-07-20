import { io, Socket } from "socket.io-client";
import type { AckResponse } from "../types";

export const SERVER_URL = import.meta.env.VITE_SERVER_URL || "http://localhost:8000";

export const socket: Socket = io(SERVER_URL, {
  autoConnect: true,
  transports: ["websocket", "polling"],
});

/** Emit an event and await the server's ack callback. */
export function emitWithAck<T = AckResponse>(event: string, data: unknown): Promise<T> {
  return new Promise((resolve) => {
    socket.emit(event, data, (response: T) => resolve(response));
  });
}
