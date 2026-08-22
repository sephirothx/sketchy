import { apiRequest } from "./api";

export type DataExportStatus = "pending" | "processing" | "ready" | "failed";

export interface DataExportJob {
  id: string;
  status: DataExportStatus;
  schemaVersion: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  expiresAt: string;
  downloadUrl: string | null;
  failureCode: string | null;
}

export function requestDataExport(): Promise<DataExportJob> {
  return apiRequest("/api/auth/data-exports", { method: "POST" });
}

export function fetchDataExports(): Promise<{ exports: DataExportJob[] }> {
  return apiRequest("/api/auth/data-exports");
}

export function deleteAccount(password?: string): Promise<{
  ok: boolean;
  identitiesAnonymized: number;
  sessionsRevoked: number;
}> {
  return apiRequest("/api/auth/account", {
    method: "DELETE",
    body: password ? { password } : {},
  });
}
