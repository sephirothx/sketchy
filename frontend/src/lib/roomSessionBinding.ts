/** Tracks whether an in-memory room session has been rebound to the current socket. */

export type RoomBindingStatus = "ready" | "reconnecting" | "failed";

type Listener = (status: RoomBindingStatus) => void;

let status: RoomBindingStatus = "ready";
const listeners = new Set<Listener>();

export function getRoomBindingStatus(): RoomBindingStatus {
  return status;
}

export function setRoomBindingStatus(next: RoomBindingStatus): void {
  if (status === next) return;
  status = next;
  listeners.forEach((listener) => listener(next));
}

export function subscribeRoomBinding(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
