import { apiRequest } from "./api";

export interface PersistentRoomSummary {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  hintMode: string;
  scoringMode: string;
  version: number;
}

export async function getMyPersistentRooms(): Promise<PersistentRoomSummary[]> {
  return apiRequest<PersistentRoomSummary[]>("/api/persistent-rooms");
}
