import { apiRequest } from "./api";
import type { ColorMode, DrawingToolGroup, HintMode, ScoringMode } from "../types";

export interface RoomPresetSettings {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  customPrompts: "";
  customPromptsOnly: false;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptListSlugs: string[];
  promptListShareCodes: [];
}

export interface RoomPresetSummary {
  id: string;
  name: string;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface RoomPreset extends RoomPresetSummary {
  settings: RoomPresetSettings;
}

export function getMyRoomPresets(): Promise<RoomPresetSummary[]> {
  return apiRequest<RoomPresetSummary[]>("/api/room-presets");
}

export function getRoomPreset(id: string): Promise<RoomPreset> {
  return apiRequest<RoomPreset>(`/api/room-presets/${id}`);
}

export function createRoomPreset(name: string, settings: RoomPresetSettings): Promise<RoomPreset> {
  return apiRequest<RoomPreset>("/api/room-presets", {
    method: "POST",
    body: { name, settings },
  });
}

export function updateRoomPreset(
  id: string,
  expectedVersion: number,
  name: string,
  settings: RoomPresetSettings,
): Promise<RoomPreset> {
  return apiRequest<RoomPreset>(`/api/room-presets/${id}`, {
    method: "PUT",
    body: { expectedVersion, name, settings },
  });
}

export function deleteRoomPreset(id: string): Promise<null> {
  return apiRequest<null>(`/api/room-presets/${id}`, { method: "DELETE" });
}
